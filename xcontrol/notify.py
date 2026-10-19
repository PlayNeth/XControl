"""XControl's notifications: settings -> ~/.config/xcontrol/dunstrc, shown by dunst.

The desktop service runs dunst with this file (`dunst -config ...`) and restarts it when the
file changes; your own ~/.config/dunst/dunstrc isn't used or changed while XControl does this.
"""
import configparser
import os
import re
import shutil
import subprocess

from .paths import config_dir

POSITIONS = ["top-left", "top-center", "top-right", "left-center", "center", "right-center",
             "bottom-left", "bottom-center", "bottom-right"]
FOLLOW = ["keyboard", "mouse", "none"]          # display: with the focus, with the mouse, the first one
ICON_POSITIONS = ["left", "right", "top", "off"]
ALIGN = ["left", "center", "right"]
FORMATS = {
    "title_body": "<b>%s</b>\\n%b",
    "app_title_body": "<b>%a</b> · %s\\n%b",
    "title": "<b>%s</b>",
    "title_body_progress": "<b>%s</b> %p\\n%b",
}
CLICKS = ["close_current", "do_action, close_current", "close_all", "context", "open_url", "none"]
URGENCIES = ["low", "normal", "critical"]
RULE_ACTIONS = ["hide", "history_only", "no_timeout", "low", "critical", "no_sound"]
DEFAULT = {
    "enabled": False,
    "position": "top-right", "offset_x": 12, "offset_y": 40, "follow": "keyboard",
    "width": 340, "max_height": 300, "limit": 5, "gap": 6,
    "font": "", "corner_radius": 6, "frame_width": 2, "padding": 10, "icon_position": "left", "icon_size": 48,
    "transparency": 0, "separator": True, "alignment": "left", "format": "title_body", "custom_format": "",
    "colors": None,       # {urgency: [background, text, frame]}
    "timeouts": None,     # {urgency: seconds (0: until clicked)}
    "show_age": 60, "idle_pause": 120, "stack_duplicates": True, "history_length": 20, "sticky_history": True,
    "indicate_hidden": True, "show_indicators": True, "progress_bar": True,
    "left_click": "close_current", "middle_click": "do_action, close_current", "right_click": "close_all",
    "rules": [],          # [{"app": "Spotify", "action": "history_only"}]
    "critical_in_dnd": True,   # critical notifications still show while "do not disturb" is on
    "sound": "",          # a sound file played for normal and critical notifications ("" none)
    "extra": "",          # dunstrc lines; a [section] line starts a section, others go to [global]
}
DND_LEVEL = 50       # "do not disturb" pause level (dunst 1.10+); critical ones override above it
DEFAULT_COLORS = {"low": ["#222222", "#9a9a9a", "#444444"], "normal": ["#285577", "#ffffff", "#4c7899"],
                  "critical": ["#900000", "#ffffff", "#ff4444"]}
DEFAULT_TIMEOUTS = {"low": 5, "normal": 10, "critical": 0}
INTS = {"offset_x": (0, 2000), "offset_y": (0, 2000), "width": (100, 2000), "max_height": (40, 2000),
        "limit": (0, 50), "gap": (0, 100), "corner_radius": (0, 50), "frame_width": (0, 20), "padding": (0, 60),
        "icon_size": (16, 256), "transparency": (0, 100), "show_age": (-1, 3600), "idle_pause": (0, 3600),
        "history_length": (0, 1000)}
CHOICES = {"position": POSITIONS, "follow": FOLLOW, "icon_position": ICON_POSITIONS, "alignment": ALIGN,
           "format": list(FORMATS) + ["custom"], "left_click": CLICKS, "middle_click": CLICKS, "right_click": CLICKS}


def normalize(n):
    out = dict(DEFAULT)
    if isinstance(n, dict):
        out.update({k: v for k, v in n.items() if k in DEFAULT})
    for k, choices in CHOICES.items():
        if out[k] not in choices:
            out[k] = DEFAULT[k]
    for k, (lo, hi) in INTS.items():
        try:
            out[k] = max(lo, min(hi, int(out[k])))
        except (TypeError, ValueError):
            out[k] = DEFAULT[k]
    for k in ("enabled", "critical_in_dnd", "separator", "stack_duplicates", "sticky_history", "indicate_hidden",
              "show_indicators", "progress_bar"):
        out[k] = bool(out[k])
    colors = {u: list(c) for u, c in DEFAULT_COLORS.items()}
    for u, c in (out["colors"] or {}).items():
        if u in colors and isinstance(c, (list, tuple)) and len(c) == 3:
            colors[u] = [str(x) for x in c]
    out["colors"] = colors
    times = dict(DEFAULT_TIMEOUTS)
    for u, t in (out["timeouts"] or {}).items():
        if u in times:
            try:
                times[u] = max(0, min(3600, int(t)))
            except (TypeError, ValueError):
                pass
    out["timeouts"] = times
    out["rules"] = [{"app": str(r.get("app", "")).strip(), "action": r.get("action")}
                    for r in out["rules"] if isinstance(r, dict) and str(r.get("app", "")).strip()
                    and r.get("action") in RULE_ACTIONS]
    out["font"], out["custom_format"], out["sound"], out["extra"] = (
        str(out["font"] or ""), str(out["custom_format"] or ""), str(out["sound"] or ""), str(out["extra"] or ""))
    return out


def config_path():
    return os.path.join(config_dir(), "dunstrc")


def version():
    try:
        out = subprocess.run(["dunst", "--version"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _gtk_setting(key):
    """A value from GTK 3's settings.ini (what the Appearance page writes)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read(os.path.join(base, "gtk-3.0", "settings.ini"))
        return cp.get("Settings", key, fallback="").strip()
    except configparser.Error:
        return ""


def _q(text):
    """A quoted dunstrc string (dunst reads \\n inside quotes as a line break, which formats use)."""
    return '"' + str(text).replace('"', '\\"') + '"'


def _menu():
    if shutil.which("rofi"):
        return "rofi -dmenu -p dunst"
    return "dmenu -p dunst:"


def generate(n, ver=None, font=None, icons=None):
    """The dunstrc text for settings `n` (normalized)."""
    ver = ver if ver is not None else version()
    new = ver is None or ver >= (1, 12)     # (x, y) tuples instead of 10x50 / a single height
    levels = ver is None or ver >= (1, 10)  # pause levels: critical ones can get through "do not disturb"
    font = n["font"] or font or _gtk_setting("gtk-font-name") or "Sans 10"
    icon_theme = icons if icons is not None else (_gtk_setting("gtk-icon-theme-name") or "Adwaita")
    themes = ", ".join(dict.fromkeys(t for t in (icon_theme, "Adwaita", "hicolor") if t))
    custom = n["format"] == "custom" and n["custom_format"]
    fmt = n["custom_format"] if custom else FORMATS.get(n["format"], FORMATS["title_body"])
    fmt = fmt.replace("\n", "\\n")
    offset = f"({n['offset_x']}, {n['offset_y']})" if new else f"{n['offset_x']}x{n['offset_y']}"
    height = f"(0, {n['max_height']})" if new else str(n["max_height"])
    g = [
        "monitor = 0",
        f"follow = {n['follow']}",
        f"width = {n['width']}",
        f"height = {height}",
        f"origin = {n['position']}",
        f"offset = {offset}",
        f"notification_limit = {n['limit']}",
        f"gap_size = {n['gap']}",
        f"progress_bar = {str(n['progress_bar']).lower()}",
        f"indicate_hidden = {'yes' if n['indicate_hidden'] else 'no'}",
        f"transparency = {n['transparency']}",
        f"separator_height = {2 if n['separator'] else 0}",
        f"padding = {n['padding']}",
        f"horizontal_padding = {n['padding']}",
        f"text_icon_padding = {n['padding']}",
        f"frame_width = {n['frame_width']}",
        f"frame_color = {_q(n['colors']['normal'][2])}",
        "separator_color = frame",
        "sort = yes",
        f"font = {font}",
        "markup = full",
        f"format = {_q(fmt)}",
        f"alignment = {n['alignment']}",
        "vertical_alignment = center",
        f"show_age_threshold = {n['show_age']}",
        f"idle_threshold = {n['idle_pause']}",
        "ellipsize = middle",
        f"stack_duplicates = {str(n['stack_duplicates']).lower()}",
        f"show_indicators = {'yes' if n['show_indicators'] else 'no'}",
        "enable_recursive_icon_lookup = true",
        f"icon_theme = {_q(themes)}",
        f"icon_position = {n['icon_position']}",
        "min_icon_size = 16",
        f"max_icon_size = {n['icon_size']}",
        f"sticky_history = {'yes' if n['sticky_history'] else 'no'}",
        f"history_length = {n['history_length']}",
        f"dmenu = {_menu()}",
        "browser = xdg-open",
        "always_run_script = true",
        "title = Dunst",
        "class = Dunst",
        f"corner_radius = {n['corner_radius']}",
        f"mouse_left_click = {n['left_click']}",
        f"mouse_middle_click = {n['middle_click']}",
        f"mouse_right_click = {n['right_click']}",
    ]
    extra_global, extra_sections = _split_extra(n["extra"])
    keys = {ln.split("=", 1)[0].strip() for ln in extra_global}
    g = [ln for ln in g if ln.split("=", 1)[0].strip() not in keys] + extra_global

    L = ["# Generated by XControl (Notifications page). It's rewritten on every change; edits here are lost.",
         "# Your own ~/.config/dunst/dunstrc isn't used while XControl runs dunst.", "", "[global]"]
    L += ["    " + ln for ln in g]
    for u in URGENCIES:
        bg, fg, frame = n["colors"][u]
        L += ["", f"[urgency_{u}]", f"    background = {_q(bg)}", f"    foreground = {_q(fg)}",
              f"    frame_color = {_q(frame)}", f"    highlight = {_q(frame)}", f"    timeout = {n['timeouts'][u]}"]
        if u == "critical" and levels and n["critical_in_dnd"]:
            L.append(f"    override_pause_level = {DND_LEVEL + 10}")
    if n["sound"]:
        L += ["", "[xcontrol_sound]", "    msg_urgency = normal", f"    script = {_q(sound_script())}",
              "", "[xcontrol_sound_critical]", "    msg_urgency = critical", f"    script = {_q(sound_script())}"]
    for i, r in enumerate(n["rules"], 1):
        L += ["", f"[xcontrol_rule_{i}]", f"    appname = {_q(r['app'])}"]
        L += ["    " + ln for ln in {
            "hide": ["skip_display = true", "history_ignore = true"],
            "history_only": ["skip_display = true"],
            "no_timeout": ["timeout = 0"],
            "low": ["urgency = low"],
            "critical": ["urgency = critical"],
            "no_sound": ["script = \"\""],
        }[r["action"]]]
    for name, lines in extra_sections:
        L += ["", f"[{name}]"] + ["    " + ln for ln in lines]
    return "\n".join(L) + "\n"


def _split_extra(text):
    """Extra lines: before any [section] they go to [global]."""
    glob_lines, sections, cur = [], [], None
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s or s.startswith(("#", ";")):
            continue
        m = re.match(r"^\[(.+)\]$", s)
        if m:
            cur = (m.group(1).strip(), [])
            sections.append(cur)
        elif cur:
            cur[1].append(s)
        elif "=" in s:
            glob_lines.append(s)
    return glob_lines, sections


def sound_script():
    return os.path.join(config_dir(), "notification-sound.sh")


def write_sound_script(n):
    """dunst runs a script per notification; this one plays the chosen sound."""
    if not n["sound"]:
        return
    player = next((p for p in ("pw-play", "paplay", "aplay") if shutil.which(p)), "paplay")
    path = sound_script()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("#!/bin/sh\n# Written by XControl: the notification sound.\n"
                f"exec {player} {_shq(n['sound'])} >/dev/null 2>&1\n")
    os.chmod(path, 0o755)


def _shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def write(n, **kw):
    """Write the config if it changed; True when it did."""
    write_sound_script(n)
    text = generate(n, **kw)
    path = config_path()
    try:
        with open(path) as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)
    return True


def command():
    return ["dunst", "-config", config_path()]


# ---------------------------------------------------------------- the session bus
def owner():
    """(pid, program name) of whatever shows notifications now, or None."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        name = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                             "GetNameOwner", GLib.Variant("(s)", ("org.freedesktop.Notifications",)),
                             None, 0, 2000, None).unpack()[0]
        pid = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                            "GetConnectionUnixProcessID", GLib.Variant("(s)", (name,)),
                            None, 0, 2000, None).unpack()[0]
    except Exception:  # noqa: BLE001 - nobody owns it, or no session bus
        return None
    try:
        with open(f"/proc/{pid}/comm") as f:
            comm = f.read().strip()
    except OSError:
        comm = "?"
    return pid, comm


def send_test(urgency="normal", summary="", body=""):
    """Show a notification through whatever daemon runs (no notify-send needed)."""
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    level = {"low": 0, "normal": 1, "critical": 2}[urgency]
    bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                  "org.freedesktop.Notifications", "Notify",
                  GLib.Variant("(susssasa{sv}i)", ("XControl", 0, "dialog-information", summary, body,
                                                   [], {"urgency": GLib.Variant("y", level)}, -1)),
                  None, 0, 5000, None)


def dunstctl(*args):
    """Run dunstctl; its output, or None when that didn't work."""
    if not shutil.which("dunstctl"):
        return None
    try:
        r = subprocess.run(["dunstctl", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def paused():
    level = dunstctl("get-pause-level")
    if level is not None and level.isdigit():
        return int(level) > 0
    return dunstctl("is-paused") == "true"


def set_paused(on):
    """Do not disturb: notifications wait (and show when it's turned off); critical ones still
    show when the setting allows it (pause levels, dunst 1.10+)."""
    if dunstctl("get-pause-level") is not None:
        return dunstctl("set-pause-level", str(DND_LEVEL if on else 0)) is not None
    return dunstctl("set-paused", "true" if on else "false") is not None
