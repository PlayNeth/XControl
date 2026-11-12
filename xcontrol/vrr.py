"""Variable refresh (FreeSync) and vkBasalt: what is available on this system."""
import glob
import os
import re

_VRR_LINE = re.compile(r"\((?:\*\*|==|--|II)\) \w+\(\d+\): VariableRefresh: (en|dis)abled")
_LAYER_DIRS = ("/usr/share/vulkan/implicit_layer.d", "/usr/local/share/vulkan/implicit_layer.d",
               "/etc/vulkan/implicit_layer.d")


LOG_DIR = "/var/log"   # where a server started as root logs


def _display_number(display):
    m = re.match(r"^[^:]*:(\d+)", display or "")
    return m.group(1) if m else None


def server_log(display=None, home=None):
    """The log of the running X server for $DISPLAY (newest matching file), or None.
    A rootless server logs under your home: XLibre from 25.2 in ~/.local/state, X.Org and
    older XLibre in ~/.local/share. A log left behind in the other place is older, so it loses."""
    n = _display_number(display if display is not None else os.environ.get("DISPLAY"))
    if n is None:
        return None
    home = home if home is not None else os.path.expanduser("~")
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    candidates = []
    for d in (os.path.join(state, "xorg"), os.path.join(state, "xlibre"), os.path.join(data, "xorg"), LOG_DIR):
        candidates += [p for p in glob.glob(os.path.join(d, f"*.{n}.log")) if os.path.isfile(p)]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def x_vrr_enabled(log_text=None):
    """True/False from the X driver's 'VariableRefresh: enabled/disabled' log line,
    None when unknown (no log, or a driver that doesn't print it)."""
    if log_text is None:
        path = server_log()
        if not path:
            return None
        try:
            with open(path, errors="replace") as f:
                log_text = f.read()
        except OSError:
            return None
    found = None
    for m in _VRR_LINE.finditer(log_text):
        found = m.group(1) == "en"
    if found is None and re.search(r"\(\*\*\) \w+\(\d+\): Option \"VariableRefresh\" \"(true|on|1|yes)\"",
                                   log_text, re.I):
        found = True
    return found


def vkbasalt_installed():
    dirs = list(_LAYER_DIRS)
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs.insert(0, os.path.join(xdg, "vulkan", "implicit_layer.d"))
    for d in dirs:
        for path in glob.glob(os.path.join(d, "*.json")):
            try:
                with open(path, errors="replace") as f:
                    if "vkbasalt" in f.read().lower():
                        return True
            except OSError:
                continue
    return False
