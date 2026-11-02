"""Plymouth, the boot splash: its themes, the one in use, and whether it can show at all.

For the splash to show at boot, three things are needed (Arch Linux wiki, "Plymouth"):
  - the `plymouth` hook in mkinitcpio's HOOKS, after `systemd` (or `udev`) and `kms`, and
    before `sd-encrypt` / `encrypt`, so the initramfs starts it;
  - `splash` on the kernel command line (`quiet` hides the kernel's messages too);
  - a theme, set in /etc/plymouth/plymouthd.conf, copied into the initramfs when it's rebuilt.
XControl sets the theme (through xcontrol-plymouth-helper); the hook and the kernel command line
belong to the user's own files, so for those it only says which line to change.
"""
import configparser
import glob
import locale
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass

from . import pkexec
from .paths import LIBDIR, PLYMOUTH_PREVIEWS

HELPER = os.path.join(LIBDIR, "xcontrol-plymouth-helper")
THEMES = "/usr/share/plymouth/themes"
CONF = "/etc/plymouth/plymouthd.conf"
DEFAULTS = "/usr/share/plymouth/plymouthd.defaults"
MKINITCPIO = "/etc/mkinitcpio.conf"
PREVIEWS = PLYMOUTH_PREVIEWS
# Text-mode themes: they draw on the console, not in pictures
TEXT_THEMES = {"details", "text", "tribar"}
VALID_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}\Z")
X11_RENDERER = ("/usr/lib/plymouth/renderers/x11.so", "/usr/lib64/plymouth/renderers/x11.so")


@dataclass
class Theme:
    name: str           # directory name, what Theme= takes
    title: str          # Name= (translated when the theme has it)
    description: str
    module: str         # the plugin it uses (two-step, script, text, ...)


@dataclass
class Settings:
    theme: str = ""
    delay: str = ""     # ShowDelay, seconds ("" = Plymouth's default, 0)
    scale: str = ""     # DeviceScale ("" = automatic)


def installed():
    return bool(shutil.which("plymouthd") or os.path.exists("/usr/bin/plymouthd")
                or os.path.exists("/usr/sbin/plymouthd"))


def _keyfile(path):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            cp.read_file(f)
    except (OSError, configparser.Error):
        return None
    return cp


def _localized(section, key):
    """Name[pt_BR], Name[pt] or Name, for the user's language."""
    try:
        lang = locale.setlocale(locale.LC_MESSAGES)   # (the current one; getlocale() can raise)
    except (locale.Error, AttributeError):
        lang = ""
    if lang in ("", "C", "POSIX") or lang.startswith("C."):
        lang = os.environ.get("LANG", "")
    lang = re.split(r"[.@]", lang)[0]
    if lang in ("C", "POSIX"):
        lang = ""
    for k in (f"{key}[{lang}]", f"{key}[{lang.split('_')[0]}]", key):
        if lang or k == key:
            v = section.get(k)
            if v:
                return v
    return ""


def themes(themes_dir=THEMES):
    """The installed themes, by name."""
    out = []
    for path in sorted(glob.glob(os.path.join(themes_dir, "*", "*.plymouth"))):
        name = os.path.basename(os.path.dirname(path))
        if os.path.basename(path) != name + ".plymouth" or not VALID_NAME.match(name):
            continue   # (the helper only takes names like these)
        cp = _keyfile(path)
        if cp is None or not cp.has_section("Plymouth Theme"):
            continue
        sec = cp["Plymouth Theme"]
        out.append(Theme(name, _localized(sec, "Name") or name, _localized(sec, "Description"),
                         sec.get("ModuleName", "")))
    return out


def settings(conf=CONF, defaults=DEFAULTS):
    """What's set: plymouthd.conf first, then the distribution's defaults."""
    out = Settings()
    for path in (defaults, conf):
        cp = _keyfile(path)
        if cp is None or not cp.has_section("Daemon"):
            continue
        d = cp["Daemon"]
        out.theme = d.get("Theme", out.theme).strip()
        if path == conf:
            out.delay = d.get("ShowDelay", "").strip()
            out.scale = d.get("DeviceScale", "").strip()
    return out


def picture(name, previews=None):
    """A picture of the theme: XControl's own (for the built-in themes), or the theme's."""
    for path in (os.path.join(previews or PREVIEWS, name + ".png"),
                 os.path.join(THEMES, name, "preview.png")):
        if os.path.isfile(path):
            return path
    return None


# ---------------------------------------------------------------- the mkinitcpio hook
_COMMENT = re.compile(r"(^|\s)#[^\n]*")
_HOOKS = re.compile(r"^\s*HOOKS\s*(\+?=)\s*\(([^)]*)\)", re.M)


def hooks(texts):
    """The HOOKS in effect: mkinitcpio.conf and then its conf.d drop-ins (`texts` in that order),
    read like bash would (HOOKS=(...), HOOKS+=(...), quotes, comments). None when there's none."""
    found = None
    for text in texts:
        for m in _HOOKS.finditer(_COMMENT.sub(r"\1", text or "")):
            try:
                words = shlex.split(m.group(2))
            except ValueError:
                words = m.group(2).split()
            new = []
            for w in words:   # HOOKS=(${HOOKS[@]} plymouth); $HOOKS is only the first one in bash
                new += ((found or []) if w in ("${HOOKS[@]}", "${HOOKS[*]}") else
                        (found or [])[:1] if w in ("$HOOKS", "${HOOKS}") else [w])
            found = (found or []) + new if m.group(1) == "+=" else new
    return found


def read_hooks(conf=MKINITCPIO):
    texts = []
    for path in [conf] + sorted(glob.glob(conf + ".d/*.conf")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                texts.append(f.read())
        except OSError:
            continue
    return texts


def hook_state(hk):
    """'ok', 'missing', 'early' (before systemd/udev) or 'late' (after an encrypt hook);
    None when mkinitcpio's HOOKS aren't known (dracut, another initramfs tool). (kms only adds
    modules to the image, so where it is doesn't matter at boot; suggested_hooks() still puts
    plymouth after it, like the usual lists do.)"""
    if hk is None:
        return None
    if "plymouth" not in hk:
        return "missing"
    i = hk.index("plymouth")
    if any(h in hk[i + 1:] for h in ("systemd", "udev")):
        return "early"
    if any(h in hk[:i] for h in ("encrypt", "sd-encrypt")):
        return "late"
    return "ok"


def suggested_hooks(hk):
    """HOOKS with `plymouth` where the wiki wants it: after systemd/udev and kms, before the
    encrypt hooks (right after kms in Arch's default list)."""
    rest = [h for h in hk if h != "plymouth"]
    after = max([rest.index(h) for h in ("base", "systemd", "udev", "kms") if h in rest], default=-1)
    before = min([rest.index(h) for h in ("encrypt", "sd-encrypt") if h in rest], default=len(rest))
    at = min(after + 1, before)
    return rest[:at] + ["plymouth"] + rest[at:]


def format_hooks(hk):
    return "HOOKS=(" + " ".join(hk) + ")"


# ---------------------------------------------------------------- the kernel command line
def cmdline(path="/proc/cmdline"):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


_KWORD = re.compile(r'(?:[^\s"]+|"[^"]*"?)+')


def has_splash(line):
    words = line.split()
    return "splash" in words and "nosplash" not in words and "plymouth.enable=0" not in words


def suggested_cmdline(line):
    """The kernel options with `splash` (and `quiet`) added, without what the boot loader adds
    itself (initrd=, BOOT_IMAGE=)."""
    words = _KWORD.findall(line)    # (the kernel's own rule: only double quotes, kept as written)
    words = [w for w in words if not w.startswith(("initrd=", "BOOT_IMAGE=")) and w != "nosplash"]
    for w in ("quiet", "splash"):
        if w not in words:
            words.append(w)
    return " ".join(words)


LOADER_INFO = "/sys/firmware/efi/efivars/LoaderInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"


def _loader_info():
    """The boot loader's name as it tells the system (systemd-boot, GRUB 2.12, ...), or ''."""
    try:
        with open(LOADER_INFO, "rb") as f:
            return f.read()[4:].decode("utf-16-le", "replace").rstrip("\0")
    except OSError:
        return ""


def bootloader():
    """'uki' (options in /etc/kernel/cmdline), 'systemd-boot', 'grub', 'limine', 'refind' or ''."""
    if os.path.exists("/etc/kernel/cmdline"):
        return "uki"
    if _loader_info().startswith("systemd-boot"):   # (/boot itself may be unreadable: umask=0077)
        return "systemd-boot"
    for d in ("/boot/loader", "/efi/loader", "/boot/efi/loader"):
        if os.path.isdir(d):
            return "systemd-boot"
    if os.path.exists("/etc/default/grub"):
        return "grub"
    if glob.glob("/boot/limine.conf") or glob.glob("/boot/limine/limine.conf") or glob.glob("/boot/EFI/limine/*"):
        return "limine"
    if glob.glob("/boot/refind_linux.conf"):
        return "refind"
    return ""


# ---------------------------------------------------------------- applying
def apply(theme, delay="", scale=""):
    """Set the theme (and the delay and scale) and rebuild the initramfs. (ok, output)."""
    cmd = ["pkexec", HELPER, "set", theme, delay or "-", scale or "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return _result(r)


def _result(r):
    out = (r.stdout + r.stderr).strip()
    if pkexec.cancelled(r):
        return False, None   # (the password prompt was cancelled: nothing to report)
    return r.returncode == 0, out


def can_preview(theme):
    """A theme can be played in a window when Plymouth has its X11 renderer (graphical themes)."""
    return theme not in TEXT_THEMES and any(os.path.exists(p) for p in X11_RENDERER)


def preview(theme):
    """Play the theme for a few seconds in a window (root, through the helper). (ok, output)."""
    display = os.environ.get("DISPLAY", "")
    xauth = os.environ.get("XAUTHORITY") or os.path.expanduser("~/.Xauthority")
    cmd = ["pkexec", HELPER, "preview", theme, display, xauth if os.path.isfile(xauth) else "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return _result(r)
