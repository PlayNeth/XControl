"""Turning DualShock 4 input into an Xbox 360 controller's, with the buttons remapped.

Pure logic (no devices), so it can be tested: feed it (type, code, value) events from the
DS4's gamepad and touchpad devices, get the Xbox pad's events back.
"""
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_HAT0X, ABS_HAT0Y = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x10, 0x11
BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST = 0x130, 0x131, 0x133, 0x134
BTN_TL, BTN_TR, BTN_TL2, BTN_TR2 = 0x136, 0x137, 0x138, 0x139
BTN_SELECT, BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR = 0x13A, 0x13B, 0x13C, 0x13D, 0x13E
BTN_LEFT = 0x110   # the touchpad's click (on the touchpad device)

# the DualShock 4's buttons as hid-playstation reports them
SOURCES = {
    "cross": BTN_SOUTH, "circle": BTN_EAST, "triangle": BTN_NORTH, "square": BTN_WEST,
    "l1": BTN_TL, "r1": BTN_TR, "l2": BTN_TL2, "r2": BTN_TR2,
    "share": BTN_SELECT, "options": BTN_START, "ps": BTN_MODE, "l3": BTN_THUMBL, "r3": BTN_THUMBR,
    "touchpad": BTN_LEFT,
    "dpad_up": "hat_up", "dpad_down": "hat_down", "dpad_left": "hat_left", "dpad_right": "hat_right",
}
SOURCE_ORDER = ["cross", "circle", "square", "triangle", "l1", "r1", "l2", "r2", "l3", "r3", "share", "options",
                "ps", "touchpad", "dpad_up", "dpad_down", "dpad_left", "dpad_right"]
# what an Xbox 360 pad has (xpad's codes: its X is BTN_X = BTN_NORTH, its Y is BTN_Y = BTN_WEST)
TARGETS = {
    "a": BTN_SOUTH, "b": BTN_EAST, "x": BTN_NORTH, "y": BTN_WEST, "lb": BTN_TL, "rb": BTN_TR,
    "back": BTN_SELECT, "start": BTN_START, "guide": BTN_MODE, "ls": BTN_THUMBL, "rs": BTN_THUMBR,
    "lt": "lt", "rt": "rt", "dpad_up": "hat_up", "dpad_down": "hat_down", "dpad_left": "hat_left",
    "dpad_right": "hat_right", "none": None,
}
TARGET_ORDER = ["a", "b", "x", "y", "lb", "rb", "lt", "rt", "ls", "rs", "back", "start", "guide",
                "dpad_up", "dpad_down", "dpad_left", "dpad_right", "none"]
DEFAULT_MAP = {"cross": "a", "circle": "b", "square": "x", "triangle": "y", "l1": "lb", "r1": "rb",
               "l2": "lt", "r2": "rt", "l3": "ls", "r3": "rs", "share": "back", "options": "start", "ps": "guide",
               "touchpad": "none", "dpad_up": "dpad_up", "dpad_down": "dpad_down", "dpad_left": "dpad_left",
               "dpad_right": "dpad_right"}
XBOX_BUTTONS = [BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST, BTN_TL, BTN_TR, BTN_SELECT, BTN_START, BTN_MODE,
                BTN_THUMBL, BTN_THUMBR]
# axes of the virtual pad: (code, min, max, fuzz, flat)
XBOX_AXES = [(ABS_X, -32768, 32767, 16, 128), (ABS_Y, -32768, 32767, 16, 128),
             (ABS_RX, -32768, 32767, 16, 128), (ABS_RY, -32768, 32767, 16, 128),
             (ABS_Z, 0, 255, 0, 0), (ABS_RZ, 0, 255, 0, 0), (ABS_HAT0X, -1, 1, 0, 0), (ABS_HAT0Y, -1, 1, 0, 0)]


def normalize_map(m):
    out = dict(DEFAULT_MAP)
    for k, v in (m or {}).items():
        if k in SOURCES and v in TARGETS:
            out[k] = v
    return out


def _stick(v):
    """0..255 (DS4) -> -32768..32767 (Xbox), with 128 exactly in the middle."""
    d = v - 128
    out = d * 32767 / 127 if d >= 0 else d * 32768 / 128
    return max(-32768, min(32767, int(round(out))))


class Mapper:
    def __init__(self, mapping=None):
        self.map = normalize_map(mapping)
        self.held = {}          # target -> set of sources holding it
        self.trigger = {"lt": 0, "rt": 0}    # analog trigger values from the DS4
        self.hat_src = {"hat_left": 0, "hat_right": 0, "hat_up": 0, "hat_down": 0}
        self.out_state = {}     # (type, code) -> last value sent
        # analog triggers go to LT/RT only while L2/R2 are mapped there
        self.analog = {"lt": self.map["l2"] == "lt", "rt": self.map["r2"] == "rt"}

    def _press(self, source, down):
        target = self.map.get(source)
        if target is None or TARGETS.get(target) is None:
            return
        holders = self.held.setdefault(target, set())
        if down:
            holders.add(source)
        else:
            holders.discard(source)

    def _target_value(self, target):
        on = bool(self.held.get(target))
        if target in ("lt", "rt"):
            src = "l2" if target == "lt" else "r2"
            analog = self.trigger[target] if self.analog[target] and self.map[src] == target else 0
            others = any(s != src for s in self.held.get(target, ())) or (on and not self.analog[target])
            return 255 if others else analog
        return 1 if on else 0

    def feed(self, etype, code, value):
        """One input event from the DS4; returns the output events (without SYN) to send now,
        or None when it's a SYN_REPORT (send the collected changes then)."""
        if etype == EV_KEY:
            source = next((s for s, c in SOURCES.items() if c == code), None)
            if source:
                self._press(source, value != 0)
            return self._changes()
        if etype == EV_ABS:
            if code in (ABS_X, ABS_Y, ABS_RX, ABS_RY):
                return self._emit(EV_ABS, code, _stick(value))
            if code in (ABS_Z, ABS_RZ):
                self.trigger["lt" if code == ABS_Z else "rt"] = value
                return self._changes()
            if code == ABS_HAT0X:
                self._hat("hat_left", value < 0)
                self._hat("hat_right", value > 0)
                return self._changes()
            if code == ABS_HAT0Y:
                self._hat("hat_up", value < 0)
                self._hat("hat_down", value > 0)
                return self._changes()
        return []

    def _hat(self, hat_source, down):
        if self.hat_src[hat_source] == int(down):
            return
        self.hat_src[hat_source] = int(down)
        source = next(s for s, c in SOURCES.items() if c == hat_source)
        self._press(source, down)

    def _emit(self, etype, code, value):
        if self.out_state.get((etype, code)) == value:
            return []
        self.out_state[(etype, code)] = value
        return [(etype, code, value)]

    def _changes(self):
        out = []
        for name in ("a", "b", "x", "y", "lb", "rb", "back", "start", "guide", "ls", "rs"):
            out += self._emit(EV_KEY, TARGETS[name], self._target_value(name))
        out += self._emit(EV_ABS, ABS_Z, self._target_value("lt"))
        out += self._emit(EV_ABS, ABS_RZ, self._target_value("rt"))
        hx = self._target_value("dpad_right") - self._target_value("dpad_left")
        hy = self._target_value("dpad_down") - self._target_value("dpad_up")
        out += self._emit(EV_ABS, ABS_HAT0X, hx)
        out += self._emit(EV_ABS, ABS_HAT0Y, hy)
        return out
