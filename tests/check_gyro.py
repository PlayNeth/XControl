"""Gyro aiming: calibration, which way it turns, sensitivity, activation, stick output, and
the service passing the motion sensors to a virtual mouse (fake devices: pipes)."""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
from xcontrol import gyro as G, pad_service as S, padmap as M  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def near(what, got, want, tol):
    global bad
    if abs(got - want) > tol:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r} ± {tol}")


class Run:
    """Reports from a controller at 250 Hz: rates in deg/s (pitch, yaw, roll), accel in g."""

    def __init__(self, g, stamp=0):
        self.g, self.stamp = g, stamp
        self.g.feed(G.EV_MSC, G.MSC_TIMESTAMP, stamp)

    def events(self, rate, accel=(0, 1, 0), dt=0.004):
        self.stamp = (self.stamp + int(dt * 1e6)) & 0xFFFFFFFF
        ev = [(G.EV_ABS, c, int(v * G.GYRO_RES)) for c, v in zip((G.ABS_RX, G.ABS_RY, G.ABS_RZ), rate)]
        ev += [(G.EV_ABS, c, int(v * G.ACCEL_RES)) for c, v in zip((G.ABS_X, G.ABS_Y, G.ABS_Z), accel)]
        return ev + [(G.EV_MSC, G.MSC_TIMESTAMP, self.stamp), (G.EV_SYN, 0, 0)]

    def go(self, seconds, rate, accel=(0, 1, 0)):
        dx = dy = 0
        sticks = []
        for _ in range(int(round(seconds / 0.004))):
            for e in self.events(rate, accel):
                r = self.g.feed(*e)
                if isinstance(r, tuple):
                    dx, dy = dx + r[0], dy + r[1]
            sticks.append(self.g.stick)
        return dx, dy, sticks


# drift: lying still with 0.6 deg/s of yaw drift -> learned, then it doesn't creep
g = G.Gyro({"output": "mouse", "mode": "always", "sens": 10})
r = Run(g)
r.go(2.0, (0.1, 0.6, -0.2))
expect("auto-calibrated", g.status(), "calibrated")
near("drift learned", g.bias[1], 0.6, 0.01)
dx, dy, _ = r.go(2.0, (0.1, 0.6, -0.2))
expect("no creep after", (dx, dy), (0, 0))

# turning left at 90 deg/s for half a second, 10 counts per degree: 450 counts left
dx, dy, _ = r.go(0.5, (0.1, 90.6, -0.2))
near("yaw left", dx, -450, 25)
expect("no vertical", dy, 0)
r.go(0.2, (0.1, 0.6, -0.2))
dx, dy, _ = r.go(0.5, (40.1, 0.6, -0.2))
near("nose up moves up", dy, -200, 15)
expect("invert y", (G.normalize({"invert_y": "yes"})["invert_y"]), True)

# player space: held upright (gravity along the controller's z), turning shows up as roll
g = G.Gyro({"output": "mouse", "mode": "always", "sens": 10, "auto_cal": False})
r = Run(g)
r.go(0.4, (0, 0, 0), accel=(0, 0, 1))
dx, _dy, _ = r.go(0.5, (0, 0, 90), accel=(0, 0, 1))
near("player space follows the world's vertical", dx, -450, 30)
g.set({"output": "mouse", "mode": "always", "sens": 10, "auto_cal": False, "space": "yaw"})
dx, _dy, _ = r.go(0.5, (0, 0, 90), accel=(0, 0, 1))
expect("plain yaw ignores it", dx, 0)

# hand tremor is tightened away; quick movement isn't smoothed
g = G.Gyro({"output": "mouse", "mode": "always", "sens": 10, "auto_cal": False})
r = Run(g)
dx, _dy, _ = r.go(1.0, (0, 0.5, 0))
near("tremor tightened", dx, -2, 1.5)

# activation
g = G.Gyro({"output": "mouse", "mode": "hold", "sens": 10, "auto_cal": False})
r = Run(g)
expect("hold: off by default", r.go(0.2, (0, 90, 0))[0], 0)
g.press(True)
near("hold: on while held", r.go(0.2, (0, 90, 0))[0], -180, 20)
g.set({"output": "mouse", "mode": "toggle", "sens": 10, "auto_cal": False})
g.press(False)
g.press(True)
g.press(False)
expect("toggle on", g.active(), True)
g.press(True)
expect("toggle off", g.active(), False)
g.set({"mode": "hold_off"})
expect("off while held", (g.active(), g.press(False) or g.active()), (False, True))

# stick: 90 deg/s of 180 for full, past a 15 % deadzone -> 0.15 + 0.85 * 0.5
g = G.Gyro({"output": "stick", "mode": "always", "stick_speed": 180, "stick_dz": 15, "auto_cal": False})
r = Run(g)
_dx, _dy, sticks = r.go(0.3, (0, 90, 0))
near("stick deflection", sticks[-1][0], -0.575, 0.01)
near("added to the real stick", g.stick_value(G.ABS_RX, 0), -0.575 * 32767, 400)
expect("clamped", g.stick_value(G.ABS_RX, -32768), -32768)
_dx, _dy, sticks = r.go(0.3, (0, 0, 0))
expect("back to center", sticks[-1], (0.0, 0.0))

# the timestamp wraps around at 2^32
g = G.Gyro({"output": "mouse", "mode": "always", "sens": 10, "auto_cal": False})
r = Run(g, stamp=0xFFFFFFFF - 1000)
near("across the wrap", r.go(0.2, (0, 90, 0))[0], -180, 20)

# settings
n = G.normalize({"output": "joystick", "mode": "x", "button": "nope", "sens": 999, "stick_dz": -5}, S.ACTIVATORS)
expect("normalized", (n["output"], n["mode"], n["button"], n["sens"], n["stick_dz"]), ("off", "hold", "l2", 60.0, 0))
expect("touch can switch it", G.normalize({"button": "touch"}, S.ACTIVATORS)["button"], "touch")
expect("in the controller settings", S.normalize({"gyro": {"output": "stick"}})["gyro"]["output"], "stick")

# the service: motion sensors -> virtual mouse, L2 switches it on (no Xbox pad needed)
moves = []


class StubMouse:
    def __init__(self):
        pass

    def move(self, dx, dy):
        moves.append((dx, dy))

    def close(self):
        pass


real_mouse = S.VirtualMouse
S.VirtualMouse = StubMouse
try:
    import tempfile
    tmp = tempfile.mkdtemp()
    se_r, se_w = os.pipe()
    gp_r, gp_w = os.pipe()
    from xcontrol import pads as P
    pad = P.Pad(key="k", name="DS4", bus="usb", hid="/x")
    settings = S.normalize({"enabled": True, "emulate": "off",
                            "gyro": {"output": "mouse", "mode": "hold", "button": "l2", "auto_cal": False}})
    c = S.Controller(pad, settings, lambda m: None)
    c.fds.update({se_r: "sensors", gp_r: "gamepad"})
    os.set_blocking(se_r, False)
    run = Run(G.Gyro())

    def frames(n, rate):
        return b"".join(S.EVENT.pack(0, 0, t, code, v) for _ in range(n) for t, code, v in run.events(rate))

    os.write(se_w, frames(20, (0, 90, 0)))
    c.read(se_r)
    expect("not while L2 is up", moves, [])
    os.write(gp_w, S.EVENT.pack(0, 0, M.EV_KEY, M.BTN_TL2, 1) + S.EVENT.pack(0, 0, 0, 0, 0))
    c.read(gp_r)
    os.write(se_w, frames(20, (0, 90, 0)))
    c.read(se_r)
    expect("moves while L2 is held", sum(m[0] for m in moves) < -40, True)
    expect("status", c.status()["gyro"], "uncalibrated")
    c.gyro.calibrate(0.04)
    os.write(se_w, frames(15, (0, 0.3, 0)))
    c.read(se_r)
    expect("calibrated on request", c.status()["gyro"], "calibrated")
    c.close()
finally:
    S.VirtualMouse = real_mouse

print("check_gyro:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
