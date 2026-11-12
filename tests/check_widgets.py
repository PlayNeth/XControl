"""Sliders stop only on their steps."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import widgets as W  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


# the notched sliders (anti-aliasing, anisotropic filtering): positions 0..3
expect("between two notches, nearer the lower", W.snap_value(0, 3, 1, 1.45), 1)
expect("between two notches, nearer the upper", W.snap_value(0, 3, 1, 1.55), 2)
expect("below the range", W.snap_value(0, 3, 1, -0.7), 0)
expect("above the range", W.snap_value(0, 3, 1, 3.4), 3)
# steps that aren't 1, and a range that doesn't start at 0
expect("steps of 5", W.snap_value(0, 100, 5, 37), 35)
expect("steps of 100 from 1500", W.snap_value(1500, 6000, 100, 3449), 3400)
expect("steps of 0.25 from 0.25", W.snap_value(0.25, 4, 0.25, 1.13), 1.25)
expect("no float dust", W.snap_value(0.5, 2.0, 0.05, 0.66), 0.65)
expect("negative range", W.snap_value(-1, 1, 0.05, -0.02), 0)
# the top end is a stop even when it's off the grid
expect("off-grid top end is reachable", W.snap_value(0, 10, 4, 9.5), 10)
expect("and the step below it still is", W.snap_value(0, 10, 4, 8.6), 8)
expect("no step: only clamped", W.snap_value(0, 10, 0, 3.3), 3.3)

if bad:
    sys.exit(1)
print("check_widgets: ok")
