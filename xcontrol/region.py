"""Date, time and language: systemd's timedated and localed (polkit asks for the password),
the per-user ~/.config/locale.conf, and turning languages on (locale-gen, through a root helper).
"""
import os
import re
import shutil
import subprocess
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .paths import LIBDIR  # noqa: E402

HELPER = os.path.join(LIBDIR, "xcontrol-locale-helper")
FORMAT_VARS = ["LC_TIME", "LC_NUMERIC", "LC_MONETARY", "LC_MEASUREMENT", "LC_PAPER"]
ALL_VARS = ["LANG", "LANGUAGE"] + FORMAT_VARS + ["LC_COLLATE", "LC_CTYPE", "LC_MESSAGES", "LC_ADDRESS",
                                                 "LC_TELEPHONE", "LC_NAME", "LC_IDENTIFICATION"]


# ---------------------------------------------------------------- D-Bus
def _bus():
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def _props(name, path, iface):
    r = _bus().call_sync(name, path, "org.freedesktop.DBus.Properties", "GetAll", GLib.Variant("(s)", (iface,)),
                         None, 0, 5000, None)
    return r.unpack()[0]


def call(name, path, iface, method, signature, args, done):
    """Call a method (interactive: polkit may ask for the password) without blocking; done(error or None)."""
    def finish(conn, res):
        try:
            conn.call_finish(res)
            done(None)
        except GLib.Error as e:
            done(_error_text(e))
    _bus().call(name, path, iface, method, GLib.Variant(signature, args), None,
                Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 120000, None, finish)


def _error_text(e):
    msg = e.message
    msg = re.sub(r"^GDBus\.Error:[\w.]+:\s*", "", msg)
    return msg


TD = ("org.freedesktop.timedate1", "/org/freedesktop/timedate1", "org.freedesktop.timedate1")
LD = ("org.freedesktop.locale1", "/org/freedesktop/locale1", "org.freedesktop.locale1")


def time_state():
    """{"Timezone", "LocalRTC", "CanNTP", "NTP", "NTPSynchronized", "TimeUSec"} or {} without timedated."""
    try:
        return _props(*TD)
    except GLib.Error:
        return {}


def set_timezone(tz, done):
    call(*TD, "SetTimezone", "(sb)", (tz, True), done)


def set_ntp(on, done):
    call(*TD, "SetNTP", "(bb)", (on, True), done)


def set_time(usec, done):
    call(*TD, "SetTime", "(xbb)", (int(usec), False, True), done)


def set_local_rtc(on, done):
    call(*TD, "SetLocalRTC", "(bbb)", (on, False, True), done)


def timezones():
    """All time zone names."""
    try:
        out = subprocess.run(["timedatectl", "list-timezones", "--no-pager"], capture_output=True, text=True,
                             timeout=10).stdout.split()
        if out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    zones = set()
    for tab in ("/usr/share/zoneinfo/tzdata.zi",):
        try:
            with open(tab) as f:
                for line in f:
                    m = re.match(r"^[ZL]\s+(\S+)(?:\s+(\S+))?", line)
                    if m:
                        zones.add(m.group(2) if line.startswith("L") and m.group(2) else m.group(1))
        except OSError:
            pass
    return sorted(z for z in zones if "/" in z or z == "UTC")


def system_locale():
    """{VAR: value} of the system language (localed)."""
    try:
        return _vars(_props(*LD).get("Locale") or [])
    except GLib.Error:
        return _read_conf("/etc/locale.conf")


def set_system_locale(values, done):
    call(*LD, "SetLocale", "(asb)", ([f"{k}={v}" for k, v in values.items() if v], True), done)


def _vars(lines):
    out = {}
    for ln in lines:
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


# ---------------------------------------------------------------- per user
def user_conf_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "locale.conf")


def _read_conf(path):
    try:
        with open(path, errors="replace") as f:
            return _vars(ln for ln in f if not ln.lstrip().startswith("#"))
    except OSError:
        return {}


def user_locale():
    return _read_conf(user_conf_path())


def write_user_locale(values):
    """~/.config/locale.conf (read at login on Arch, by /etc/profile.d/locale.sh); {} removes it."""
    path = user_conf_path()
    values = {k: v for k, v in values.items() if v and k in ALL_VARS}
    if not values:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write("# Your language and formats (set by XControl). Read when you log in.\n")
        for k in ALL_VARS:
            if k in values:
                f.write(f"{k}={values[k]}\n")
    os.replace(path + ".tmp", path)


def session_locale():
    """What this session runs with now."""
    return {k: os.environ[k] for k in ALL_VARS if os.environ.get(k)}


# ---------------------------------------------------------------- available languages
def _norm(name):
    """'pt_BR.utf8' -> 'pt_BR.UTF-8'."""
    m = re.match(r"^([A-Za-z]{2,3}(?:_[A-Z]{2})?)(?:\.([\w-]+))?(@\w+)?$", name)
    if not m:
        return name
    enc = m.group(2) or ""
    if enc.lower().replace("-", "") == "utf8":
        enc = "UTF-8"
    return m.group(1) + (f".{enc}" if enc else "") + (m.group(3) or "")


def installed():
    """UTF-8 locales ready to use (locale -a)."""
    try:
        out = subprocess.run(["locale", "-a"], capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({_norm(x) for x in out if "utf8" in x.lower().replace("-", "")
                   and not x.startswith(("C.", "POSIX"))})


def supported(path="/usr/share/i18n/SUPPORTED"):
    """UTF-8 locales this system can generate."""
    try:
        with open(path) as f:
            return sorted({ln.split()[0] for ln in f if ln.strip() and ln.split()[-1] == "UTF-8"})
    except OSError:
        return []


_NAMES = {}


def describe(loc, base="/usr/share/i18n/locales"):
    """'pt_BR.UTF-8' -> 'Portuguese (Brazil)', from the locale's source (no need to have it
    generated); else from the generated data; else the code."""
    if loc in _NAMES:
        return _NAMES[loc]
    name = None
    src = re.sub(r"\.[^@]*", "", loc)            # pt_BR.UTF-8@x -> pt_BR@x
    try:
        with open(os.path.join(base, src), errors="replace") as f:
            text = f.read(20000)
        lang = re.search(r'^language\s+"([^"]+)"', text, re.M)
        terr = re.search(r'^territory\s+"([^"]+)"', text, re.M)
        if lang:
            name = lang.group(1) + (f" ({terr.group(1)})" if terr else "")
    except OSError:
        name = _probe(loc, "lang")
    _NAMES[loc] = name or loc
    return _NAMES[loc]


def preview(loc):
    """Examples in a locale: {date, time, number, money, measurement} (empty when not installed)."""
    return _probe(loc, "preview") or {}


_PROBE = r"""
import json, locale, sys, time
loc, what = sys.argv[1], sys.argv[2]
try:
    locale.setlocale(locale.LC_ALL, loc)
except locale.Error:
    print("null"); sys.exit()
if what == "lang":
    import subprocess
    try:
        out = subprocess.run(["locale", "language", "territory"], capture_output=True, text=True,
                             env={"LC_ALL": loc, "PATH": "/usr/bin:/bin"}).stdout.split("\n")
        lang, terr = out[0].strip(), out[1].strip()
        print(json.dumps(f"{lang} ({terr})" if lang and terr else lang or None))
    except Exception:
        print("null")
    sys.exit()
t = time.localtime()
try:
    money = locale.currency(1234.56, grouping=True)
except ValueError:
    money = ""
print(json.dumps({"date": time.strftime("%A, %x", t), "time": time.strftime("%X", t),
                  "number": locale.format_string("%.2f", 1234567.89, grouping=True), "money": money}))
"""


def _probe(loc, what):
    import json
    try:
        r = subprocess.run([sys.executable, "-c", _PROBE, loc, what], capture_output=True, text=True, timeout=10,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        return json.loads(r.stdout or "null")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def can_enable():
    return bool(shutil.which("pkexec")) and os.path.exists(HELPER) and bool(supported())


def enable(locales):
    """Turn languages on (pkexec helper: /etc/locale.gen and locale-gen). Returns (ok, message)."""
    try:
        r = subprocess.run(["pkexec", HELPER, "enable", *locales], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if r.returncode in (126, 127):
        return False, ""   # cancelled
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-500:]
