"""Bar (polybar) and compositor (picom) config generation, and conflict detection."""
import os
import shutil
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, ".config"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import bar as B, compositor as C, desktop as D  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def mk(path, text=""):
    full = os.path.join(tmp, path.lstrip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)


def ini(text):
    """{section: {key: value}} of a polybar file (enough to check it)."""
    out, sec = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            sec = out.setdefault(line[1:-1], {})
        elif "=" in line and sec is not None and not line.startswith(";"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip()
    return out


# ---- fake hardware for the modules that look at it
mk("/sys/class/hwmon/hwmon3/name", "k10temp")
mk("/sys/class/hwmon/hwmon3/temp1_input", "45000")
mk("/sys/class/hwmon/hwmon0/name", "acpitz")
mk("/sys/class/hwmon/hwmon0/temp1_input", "30000")
mk("/sys/class/power_supply/AC0/type", "Mains")
mk("/sys/class/power_supply/BAT1/type", "Battery")
mk("/sys/class/net/enp5s0/operstate", "up")
os.makedirs(os.path.join(tmp, "sys/class/net/enp5s0/device"))
mk("/sys/class/net/wlan0/operstate", "down")
os.makedirs(os.path.join(tmp, "sys/class/net/wlan0/device"))
os.makedirs(os.path.join(tmp, "sys/class/net/wlan0/wireless"))
root = tmp

b = B.normalize({"position": "top", "height": 30, "font": "Inter Medium 11", "opacity": 80,
                 "modules": [["clock", "center", True], ["workspaces", "left", True], ["temperature", "right", True],
                             ["battery", "right", True], ["network", "right", True], ["tray", "right", True],
                             ["cpu", "right", False], ["bogus", "left", True]]})
expect("unknown modules dropped, missing ones added", sorted(m[0] for m in b["modules"]), sorted(B.MODULES))
cfg = ini(B.generate(b, ver=(3, 7), nerd="", root=root, has_pavu=False))
bar = cfg["bar/xcontrol"]
expect("position/height", (bar["bottom"], bar["height"]), ("false", "30"))
expect("font", bar["font-0"], '"Inter Medium:size=11;4"')
expect("module lists", (bar["modules-left"], bar["modules-center"], bar["modules-right"]),
       ("i3", "date", "temperature battery network systray"))
expect("disabled module not defined", "module/cpu" in cfg, False)
expect("see-through background", cfg["colors"]["background"], "#cc282a2e")
expect("temperature from k10temp", cfg["module/temperature"]["hwmon-path"],
       os.path.realpath(os.path.join(tmp, "sys/class/hwmon/hwmon3/temp1_input")))
expect("battery names", (cfg["module/battery"]["battery"], cfg["module/battery"]["adapter"]), ("BAT1", "AC0"))
expect("network kind of the connected interface", cfg["module/network"]["interface-type"], "wired")
expect("tray module on 3.7", cfg["module/systray"]["type"], "internal/tray")
expect("per-display bars", bar["monitor"], "${env:MONITOR:}")
old = ini(B.generate(b, ver=(3, 6), nerd="", root=root, has_pavu=False))
expect("tray on older polybar", ("tray-position" in old["bar/xcontrol"], "systray" in old["bar/xcontrol"]["modules-right"]),
       (True, False))
icons = B.generate(B.normalize({"labels": "icons"}), ver=(3, 7), nerd="Symbols Nerd Font Mono", root=root,
                   has_pavu=False)
expect("icon font added", 'font-1 = "Symbols Nerd Font Mono:size=10;3"' in icons, True)
words = B.generate(B.normalize({"labels": "icons"}), ver=(3, 7), nerd="", root=root, has_pavu=False)
expect("icons need a Nerd Font", ("font-1" in words, 'format-prefix = "CPU "' in words), (False, True))
expect("no battery: no module", "module/battery" in B.generate(B.normalize({}), ver=(3, 7), nerd="", root="/nowhere",
                                                                has_pavu=False), False)
cmd, env = B.command("DP-2")
expect("bar command", (cmd[-1], env), ("xcontrol", {"MONITOR": "DP-2"}))
expect("config option form", cmd[3].startswith("--config="), True)
expect("write only when changed", (B.write(b, ver=(3, 7), nerd="", root=root, has_pavu=False),
                                   B.write(b, ver=(3, 7), nerd="", root=root, has_pavu=False)), (True, False))

expect("session language", (B.system_locale({"LANG": "pt_BR.UTF-8"}), B.system_locale({"LC_ALL": "C.UTF-8"}),
                            B.system_locale({"LC_TIME": "de_DE.UTF-8", "LANG": "en_US.UTF-8"}), B.system_locale({})),
       ("pt_BR.UTF-8", None, "de_DE.UTF-8", None))
os.environ["LANG"] = "pt_BR.UTF-8"
os.environ.pop("LC_ALL", None)
os.environ.pop("LC_TIME", None)
barsec = ini(B.generate(B.normalize({}), ver=(3, 7), nerd="", root=root, has_pavu=False))["bar/xcontrol"]
expect("dates follow the system language (set on the bar)", barsec.get("locale"), "pt_BR.UTF-8")
barsec = ini(B.generate(B.normalize({"clock_locale": "en_GB.UTF-8"}), ver=(3, 7), nerd="", root=root,
                        has_pavu=False))["bar/xcontrol"]
expect("chosen clock language", barsec.get("locale"), "en_GB.UTF-8")

# ---- every module's options, the i3 module in full, extra lines
full = B.normalize({
    "height": 21, "height_unit": "pt", "radius": 6, "separator": " | ", "scroll_workspaces": True,
    "modules": [["workspaces", "left", True], ["title", "left", True], ["keyboard", "right", True],
                ["memory", "right", True], ["volume", "right", True], ["tray", "right", True], ["clock", "right", True]],
    "options": {"workspaces": {"label": "index", "strip_wsnumbers": True, "separator": "|", "focused_fg": "#ffffff",
                               "focused_bg": "#3f3f3f", "focused_underline": "#fba922", "visible_underline": "#555555",
                               "urgent_fg": "#000000", "urgent_bg": "#bd2c40", "mode_bg": "#e60053", "bogus": 1},
                "title": {"max_length": 30}, "keyboard": {"show_layout": False},
                "volume": {"right_click": "alacritty -e wiremix", "step": 2}, "memory": {"show": "amount"},
                "tray": {"spacing": 8, "margin": 4}, "clock": {"format": "%H:%M ", "alt": "%a, %d. %b  %H:%M "}},
    "extra": {"workspaces": "fuzzy-match = true\nlabel-focused-padding = 2\n; a comment",
              "bar": "cursor-scroll = ns-resize", "nonsense": "x = 1"}})
cfg = ini(B.generate(full, ver=(3, 7), nerd="", root=root, has_pavu=False))
bar = cfg["bar/xcontrol"]
expect("height in points, radius", (bar["height"], bar["radius"]), ("21pt", "6"))
expect("separator with spaces kept", bar["separator"], '" | "')
expect("bar scroll switches workspaces", bar["scroll-down"], "i3-msg -q workspace next_on_output")
expect("bar extra replaces the generated line", bar["cursor-scroll"], "ns-resize")
i3 = cfg["module/i3"]
expect("i3 type", i3["type"], "internal/i3")
expect("i3 labels by number", (i3["label-focused"], i3["label-urgent"]), ("%index%", "%index%"))
expect("i3 parameters", (i3["strip-wsnumbers"], i3["show-urgent"], i3["pin-workspaces"], i3["wrapping-scroll"],
                          i3["format"], i3["label-separator"]),
       ("true", "true", "true", "false", "<label-state> <label-mode>", "|"))
expect("i3 colors", (i3["label-focused-foreground"], i3["label-focused-background"], i3["label-focused-underline"],
                     i3["label-visible-underline"], i3["label-urgent-foreground"], i3["label-urgent-background"],
                     i3["label-mode-background"]),
       ("#ffffff", "#3f3f3f", "#fba922", "#555555", "#000000", "#bd2c40", "#e60053"))
expect("module extra wins and adds", (i3["label-focused-padding"], i3["fuzzy-match"]), ("2", "true"))
expect("unknown option ignored", "bogus" in str(i3), False)
expect("title length", cfg["module/title"]["label-maxlen"], "30")
expect("keyboard: indicators only", cfg["module/xkeyboard"]["label-layout"], "")
expect("volume", (cfg["module/pulseaudio"]["click-right"], cfg["module/pulseaudio"]["interval"]),
       ("alacritty -e wiremix", "2"))
expect("memory as amount", cfg["module/memory"]["label"], "%gb_used%/%gb_total%")
expect("tray spacing", (cfg["module/systray"]["tray-spacing"], cfg["module/systray"]["format-margin"]), ("8pt", "4pt"))
expect("clock format keeps its trailing space (quoted)", cfg["module/date"]["date"], '"%H:%M "')
expect("extras for unknown sections dropped", "nonsense" in full["extra"], False)
legacy = B.normalize({"clock_format": "%H.%M", "temp_warn": 70, "disk_mount": "/home"})
expect("pre-0.18 settings carried over", (B.module_options(legacy, "clock")["format"],
                                          B.module_options(legacy, "temperature")["warn"],
                                          B.module_options(legacy, "disk")["mount"]), ("%H.%M", 70, "/home"))
expect("defaults stay neutral", (B.module_options(B.normalize({}), "workspaces")["label"],
                                 B.module_options(B.normalize({}), "workspaces")["focused_fg"]), ("name", ""))

# ---- picom
p = C.normalize({"backend": "glx", "blur": "medium", "corner_radius": 8, "inactive_opacity": 85,
                 "shadow_radius": 99, "fade_speed": 0})
text = C.generate(p, ver=(12, 5))
for want in ('backend = "glx";', "vsync = true;", "unredir-if-possible = true;", "corner-radius = 8;",
             "inactive-opacity = 0.85;", 'blur-method = "dual_kawase";', "blur-strength = 5;",
             "shadow-radius = 40;", "shadow-offset-x = -40;", "fade-in-step = 0.01;", '"_GTK_FRAME_EXTENTS@"'):
    expect(f"picom has {want}", want in text, True)
expect("xrender: no blur", "blur-method" in C.generate(C.normalize({"backend": "xrender", "blur": "strong"}), ver=(12, 0)),
       False)
expect("egl needs picom 10", 'backend = "glx";' in C.generate(C.normalize({"backend": "egl"}), ver=(9, 1)), True)
expect("type suffix only before picom 12", ('"_GTK_FRAME_EXTENTS@:c"' in text,
                                            '"_GTK_FRAME_EXTENTS@:c"' in C.generate(p, ver=(11, 2))), (False, True))
expect("braces balanced", text.count("{") == text.count("}") and text.count("[") == text.count("]"), True)

# ---- the service decides what to run
desk = D.normalize({"bar": {"enabled": True, "displays": "all"}, "picom": {"enabled": True}})
expect("service wanted for bar/picom", D.wanted(desk), True)
expect("nothing on: no service", D.wanted(D.normalize({})), False)

# ---- i3 config conflicts
mk("/.config/i3/config", "exec --no-startup-id ~/.config/polybar/launch.sh\nexec_always picom -b\n"
   "exec --no-startup-id xcontrol --session\nbar {\n    status_command i3status\n}\n")
expect("conflicts", [k for k, _l in D.session_conflicts()], ["bar", "compositor", "i3bar"])

# the generic workspaces module (other window managers), next to i3's
b = B.normalize({"enabled": True, "modules": [["workspaces", "left", False], ["xworkspaces", "left", True]],
                 "options": {"xworkspaces": {"label": "index", "show_empty": False}}})
x = ini(B.generate(b, ver=(3, 7), nerd="", has_pavu=False))
expect("xworkspaces type", x.get("module/xworkspaces", {}).get("type"), "internal/xworkspaces")
expect("xworkspaces in the bar", x["bar/xcontrol"]["modules-left"].split()[0], "xworkspaces")
expect("xworkspaces label", x["module/xworkspaces"]["label-active"], "%index%")
expect("no i3 module", "module/i3" in x, False)
mods = B.normalize({"modules": [["clock", "left", True], ["workspaces", "right", True]]})["modules"]
expect("added after workspaces, same side", mods[2], ["xworkspaces", "right", False])

print("check_panel:", "FAILED" if bad else "ok")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
