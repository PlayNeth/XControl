"""Which window manager is running, so the header bar only shows buttons that work.

Tiling window managers (i3 and friends) don't minimize or maximize windows, so
GTK's minimize/maximize buttons do nothing there.
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


def decoration_layout(name=None):
    """Header bar buttons: None keeps GTK's (and the user's) setting.
    MESAPANEL_DECORATION overrides, e.g. ":close" or "menu:minimize,maximize,close"."""
    override = os.environ.get("MESAPANEL_DECORATION")
    if override is not None:
        return override
    if is_tiling(window_manager_name() if name is None else name):
        return ":close"
    return None
