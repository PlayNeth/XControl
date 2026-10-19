"""Desktop look on X11: GTK theme, icons, cursor, fonts and the dark preference.

Every toolkit reads a different place, which is why changes often "don't apply":
  - running GTK 2/3/4 apps:  the XSETTINGS manager (xsettingsd here), live
  - GTK 3 / GTK 4 at start:  ~/.config/gtk-3.0/settings.ini, gtk-4.0/settings.ini
                              (ignored for anything an XSETTINGS manager provides)
  - GTK 2 at start:          ~/.gtkrc-2.0
  - libadwaita, portals:     gsettings org.gnome.desktop.interface (color-scheme)
  - X cursors (i3, xterm):   ~/.icons/default/index.theme and Xcursor.* resources
  - Qt (qt5ct/qt6ct):        ~/.config/qt5ct/qt5ct.conf, qt6ct/qt6ct.conf
apply() writes all of them; other settings in those files are kept.
"""
import configparser
import glob
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass, field

GTK3_BUILTIN = ("Adwaita", "Adwaita-dark", "HighContrast", "HighContrastInverse")
HINT_STYLES = ["hintnone", "hintslight", "hintmedium", "hintfull"]
SUBPIXEL = ["none", "rgb", "bgr", "vrgb", "vbgr"]
CURSOR_SIZES = [16, 24, 32, 40, 48, 64, 72, 96]
BLOCK_START = "! >>> XControl appearance (managed by XControl; edits here are replaced)"
BLOCK_END = "! <<< XControl appearance"


@dataclass
class Look:
    gtk_theme: str = "Adwaita"
    icon_theme: str = "hicolor"
    cursor_theme: str = ""
    cursor_size: int = 24
    font: str = "Sans 10"
    prefer_dark: bool = False
    antialias: bool = True
    hinting: bool = True
    hint_style: str = "hintslight"
    subpixel: str = "none"


@dataclass
class Theme:
    name: str           # directory name: what the settings store
    title: str = ""     # Name= from index.theme
    toolkits: list = field(default_factory=list)   # gtk2/gtk3/gtk4 for GTK themes


# ---- where things are
def home():
    return os.path.expanduser("~")


def config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(home(), ".config")


def _data_dirs():
    dirs = [os.environ.get("XDG_DATA_HOME") or os.path.join(home(), ".local", "share")]
    dirs += [d for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    return dirs


def theme_dirs():
    return [os.path.join(home(), ".themes")] + [os.path.join(d, "themes") for d in _data_dirs()]


def icon_dirs():
    return [os.path.join(home(), ".icons")] + [os.path.join(d, "icons") for d in _data_dirs()]


def _index_name(path, section="Icon Theme"):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read(os.path.join(path, "index.theme"), encoding="utf-8")
        return cp.get(section, "Name", fallback=""), cp
    except (configparser.Error, UnicodeDecodeError):
        return "", None


# ---- discovery (the first directory in search order wins, like the toolkits do)
def gtk_themes():
    found = {}
    for base in theme_dirs():
        for path in sorted(glob.glob(os.path.join(base, "*"))):
            name = os.path.basename(path)
            if name in found or not os.path.isdir(path):
                continue
            kits = [kit for kit, f in (("gtk2", "gtk-2.0/gtkrc"), ("gtk3", "gtk-3.0/gtk.css"),
                                       ("gtk4", "gtk-4.0/gtk.css")) if os.path.exists(os.path.join(path, f))]
            if kits:  # skips keybinding-only themes such as "Emacs"
                found[name] = Theme(name, _index_name(path, "Desktop Entry")[0] or name, kits)
    for name in GTK3_BUILTIN:  # compiled into GTK 3
        t = found.setdefault(name, Theme(name, name, []))
        if "gtk3" not in t.toolkits:
            t.toolkits.append("gtk3")
    return sorted(found.values(), key=lambda t: t.name.lower())


def icon_themes():
    found = {}
    for base in icon_dirs():
        for path in sorted(glob.glob(os.path.join(base, "*"))):
            name = os.path.basename(path)
            if name in found or name in ("default", "hicolor", "locolor") or not os.path.isdir(path):
                continue
            title, cp = _index_name(path)
            if cp is not None and cp.get("Icon Theme", "Directories", fallback="").strip():
                found[name] = Theme(name, title or name)
    return sorted(found.values(), key=lambda t: t.title.lower())


def cursor_themes():
    found = {}
    for base in icon_dirs():
        for path in sorted(glob.glob(os.path.join(base, "*"))):
            name = os.path.basename(path)
            if name in found or name == "default":
                continue
            if os.path.isdir(os.path.join(path, "cursors")):
                found[name] = Theme(name, _index_name(path)[0] or name)
    return sorted(found.values(), key=lambda t: t.title.lower())


# ---- small file helpers
def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.xcontrol-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _set_ini(path, section, values):
    """Update keys in an ini file, keeping everything else (and its order)."""
    lines = _read(path).splitlines()
    out, in_section, seen, done = [], False, set(), False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not done:
                out += [f"{k}={v}" for k, v in values.items() if k not in seen]
                done = True
            in_section = stripped[1:-1] == section
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else None
        if in_section and key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
            continue
        out.append(line)
    if not done:
        if not in_section:
            if out and out[-1].strip():
                out.append("")
            out.append(f"[{section}]")
        out += [f"{k}={v}" for k, v in values.items() if k not in seen]
    _write(path, "\n".join(out) + "\n")


# ---- what each toolkit gets
def gtk_ini_values(look, gtk4=False):
    v = {
        "gtk-theme-name": look.gtk_theme,
        "gtk-icon-theme-name": look.icon_theme,
        "gtk-font-name": look.font,
        "gtk-application-prefer-dark-theme": "true" if look.prefer_dark else "false",
        "gtk-xft-antialias": "1" if look.antialias else "0",
        "gtk-xft-hinting": "1" if look.hinting else "0",
        "gtk-xft-hintstyle": look.hint_style,
        "gtk-xft-rgba": look.subpixel,
    }
    if look.cursor_theme:
        v["gtk-cursor-theme-name"] = look.cursor_theme
        v["gtk-cursor-theme-size"] = str(look.cursor_size)
    if gtk4:  # GTK 4 dropped these
        for k in ("gtk-xft-antialias", "gtk-xft-hinting", "gtk-xft-hintstyle", "gtk-xft-rgba"):
            v.pop(k)
    return v


def gtkrc2_text(existing, look):
    """~/.gtkrc-2.0 with our keys replaced and everything else kept."""
    values = {
        "gtk-theme-name": f'"{look.gtk_theme}"',
        "gtk-icon-theme-name": f'"{look.icon_theme}"',
        "gtk-font-name": f'"{look.font}"',
        "gtk-xft-antialias": "1" if look.antialias else "0",
        "gtk-xft-hinting": "1" if look.hinting else "0",
        "gtk-xft-hintstyle": f'"{look.hint_style}"',
        "gtk-xft-rgba": f'"{look.subpixel}"',
    }
    if look.cursor_theme:
        values["gtk-cursor-theme-name"] = f'"{look.cursor_theme}"'
        values["gtk-cursor-theme-size"] = str(look.cursor_size)
    out, seen = [], set()
    for line in existing.splitlines():
        m = re.match(r"\s*([a-z0-9-]+)\s*=", line)
        if m and m.group(1) in values:
            out.append(f"{m.group(1)}={values[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in seen]
    return "\n".join(out) + "\n"


def xsettings_values(look):
    v = {
        "Net/ThemeName": f'"{look.gtk_theme}"',
        "Net/IconThemeName": f'"{look.icon_theme}"',
        "Gtk/FontName": f'"{look.font}"',
        "Xft/Antialias": "1" if look.antialias else "0",
        "Xft/Hinting": "1" if look.hinting else "0",
        "Xft/HintStyle": f'"{look.hint_style}"',
        "Xft/RGBA": f'"{look.subpixel}"',
    }
    if look.cursor_theme:
        v["Gtk/CursorThemeName"] = f'"{look.cursor_theme}"'
        v["Gtk/CursorThemeSize"] = str(look.cursor_size)
    return v


def xsettingsd_text(existing, look):
    """xsettingsd.conf with our settings replaced; other settings (e.g. Xft/DPI) kept."""
    values = xsettings_values(look)
    out, seen = [], set()
    for line in existing.splitlines():
        key = line.split(None, 1)[0] if line.strip() and not line.lstrip().startswith("#") else None
        if key in values:
            out.append(f"{key} {values[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k} {v}" for k, v in values.items() if k not in seen]
    return "\n".join(out) + "\n"


def xresources_block(look):
    lines = [BLOCK_START,
             f"Xft.antialias: {1 if look.antialias else 0}",
             f"Xft.hinting: {1 if look.hinting else 0}",
             f"Xft.hintstyle: {look.hint_style}",
             f"Xft.rgba: {look.subpixel}"]
    if look.cursor_theme:
        lines += [f"Xcursor.theme: {look.cursor_theme}", f"Xcursor.size: {look.cursor_size}"]
    return "\n".join(lines + [BLOCK_END]) + "\n"


def xresources_text(existing, look):
    """~/.Xresources with our block replaced (or added); the rest kept."""
    pattern = re.compile(re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.S)
    block = xresources_block(look)
    if pattern.search(existing):
        return pattern.sub(lambda _m: block, existing)
    sep = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    return existing + sep + block


def qt_font(font):
    """GTK "Family Name 11" -> qt5ct/qt6ct font string."""
    m = re.match(r"^(.*?)\s+(\d+(?:\.\d+)?)$", font.strip())
    family, size = (m.group(1), m.group(2)) if m else (font, "10")
    return f'"{family},{size},-1,5,50,0,0,0,0,0"'


# ---- XSETTINGS
def xsettings_owner_pid():
    """PID owning the _XSETTINGS_S0 selection (via xprop on the owner window), or None."""
    try:
        import ctypes
        import ctypes.util
        x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XGetSelectionOwner.restype = ctypes.c_ulong
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        dpy = x11.XOpenDisplay(None)
        if not dpy:
            return None
        try:
            screen = int(os.environ.get("DISPLAY", ":0").rsplit(".", 1)[-1]) if "." in os.environ.get(
                "DISPLAY", "").split(":")[-1] else 0
            owner = x11.XGetSelectionOwner(dpy, x11.XInternAtom(dpy, f"_XSETTINGS_S{screen}".encode(), 0))
        finally:
            x11.XCloseDisplay(dpy)
        return owner or None
    except (OSError, AttributeError, ValueError):
        return None


def _procs():
    """{pid: command name} for the user's processes."""
    out = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            if os.stat(d).st_uid != os.getuid():
                continue
            with open(os.path.join(d, "comm")) as f:
                out[int(os.path.basename(d))] = f.read().strip()
        except OSError:
            continue
    return out


MANAGERS = {
    "xsettingsd": "xsettingsd",
    "gsd-xsettings": "gnome", "gnome-settings-daemon": "gnome", "csd-xsettings": "gnome",
    "mate-settings-daemon": "mate", "xfsettingsd": "xfce", "lxsession": "lxde",
}


def xsettings_manager():
    """(kind, pid) of the running XSETTINGS manager: kind is xsettingsd, gnome, mate, xfce,
    lxde or "other"; (None, None) when nothing provides XSETTINGS."""
    if not xsettings_owner_pid():
        return None, None
    for pid, comm in _procs().items():
        if comm in MANAGERS:
            return MANAGERS[comm], pid
    return "other", None


def xsettingsd_conf():
    return os.path.join(config_home(), "xsettingsd", "xsettingsd.conf")


def xsettingsd_autostart():
    return os.path.join(config_home(), "autostart", "xcontrol-xsettingsd.desktop")


# ---- applying
def _run(args, check=False):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=15)
        if check and out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or f"{args[0]} failed")
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        if check:
            raise
        return False


def _gsettings(look):
    if not shutil.which("gsettings"):
        return False
    schemas = _run(["gsettings", "list-keys", "org.gnome.desktop.interface"])
    if not schemas:
        return False
    s = "org.gnome.desktop.interface"
    pairs = [("gtk-theme", look.gtk_theme), ("icon-theme", look.icon_theme), ("font-name", look.font),
             ("color-scheme", "prefer-dark" if look.prefer_dark else "default"),
             ("font-antialiasing", ("rgba" if look.subpixel != "none" else "grayscale") if look.antialias else "none"),
             ("font-hinting", {"hintnone": "none", "hintslight": "slight", "hintmedium": "medium",
                               "hintfull": "full"}[look.hint_style] if look.hinting else "none")]
    if look.cursor_theme:
        pairs += [("cursor-theme", look.cursor_theme), ("cursor-size", str(look.cursor_size))]
    for key, value in pairs:
        _run(["gsettings", "set", s, key, value])
    return True


def _xfconf(look):
    if not shutil.which("xfconf-query"):
        return
    for prop, kind, value in (("/Net/ThemeName", "string", look.gtk_theme),
                              ("/Net/IconThemeName", "string", look.icon_theme),
                              ("/Gtk/FontName", "string", look.font),
                              ("/Gtk/CursorThemeName", "string", look.cursor_theme),
                              ("/Gtk/CursorThemeSize", "int", str(look.cursor_size)),
                              ("/Xft/Antialias", "int", "1" if look.antialias else "0"),
                              ("/Xft/Hinting", "int", "1" if look.hinting else "0"),
                              ("/Xft/HintStyle", "string", look.hint_style),
                              ("/Xft/RGBA", "string", look.subpixel)):
        if value:
            _run(["xfconf-query", "-c", "xsettings", "-p", prop, "-n", "-t", kind, "-s", value])


def _qt(look, qt_versions):
    for v in qt_versions:
        path = os.path.join(config_home(), f"qt{v}ct", f"qt{v}ct.conf")
        _set_ini(path, "Appearance", {"icon_theme": look.icon_theme})
        _set_ini(path, "Fonts", {"general": qt_font(look.font)})


def qt_tools():
    """qt5ct/qt6ct that are installed, and whether Qt apps are told to use them."""
    tools = [v for v in ("5", "6") if shutil.which(f"qt{v}ct")]
    env = os.environ.get("QT_QPA_PLATFORMTHEME", "")
    return tools, env


def apply(look, qt=True, start_xsettingsd=True):
    """Write the look everywhere and update running apps. Returns notes for the user."""
    notes = []
    cfg = config_home()
    _set_ini(os.path.join(cfg, "gtk-3.0", "settings.ini"), "Settings", gtk_ini_values(look))
    _set_ini(os.path.join(cfg, "gtk-4.0", "settings.ini"), "Settings", gtk_ini_values(look, gtk4=True))
    rc2 = os.path.join(home(), ".gtkrc-2.0")
    _write(rc2, gtkrc2_text(_read(rc2), look))

    if look.cursor_theme:
        _set_ini(os.path.join(home(), ".icons", "default", "index.theme"), "Icon Theme",
                 {"Inherits": look.cursor_theme})
    xres = os.path.join(home(), ".Xresources")
    _write(xres, xresources_text(_read(xres), look))
    if shutil.which("xrdb") and os.environ.get("DISPLAY"):
        try:
            subprocess.run(["xrdb", "-merge"], input=xresources_block(look), text=True, capture_output=True,
                           timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    if look.cursor_theme and shutil.which("xsetroot") and os.environ.get("DISPLAY"):
        env = dict(os.environ, XCURSOR_THEME=look.cursor_theme, XCURSOR_SIZE=str(look.cursor_size))
        try:
            subprocess.run(["xsetroot", "-cursor_name", "left_ptr"], env=env, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass

    _gsettings(look)
    if qt:
        tools, _env = qt_tools()
        _qt(look, tools)

    # running apps: through whatever provides XSETTINGS
    kind, pid = xsettings_manager()
    conf = xsettingsd_conf()
    if kind in (None, "xsettingsd"):
        _write(conf, xsettingsd_text(_read(conf), look))
    if kind == "xsettingsd":
        try:
            os.kill(pid, signal.SIGHUP)  # xsettingsd re-reads its file
            notes.append("live")
        except OSError:
            notes.append("xsettingsd-failed")
    elif kind is None:
        if start_xsettingsd and shutil.which("xsettingsd") and os.environ.get("DISPLAY"):
            try:
                subprocess.Popen(["xsettingsd", "-c", conf], start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _write(xsettingsd_autostart(),
                       "[Desktop Entry]\nType=Application\nName=XSETTINGS for XControl's appearance settings\n"
                       f"Exec=xsettingsd -c {conf}\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n")
                notes.append("started")
            except OSError:
                notes.append("no-xsettingsd")
        else:
            notes.append("no-xsettingsd")
    elif kind == "xfce":
        _xfconf(look)
        notes.append("live")
    elif kind in ("gnome", "mate"):
        notes.append("live")  # gsettings above
    else:
        notes.append("other-manager")
    return notes


# ---- reading what is set now
def current(gtk_settings=None):
    """The look in effect, from GTK's own settings (which already merge XSETTINGS and files)."""
    look = Look()
    if gtk_settings is not None:
        p = gtk_settings.props
        look.gtk_theme = p.gtk_theme_name or look.gtk_theme
        look.icon_theme = p.gtk_icon_theme_name or look.icon_theme
        look.cursor_theme = p.gtk_cursor_theme_name or ""
        look.cursor_size = p.gtk_cursor_theme_size or 24
        look.font = p.gtk_font_name or look.font
        look.prefer_dark = bool(p.gtk_application_prefer_dark_theme)
        look.antialias = p.gtk_xft_antialias != 0
        look.hinting = p.gtk_xft_hinting != 0
        look.hint_style = p.gtk_xft_hintstyle or look.hint_style
        look.subpixel = p.gtk_xft_rgba or look.subpixel
    if not look.cursor_theme:  # GTK leaves it empty when only X's default is used
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        for base in icon_dirs():
            path = os.path.join(base, "default", "index.theme")
            if os.path.exists(path):
                try:
                    cp.read(path)
                    look.cursor_theme = cp.get("Icon Theme", "Inherits", fallback="").split(",")[0].strip()
                except configparser.Error:
                    pass
                if look.cursor_theme:
                    break
    if look.hint_style not in HINT_STYLES:
        look.hint_style = "hintslight"
    if look.subpixel not in SUBPIXEL:
        look.subpixel = "none"
    return look
