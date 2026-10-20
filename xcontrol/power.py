"""Power: sleeping when idle (the desktop service), the power/sleep buttons and lid (logind,
through a root helper), and power profiles (power-profiles-daemon or tuned-ppd)."""
import glob
import os
import shutil
import subprocess

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .paths import LIBDIR  # noqa: E402

HELPER = os.path.join(LIBDIR, "xcontrol-power-helper")
DEFAULT = {"sleep_minutes": 0, "not_while_sound": True}
BUTTON_KEYS = ["HandlePowerKey", "HandleSuspendKey", "HandleHibernateKey", "HandleLidSwitch",
               "HandleLidSwitchExternalPower", "HandleLidSwitchDocked"]
ACTIONS = ["poweroff", "suspend", "hibernate", "hybrid-sleep", "suspend-then-hibernate", "lock", "reboot", "ignore"]
LOGIND_DEFAULTS = {"HandlePowerKey": "poweroff", "HandleSuspendKey": "suspend", "HandleHibernateKey": "hibernate",
                   "HandleLidSwitch": "suspend", "HandleLidSwitchExternalPower": "suspend",
                   "HandleLidSwitchDocked": "ignore"}


def normalize(p):
    out = dict(DEFAULT)
    if isinstance(p, dict):
        out.update({k: v for k, v in p.items() if k in DEFAULT})
    try:
        out["sleep_minutes"] = max(0, min(720, int(out["sleep_minutes"])))
    except (TypeError, ValueError):
        out["sleep_minutes"] = 0
    out["not_while_sound"] = bool(out["not_while_sound"])
    return out


# ---------------------------------------------------------------- logind
def _sys():
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


LOGIN = ("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager")


def buttons():
    """{key: action} as logind uses them now ({} without logind)."""
    try:
        props = _sys().call_sync(LOGIN[0], LOGIN[1], "org.freedesktop.DBus.Properties", "GetAll",
                                 GLib.Variant("(s)", (LOGIN[2],)), None, 0, 5000, None).unpack()[0]
    except GLib.Error:
        return {}
    return {k: props[k] for k in BUTTON_KEYS if k in props}


def can(what):
    """'yes', 'no', 'challenge' or 'na' for Suspend/Hibernate/... (logind's Can* methods)."""
    try:
        return _sys().call_sync(LOGIN[0], LOGIN[1], LOGIN[2], f"Can{what}", None, None, 0, 5000,
                                None).unpack()[0]
    except GLib.Error:
        return "na"


def suspend():
    try:
        _sys().call_sync(LOGIN[0], LOGIN[1], LOGIN[2], "Suspend", GLib.Variant("(b)", (False,)), None, 0, 10000,
                         None)
        return True
    except GLib.Error:
        return False


def has_lid():
    return bool(glob.glob("/proc/acpi/button/lid/*/state")) or os.path.exists("/sys/class/power_supply/BAT0")


def our_conf():
    """{key: action} from XControl's logind drop-in."""
    out = {}
    try:
        with open("/etc/systemd/logind.conf.d/50-xcontrol.conf") as f:
            for line in f:
                if "=" in line and not line.startswith(("#", "[")):
                    k, v = line.strip().split("=", 1)
                    out[k] = v
    except OSError:
        pass
    return out


def can_set_buttons():
    return bool(shutil.which("pkexec")) and os.path.exists(HELPER)


def set_buttons(values):
    """values: {key: action} different from logind's defaults (the rest is left to logind)."""
    args = [f"{k}={v}" for k, v in sorted(values.items()) if k in BUTTON_KEYS and v in ACTIONS]
    try:
        r = subprocess.run(["pkexec", HELPER, "logind", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if r.returncode in (126, 127) and not r.stderr.strip():
        return False, ""
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-400:]


# ---------------------------------------------------------------- power profiles
PPD = [("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
        "org.freedesktop.UPower.PowerProfiles"),
       ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles")]


def _ppd():
    try:
        bus = _sys()
    except GLib.Error:   # no system bus
        return None, {}
    for name, path, iface in PPD:
        try:
            props = bus.call_sync(name, path, "org.freedesktop.DBus.Properties", "GetAll",
                                  GLib.Variant("(s)", (iface,)), None, 0, 3000, None).unpack()[0]
            return (name, path, iface), props
        except GLib.Error:
            continue
    return None, {}


def profiles():
    """(active, [profile names], degraded reason) or None when no profile service runs."""
    where, props = _ppd()
    if not where:
        return None
    names = [p.get("Profile") for p in props.get("Profiles", []) if p.get("Profile")]
    return props.get("ActiveProfile", ""), names, props.get("PerformanceDegraded", "")


def set_profile(name, done):
    where, _props = _ppd()
    if not where:
        done("no power profile service")
        return

    def finish(conn, res):
        try:
            conn.call_finish(res)
            done(None)
        except GLib.Error as e:
            done(e.message)
    _sys().call(where[0], where[1], "org.freedesktop.DBus.Properties", "Set",
                GLib.Variant("(ssv)", (where[2], "ActiveProfile", GLib.Variant("s", name))), None,
                Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 30000, None, finish)


# ---------------------------------------------------------------- sleeping when idle
def sound_playing():
    """Whether any output is playing (pactl), so a movie or music doesn't get cut off."""
    if not shutil.which("pactl"):
        return False
    try:
        out = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.split("\t")[-1].strip() == "RUNNING" for line in out.splitlines() if line.strip())


class IdleSleep:
    """Decides, once a second, whether to suspend: idle long enough, nothing keeping the screen
    on, no sound playing (when asked), and not right after waking up."""

    def __init__(self):
        self.woke = 0.0          # last time we suspended (or resumed)
        self.sound_checked = 0.0
        self.sound = False

    def check(self, p, idle_ms, kept_awake, now):
        if not p["sleep_minutes"] or kept_awake:
            return False
        limit = p["sleep_minutes"] * 60_000
        if idle_ms < limit or now - self.woke < 120:
            return False
        if p["not_while_sound"]:
            if now - self.sound_checked >= 20:
                self.sound_checked = now
                self.sound = sound_playing()
            if self.sound:
                return False
        self.woke = now
        return True
