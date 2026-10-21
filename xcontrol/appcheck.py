"""Why doesn't this app follow my theme? Inspect a running app's process: which toolkit
it really loads, how it's packaged (AppImage, Flatpak, Snap), its environment, and the
user it runs as. Offer the fixes that can be done from here."""
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from . import theming as T


@dataclass
class Report:
    pid: int
    name: str = ""
    toolkits: list = field(default_factory=list)   # gtk2, gtk3, gtk4, libadwaita, qt5, qt6
    packaging: str = ""                            # appimage, flatpak, snap or ""
    findings: list = field(default_factory=list)   # (code, detail)
    fixes: list = field(default_factory=list)      # fix codes the UI can offer


def pick_window():
    """Let the user click a window (xprop's crosshair); returns (pid, name) or (None, reason)."""
    if not shutil.which("xprop"):
        return None, "no-xprop"
    try:   # errors="replace": WM_CLASS is Latin-1 text by the X rules; an exception here would leave
        # the page's button waiting forever (this runs in a thread)
        out = subprocess.run(["xprop", "_NET_WM_PID", "WM_CLASS"], capture_output=True, text=True,
                             errors="replace", timeout=120).stdout
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as e:
        return None, str(e)
    pid = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", out)
    cls = re.search(r'WM_CLASS\(STRING\) = "([^"]*)", "([^"]*)"', out)
    if not pid:
        return None, "no-pid"
    return int(pid.group(1)), (cls.group(2) if cls else "")


def _read(path, binary=False):
    try:
        with open(path, "rb" if binary else "r", errors=None if binary else "replace") as f:
            return f.read()
    except OSError:
        return b"" if binary else ""


def environment(pid):
    raw = _read(f"/proc/{pid}/environ", binary=True)
    env = {}
    for item in raw.split(b"\0"):
        k, sep, v = item.partition(b"=")
        if sep:
            env[k.decode(errors="replace")] = v.decode(errors="replace")
    return env


def toolkits_from_maps(maps):
    libs = set(re.findall(r"/([^/\s]+\.so[.\d]*)\s*$", maps, re.M))
    found = []
    for lib_re, kit in ((r"^libgtk-x11-2\.0\.so", "gtk2"), (r"^libgtk-3\.so", "gtk3"), (r"^libgtk-4\.so", "gtk4"),
                        (r"^libadwaita-1\.so", "libadwaita"), (r"^libQt5Gui\.so", "qt5"), (r"^libQt6Gui\.so", "qt6")):
        if any(re.match(lib_re, lib) for lib in libs):
            found.append(kit)
    return found


def packaging(pid, env, maps, exe):
    if env.get("FLATPAK_ID") or os.path.exists(f"/proc/{pid}/root/.flatpak-info"):
        return "flatpak"
    if env.get("SNAP") or exe.startswith("/snap/"):
        return "snap"
    if env.get("APPIMAGE") or env.get("APPDIR") or "/tmp/.mount_" in exe or "/tmp/.mount_" in maps:
        return "appimage"
    return ""


def analyze(pid, name="", look=None, xsettings=None):
    """Explain why the app at `pid` may not follow `look`."""
    r = Report(pid, name)
    try:
        uid = os.stat(f"/proc/{pid}").st_uid
    except OSError:
        r.findings.append(("gone", ""))
        return r
    if uid != os.getuid():
        r.findings.append(("other-user", str(uid)))
        return r  # can't read its environment or libraries
    env = environment(pid)
    maps = _read(f"/proc/{pid}/maps")
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = ""
    if not r.name:
        r.name = os.path.basename(_read(f"/proc/{pid}/comm").strip() or exe)
    r.toolkits = toolkits_from_maps(maps)
    r.packaging = packaging(pid, env, maps, exe)

    if env.get("GTK_THEME") and any(k in r.toolkits for k in ("gtk3", "gtk4", "libadwaita")):
        r.findings.append(("gtk-theme-env", env["GTK_THEME"]))
    if r.packaging == "flatpak":
        r.findings.append(("flatpak", env.get("FLATPAK_ID", "")))
        r.fixes.append("flatpak")
    elif r.packaging == "snap":
        r.findings.append(("snap", ""))
    elif r.packaging == "appimage":
        r.findings.append(("appimage", ""))
        r.fixes.append("link-home")
    if "libadwaita" in r.toolkits:
        r.findings.append(("libadwaita", ""))
    for kit in ("gtk3", "gtk4", "libadwaita"):
        css = user_css(kit)
        if css and kit in r.toolkits:
            r.findings.append(("user-css", css))
            if "user-css" not in r.fixes:
                r.fixes.append("user-css")
    if look is not None:
        theme = next((t for t in T.gtk_themes() if t.name == look.gtk_theme), None)
        kits = theme.toolkits if theme else []
        if "gtk4" in r.toolkits and "libadwaita" not in r.toolkits and "gtk4" not in kits:
            r.findings.append(("theme-no-gtk4", look.gtk_theme))
        if "gtk2" in r.toolkits and "gtk3" not in r.toolkits and "gtk2" not in kits:
            r.findings.append(("theme-no-gtk2", look.gtk_theme))
        if "gtk3" in r.toolkits and "gtk3" not in kits and "gtk2" not in r.toolkits:
            r.findings.append(("theme-no-gtk3", look.gtk_theme))
    qt = [k for k in r.toolkits if k.startswith("qt")]
    if qt and not any(k.startswith("gtk") for k in r.toolkits):
        plat = env.get("QT_QPA_PLATFORMTHEME", "")
        if plat not in ("qt5ct", "qt6ct", "gtk2", "gtk3", "kde"):
            r.findings.append(("qt-no-platformtheme", plat))
    if not r.toolkits:
        r.findings.append(("own-toolkit", ""))
    if not r.findings and xsettings is None and any(k.startswith("gtk") for k in r.toolkits):
        r.findings.append(("no-live-updates", ""))
    if not r.findings:
        r.findings.append(("restart", ""))
    return r


def user_css(kit):
    """~/.config/gtk-N.0/gtk.css when it has content: it is loaded on top of any theme.
    Theme installers (\"libadwaita\" or \"GTK 4\" options) and style editors leave it there."""
    folder = "gtk-3.0" if kit == "gtk3" else "gtk-4.0"
    path = os.path.join(T.config_home(), folder, "gtk.css")
    try:
        with open(path, errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S).strip()
    return path if code else ""


# ---- fixes
def disable_user_css():
    """Rename the override files (and the assets/ links that come with them) out of the
    way; nothing is deleted. Returns the new names."""
    done = []
    for folder in ("gtk-3.0", "gtk-4.0"):
        base = os.path.join(T.config_home(), folder)
        if not user_css("gtk3" if folder == "gtk-3.0" else "gtk4"):
            continue
        for name in ("gtk.css", "gtk-dark.css", "assets"):
            path = os.path.join(base, name)
            if not os.path.lexists(path):
                continue
            target = path + ".xcontrol-disabled"
            n = 1
            while os.path.lexists(target):
                n += 1
                target = f"{path}.xcontrol-disabled{n}"
            os.rename(path, target)
            done.append(target)
    return done



def _theme_source(name, dirs):
    for base in dirs:
        path = os.path.join(base, name)
        if os.path.isdir(path):
            return path
    return None


def link_into_home(look):
    """AppImages often bundle a GTK that doesn't search /usr/share; every GTK searches the
    home data folder, so link the themes there. Returns what was linked."""
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(T.home(), ".local", "share")
    done = []
    for name, kind, sources in ((look.gtk_theme, "themes", T.theme_dirs()[2:]),
                                (look.icon_theme, "icons", T.icon_dirs()[2:]),
                                (look.cursor_theme, "icons", T.icon_dirs()[2:])):
        if not name:
            continue
        target = os.path.join(data, kind, name)
        if os.path.lexists(target) or os.path.isdir(os.path.join(T.home(), "." + kind, name)):
            continue  # already in a home folder
        src = _theme_source(name, sources)
        if src:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.symlink(src, target)
            done.append(target)
    return done


def flatpak_fix(look):
    """Flatpak apps can only read themes from your home folder, and only when allowed:
    copy the GTK theme there and allow every Flatpak app to read the home theme folders."""
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(T.home(), ".local", "share")
    target = os.path.join(data, "themes", look.gtk_theme)
    copied = False
    if not os.path.isdir(target) or os.path.islink(target):
        # not the target itself: a link there (from link_into_home) points outside the sandbox's reach
        src = _theme_source(look.gtk_theme, [d for d in T.theme_dirs()
                                             if os.path.join(d, look.gtk_theme) != target])
        if src:
            src = os.path.realpath(src)
            if os.path.islink(target):
                os.remove(target)
            shutil.copytree(src, target, symlinks=False, ignore_dangling_symlinks=True)
            copied = True
    if shutil.which("flatpak"):
        subprocess.run(["flatpak", "override", "--user",
                        "--filesystem=xdg-data/themes:ro", "--filesystem=~/.themes:ro",
                        "--filesystem=xdg-data/icons:ro", "--filesystem=~/.icons:ro",
                        "--filesystem=xdg-config/gtk-3.0:ro", "--filesystem=xdg-config/gtk-4.0:ro"],
                       capture_output=True, timeout=30)
    return copied
