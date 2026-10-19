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
       ("workspaces", "clock", "temperature battery network tray"))
expect("disabled module not defined", "module/cpu" in cfg, False)
expect("see-through background", cfg["colors"]["background"], "#cc282a2e")
expect("temperature from k10temp", cfg["module/temperature"]["hwmon-path"],
       os.path.realpath(os.path.join(tmp, "sys/class/hwmon/hwmon3/temp1_input")))
expect("battery names", (cfg["module/battery"]["battery"], cfg["module/battery"]["adapter"]), ("BAT1", "AC0"))
expect("network kind of the connected interface", cfg["module/network"]["interface-type"], "wired")
expect("tray module on 3.7", cfg["module/tray"]["type"], "internal/tray")
expect("per-display bars", bar["monitor"], "${env:MONITOR:}")
old = ini(B.generate(b, ver=(3, 6), nerd="", root=root, has_pavu=False))
expect("tray on older polybar", ("tray-position" in old["bar/xcontrol"], "tray" in old["bar/xcontrol"]["modules-right"]),
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

# ---- picom
p = C.normalize({"backend": "glx", "blur": "medium", "corner_radius": 8, "inactive_opacity": 85,
                 "shadow_radius": 99, "fade_speed": 0})
text = C.generate(p, ver=(12, 5))
for want in ('backend = "glx";', "vsync = true;", "unredir-if-possible = true;", "corner-radius = 8;",
             "inactive-opacity = 0.85;", 'blur-method = "dual_kawase";', "blur-strength = 5;",
             "shadow-radius = 40;", "shadow-offset-x = -40;", "fade-in-step = 0.01;", '"_GTK_FRAME_EXTENTS@:c"'):
    expect(f"picom has {want}", want in text, True)
expect("xrender: no blur", "blur-method" in C.generate(C.normalize({"backend": "xrender", "blur": "strong"}), ver=(12, 0)),
       False)
expect("egl needs picom 10", 'backend = "glx";' in C.generate(C.normalize({"backend": "egl"}), ver=(9, 1)), True)
expect("braces balanced", text.count("{") == text.count("}") and text.count("[") == text.count("]"), True)

# ---- the service decides what to run
desk = D.normalize({"bar": {"enabled": True, "displays": "all"}, "picom": {"enabled": True}})
expect("service wanted for bar/picom", D.wanted(desk), True)
expect("nothing on: no service", D.wanted(D.normalize({})), False)

# ---- i3 config conflicts
mk("/.config/i3/config", "exec --no-startup-id ~/.config/polybar/launch.sh\nexec_always picom -b\n"
   "exec --no-startup-id xcontrol --session\nbar {\n    status_command i3status\n}\n")
expect("conflicts", [k for k, _l in D.session_conflicts()], ["bar", "compositor", "i3bar"])

print("check_panel:", "FAILED" if bad else "ok")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
