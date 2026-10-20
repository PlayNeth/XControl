"""Touchpad gestures: click areas, swipes (with their short presses), the touchpad as a stick,
and the controller service sending them to the virtual pad (fake devices: pipes)."""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
from xcontrol import gyro as G, pad_service as S, padmap as M, pads as P, touchgestures as T  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def touch(g, clock, path, click_at=None, dt=0.01):
    """A finger landing at path[0], moving through path, lifting; returns the actions."""
    out = []
    x, y = path[0]
    out += g.feed(T.EV_ABS, T.ABS_X, x) + g.feed(T.EV_ABS, T.ABS_Y, y)
    out += g.feed(T.EV_KEY, T.BTN_TOUCH, 1) + g.feed(T.EV_SYN, 0, 0)
    for i, (x, y) in enumerate(path[1:], 1):
        clock.t += dt
        out += g.feed(T.EV_ABS, T.ABS_X, x) + g.feed(T.EV_ABS, T.ABS_Y, y)
        if click_at == i:
            out += g.feed(T.EV_KEY, T.BTN_LEFT, 1) + g.feed(T.EV_KEY, T.BTN_LEFT, 0)
        out += g.feed(T.EV_SYN, 0, 0)
    clock.t += dt
    out += g.feed(T.EV_KEY, T.BTN_TOUCH, 0) + g.feed(T.EV_SYN, 0, 0)
    return out


clk = Clock()
g = T.Gestures({"click": "halves"}, 1920, 942, clock=clk)
expect("left half", touch(g, clk, [(300, 400), (300, 400)], click_at=1),
       [("press", "touch_left", True), ("press", "touch_left", False)])
expect("right half", touch(g, clk, [(1500, 400), (1500, 400)], click_at=1)[0], ("press", "touch_right", True))
g.set({"click": "corners"})
expect("bottom right", touch(g, clk, [(1800, 900), (1800, 900)], click_at=1)[0], ("press", "touch_br", True))
g.set({"click": "whole"})
expect("whole: the plain touchpad click", touch(g, clk, [(10, 10), (10, 10)], click_at=1)[0],
       ("press", "touchpad", True))

g.set({"swipes": True})
expect("no swipes when off", T.Gestures({}, clock=clk).feed(T.EV_KEY, T.BTN_TOUCH, 0), [])
acts = touch(g, clk, [(400, 400), (700, 400), (1100, 420)])
expect("swipe right", acts, [("press", "swipe_right", True)])
expect("released a moment later, not before", g.tick(), [])
clk.t += 0.1
expect("released", (g.tick(), g.next_due()), ([("press", "swipe_right", False)], None))
expect("swipe up", touch(g, clk, [(900, 900), (900, 600), (900, 100)])[0], ("press", "swipe_up", True))
clk.t += 1
g.tick()
expect("too short", touch(g, clk, [(900, 400), (1000, 400)]), [])
expect("too slow", touch(g, clk, [(100, 400), (600, 400), (1300, 400)], dt=0.5), [])
expect("a click isn't a swipe", [a for a in touch(g, clk, [(100, 400), (900, 400), (1500, 400)], click_at=1)
                                 if a[1].startswith("swipe")], [])

g = T.Gestures({"stick": "right", "swipes": True}, 1920, 942, clock=clk)
acts = touch(g, clk, [(1000, 500), (1000 + 192, 500), (1000 + 384 * 2, 500)])
sticks = [a[1] for a in acts if a[0] == "stick"]
expect("half way", sticks[0], (0.5, 0.0))
expect("capped at full", sticks[1], (1.0, 0.0))
expect("lifting centers it, no swipe", (acts[-1], [a for a in acts if a[0] == "press"]), (("stick", (0.0, 0.0)), []))
expect("settings", (T.normalize({"click": "x", "stick": "up"}), T.active({"swipes": True}), T.active({})),
       ({"click": "whole", "swipes": False, "stick": "off"}, True, False))

# the service: a swipe and the touchpad stick reach the virtual pad
sent = []


class StubVpad:
    fd = -5

    def send(self, events):
        sent.extend(events)


c = S.Controller.__new__(S.Controller)
c.pad, c.log, c.error = P.Pad(key="k", name="DS4", bus="usb", hid="/x"), print, ""
c.vpad, c.rumble, c.mouse = StubVpad(), None, None
c.mapper = M.Mapper({"swipe_left": "y"})
c.gyro, c.phys = G.Gyro(), {M.ABS_X: 0, M.ABS_Y: 0, M.ABS_RX: 1000, M.ABS_RY: 0}
c.gestures = T.Gestures({"swipes": True}, 1920, 942, clock=clk)
c.rate_count, c.rate_since, c.rate = 0, 0.0, 0
r, w = os.pipe()
c.fds = {r: "touchpad"}


def send(events):
    os.write(w, b"".join(S.EVENT.pack(0, 0, *e) for e in events))
    c.read(r)


send([(T.EV_ABS, T.ABS_X, 1500), (T.EV_ABS, T.ABS_Y, 400), (T.EV_KEY, T.BTN_TOUCH, 1), (0, 0, 0)])
clk.t += 0.05
send([(T.EV_ABS, T.ABS_X, 900), (0, 0, 0)])
clk.t += 0.05
send([(T.EV_ABS, T.ABS_X, 200), (T.EV_KEY, T.BTN_TOUCH, 0), (0, 0, 0)])
expect("swipe left pressed Y", (M.EV_KEY, M.BTN_WEST, 1) in sent, True)
clk.t += 0.1
c.tick()
expect("then released", sent[-1], (M.EV_KEY, M.BTN_WEST, 0))
sent.clear()
c.gestures.set({"stick": "right"})
send([(T.EV_ABS, T.ABS_X, 1000), (T.EV_ABS, T.ABS_Y, 400), (T.EV_KEY, T.BTN_TOUCH, 1), (0, 0, 0)])
send([(T.EV_ABS, T.ABS_X, 1192), (0, 0, 0)])
expect("added to the real right stick", [e for e in sent if e[1] == M.ABS_RX][-1], (M.EV_ABS, M.ABS_RX, 1000 + 16384))

print("check_touch:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
