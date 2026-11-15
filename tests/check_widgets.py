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

# every page is in the sidebar once, and the other way round
from xcontrol import app, sidebar  # noqa: E402
expect("sidebar pages", sorted(sidebar.order()), sorted(app.PAGES))

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

if Gdk.Display.get_default() is not None:   # the rest needs an X display (nothing is shown)
    s = W.slider(-1, 1, 0.05, 2)
    moves = []
    s.connect("value-changed", lambda sc: moves.append(sc.get_value()))
    s.set_value(0.33)
    expect("a value set by the program is kept as it is", (s.get_value(), moves), (0.33, [0.33]))
    s.emit("change-value", Gtk.ScrollType.JUMP, 0.471)
    s.emit("change-value", Gtk.ScrollType.JUMP, 0.46)
    expect("dragging stops on steps, one signal per step", moves[1:], [0.45])
    s.emit("change-value", Gtk.ScrollType.JUMP, 7)
    expect("dragged past the end", s.get_value(), 1)
    for _i in range(20):
        s.emit("move-slider", Gtk.ScrollType.STEP_LEFT)
    expect("20 key presses back, no drift", s.get_value(), 0)
    s.set_inverted(True)
    s.emit("move-slider", Gtk.ScrollType.STEP_RIGHT)
    expect("inverted: right is down", s.get_value(), -0.05)
    s.set_adjustment(Gtk.Adjustment(value=0, lower=0, upper=50, step_increment=5, page_increment=5))
    s.emit("change-value", Gtk.ScrollType.JUMP, 33)
    expect("a new adjustment's steps are followed", s.get_value(), 35)

    # a dialog too big for the screen: its content scrolls, its buttons don't
    dlg = Gtk.Dialog(title="test")
    dlg.add_button("Close", Gtk.ResponseType.CLOSE)
    big = Gtk.Label(label="x")
    big.set_size_request(20000, 20000)
    dlg.get_content_area().pack_start(big, False, False, 0)
    dlg.get_content_area().show_all()
    W.fit_dialog(dlg)
    expect("content scrolls", big.get_ancestor(Gtk.ScrolledWindow) is not None, True)
    expect("buttons stay put", dlg.get_action_area().get_ancestor(Gtk.ScrolledWindow), None)
    late = Gtk.Label(label="added later")
    dlg.get_content_area().pack_start(late, False, False, 0)
    W.fit_dialog(dlg)
    expect("later content scrolls too", late.get_ancestor(Gtk.ScrolledWindow) is not None, True)
    expect("buttons still stay put", dlg.get_action_area().get_ancestor(Gtk.ScrolledWindow), None)
    dlg.destroy()

if bad:
    sys.exit(1)
print("check_widgets: ok")
