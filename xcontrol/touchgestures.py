"""Touchpad gestures: click areas, swipes, and the touchpad as a stick.

Pure logic (no devices), so it can be tested. Feed it the touchpad device's events (single-touch
ABS_X/ABS_Y, BTN_TOUCH, and BTN_LEFT for the click); it returns what to do:
  ("press", source, down)    a gesture "button" (mapped like any other in padmap)
  ("stick", (x, y))          the stick deflection, -1..1 each (x right +, y down +)
Swipes are short presses: the release comes back from tick() a moment later, so games that
look at the button once a frame still see it.
"""
import math
import time

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
ABS_X, ABS_Y = 0x00, 0x01
BTN_LEFT, BTN_TOUCH = 0x110, 0x14A

CLICKS = ["whole", "halves", "corners"]
STICKS = ["off", "left", "right"]
DEFAULT = {"click": "whole", "swipes": False, "stick": "off"}
# the gesture "buttons" (mapped in the button layout like the real ones)
HALVES = ["touch_left", "touch_right"]
CORNERS = ["touch_tl", "touch_tr", "touch_bl", "touch_br"]
SWIPES = ["swipe_up", "swipe_down", "swipe_left", "swipe_right"]
SOURCES = HALVES + CORNERS + SWIPES

SWIPE_MIN = 0.25        # of the touchpad's width
SWIPE_TIME = 0.6        # seconds, at most
PRESS_TIME = 0.08       # how long a swipe's press lasts
STICK_RADIUS = 0.2      # of the width: moving the finger this far is a full stick


def normalize(t):
    out = dict(DEFAULT)
    if isinstance(t, dict):
        out.update({k: v for k, v in t.items() if k in DEFAULT})
    if out["click"] not in CLICKS:
        out["click"] = "whole"
    if out["stick"] not in STICKS:
        out["stick"] = "off"
    out["swipes"] = bool(out["swipes"])
    return out


def active(t):
    """Whether these settings use the touchpad for more than its plain click."""
    t = normalize(t)
    return t["click"] != "whole" or t["swipes"] or t["stick"] != "off"


class Gestures:
    def __init__(self, settings=None, width=1920, height=942, clock=time.monotonic):
        self.w, self.h = max(1, width), max(1, height)
        self.clock = clock
        self.set(settings)
        self.x = self.y = 0
        self.touching = False
        self.start = None            # (x, y, time) where the finger came down
        self.clicked = None          # the click area held down
        self.click_seen = False      # (a touch that clicked isn't a swipe)
        self.pending = []            # [(time, source)]: swipe releases due
        self.stick = (0.0, 0.0)

    def set(self, settings):
        self.s = normalize(settings)

    def area(self):
        """The click "button" under the finger."""
        c = self.s["click"]
        if c == "whole":
            return "touchpad"
        left = self.x < self.w / 2
        if c == "halves":
            return "touch_left" if left else "touch_right"
        top = self.y < self.h / 2
        return {(True, True): "touch_tl", (False, True): "touch_tr",
                (True, False): "touch_bl", (False, False): "touch_br"}[(left, top)]

    def feed(self, etype, code, value):
        out = []
        if etype == EV_ABS and code in (ABS_X, ABS_Y):
            if code == ABS_X:
                self.x = value
            else:
                self.y = value
        elif etype == EV_KEY and code == BTN_TOUCH:
            if value and not self.touching:
                self.touching, self.click_seen = True, False
                self.start = None          # (taken at the first position of this touch, below)
            elif not value and self.touching:
                self.touching = False
                out += self._lift()
        elif etype == EV_KEY and code == BTN_LEFT:
            if value and self.clicked is None:
                self.clicked, self.click_seen = self.area(), True
                out.append(("press", self.clicked, True))
            elif not value and self.clicked is not None:
                out.append(("press", self.clicked, False))
                self.clicked = None
        elif etype == EV_SYN and code == 0:
            if self.touching and self.start is None:
                self.start = (self.x, self.y, self.clock())
            if self.s["stick"] != "off":
                out += self._stick()
        return out

    def _stick(self):
        if not self.touching or self.start is None:
            new = (0.0, 0.0)
        else:
            r = STICK_RADIUS * self.w
            dx, dy = (self.x - self.start[0]) / r, (self.y - self.start[1]) / r
            mag = math.hypot(dx, dy)
            if mag > 1:
                dx, dy = dx / mag, dy / mag
            new = (round(dx, 4), round(dy, 4))
        if new == self.stick:
            return []
        self.stick = new
        return [("stick", new)]

    def _lift(self):
        out = []
        if self.s["stick"] != "off":
            self.stick = (0.0, 0.0)
            out.append(("stick", (0.0, 0.0)))
            return out              # (the touchpad is a stick then: no swipes)
        if not self.s["swipes"] or self.click_seen or self.start is None:
            return out
        dx, dy = self.x - self.start[0], self.y - self.start[1]
        if self.clock() - self.start[2] > SWIPE_TIME or math.hypot(dx, dy) < SWIPE_MIN * self.w:
            return out
        if abs(dx) >= abs(dy):
            source = "swipe_right" if dx > 0 else "swipe_left"
        else:
            source = "swipe_down" if dy > 0 else "swipe_up"
        self.pending.append((self.clock() + PRESS_TIME, source))
        return [("press", source, True)]

    def tick(self):
        """Releases that are due now."""
        now = self.clock()
        due = [s for t, s in self.pending if t <= now]
        self.pending = [(t, s) for t, s in self.pending if t > now]
        return [("press", s, False) for s in due]

    def next_due(self):
        """Seconds until the next release (None when nothing waits)."""
        if not self.pending:
            return None
        return max(0.0, min(t for t, _s in self.pending) - self.clock())
