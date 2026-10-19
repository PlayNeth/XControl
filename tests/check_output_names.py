"""Saved per-output settings follow the connector when the X driver renames outputs."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import output_names as O  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


for name, want in [
    ("DisplayPort-0", {"DP-1"}), ("DisplayPort-2", {"DP-3"}), ("HDMI-A-0", {"HDMI-A-1"}),
    ("DP-1", {"DP-1"}), ("HDMI-1", {"HDMI-A-1"}), ("DP1", {"DP-1"}), ("HDMI2", {"HDMI-A-2"}),
    ("VGA-0", {"VGA-1"}), ("VGA-1", {"VGA-1", "VGA-2"}), ("DVI-D-0", {"DVI-D-1"}),
    ("eDP-1", {"eDP-1", "eDP-2"}), ("DP-1-1", set()), ("default", set()),
]:
    expect(f"kernel_candidates({name})", O.kernel_candidates(name), want)

# amdgpu -> modesetting
disp = {"custom_modes": {"DisplayPort-0": [{"w": 1}], "HDMI-A-0": [{"w": 2}]},
        "edid_ignored": ["DisplayPort-0"],
        "command": ["xrandr", "--output", "DisplayPort-0", "--mode", "1024x768",
                    "--output", "HDMI-A-0", "--off"]}
r = O.migrate(disp, {"DP-1": "DP-1", "HDMI-1": "HDMI-A-1"})
expect("renames", r, {"DisplayPort-0": "DP-1", "HDMI-A-0": "HDMI-1"})
expect("custom_modes", disp["custom_modes"], {"DP-1": [{"w": 1}], "HDMI-1": [{"w": 2}]})
expect("edid_ignored", disp["edid_ignored"], ["DP-1"])
expect("command", disp["command"], ["xrandr", "--output", "DP-1", "--mode", "1024x768",
                                    "--output", "HDMI-1", "--off"])
# and back (modesetting -> amdgpu)
r = O.migrate(disp, {"DisplayPort-0": "DP-1", "HDMI-A-0": "HDMI-A-1"})
expect("renames back", r, {"DP-1": "DisplayPort-0", "HDMI-1": "HDMI-A-0"})
# nothing to do when names still exist; never overwrite an existing entry
disp = {"custom_modes": {"DP-1": [1], "DisplayPort-0": [2]}, "edid_ignored": [], "command": []}
expect("no clobber", O.migrate(disp, {"DP-1": "DP-1"}), {})
expect("no clobber kept", disp["custom_modes"], {"DP-1": [1], "DisplayPort-0": [2]})
# ambiguous: VGA-1 could be kernel VGA-1 or VGA-2, both connected under new names
disp = {"custom_modes": {"VGA-1": [1]}, "edid_ignored": [], "command": []}
expect("ambiguous", O.migrate(disp, {"VGA-0": "VGA-1", "VGA-9": "VGA-2"}), {})

print("check_output_names:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
