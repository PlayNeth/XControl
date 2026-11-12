"""How the window gets its title bar.

GNOME-style desktops expect apps to draw their own (a GTK header bar). Everywhere
else (i3 and other tiling window managers, Xfce, KDE, Openbox, ...) the window
manager draws it, like it does for Thunar or Firefox with its native title bar.
"""
import os

# names as the window managers report them in _NET_WM_NAME (lower case)
TILING = {
    "i3", "bspwm", "awesome", "xmonad", "herbstluftwm", "qtile", "spectrwm", "leftwm",
    "dwm", "ratpoison", "stumpwm", "notion", "ion3", "subtle", "wmii", "frankenwm",
    "berry", "2bwm", "monsterwm", "dk", "exwm", "instantwm", "chadwm", "dwl",
}


def window_manager_name():
    """The X11 window manager's name (from _NET_SUPPORTING_WM_CHECK), or "" if unknown."""
    try:
        import gi
        gi.require_version("GdkX11", "3.0")
        from gi.repository import Gdk, GdkX11
        screen = Gdk.Screen.get_default()
        if isinstance(screen, GdkX11.X11Screen):
            name = screen.get_window_manager_name() or ""
            return "" if name.lower() == "unknown" else name
    except (ImportError, ValueError, AttributeError):
        pass
    return ""


def is_tiling(name):
    n = name.strip().lower()
    return n in TILING or n.startswith(("i3", "dwm", "xmonad", "awesome"))


# desktops whose own apps use header bars (XDG_CURRENT_DESKTOP entries)
HEADER_BAR_DESKTOPS = {"gnome", "pantheon", "budgie", "budgie-desktop", "unity", "phosh"}


def use_header_bar(desktop=None, wm_name=None):
    """True: draw a GTK header bar. False: let the window manager decorate the window.
    XCONTROL_CSD=1/0 overrides."""
    forced = os.environ.get("XCONTROL_CSD")
    if forced in ("0", "1"):
        return forced == "1"
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") if desktop is None else desktop
    names = {d.strip().lower() for d in desktop.split(":") if d.strip()}
    if names & HEADER_BAR_DESKTOPS:
        return not is_tiling(window_manager_name() if wm_name is None else wm_name)
    return False


def decoration_layout(name=None):
    """Header bar buttons: None keeps GTK's (and the user's) setting.
    XCONTROL_DECORATION overrides, e.g. ":close" or "menu:minimize,maximize,close"."""
    override = os.environ.get("XCONTROL_DECORATION")
    if override is not None:
        return override
    if is_tiling(window_manager_name() if name is None else name):
        return ":close"
    return None


# ---------------------------------------------------------------- which one runs
SUPPORTED = ("i3", "openbox")   # the window managers XControl writes a config for
_running = [0.0, None]          # (when, what): the pages ask on every status refresh


def running():
    """The supported window manager this user is running ("i3" or "openbox"), or None. From the
    process list, so it also works without a display (the desktop service, the bar's config)."""
    import glob
    import time
    now = time.monotonic()
    if now - _running[0] < 5:
        return _running[1]
    found, uid = None, os.getuid()
    for d in glob.glob("/proc/[0-9]*"):
        try:
            with open(os.path.join(d, "comm")) as f:
                name = f.read().strip()
            if name in SUPPORTED and os.stat(d).st_uid == uid:
                found = name
                break
        except OSError:
            continue
    _running[:] = [now, found]
    return found


def page_for():
    """Which Window Manager page to show: the running one's; else the one that's installed (i3
    when both or neither are)."""
    import shutil
    now = running()
    if now:
        return now
    if shutil.which("openbox") and not shutil.which("i3"):
        return "openbox"
    return "i3"


def startup_line(cmd, which=None):
    """How to start `cmd` at login in this window manager's config (for hints to copy)."""
    which = which or page_for()
    return f"{cmd} &" if which == "openbox" else f"exec --no-startup-id {cmd}"


def startup_file(which=None):
    """Where this window manager's login programs are listed, as shown to the user."""
    return "~/.config/openbox/autostart" if (which or page_for()) == "openbox" else "~/.config/i3/config"
