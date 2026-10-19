"""XControl's own polybar: settings -> ~/.config/xcontrol/polybar.ini.

The file is generated from scratch every time (it's XControl's, not yours to edit), and
polybar runs with --reload, so a new file shows right away. One bar per display, started by
the desktop service (xcontrol --session), with MONITOR telling each bar where it goes.
"""
import glob
import os
import re
import shutil
import subprocess

from .paths import config_dir

POSITIONS = ["left", "center", "right"]
# id: (polybar module type, label)
MODULES = {
    "workspaces": "internal/i3",
    "title": "internal/xwindow",
    "clock": "internal/date",
    "cpu": "internal/cpu",
    "memory": "internal/memory",
    "temperature": "internal/temperature",
    "volume": "internal/pulseaudio",
    "network": "internal/network",
    "disk": "internal/fs",
    "keyboard": "internal/xkeyboard",
    "battery": "internal/battery",
    "tray": "internal/tray",
}
DEFAULT_MODULES = [  # [id, position, enabled], in order
    ["workspaces", "left", True], ["title", "left", True],
    ["cpu", "right", True], ["memory", "right", True], ["temperature", "right", False],
    ["volume", "right", True], ["network", "right", False], ["disk", "right", False],
    ["keyboard", "right", False], ["battery", "right", True], ["tray", "right", True],
    ["clock", "right", True],
]
DEFAULT = {
    "enabled": False, "position": "bottom", "height": 24, "displays": "all",
    "font": "Sans 10", "labels": "words",
    "background": "#282a2e", "opacity": 100, "foreground": "#c5c8c6", "accent": "#f0c674",
    "urgent": "#a54242", "dim": "#707880",
    "modules": DEFAULT_MODULES,
    "clock_format": "%H:%M", "clock_alt": "%a %d %b %Y", "temp_warn": 80, "disk_mount": "/",
}
CLOCK_FORMATS = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%a %H:%M", "%a %d %b  %H:%M", "%d/%m %H:%M"]

# icons from Nerd Fonts (used only when one is installed and chosen)
ICONS = {"cpu": " ", "memory": " ", "temperature": " ", "volume": " ",
         "muted": " ", "network": " ", "disk": " ", "keyboard": " ",
         "battery": " ", "charging": " ", "clock": " "}
WORDS = {"cpu": "CPU ", "memory": "RAM ", "temperature": "TEMP ", "volume": "VOL ", "muted": "muted",
         "network": "NET ", "disk": "DISK ", "keyboard": "", "battery": "BAT ", "charging": "CHG ", "clock": ""}


def normalize(b):
    out = {k: (list(map(list, v)) if k == "modules" else v) for k, v in DEFAULT.items()}
    if isinstance(b, dict):
        for k, v in b.items():
            if k in DEFAULT and k != "modules":
                out[k] = v
        mods = b.get("modules")
        if isinstance(mods, list):
            seen, clean = set(), []
            for m in mods:
                if isinstance(m, (list, tuple)) and len(m) == 3 and m[0] in MODULES and m[0] not in seen \
                        and m[1] in POSITIONS:
                    clean.append([m[0], m[1], bool(m[2])])
                    seen.add(m[0])
            # modules added in later versions show up in the list, switched off
            clean += [[m[0], m[1], False] for m in DEFAULT_MODULES if m[0] not in seen]
            out["modules"] = clean
    if out["position"] not in ("top", "bottom"):
        out["position"] = "bottom"
    if out["displays"] not in ("all", "primary"):
        out["displays"] = "all"
    out["height"] = max(16, min(64, int(out["height"] or 24)))
    out["opacity"] = max(0, min(100, int(out["opacity"] if out["opacity"] is not None else 100)))
    return out


def config_path():
    return os.path.join(config_dir(), "polybar.ini")


# ---------------------------------------------------------------- what this system has
def version():
    try:
        out = subprocess.run(["polybar", "--version"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"polybar (\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def nerd_font():
    """The family name of an installed Nerd Font, or None."""
    if not shutil.which("fc-list"):
        return None
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    fams = sorted({f.split(",")[0].strip() for f in out.splitlines() if "nerd font" in f.lower()})
    mono = [f for f in fams if "mono" in f.lower() and "propo" not in f.lower()]
    return (mono or fams or [None])[0]


def cpu_temp_path(root="/"):
    """The CPU temperature input (k10temp Tctl, coretemp package...) as it is right now;
    hwmon numbers change between boots, which is fine since the file is regenerated."""
    best = None
    for d in sorted(glob.glob(os.path.join(root, "sys/class/hwmon/hwmon*"))):
        try:
            with open(os.path.join(d, "name")) as f:
                name = f.read().strip()
        except OSError:
            continue
        rank = {"k10temp": 0, "zenpower": 0, "coretemp": 1, "cpu_thermal": 2, "acpitz": 3}.get(name)
        if rank is None or not os.path.exists(os.path.join(d, "temp1_input")):
            continue
        if best is None or rank < best[0]:
            best = (rank, os.path.realpath(os.path.join(d, "temp1_input")))
    return best[1] if best else None


def _supply_type(d):
    try:
        with open(os.path.join(d, "type")) as f:
            return f.read().strip()
    except OSError:
        return ""


def battery(root="/"):
    """(battery, adapter) names, or None without a battery."""
    supplies = sorted(glob.glob(os.path.join(root, "sys/class/power_supply/*")))
    bats = [os.path.basename(d) for d in supplies if _supply_type(d) == "Battery"]
    if not bats:
        return None
    mains = [os.path.basename(d) for d in supplies if _supply_type(d) == "Mains"]
    return bats[0], (mains[0] if mains else "AC")


def network_kind(root="/"):
    """'wired' or 'wireless': the kind of the first physical interface that's up."""
    kinds = []
    for d in sorted(glob.glob(os.path.join(root, "sys/class/net/*"))):
        if not os.path.exists(os.path.join(d, "device")):
            continue
        wireless = os.path.exists(os.path.join(d, "wireless"))
        try:
            with open(os.path.join(d, "operstate")) as f:
                up = f.read().strip() == "up"
        except OSError:
            up = False
        kinds.append((not up, "wireless" if wireless else "wired"))
    return sorted(kinds)[0][1] if kinds else "wired"


# ---------------------------------------------------------------- the file
def _font(desc):
    """'Inter Medium 10' (Pango) -> 'Inter Medium:size=10'."""
    m = re.match(r"^(.*?)[ ,]+(\d+(?:\.\d+)?)$", (desc or "").strip())
    family, size = (m.group(1), m.group(2)) if m else ((desc or "Sans").strip() or "Sans", "10")
    return f"{family}:size={size}"


def _argb(color, opacity):
    c = (color or "#000000").lstrip("#")[:6].rjust(6, "0")
    return f"#{round(opacity * 2.55):02x}{c}" if opacity < 100 else f"#{c}"


def available(b, ver=None, root="/"):
    """Modules that can work here (battery only with a battery, tray needs polybar 3.7)."""
    ver = ver if ver is not None else version()
    out = set(MODULES)
    if not battery(root):
        out.discard("battery")
    if ver and ver < (3, 7):
        out.discard("tray")  # older polybar: the tray is a bar setting, added below instead
    return out


def generate(b, ver=None, nerd=None, root="/", has_pavu=None):
    """The polybar config text for settings `b` (normalized)."""
    ver = ver if ver is not None else version()
    nerd = nerd_font() if nerd is None else (nerd or None)
    use_icons = b["labels"] == "icons" and nerd
    L = ICONS if use_icons else WORDS
    can = available(b, ver, root)
    on = [m for m in b["modules"] if m[2] and m[0] in can]
    lists = {p: " ".join(m[0] for m in on if m[1] == p) for p in POSITIONS}
    tray_old = ver is not None and ver < (3, 7) and any(m[0] == "tray" and m[2] for m in b["modules"])
    pad = max(2, (b["height"] - 12) // 4)

    lines = [
        "; Generated by XControl (Bar & Compositor page). It's rewritten on every change;",
        "; edits here are lost. Your own polybar config isn't used while XControl runs the bar.",
        "",
        "[colors]",
        f"background = {_argb(b['background'], b['opacity'])}",
        f"background-alt = {_argb(_mix(b['background'], b['foreground'], 0.12), max(b['opacity'], 60))}",
        f"foreground = {b['foreground']}",
        f"primary = {b['accent']}",
        f"alert = {b['urgent']}",
        f"disabled = {b['dim']}",
        "",
        "[bar/xcontrol]",
        "monitor = ${env:MONITOR:}",
        "width = 100%",
        f"height = {b['height']}",
        f"bottom = {'true' if b['position'] == 'bottom' else 'false'}",
        "background = ${colors.background}",
        "foreground = ${colors.foreground}",
        "line-size = 2",
        "padding-left = 0",
        "padding-right = 1",
        "module-margin = 1",
        "separator = |",
        "separator-foreground = ${colors.disabled}",
        f"font-0 = \"{_font(b['font'])};{pad}\"",
    ]
    if use_icons:
        size = re.search(r"size=(\d+(?:\.\d+)?)", _font(b["font"])).group(1)
        lines.append(f"font-1 = \"{nerd}:size={size};{pad}\"")
    lines += [
        f"modules-left = {lists['left']}",
        f"modules-center = {lists['center']}",
        f"modules-right = {lists['right']}",
        "cursor-click = pointer",
        "enable-ipc = true",
    ]
    if tray_old:
        lines += ["tray-position = right", "tray-padding = 2", "tray-background = ${colors.background}"]
    lines.append("")

    def module(mid, *body):
        lines.extend([f"[module/{mid}]", f"type = {MODULES[mid]}", *body, ""])

    prefix = "format-prefix-foreground = ${colors.primary}"
    for mid, _pos, enabled in b["modules"]:
        if not enabled or mid not in can:
            continue
        if mid == "workspaces":
            module(mid, "pin-workspaces = true", "index-sort = true", "enable-click = true", "enable-scroll = false",
                   "label-mode-padding = 1", "label-mode-background = ${colors.alert}",
                   "label-focused = %name%", "label-focused-background = ${colors.background-alt}",
                   "label-focused-underline = ${colors.primary}", "label-focused-padding = 1",
                   "label-unfocused = %name%", "label-unfocused-padding = 1",
                   "label-visible = %name%", "label-visible-padding = 1",
                   "label-urgent = %name%", "label-urgent-background = ${colors.alert}", "label-urgent-padding = 1")
        elif mid == "title":
            module(mid, "label = %title:0:60:...%")
        elif mid == "clock":
            module(mid, "interval = 1", f"date = {b['clock_format']}", f"date-alt = {b['clock_alt']}",
                   f"format-prefix = \"{L['clock']}\"", prefix, "label = %date%")
        elif mid == "cpu":
            module(mid, "interval = 2", f"format-prefix = \"{L['cpu']}\"", prefix, "label = %percentage:2%%")
        elif mid == "memory":
            module(mid, "interval = 2", f"format-prefix = \"{L['memory']}\"", prefix, "label = %percentage_used:2%%")
        elif mid == "temperature":
            path = cpu_temp_path(root)
            module(mid, *( [f"hwmon-path = {path}"] if path else ["thermal-zone = 0"]),
                   f"warn-temperature = {int(b['temp_warn'])}", f"format-prefix = \"{L['temperature']}\"", prefix,
                   f"format-warn-prefix = \"{L['temperature']}\"", "format-warn-prefix-foreground = ${colors.alert}",
                   "label = %temperature-c%", "label-warn = %temperature-c%", "label-warn-foreground = ${colors.alert}")
        elif mid == "volume":
            pavu = shutil.which("pavucontrol") if has_pavu is None else has_pavu
            module(mid, f"format-volume-prefix = \"{L['volume']}\"",
                   "format-volume-prefix-foreground = ${colors.primary}", "format-volume = <label-volume>",
                   "label-volume = %percentage%%", f"label-muted = \"{L['muted'].strip() or 'muted'}\"",
                   "label-muted-foreground = ${colors.disabled}", *(["click-right = pavucontrol"] if pavu else []))
        elif mid == "network":
            module(mid, f"interface-type = {network_kind(root)}", "interval = 3",
                   f"format-connected-prefix = \"{L['network']}\"", "format-connected-prefix-foreground = ${colors.primary}",
                   "label-connected = %local_ip%", "label-disconnected = offline",
                   "label-disconnected-foreground = ${colors.disabled}")
        elif mid == "disk":
            module(mid, "interval = 25", f"mount-0 = {b['disk_mount']}",
                   f"label-mounted = \"%{{F{b['accent']}}}{L['disk']}%{{F-}}%percentage_used%%\"",
                   "label-unmounted = %mountpoint% not mounted", "label-unmounted-foreground = ${colors.disabled}")
        elif mid == "keyboard":
            module(mid, "blacklist-0 = num lock", "blacklist-1 = scroll lock", "label-layout = %layout%",
                   "label-layout-foreground = ${colors.primary}", "label-indicator-padding = 1",
                   "label-indicator-background = ${colors.background-alt}")
        elif mid == "battery":
            bat, ac = battery(root) or ("BAT0", "AC")
            module(mid, f"battery = {bat}", f"adapter = {ac}", "full-at = 98",
                   f"format-charging-prefix = \"{L['charging']}\"", "format-charging-prefix-foreground = ${colors.primary}",
                   f"format-discharging-prefix = \"{L['battery']}\"",
                   "format-discharging-prefix-foreground = ${colors.primary}",
                   "label-charging = %percentage%%", "label-discharging = %percentage%%", "label-full = full")
        elif mid == "tray":
            module(mid, "tray-spacing = 6px", "tray-padding = 2px")
    return "\n".join(lines) + "\n"


def _mix(a, b, t):
    ca = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def write(b, **kw):
    """Write the config if it changed; returns True when it did."""
    text = generate(b, **kw)
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


def command(monitor_name):
    """How the service starts one bar."""
    return ["polybar", "--reload", "--quiet", f"--config={config_path()}", "xcontrol"], dict(MONITOR=monitor_name)
