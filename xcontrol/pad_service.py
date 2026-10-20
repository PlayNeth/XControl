"""xcontrol --pads: the controller service.

For every DualShock 4 it sets the light bar and the Bluetooth report rate, measures the rate
it really reports at, and (when asked) hides it from games and shows a virtual Xbox 360
controller instead, with the buttons remapped and rumble passed back to the DualShock 4.
It runs under the desktop service, which restarts it when the settings change.
"""
import fcntl
import json
import os
import select
import signal
import struct
import sys
import time

from . import config, padmap, pads

# ---------------------------------------------------------------- kernel interfaces
EVENT = struct.Struct("llHHi")              # struct input_event (64-bit)
EV_SYN, EV_KEY, EV_ABS, EV_FF, EV_UINPUT = 0x00, 0x01, 0x03, 0x15, 0x0101
FF_RUMBLE, FF_PERIODIC, FF_GAIN = 0x50, 0x51, 0x60
UI_FF_UPLOAD, UI_FF_ERASE = 1, 2
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT, UI_SET_FFBIT = 0x40045564, 0x40045565, 0x40045567, 0x4004556B
UI_DEV_SETUP, UI_ABS_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY = 0x405C5503, 0x401C5504, 0x5501, 0x5502
UI_BEGIN_FF_UPLOAD, UI_END_FF_UPLOAD = 0xC06855C8, 0x406855C9
UI_BEGIN_FF_ERASE, UI_END_FF_ERASE = 0xC00C55CA, 0x400C55CB
EVIOCGRAB, EVIOCSFF, EVIOCRMFF = 0x40044590, 0x40304580, 0x40044581
FF_EFFECT = struct.Struct("HhHHHHH2x32s")   # type, id, direction, trigger(2), replay(2), union
XBOX_ID = (0x0003, 0x045E, 0x028E, 0x0110)  # USB, Microsoft, Xbox 360 controller

DEFAULT = {"enabled": False, "emulate": "xbox360", "hide_real": True, "touchpad_mouse": False,
           "map": {}, "lightbar": "#0044ff", "brightness": 60, "bt_poll_ms": 1}
EMULATE = ["xbox360", "off"]


def normalize(c):
    out = dict(DEFAULT)
    if isinstance(c, dict):
        out.update({k: v for k, v in c.items() if k in DEFAULT})
    out["enabled"] = bool(out["enabled"])
    out["hide_real"] = bool(out["hide_real"])
    out["touchpad_mouse"] = bool(out["touchpad_mouse"])
    if out["emulate"] not in EMULATE:
        out["emulate"] = "xbox360"
    out["map"] = padmap.normalize_map(out["map"])
    c = str(out["lightbar"] or "")
    out["lightbar"] = c if len(c) == 7 and c.startswith("#") else DEFAULT["lightbar"]
    for k, lo, hi in (("brightness", 0, 100), ("bt_poll_ms", 0, 16)):
        try:
            out[k] = max(lo, min(hi, int(out[k])))
        except (TypeError, ValueError):
            out[k] = DEFAULT[k]
    return out


def load():
    return normalize(config.load().get("controllers"))


def save(c):
    data = config.load()
    data["controllers"] = c
    config.save(data)


def _runtime(name):
    run = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(run, f"xcontrol-{name}")


def state():
    """What the service last reported: {"pid", "pads": [...], "uinput": error or ""}."""
    try:
        with open(_runtime("pads.json")) as f:
            st = json.load(f)
    except (OSError, ValueError):
        return {}
    if not st.get("pid") or not os.path.exists(f"/proc/{st['pid']}"):
        return {}
    return st


# ---------------------------------------------------------------- the virtual pad
class VirtualPad:
    """An Xbox 360 controller made through /dev/uinput, with rumble."""

    def __init__(self, name="Microsoft X-Box 360 pad"):
        self.fd = os.open("/dev/uinput", os.O_RDWR | os.O_NONBLOCK)
        try:
            for ev in (EV_SYN, EV_KEY, EV_ABS, EV_FF):
                fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
            for key in padmap.XBOX_BUTTONS:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, key)
            for code, lo, hi, fuzz, flat in padmap.XBOX_AXES:
                fcntl.ioctl(self.fd, UI_SET_ABSBIT, code)
                fcntl.ioctl(self.fd, UI_ABS_SETUP, struct.pack("H2xiiiiii", code, 0, lo, hi, fuzz, flat, 0))
            for ff in (FF_RUMBLE, FF_PERIODIC, FF_GAIN):
                fcntl.ioctl(self.fd, UI_SET_FFBIT, ff)
            setup = struct.pack("HHHH80sI", *XBOX_ID, name.encode()[:79], 16)
            fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise

    def send(self, events):
        if not events:
            return
        data = b"".join(EVENT.pack(0, 0, t, c, v) for t, c, v in events) + EVENT.pack(0, 0, EV_SYN, 0, 0)
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)


class Rumble:
    """Effects a game uploads to the virtual pad, uploaded again to the real controller."""

    def __init__(self, vpad, real_fd):
        self.vpad, self.real = vpad, real_fd
        self.ids = {}            # virtual effect id -> real effect id

    def handle(self, etype, code, value):
        if etype == EV_UINPUT and code == UI_FF_UPLOAD:
            self._upload(value)
        elif etype == EV_UINPUT and code == UI_FF_ERASE:
            self._erase(value)
        elif etype == EV_FF and self.real is not None:
            real_code = code if code == FF_GAIN else self.ids.get(code)
            if real_code is not None:
                try:
                    os.write(self.real, EVENT.pack(0, 0, EV_FF, real_code, value))
                except OSError:
                    pass

    def _upload(self, request):
        buf = bytearray(struct.pack("Ii", request, 0) + bytes(96))
        try:
            fcntl.ioctl(self.vpad.fd, UI_BEGIN_FF_UPLOAD, buf)
        except OSError:
            return
        etype, vid, direction, tb, ti, length, delay, union = FF_EFFECT.unpack_from(buf, 8)
        if etype == FF_PERIODIC:   # some games shake with a periodic effect: make it a rumble
            magnitude = abs(struct.unpack_from("HHhhH", union)[2])
            strong, weak = magnitude * 2 if magnitude < 16384 else 65535, 0
        elif etype == FF_RUMBLE:
            strong, weak = struct.unpack_from("HH", union)
        else:
            strong = weak = 0
        retval = 0
        if self.real is not None:
            effect = bytearray(FF_EFFECT.pack(FF_RUMBLE, self.ids.get(vid, -1), direction, 0, 0, length, delay,
                                              struct.pack("HH", strong, weak) + bytes(28)))
            try:
                fcntl.ioctl(self.real, EVIOCSFF, effect)
                self.ids[vid] = struct.unpack_from("h", effect, 2)[0]
            except OSError:
                retval = 0      # the real pad can't: the game still thinks it worked
        struct.pack_into("i", buf, 4, retval)
        try:
            fcntl.ioctl(self.vpad.fd, UI_END_FF_UPLOAD, bytes(buf))
        except OSError:
            pass

    def _erase(self, request):
        buf = bytearray(struct.pack("IiI", request, 0, 0))
        try:
            fcntl.ioctl(self.vpad.fd, UI_BEGIN_FF_ERASE, buf)
        except OSError:
            return
        vid = struct.unpack_from("I", buf, 8)[0]
        real = self.ids.pop(vid, None)
        if real is not None and self.real is not None:
            try:
                fcntl.ioctl(self.real, EVIOCRMFF, real)
            except OSError:
                pass
        try:
            fcntl.ioctl(self.vpad.fd, UI_END_FF_ERASE, bytes(buf))
        except OSError:
            pass


# ---------------------------------------------------------------- one controller
class Controller:
    def __init__(self, pad, settings, log):
        self.pad, self.log = pad, log
        self.fds = {}            # fd -> role
        self.vpad = self.rumble = None
        self.mapper = None
        self.rate_count, self.rate_since, self.rate = 0, time.monotonic(), 0
        self.error = ""
        self.lightbar_ok = pads.set_lightbar(pad, settings["lightbar"], settings["brightness"])
        self.poll_ok = None
        if pad.bus == "bluetooth" and settings["bt_poll_ms"]:
            self.poll_ok = pads.set_bt_poll(pad, settings["bt_poll_ms"])
        if pad.sensors:
            self._open(pad.sensors, "sensors", grab=False)
        if settings["emulate"] == "xbox360":
            try:
                self.vpad = VirtualPad()
            except OSError as e:
                self.error = f"uinput: {e.strerror}"
            if self.vpad:
                real = self._open(pad.gamepad, "gamepad", grab=settings["hide_real"], write=True)
                if pad.touchpad:
                    self._open(pad.touchpad, "touchpad", grab=not settings["touchpad_mouse"])
                self.mapper = padmap.Mapper(settings["map"])
                self.rumble = Rumble(self.vpad, real)
                self.fds[self.vpad.fd] = "virtual"

    def _open(self, path, role, grab=False, write=False):
        try:
            fd = os.open(path, (os.O_RDWR if write else os.O_RDONLY) | os.O_NONBLOCK)
        except OSError as e:
            if write:   # rumble needs write access; reading is enough for the rest
                return self._open(path, role, grab=grab)
            self.error = self.error or f"{os.path.basename(path)}: {e.strerror}"
            return None
        if grab:
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 1)
            except OSError:
                pass
        self.fds[fd] = role
        return fd if write else None

    def read(self, fd):
        role = self.fds.get(fd)
        try:
            data = os.read(fd, EVENT.size * 64)
        except BlockingIOError:
            return True
        except OSError:
            return False    # unplugged
        if not data:
            return False
        out = []
        for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _s, _u, etype, code, value = EVENT.unpack_from(data, off)
            if role == "sensors":
                if etype == EV_SYN and code == 0:
                    self.rate_count += 1
            elif role == "virtual":
                self.rumble.handle(etype, code, value)
            elif role in ("gamepad", "touchpad") and self.mapper:
                if role == "touchpad" and not (etype == EV_KEY and code == padmap.BTN_LEFT):
                    continue
                if etype == EV_SYN:
                    continue
                out += self.mapper.feed(etype, code, value)
        if out and self.vpad:
            self.vpad.send(out)
        now = time.monotonic()
        if now - self.rate_since >= 1.0:
            self.rate = round(self.rate_count / (now - self.rate_since))
            self.rate_count, self.rate_since = 0, now
        return True

    def status(self):
        pct, charging = pads.battery(self.pad)
        return {"key": self.pad.key, "name": self.pad.name, "bus": self.pad.bus, "battery": pct,
                "charging": charging, "rate": self.rate, "virtual": bool(self.vpad),
                "lightbar_ok": self.lightbar_ok, "poll_ok": self.poll_ok, "error": self.error,
                "hidraw_ok": pads.hidraw_writable(self.pad)}

    def close(self):
        for fd in list(self.fds):
            if self.vpad and fd == self.vpad.fd:
                continue
            try:
                os.close(fd)
            except OSError:
                pass
        if self.vpad:
            self.vpad.close()
        self.fds.clear()


# ---------------------------------------------------------------- the service
def service():
    def log(msg):
        if os.environ.get("XCONTROL_DEBUG"):
            print(f"xcontrol-pads: {msg}", file=sys.stderr, flush=True)

    flags = {"quit": False, "reload": True}
    signal.signal(signal.SIGTERM, lambda *_a: flags.update(quit=True))
    signal.signal(signal.SIGINT, lambda *_a: flags.update(quit=True))
    signal.signal(signal.SIGHUP, lambda *_a: flags.update(reload=True))
    controllers = {}         # pad key -> Controller
    settings = load()
    scanned = 0.0
    written = None
    try:
        while not flags["quit"]:
            if flags["reload"]:
                flags["reload"] = False
                settings = load()
                for c in controllers.values():
                    c.close()
                controllers.clear()
                scanned = 0.0
            if time.monotonic() - scanned >= 2:
                scanned = time.monotonic()
                found = {p.key: p for p in pads.discover()}
                for key in list(controllers):
                    if key not in found:
                        controllers.pop(key).close()
                        log(f"gone: {key}")
                for key, pad in found.items():
                    if key not in controllers:
                        controllers[key] = Controller(pad, settings, log)
                        log(f"connected: {pad.name} ({pad.bus})")
            st = {"pid": os.getpid(), "pads": [c.status() for c in controllers.values()]}
            if st != written:
                tmp = _runtime("pads.json.tmp")
                with open(tmp, "w") as f:
                    json.dump(st, f)
                os.replace(tmp, _runtime("pads.json"))
                written = st
            fds = [fd for c in controllers.values() for fd in c.fds]
            try:
                ready, _w, _x = select.select(fds, [], [], 1.0)
            except InterruptedError:
                continue
            for fd in ready:
                for key, c in list(controllers.items()):
                    if fd in c.fds and not c.read(fd):
                        controllers.pop(key).close()
                        break
    finally:
        for c in controllers.values():
            c.close()
        try:
            os.remove(_runtime("pads.json"))
        except OSError:
            pass
    return 0
