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
    "workspaces": "internal/i3",        # i3's own: modes, urgent workspaces, i3 workspace names
    "xworkspaces": "internal/xworkspaces",   # any EWMH window manager (bspwm, openbox, xfwm...)
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
    ["workspaces", "left", True], ["xworkspaces", "left", False], ["title", "left", True],
    ["cpu", "right", True], ["memory", "right", True], ["temperature", "right", False],
    ["volume", "right", True], ["network", "right", False], ["disk", "right", False],
    ["keyboard", "right", False], ["battery", "right", True], ["tray", "right", True],
    ["clock", "right", True],
]
# section names as polybar's own examples use them, so the generated file reads familiar
SECTIONS = {"workspaces": "i3", "xworkspaces": "xworkspaces", "title": "title", "clock": "date", "cpu": "cpu", "memory": "memory",
            "temperature": "temperature", "volume": "pulseaudio", "network": "network", "disk": "filesystem",
            "keyboard": "xkeyboard", "battery": "battery", "tray": "systray"}
DEFAULT = {
    "enabled": False, "position": "bottom", "height": 24, "height_unit": "px", "radius": 0,
    "displays": "all", "font": "Sans 10", "labels": "words", "separator": "|", "scroll_workspaces": False,
    "background": "#282a2e", "opacity": 100, "foreground": "#c5c8c6", "accent": "#f0c674",
    "secondary": "#8abeb7", "highlight": "", "urgent": "#a54242", "dim": "#707880",
    "modules": DEFAULT_MODULES,
    "options": {},        # {module: {option: value}}, see OPTIONS
    "extra": {},          # {"bar" or module: "polybar lines"} added as they are (they win)
    "clock_format": "%H:%M", "clock_alt": "%a %d %b %Y", "temp_warn": 80, "disk_mount": "/",  # before 0.18
    "clock_locale": "",   # "" = the session's language (LC_ALL, LC_TIME or LANG)
}
# per module: (option, kind, default). Kinds: bool, int, str, color ("" = the theme's), or a list of choices.
OPTIONS = {
    "workspaces": [
        ("label", ["name", "index"], "name"), ("pin_workspaces", "bool", True), ("show_urgent", "bool", True),
        ("strip_wsnumbers", "bool", False), ("index_sort", "bool", True), ("enable_click", "bool", True),
        ("enable_scroll", "bool", False), ("wrapping_scroll", "bool", False), ("reverse_scroll", "bool", False),
        ("separator", "str", ""), ("padding", "int", 1),
        ("focused_fg", "color", ""), ("focused_bg", "color", ""), ("focused_underline", "color", ""),
        ("unfocused_fg", "color", ""), ("visible_underline", "color", ""),
        ("urgent_fg", "color", ""), ("urgent_bg", "color", ""), ("mode_bg", "color", ""),
    ],
    "xworkspaces": [
        ("label", ["name", "index"], "name"), ("pin_workspaces", "bool", True), ("show_empty", "bool", True),
        ("enable_click", "bool", True), ("enable_scroll", "bool", False), ("reverse_scroll", "bool", False),
        ("padding", "int", 1),
        ("active_fg", "color", ""), ("active_bg", "color", ""), ("active_underline", "color", ""),
        ("occupied_fg", "color", ""), ("empty_fg", "color", ""), ("urgent_bg", "color", ""),
    ],
    "title": [("max_length", "int", 60)],
    "clock": [("format", "str", "%H:%M"), ("alt", "str", "%a %d %b %Y"), ("color", "color", "")],
    "cpu": [("interval", "int", 2)],
    "memory": [("show", ["percent", "amount"], "percent"), ("interval", "int", 2)],
    "temperature": [("warn", "int", 80), ("units", ["c", "f"], "c")],
    "volume": [("step", "int", 5), ("right_click", "str", "")],
    "network": [("kind", ["auto", "wired", "wireless"], "auto"), ("show", ["ip", "speed", "name"], "ip")],
    "disk": [("mount", "str", "/")],
    "keyboard": [("show_layout", "bool", True), ("show_indicators", "bool", True)],
    "battery": [("full_at", "int", 98)],
    "tray": [("spacing", "int", 6), ("margin", "int", 4), ("size", "int", 66)],
}


def module_options(b, mid):
    """This module's options with defaults filled in (and pre-0.18 settings carried over)."""
    opts = {k: d for k, _kind, d in OPTIONS.get(mid, [])}
    legacy = {"clock": {"format": b.get("clock_format"), "alt": b.get("clock_alt")},
              "temperature": {"warn": b.get("temp_warn")}, "disk": {"mount": b.get("disk_mount")}}.get(mid, {})
    opts.update({k: v for k, v in legacy.items() if v not in (None, "")})
    for k, v in (b.get("options") or {}).get(mid, {}).items():
        kind = next((kd for key, kd, _d in OPTIONS.get(mid, []) if key == k), None)
        if kind is None:
            continue
        if isinstance(kind, list):
            if v in kind:
                opts[k] = v
        elif kind == "bool":
            opts[k] = bool(v)
        elif kind == "int":
            try:
                opts[k] = int(v)
            except (TypeError, ValueError):
                pass
        else:
            opts[k] = str(v)
    return opts


def parse_extra(text):
    """'key = value' lines -> ordered [(key, line)]; comments and blanks skipped."""
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith((";", "#")) or "=" not in s:
            continue
        out.append((s.split("=", 1)[0].strip(), s))
    return out
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
            for k, m in enumerate(DEFAULT_MODULES):
                if m[0] not in seen:   # next to the module it follows by default
                    prev = DEFAULT_MODULES[k - 1][0] if k else None
                    at = next((i + 1 for i, c in enumerate(clean) if c[0] == prev), len(clean))
                    clean.insert(at, [m[0], clean[at - 1][1] if prev and at <= len(clean) and at > 0 else m[1], False])
                    seen.add(m[0])
            out["modules"] = clean
    out["options"] = {k: dict(v) for k, v in (out.get("options") or {}).items() if k in MODULES and isinstance(v, dict)}
    out["extra"] = {k: str(v) for k, v in (out.get("extra") or {}).items() if k == "bar" or k in MODULES}
    if out["height_unit"] not in ("px", "pt"):
        out["height_unit"] = "px"
    out["radius"] = max(0, min(30, int(out["radius"] or 0)))
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
def system_locale(env=None):
    """The language dates use in this session, e.g. 'pt_BR.UTF-8'; None for C/POSIX."""
    env = os.environ if env is None else env
    for var in ("LC_ALL", "LC_TIME", "LANG"):
        value = env.get(var, "").strip()
        if value:
            return None if value.split(".")[0] in ("C", "POSIX") else value
    return None


def locales():
    """UTF-8 locales installed (locale -a), as polybar wants them: 'pt_BR.UTF-8'."""
    try:
        out = subprocess.run(["locale", "-a"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for name in out.split():
        m = re.match(r"^([a-z]{2,3}_[A-Z]{2}(?:@\w+)?)\.(utf8|UTF-8)$", name)
        if m:
            found.append(m.group(1).split("@")[0] + ".UTF-8" + ("@" + m.group(1).split("@")[1]
                                                               if "@" in m.group(1) else ""))
    return sorted(set(found))


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
    names = {mid: SECTIONS[mid] for mid in MODULES}
    lists = {p: " ".join(names[m[0]] for m in on if m[1] == p) for p in POSITIONS}
    tray_old = ver is not None and ver < (3, 7) and any(m[0] == "tray" and m[2] for m in b["modules"])
    px = b["height"] if b["height_unit"] == "px" else round(b["height"] * 4 / 3)
    pad = max(2, (px - 12) // 4)
    unit = "pt" if b["height_unit"] == "pt" else ""
    extra = b.get("extra") or {}
    out = [
        "; Generated by XControl (Bar & Compositor page). It's rewritten on every change;",
        "; edits here are lost. Your own polybar config isn't used while XControl runs the bar.",
        "",
    ]

    def section(name, body, extra_text=""):
        """[name] with `body` lines; extra lines replace generated ones with the same key."""
        extras = parse_extra(extra_text)
        keys = {k for k, _l in extras}
        out.append(f"[{name}]")
        out.extend(line for line in body if line.split("=", 1)[0].strip() not in keys)
        if extras:
            out.append("; added on the page")
            out.extend(line for _k, line in extras)
        out.append("")

    section("colors", [
        f"background = {_argb(b['background'], b['opacity'])}",
        f"background-alt = {b['highlight'] or _argb(_mix(b['background'], b['foreground'], 0.12), max(b['opacity'], 60))}",
        f"foreground = {b['foreground']}",
        f"primary = {b['accent']}",
        f"secondary = {b['secondary']}",
        f"alert = {b['urgent']}",
        f"disabled = {b['dim']}",
    ])

    bar = [
        "monitor = ${env:MONITOR:}",
        "width = 100%",
        f"height = {b['height']}{unit}",
        f"radius = {b['radius']}",
        f"bottom = {'true' if b['position'] == 'bottom' else 'false'}",
        "background = ${colors.background}",
        "foreground = ${colors.foreground}",
        "line-size = 2",
        "padding-left = 0",
        "padding-right = 1",
        "module-margin = 1",
        _separator(b["separator"]),
        "separator-foreground = ${colors.disabled}",
        f"font-0 = \"{_font(b['font'])};{pad}\"",
    ]
    if use_icons:
        size = re.search(r"size=(\d+(?:\.\d+)?)", _font(b["font"])).group(1)
        bar.append(f"font-1 = \"{nerd}:size={size};{pad}\"")
    bar += [
        f"modules-left = {lists['left']}",
        f"modules-center = {lists['center']}",
        f"modules-right = {lists['right']}",
        "cursor-click = pointer",
        "cursor-scroll = default",
        "enable-ipc = true",
    ]
    if b["scroll_workspaces"]:
        bar += ["scroll-up = i3-msg -q workspace prev_on_output", "scroll-down = i3-msg -q workspace next_on_output"]
    loc = b["clock_locale"] or system_locale()
    if loc:  # polybar reads this from the bar, not the clock; without it dates come out in English
        bar.append(f"locale = {loc}")
    if tray_old:
        bar += ["tray-position = right", "tray-padding = 2", "tray-background = ${colors.background}"]
    section("bar/xcontrol", bar, extra.get("bar", ""))

    def col(value, fallback):
        return value or fallback

    for mid, _pos, enabled in b["modules"]:
        if not enabled or mid not in can:
            continue
        o = module_options(b, mid)
        body = [f"type = {MODULES[mid]}"]
        prefix = "format-prefix-foreground = ${colors.primary}"
        if mid == "workspaces":
            lab = "%index%" if o["label"] == "index" else "%name%"
            pad_ws = max(0, o["padding"])
            body += [
                f"pin-workspaces = {str(o['pin_workspaces']).lower()}",
                f"show-urgent = {str(o['show_urgent']).lower()}",
                f"strip-wsnumbers = {str(o['strip_wsnumbers']).lower()}",
                f"index-sort = {str(o['index_sort']).lower()}",
                f"enable-click = {str(o['enable_click']).lower()}",
                f"enable-scroll = {str(o['enable_scroll']).lower()}",
                f"wrapping-scroll = {str(o['wrapping_scroll']).lower()}",
                f"reverse-scroll = {str(o['reverse_scroll']).lower()}",
                "format = <label-state> <label-mode>",
                "label-mode = %mode%",
                f"label-mode-padding = {pad_ws + 1}",
                f"label-mode-background = {col(o['mode_bg'], '${colors.alert}')}",
                f"label-focused = {lab}",
                f"label-focused-foreground = {col(o['focused_fg'], '${colors.foreground}')}",
                f"label-focused-background = {col(o['focused_bg'], '${colors.background-alt}')}",
                f"label-focused-underline = {col(o['focused_underline'], '${colors.primary}')}",
                f"label-focused-padding = {pad_ws}",
                f"label-unfocused = {lab}",
                *([f"label-unfocused-foreground = {o['unfocused_fg']}"] if o["unfocused_fg"] else []),
                f"label-unfocused-padding = {pad_ws}",
                f"label-visible = {lab}",
                *([f"label-visible-underline = {o['visible_underline']}"] if o["visible_underline"] else []),
                f"label-visible-padding = {pad_ws}",
                f"label-urgent = {lab}",
                *([f"label-urgent-foreground = {o['urgent_fg']}"] if o["urgent_fg"] else []),
                f"label-urgent-background = {col(o['urgent_bg'], '${colors.alert}')}",
                f"label-urgent-padding = {pad_ws}",
            ]
            if o["separator"]:
                body += [f"label-separator = {_q(o['separator'])}", "label-separator-padding = 1",
                         "label-separator-foreground = ${colors.disabled}"]
        elif mid == "xworkspaces":
            lab = "%index%" if o["label"] == "index" else "%name%"
            pad_ws = max(0, o["padding"])
            body += [
                f"pin-workspaces = {str(o['pin_workspaces']).lower()}",
                f"enable-click = {str(o['enable_click']).lower()}",
                f"enable-scroll = {str(o['enable_scroll']).lower()}",
                f"reverse-scroll = {str(o['reverse_scroll']).lower()}",
                "format = <label-state>",
                f"label-active = {lab}",
                f"label-active-foreground = {col(o['active_fg'], '${colors.foreground}')}",
                f"label-active-background = {col(o['active_bg'], '${colors.background-alt}')}",
                f"label-active-underline = {col(o['active_underline'], '${colors.primary}')}",
                f"label-active-padding = {pad_ws}",
                f"label-occupied = {lab}",
                *([f"label-occupied-foreground = {o['occupied_fg']}"] if o["occupied_fg"] else []),
                f"label-occupied-padding = {pad_ws}",
                f"label-urgent = {lab}",
                f"label-urgent-background = {col(o['urgent_bg'], '${colors.alert}')}",
                f"label-urgent-padding = {pad_ws}",
                f"label-empty = {lab if o['show_empty'] else ''}",
                f"label-empty-foreground = {col(o['empty_fg'], '${colors.disabled}')}",
                f"label-empty-padding = {pad_ws if o['show_empty'] else 0}",
            ]
        elif mid == "title":
            body += ["label = %title%", f"label-maxlen = {max(5, o['max_length'])}"]
        elif mid == "clock":
            body += ["interval = 1", f"date = {_q(o['format'])}", f"date-alt = {_q(o['alt'])}",
                     f"format-prefix = \"{L['clock']}\"", prefix, "label = %date%",
                     *([f"label-foreground = {o['color']}"] if o["color"] else [])]
        elif mid == "cpu":
            body += [f"interval = {max(1, o['interval'])}", f"format-prefix = \"{L['cpu']}\"", prefix,
                     "label = %percentage:2%%"]
        elif mid == "memory":
            label = "%percentage_used:2%%" if o["show"] == "percent" else "%gb_used%/%gb_total%"
            body += [f"interval = {max(1, o['interval'])}", f"format-prefix = \"{L['memory']}\"", prefix,
                     f"label = {label}"]
        elif mid == "temperature":
            path = cpu_temp_path(root)
            u = "%temperature-c%" if o["units"] == "c" else "%temperature-f%"
            body += [*([f"hwmon-path = {path}"] if path else ["thermal-zone = 0"]),
                     f"warn-temperature = {int(o['warn'])}", f"format-prefix = \"{L['temperature']}\"", prefix,
                     f"format-warn-prefix = \"{L['temperature']}\"", "format-warn-prefix-foreground = ${colors.alert}",
                     f"label = {u}", f"label-warn = {u}", "label-warn-foreground = ${colors.alert}"]
        elif mid == "volume":
            pavu = shutil.which("pavucontrol") if has_pavu is None else has_pavu
            click = o["right_click"] or ("pavucontrol" if pavu else "")
            body += [f"interval = {max(1, o['step'])}",
                     f"format-volume-prefix = \"{L['volume']}\"", "format-volume-prefix-foreground = ${colors.primary}",
                     "format-volume = <label-volume>", "label-volume = %percentage%%",
                     f"label-muted = \"{L['muted'].strip() or 'muted'}\"", "label-muted-foreground = ${colors.disabled}",
                     *([f"click-right = {click}"] if click else [])]
        elif mid == "network":
            kind = network_kind(root) if o["kind"] == "auto" else o["kind"]
            label = {"ip": "%local_ip%", "speed": "%downspeed:9% %upspeed:9%", "name": "%ifname%"}[o["show"]]
            body += [f"interface-type = {kind}", "interval = 3",
                     f"format-connected-prefix = \"{L['network']}\"", "format-connected-prefix-foreground = ${colors.primary}",
                     f"label-connected = {label}", "label-disconnected = offline",
                     "label-disconnected-foreground = ${colors.disabled}"]
        elif mid == "disk":
            body += ["interval = 25", f"mount-0 = {o['mount']}",
                     f"label-mounted = \"%{{F{b['accent']}}}{L['disk']}%{{F-}}%percentage_used%%\"",
                     "label-unmounted = %mountpoint% not mounted", "label-unmounted-foreground = ${colors.disabled}"]
        elif mid == "keyboard":
            body += ["blacklist-0 = num lock", "blacklist-1 = scroll lock",
                     f"label-layout = {'%layout%' if o['show_layout'] else ''}",
                     "label-layout-foreground = ${colors.primary}",
                     *(["label-indicator-padding = 1", "label-indicator-margin = 1",
                        "label-indicator-foreground = ${colors.background}",
                        "label-indicator-background = ${colors.secondary}"] if o["show_indicators"] else
                       ["format = <label-layout>"])]
        elif mid == "battery":
            bat, ac = battery(root) or ("BAT0", "AC")
            body += [f"battery = {bat}", f"adapter = {ac}", f"full-at = {o['full_at']}",
                     f"format-charging-prefix = \"{L['charging']}\"", "format-charging-prefix-foreground = ${colors.primary}",
                     f"format-discharging-prefix = \"{L['battery']}\"",
                     "format-discharging-prefix-foreground = ${colors.primary}",
                     "label-charging = %percentage%%", "label-discharging = %percentage%%", "label-full = full"]
        elif mid == "tray":
            body += [f"format-margin = {max(0, o['margin'])}pt", f"tray-spacing = {max(0, o['spacing'])}pt",
                     f"tray-size = {max(20, min(100, o['size']))}%"]
        section(f"module/{names[mid]}", body, extra.get(mid, ""))
    return "\n".join(out)


def _q(value):
    """Quote values with leading/trailing spaces, which polybar would trim otherwise."""
    value = str(value)
    return f'"{value}"' if value != value.strip() else value


def _separator(text):
    """Between modules: '|' as is, text with spaces quoted so polybar keeps them, '' for none."""
    if not text:
        return "separator ="
    return f'separator = "{text}"' if text != text.strip() else f"separator = {text}"


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
