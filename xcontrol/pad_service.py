"""xcontrol --pads: the controller service.

For every DualShock 4 and DualSense it sets the light bar, the player lights, the Bluetooth report
rate (DualShock 4) and adaptive triggers (DualSense), measures the rate it really reports at,
and (when asked) hides it from games and shows a virtual Xbox 360 controller instead, with the
buttons remapped, gyro aiming, and rumble passed back to the controller.
It runs under the desktop service, which restarts it when the settings change.
"""
import fcntl
import json
import os
import re
import select
import signal
import struct
import sys
import time

from . import config, focus, gyro, padmap, pads, touchgestures

# ---------------------------------------------------------------- kernel interfaces
EVENT = struct.Struct("llHHi")              # struct input_event (64-bit)
EV_SYN, EV_KEY, EV_ABS, EV_FF, EV_UINPUT = 0x00, 0x01, 0x03, 0x15, 0x0101
FF_RUMBLE, FF_PERIODIC, FF_GAIN = 0x50, 0x51, 0x60
UI_FF_UPLOAD, UI_FF_ERASE = 1, 2
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT, UI_SET_FFBIT = 0x40045564, 0x40045565, 0x40045567, 0x4004556B
UI_SET_RELBIT = 0x40045566
EV_REL, EV_MSC, REL_X, REL_Y = 0x02, 0x04, 0x00, 0x01
BTN_LEFT, BTN_RIGHT, BTN_TOUCH = 0x110, 0x111, 0x14A
UI_DEV_SETUP, UI_ABS_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY = 0x405C5503, 0x401C5504, 0x5501, 0x5502
UI_BEGIN_FF_UPLOAD, UI_END_FF_UPLOAD = 0xC06855C8, 0x406855C9
UI_BEGIN_FF_ERASE, UI_END_FF_ERASE = 0xC00C55CA, 0x400C55CB
EVIOCGRAB, EVIOCSFF, EVIOCRMFF = 0x40044590, 0x40304580, 0x40044581
EVIOCGABS = 0x80184540          # + the axis: struct input_absinfo (6 ints)
FF_EFFECT = struct.Struct("HhHHHHH2x32s")   # type, id, direction, trigger(2), replay(2), union
XBOX_ID = (0x0003, 0x045E, 0x028E, 0x0110)  # USB, Microsoft, Xbox 360 controller

DEFAULT = {"enabled": False, "emulate": "xbox360", "hide_real": True, "touchpad_mouse": False,
           "map": {}, "lightbar": "#0044ff", "brightness": 60, "bt_poll_ms": 1, "gyro": dict(gyro.DEFAULT),
           "player_lights": "auto", "triggers": {"l2": dict(pads.TRIGGER_DEFAULT), "r2": dict(pads.TRIGGER_DEFAULT)},
           "touchpad": dict(touchgestures.DEFAULT), "profiles": []}
# what a per-game layout can change; the rest is the same for every game
PROFILE_KEYS = ("map", "gyro", "lightbar", "brightness", "triggers", "touchpad")
# what can switch the gyro on or off: any button, or touching the touchpad
ACTIVATORS = padmap.SOURCE_ORDER + padmap.EDGE_SOURCES + ["touch"]
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
    out["gyro"] = gyro.normalize(out["gyro"], ACTIVATORS)
    out["touchpad"] = touchgestures.normalize(out["touchpad"])
    if out["player_lights"] not in ("auto", "off"):
        out["player_lights"] = "auto"
    trig = out["triggers"] if isinstance(out["triggers"], dict) else {}
    out["triggers"] = {k: pads.normalize_trigger(trig.get(k)) for k in ("l2", "r2")}
    profiles = []
    for p in out["profiles"] if isinstance(out["profiles"], list) else []:
        if not isinstance(p, dict):
            continue
        sub = p.get("settings") if isinstance(p.get("settings"), dict) else {}
        sub = {k: v for k, v in sub.items() if k in PROFILE_KEYS}
        norm = normalize(sub) if sub else {}
        profiles.append({"name": str(p.get("name") or "").strip()[:60] or "?",
                         "match": [str(m).strip()[:200] for m in (p.get("match") or []) if str(m).strip()][:12],
                         "settings": {k: norm[k] for k in sub}})
    out["profiles"] = profiles[:50]
    c = str(out["lightbar"] or "")
    out["lightbar"] = c if re.fullmatch(r"#[0-9A-Fa-f]{6}", c) else DEFAULT["lightbar"]
    for k, lo, hi in (("brightness", 0, 100), ("bt_poll_ms", 0, 16)):
        try:
            out[k] = max(lo, min(hi, int(out[k])))
        except (TypeError, ValueError):
            out[k] = DEFAULT[k]
    return out


def effective(settings, profile):
    """The settings with a per-game layout (an index into settings["profiles"], or None) applied."""
    if profile is None or not 0 <= profile < len(settings["profiles"]):
        return settings
    merged = dict(settings)
    merged.update(settings["profiles"][profile]["settings"])
    return merged


def choose(settings, names):
    """The per-game layout for the program in front (its names, from focus.Focus), or None."""
    for i, p in enumerate(settings["profiles"]):
        if p["match"] and focus.matches(p["match"], names):
            return i
    return None


def _layout(settings, names, keep=None):
    """choose(), except that with XControl's own window in front the layout named `keep` (the one
    in use) stays: saving a game's layout from there shouldn't switch back to the default."""
    pick = choose(settings, names)
    if pick is None and keep is not None and _ours(names):
        pick = next((i for i, p in enumerate(settings["profiles"]) if p["name"] == keep), None)
    return pick


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


class VirtualMouse:
    """A plain mouse made through /dev/uinput, moved by the gyro."""

    def __init__(self, name="XControl gyro mouse"):
        self.fd = os.open("/dev/uinput", os.O_RDWR | os.O_NONBLOCK)
        try:
            for ev in (EV_SYN, EV_KEY, EV_REL):
                fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
            for key in (BTN_LEFT, BTN_RIGHT):     # (without buttons it isn't taken for a mouse)
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, key)
            for rel in (REL_X, REL_Y):
                fcntl.ioctl(self.fd, UI_SET_RELBIT, rel)
            fcntl.ioctl(self.fd, UI_DEV_SETUP, struct.pack("HHHH80sI", 0x06, 0, 0, 1, name.encode()[:79], 0))
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise

    def move(self, dx, dy):
        events = [(EV_REL, REL_X, dx)] if dx else []
        events += [(EV_REL, REL_Y, dy)] if dy else []
        if events:
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
    def __init__(self, pad, settings, log, player=1):
        self.pad, self.log, self.player = pad, log, player
        self.seq = 0             # DualSense Bluetooth output report sequence
        self.triggers_ok = None
        self.fds = {}            # fd -> role
        self.vpad = self.rumble = None
        self.mapper = None
        self.rate_count, self.rate_since, self.rate = 0, time.monotonic(), 0
        self.error = ""
        self.hidden, self.hide_error = [], ""
        self.raw = None          # the hidraw node, kept open: the report rate still works once it's hidden
        if pad.hidraw:
            try:
                self.raw = os.open(pad.hidraw, os.O_WRONLY | os.O_NONBLOCK)
            except OSError:
                pass
        self.lightbar_ok = self.poll_ok = None
        self.gyro, self.mouse, self.mouse_error = gyro.Gyro(settings["gyro"]), None, ""
        self.phys = {padmap.ABS_X: 0, padmap.ABS_Y: 0, padmap.ABS_RX: 0, padmap.ABS_RY: 0}   # the real sticks
        self.gestures = touchgestures.Gestures(settings["touchpad"], *self._touch_size())
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
                if settings["hide_real"]:
                    self._hide()
        self.apply(settings)

    def _touch_size(self):
        """The touchpad's size (from its device; the known sizes otherwise)."""
        default = (1920, 1080) if self.pad.model == "dualsense" else (1920, 942)
        if not self.pad.touchpad:
            return default
        try:
            fd = os.open(self.pad.touchpad, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return default
        try:
            size = []
            for axis in (0, 1):
                buf = bytearray(24)
                fcntl.ioctl(fd, EVIOCGABS + axis, buf)
                size.append(struct.unpack("6i", buf)[2] + 1)
            return tuple(size) if all(v > 1 for v in size) else default
        except OSError:
            return default
        finally:
            os.close(fd)

    def _axis(self, code):
        """A stick axis as games get it: the real stick, plus the gyro and the touchpad."""
        v = self.phys.get(code, 0)
        if code in (padmap.ABS_RX, padmap.ABS_RY):
            v = self.gyro.stick_value(code, v)
        side = self.gestures.s["stick"]
        if (side == "right" and code in (padmap.ABS_RX, padmap.ABS_RY)) or \
                (side == "left" and code in (padmap.ABS_X, padmap.ABS_Y)):
            v += self.gestures.stick[0 if code in (padmap.ABS_X, padmap.ABS_RX) else 1] * 32767
        return max(-32768, min(32767, int(round(v))))

    def _sticks(self, codes):
        return [(EV_ABS, c, self._axis(c)) for c in codes]

    def tick(self):
        """Swipe releases that are due; returns seconds until the next one (or None)."""
        if self.mapper and self.vpad:
            out = []
            for _kind, src, down in self.gestures.tick():
                out += self.mapper.press(src, down)
            if out:
                self.vpad.send(out)
        return self.gestures.next_due()

    def apply(self, settings):
        """The light bar, the Bluetooth report rate and the gyro (no need to reopen anything)."""
        self.lightbar_ok = pads.set_lightbar(self.pad, settings["lightbar"], settings["brightness"])
        if self.pad.bus == "bluetooth" and self.pad.model == "ds4":
            self.poll_ok = pads.set_bt_poll(self.pad, settings["bt_poll_ms"], self.raw)
        if self.pad.players:
            pads.set_player_lights(self.pad, self.player if settings["player_lights"] == "auto" else 0)
        if self.pad.model == "dualsense":
            self._set_triggers(settings["triggers"])
        if self.mapper and padmap.normalize_map(settings["map"]) != self.mapper.map:
            self.mapper = padmap.Mapper(settings["map"])     # (a per-game layout, or edited)
        old_side = self.gestures.s["stick"]
        self.gestures.set(settings["touchpad"])
        if old_side != self.gestures.s["stick"] and self.vpad:
            self.gestures.stick = (0.0, 0.0)
            self.vpad.send(self._sticks(list(self.phys)))
        g = settings["gyro"]
        self.gyro.set(g)
        if g["output"] == "mouse" and not self.mouse:
            try:
                self.mouse = VirtualMouse()
                self.mouse_error = ""
            except OSError as e:
                self.mouse_error = f"uinput: {e.strerror}"
        elif g["output"] != "mouse" and self.mouse:
            self.mouse.close()
            self.mouse = None
        if g["output"] != "off":
            # the activation button is read from the controller, even without the Xbox pad
            roles = set(self.fds.values())
            if "gamepad" not in roles and self.pad.gamepad:
                self._open(self.pad.gamepad, "gamepad")
            if g["button"] == "touch" and "touchpad" not in roles and self.pad.touchpad:
                self._open(self.pad.touchpad, "touchpad")
        if g["output"] != "stick" and self.vpad and self.gyro.stick != (0.0, 0.0):
            self.gyro.stick = (0.0, 0.0)
            self.vpad.send(self._sticks(list(self.phys)))

    def _set_triggers(self, triggers):
        self.triggers_ok = pads.set_triggers(self.pad, triggers["l2"], triggers["r2"], self.raw, self.seq)
        self.seq = (self.seq + 1) & 0x0F

    def _activation(self, role, etype, code, value):
        b = self.gyro.s["button"]
        if b == "touch":
            if role == "touchpad" and etype == EV_KEY and code == BTN_TOUCH:
                self.gyro.press(value != 0)
            return
        src = padmap.SOURCES.get(b)
        if isinstance(src, int):
            if etype == EV_KEY and code == src and role == ("touchpad" if b == "touchpad" else "gamepad"):
                self.gyro.press(value != 0)
        elif src and role == "gamepad" and etype == EV_ABS:
            axis = padmap.ABS_HAT0Y if src in ("hat_up", "hat_down") else padmap.ABS_HAT0X
            if code == axis:
                self.gyro.press(value < 0 if src in ("hat_up", "hat_left") else value > 0)

    def _hide(self):
        """Games find controllers through their device files (SDL, Wine and Steam read the raw
        HID device, past any grab), so take the user's access to them away; what this service
        already opened keeps working."""
        nodes = pads.hide_nodes(self.pad)
        ok, msg = pads.set_hidden(nodes, True)
        if ok:
            self.hidden = nodes
            self.log(f"hidden: {' '.join(nodes)}")
        else:
            self.hide_error = msg
            self.log(f"couldn't hide: {msg}")

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
            data = os.read(fd, EVENT.size * 512)
        except BlockingIOError:
            return True
        except OSError:
            return False    # unplugged
        if not data:
            return False
        out = []
        pending = []     # touchpad events, for the gestures (with their SYN_REPORTs)
        for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _s, _u, etype, code, value = EVENT.unpack_from(data, off)
            if role == "sensors":
                if etype == EV_SYN and code == 0:
                    self.rate_count += 1
                moved = self.gyro.feed(etype, code, value)
                if moved is True and self.vpad:
                    out += self._sticks((padmap.ABS_RX, padmap.ABS_RY))
                elif moved and moved is not True and self.mouse:
                    self.mouse.move(*moved)
            elif role == "virtual":
                self.rumble.handle(etype, code, value)
            elif role in ("gamepad", "touchpad"):
                if etype == EV_SYN:
                    if role == "touchpad" and self.mapper and code == 0:
                        pending.append((etype, code, value))    # (the end of a touchpad report)
                    continue
                self._activation(role, etype, code, value)
                if not self.mapper:
                    continue
                if role == "touchpad":
                    pending.append((etype, code, value))
                    continue
                for t, c, v in self.mapper.feed(etype, code, value):
                    if t == EV_ABS and c in self.phys:      # the sticks, plus the gyro and the touchpad
                        self.phys[c] = v
                        v = self._axis(c)
                    out.append((t, c, v))
        for etype, code, value in pending:
            for action in self.gestures.feed(etype, code, value):
                if action[0] == "press":
                    out += self.mapper.press(action[1], action[2])
                else:
                    side = self.gestures.s["stick"]
                    out += self._sticks((padmap.ABS_RX, padmap.ABS_RY) if side == "right"
                                        else (padmap.ABS_X, padmap.ABS_Y))
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
                "hidraw_ok": self.raw is not None or pads.hidraw_writable(self.pad),
                "hidden": bool(self.hidden), "hide_error": self.hide_error,
                "gyro": self.gyro.status() if self.gyro.s["output"] != "off" else "",
                "gyro_error": self.mouse_error, "model": self.pad.model, "triggers_ok": self.triggers_ok}

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
        if self.mouse:
            self.mouse.close()
            self.mouse = None
        self.fds.clear()
        if self.pad.model == "dualsense" and self.raw is not None:    # triggers back to normal
            off = pads.normalize_trigger({})
            self._set_triggers({"l2": off, "r2": off})
        if self.raw is not None:
            try:
                os.close(self.raw)
            except OSError:
                pass
            self.raw = None
        if self.hidden:
            pads.set_hidden(self.hidden, False)     # (gone already when it was unplugged)
            self.hidden = []


# ---------------------------------------------------------------- the service
# applied without reopening the controllers
LIVE = ("lightbar", "brightness", "bt_poll_ms", "gyro", "player_lights", "triggers", "map", "profiles", "touchpad")


def restart_keys(settings):
    return {k: v for k, v in settings.items() if k not in LIVE}


def calibrate_running():
    """Ask a running service to calibrate the gyros now (the controllers should lie still)."""
    pid = state().get("pid")
    try:
        os.kill(pid, signal.SIGUSR1)
        return True
    except (OSError, TypeError):
        return False


def _ours(names):
    """XControl's own window: editing a game's layout there shouldn't switch it back."""
    return any("xcontrol" in n.lower() for n in names[:2])     # (its WM_CLASS)


def reload_running():
    """Tell a running service to pick up the saved settings; False when none runs."""
    pid = state().get("pid")
    if not pid:
        return False
    try:
        os.kill(pid, signal.SIGHUP)
        return True
    except OSError:
        return False


def service():
    def log(msg):
        if os.environ.get("XCONTROL_DEBUG"):
            print(f"xcontrol-pads: {msg}", file=sys.stderr, flush=True)

    flags = {"quit": False, "reload": True, "calibrate": False}
    signal.signal(signal.SIGTERM, lambda *_a: flags.update(quit=True))
    signal.signal(signal.SIGINT, lambda *_a: flags.update(quit=True))
    signal.signal(signal.SIGHUP, lambda *_a: flags.update(reload=True))
    signal.signal(signal.SIGUSR1, lambda *_a: flags.update(calibrate=True))
    controllers = {}         # pad key -> Controller
    settings = load()
    scanned = reported = 0.0
    written = None
    front = focus.Focus()    # which program is in front, for the per-game layouts
    looked, names, active = 0.0, [], None
    recent = []              # the last few programs in front (not XControl), for the page
    try:
        while not flags["quit"]:
            if flags["reload"]:
                flags["reload"] = False
                new = load()
                in_place = restart_keys(new) == restart_keys(settings) and controllers
                keep = settings["profiles"][active]["name"] if active is not None else None
                settings = new
                active = _layout(settings, names, keep)    # (the layouts may have changed, or gone)
                reported = 0.0
                if in_place:
                    for c in controllers.values():      # (light bar, rate, gyro, layouts...: in place)
                        c.apply(effective(settings, active))
                else:
                    for c in controllers.values():
                        c.close()
                    controllers.clear()
                    scanned = 0.0
            if flags["calibrate"]:
                flags["calibrate"] = False
                for c in controllers.values():
                    c.gyro.calibrate()
            if front.dpy and time.monotonic() - looked >= 0.5:
                looked = time.monotonic()
                now = front.names()
                if now != names:
                    names = now
                    if names and not _ours(names):
                        recent = ([names] + [r for r in recent if r != names])[:8]
                    pick = choose(settings, names)
                    if pick != active and not (pick is None and _ours(names)):
                        active, reported = pick, 0.0
                        log(f"layout: {settings['profiles'][active]['name'] if active is not None else 'default'}")
                        for c in controllers.values():
                            c.apply(effective(settings, active))
            if time.monotonic() - scanned >= 2:
                scanned = time.monotonic()
                found = {p.key: p for p in pads.discover()}
                for key in list(controllers):
                    if key not in found:
                        controllers.pop(key).close()
                        log(f"gone: {key}")
                        reported = 0.0
                for key, pad in found.items():
                    if key not in controllers:
                        reported = 0.0
                        taken = {c.player for c in controllers.values()}
                        player = next(n for n in range(1, len(controllers) + 2) if n not in taken)
                        controllers[key] = Controller(pad, effective(settings, active), log, player)
                        log(f"connected: {pad.name} ({pad.bus})")
            # what the page shows (it looks every 2 s): not after every event, the sensors send hundreds a second
            if time.monotonic() - reported >= 1.0:
                reported = time.monotonic()
                st = {"pid": os.getpid(), "pads": [c.status() for c in controllers.values()],
                      "profile": settings["profiles"][active]["name"] if active is not None else "",
                      "recent": recent}
                if st != written:
                    tmp = _runtime("pads.json.tmp")
                    try:
                        with open(tmp, "w") as f:
                            json.dump(st, f)
                        os.replace(tmp, _runtime("pads.json"))
                        written = st
                    except OSError as e:
                        log(f"couldn't write the state: {e}")
            fds = [fd for c in controllers.values() for fd in c.fds]
            wait = 0.5
            for c in controllers.values():        # (swipe presses to let go of)
                due = c.tick()
                if due is not None:
                    wait = min(wait, due)
            ready, _w, _x = select.select(fds, [], [], wait)    # (signals: retried, then the flags are seen)
            for fd in ready:
                for key, c in list(controllers.items()):
                    if fd in c.fds and not c.read(fd):
                        controllers.pop(key).close()
                        reported = 0.0
                        break
    finally:
        for c in controllers.values():
            c.close()
        front.close()
        try:
            os.remove(_runtime("pads.json"))
        except OSError:
            pass
    return 0
