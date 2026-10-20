"""Gyro aiming: the DualShock 4's motion sensors turned into mouse movement or right-stick input.

Pure logic (no devices), so it can be tested. Feed it the motion sensor device's events and the
activation button's state; it returns mouse movement (whole counts) or a right-stick deflection.

Axes, as hid-playstation reports them (controller lying flat, face up):
  gyro   ABS_RX pitch (nose up +), ABS_RY yaw (turning left +), ABS_RZ roll, in 1/1024 deg/s
  accel  ABS_X, ABS_Y (up +1 g when flat), ABS_Z, in 1/8192 g
  MSC_TIMESTAMP, microseconds (wraps at 2^32)
"""
import math

EV_SYN, EV_ABS, EV_MSC = 0x00, 0x03, 0x04
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
MSC_TIMESTAMP = 0x05
GYRO_RES, ACCEL_RES = 1024.0, 8192.0

OUTPUTS = ["off", "mouse", "stick"]
MODES = ["always", "hold", "toggle", "hold_off"]
SPACES = ["player", "yaw", "roll"]

DEFAULT = {"output": "off", "mode": "hold", "button": "l2", "space": "player", "sens": 12.0,
           "stick_speed": 180, "stick_dz": 15, "invert_x": False, "invert_y": False, "auto_cal": True}

# feel (deg/s): below TIGHTEN, movement shrinks toward zero (hand tremor, leftover drift);
# between SMOOTH_LO and SMOOTH_HI it's gradually smoothed; above, it's raw
TIGHTEN, SMOOTH_LO, SMOOTH_HI, SMOOTH_TAU = 1.0, 2.0, 6.0, 0.06
# auto-calibration: this still (deg/s from its own average) for this long (s)
STILL_NOISE, STILL_TIME, STILL_MAX = 1.2, 1.5, 6.0


def normalize(g, sources=()):
    out = dict(DEFAULT)
    if isinstance(g, dict):
        out.update({k: v for k, v in g.items() if k in DEFAULT})
    for k, choices in (("output", OUTPUTS), ("mode", MODES), ("space", SPACES)):
        if out[k] not in choices:
            out[k] = DEFAULT[k]
    if sources and out["button"] not in sources:
        out["button"] = DEFAULT["button"]
    for k in ("invert_x", "invert_y", "auto_cal"):
        out[k] = bool(out[k])
    for k, lo, hi, kind in (("sens", 0.5, 60.0, float), ("stick_speed", 30, 720, int), ("stick_dz", 0, 50, int)):
        try:
            out[k] = kind(max(lo, min(hi, float(out[k]))))
        except (TypeError, ValueError):
            out[k] = DEFAULT[k]
    return out


class Gyro:
    def __init__(self, settings=None):
        self.set(settings)
        self.raw = {ABS_X: 0, ABS_Y: int(ACCEL_RES), ABS_Z: 0, ABS_RX: 0, ABS_RY: 0, ABS_RZ: 0}
        self.stamp = None
        self.bias = [0.0, 0.0, 0.0]          # deg/s, pitch/yaw/roll
        self.calibrated = False
        self.grav = [0.0, 1.0, 0.0]          # "up" in the controller's axes, filtered
        self.smooth = [0.0, 0.0]
        self.remainder = [0.0, 0.0]          # mouse movement below one count, kept for later
        self.stick = (0.0, 0.0)              # current deflection, -1..1
        self.button = False
        self.toggled = False
        self.still = None                    # [time, sums, count, first sample] while it lies still
        self.manual = None                   # [time left, sums, count] while calibrating on request

    def set(self, settings):
        self.s = normalize(settings)

    # ------------------------------------------------------------ activation
    def press(self, down):
        """The activation button."""
        if self.s["mode"] == "toggle" and down and not self.button:
            self.toggled = not self.toggled
        self.button = down

    def active(self):
        mode = self.s["mode"]
        if mode == "always":
            return True
        if mode == "hold":
            return self.button
        if mode == "hold_off":
            return not self.button
        return self.toggled

    def calibrate(self, seconds=2.0):
        """Average what it reads for a while (it should be lying still) as its drift."""
        self.manual = [seconds, [0.0, 0.0, 0.0], 0]

    def status(self):
        if self.manual:
            return "calibrating"
        return "calibrated" if self.calibrated else "uncalibrated"

    # ------------------------------------------------------------ input
    def feed(self, etype, code, value):
        """One motion sensor event. At each report's end returns (dx, dy) of mouse counts when
        the output is the mouse, or True when the stick deflection changed; else None."""
        if etype == EV_ABS and code in self.raw:
            self.raw[code] = value
        elif etype == EV_MSC and code == MSC_TIMESTAMP:
            dt = None
            if self.stamp is not None:
                dt = ((value - self.stamp) & 0xFFFFFFFF) / 1e6
            self.stamp = value
            self._dt = dt
        elif etype == EV_SYN and code == 0:
            dt = getattr(self, "_dt", None)
            self._dt = None
            if dt is None or dt <= 0:
                return None
            return self._frame(min(dt, 0.05))
        return None

    def _frame(self, dt):
        rate = [self.raw[ABS_RX] / GYRO_RES, self.raw[ABS_RY] / GYRO_RES, self.raw[ABS_RZ] / GYRO_RES]
        accel = [self.raw[ABS_X] / ACCEL_RES, self.raw[ABS_Y] / ACCEL_RES, self.raw[ABS_Z] / ACCEL_RES]
        self._calibration(rate, dt)
        pitch, yaw, roll = (r - b for r, b in zip(rate, self.bias))
        # which way is up, slowly (so turning doesn't shake it)
        n = math.sqrt(sum(a * a for a in accel))
        if 0.5 < n < 1.5:
            k = min(1.0, dt / 0.2)
            self.grav = [g + (a / n - g) * k for g, a in zip(self.grav, accel)]
        h, v = self._axes(pitch, yaw, roll)
        if self.s["invert_x"]:
            h = -h
        if self.s["invert_y"]:
            v = -v
        h, v = self._feel(h, v, dt)
        if not self.active():
            h = v = 0.0
            self.remainder = [0.0, 0.0]
        if self.s["output"] == "mouse":
            # turning left (+) moves left (-); nose up (+) moves up (-)
            mx = -h * dt * self.s["sens"] + self.remainder[0]
            my = -v * dt * self.s["sens"] + self.remainder[1]
            ix, iy = int(mx), int(my)       # (toward zero; the rest waits for the next report)
            self.remainder = [mx - ix, my - iy]
            return (ix, iy) if (ix or iy) else None
        if self.s["output"] == "stick":
            new = self._deflect(h, v)
            changed = new != self.stick
            self.stick = new
            return True if changed else None
        return None

    def _axes(self, pitch, yaw, roll):
        """(horizontal, vertical) turning in deg/s: + is left and up."""
        space = self.s["space"]
        if space == "roll":
            return -roll, pitch
        if space == "yaw":
            return yaw, pitch
        # player space: turning around the real world's vertical, however it's held
        gx, gy, gz = self.grav
        world = gy * yaw + gz * roll
        local = math.hypot(yaw, roll)
        mag = min(abs(world) * 1.41, local)
        return math.copysign(mag, world), pitch

    def _feel(self, h, v, dt):
        speed = math.hypot(h, v)
        if speed <= 0:
            self.smooth = [0.0, 0.0]
            return 0.0, 0.0
        # smoothing only for slow movement, so quick turns stay immediate
        k = min(1.0, dt / SMOOTH_TAU)
        self.smooth = [self.smooth[0] + (h - self.smooth[0]) * k, self.smooth[1] + (v - self.smooth[1]) * k]
        direct = min(1.0, max(0.0, (speed - SMOOTH_LO) / (SMOOTH_HI - SMOOTH_LO)))
        h = h * direct + self.smooth[0] * (1 - direct)
        v = v * direct + self.smooth[1] * (1 - direct)
        if speed < TIGHTEN:
            h, v = h * speed / TIGHTEN, v * speed / TIGHTEN
        return h, v

    def _deflect(self, h, v):
        """Turning speed -> stick deflection (-1..1, x right +, y down +), past the game's deadzone."""
        x, y = -h / self.s["stick_speed"], -v / self.s["stick_speed"]
        mag = math.hypot(x, y)
        if mag < 1e-3:
            return (0.0, 0.0)
        dz = self.s["stick_dz"] / 100.0
        out = dz + (1 - dz) * min(mag, 1.0)
        return (round(x / mag * out, 4), round(y / mag * out, 4))

    def _calibration(self, rate, dt):
        if self.manual:
            left, sums, count = self.manual
            sums = [s + r for s, r in zip(sums, rate)]
            count += 1
            left -= dt
            if left <= 0:
                self.bias = [s / count for s in sums]
                self.calibrated = True
                self.manual = None
            else:
                self.manual = [left, sums, count]
            return
        if not self.s["auto_cal"]:
            return
        # it's been lying still (no hand holds it that steady): learn the drift from it
        if self.still is None or any(abs(r - f) > STILL_NOISE for r, f in zip(rate, self.still[3])) \
                or max(abs(r) for r in rate) > STILL_MAX:
            self.still = [0.0, [0.0, 0.0, 0.0], 0, rate]
            return
        self.still[0] += dt
        self.still[1] = [s + r for s, r in zip(self.still[1], rate)]
        self.still[2] += 1
        if self.still[0] >= STILL_TIME:
            self.bias = [s / self.still[2] for s in self.still[1]]
            self.calibrated = True
            self.still = [0.0, [0.0, 0.0, 0.0], 0, rate]

    def stick_value(self, axis, physical):
        """The right stick sent to games: the real stick plus the gyro (-32768..32767)."""
        if self.s["output"] != "stick":
            return physical
        g = self.stick[0 if axis == ABS_RX else 1]
        return max(-32768, min(32767, int(round(physical + g * 32767))))
