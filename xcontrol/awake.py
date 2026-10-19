"""Keeping the screen on: what the desktop service uses for the "Keep the screen on" settings.

- Gamepads and joysticks count as activity (like joystickwake): any button or a real stick
  movement resets X's idle timer, so the screen lock and screen-off timers start over,
  exactly as a key press would.
- Apps that ask: XControl answers org.freedesktop.ScreenSaver.Inhibit on the session bus
  (Steam, browsers, video players and SDL games use it) when no desktop does.
- Full-screen windows: while the focused window is full screen.
- By hand: `xcontrol --awake on|off|toggle|MINUTES`.

While something keeps the screen on, the service suspends X's screen saver and DPMS timers
(XScreenSaverSuspend); X lifts that by itself if the service ever goes away.
"""
import ctypes
import ctypes.util
import glob
import json
import os
import re
import struct
import time

# ---------------------------------------------------------------- by hand


def _manual_path(runtime):
    return runtime("awake")


def manual_until(runtime):
    """None when off; 0 when on until turned off; else the time it ends."""
    try:
        with open(_manual_path(runtime)) as f:
            until = float(json.load(f).get("until", 0))
    except (OSError, ValueError, AttributeError):
        return None
    if until and until <= time.time():
        try:
            os.remove(_manual_path(runtime))
        except OSError:
            pass
        return None
    return until


def set_manual(runtime, how):
    """how: "on", "off", "toggle" or a number of minutes. Returns the new manual_until()."""
    path = _manual_path(runtime)
    if how == "toggle":
        how = "off" if manual_until(runtime) is not None else "on"
    if how == "off":
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    until = 0 if how == "on" else time.time() + max(1, int(float(how))) * 60
    with open(path + ".tmp", "w") as f:
        json.dump({"until": until}, f)
    os.replace(path + ".tmp", path)
    return until


# ---------------------------------------------------------------- gamepads
EV_KEY, EV_ABS = 0x01, 0x03
BTN_JOYSTICK, BTN_GAMEPAD, BTN_DIGI = 0x120, 0x130, 0x140
_EVENT = struct.Struct("llHHi")          # struct input_event (64-bit time)
_ABSINFO = struct.Struct("iiiiii")       # value, minimum, maximum, fuzz, flat, resolution


def _ioc(direction, nr, size):
    return (direction << 30) | (size << 16) | (ord("E") << 8) | nr


def _udev_props(dev):
    """udev's properties for an input device node, from /run/udev/data."""
    try:
        rdev = os.stat(dev).st_rdev
    except OSError:
        return {}
    props = {}
    try:
        with open(f"/run/udev/data/c{os.major(rdev)}:{os.minor(rdev)}", errors="replace") as f:
            for line in f:
                if line.startswith("E:") and "=" in line:
                    k, v = line[2:].rstrip("\n").split("=", 1)
                    props[k] = v
    except OSError:
        pass
    return props


def _key_bits(sysdir):
    try:
        with open(os.path.join(sysdir, "device", "capabilities", "key")) as f:
            words = f.read().split()
    except OSError:
        return 0
    bits = 0
    for w in words:   # highest word first, each a long
        bits = (bits << (8 * struct.calcsize("l"))) | int(w, 16)
    return bits


def is_gamepad(dev, sysroot="/sys/class/input"):
    """A joystick or gamepad (not its motion sensor or touchpad)."""
    props = _udev_props(dev)
    if props:
        return props.get("ID_INPUT_JOYSTICK") == "1" and props.get("ID_INPUT_ACCELEROMETER") != "1"
    bits = _key_bits(os.path.join(sysroot, os.path.basename(dev)))   # no udev data: guess from the buttons
    return any(bits >> b & 1 for b in range(BTN_JOYSTICK, BTN_DIGI))


def device_name(dev, sysroot="/sys/class/input"):
    try:
        with open(os.path.join(sysroot, os.path.basename(dev), "device", "name")) as f:
            return f.read().strip()
    except OSError:
        return os.path.basename(dev)


def is_virtual(dev, sysroot="/sys/class/input"):
    """Made by a program through /dev/uinput (Steam Input, sc-controller, xboxdrv, input-remapper...),
    not a device plugged in."""
    return "/devices/virtual/" in os.path.realpath(os.path.join(sysroot, os.path.basename(dev)))


_INTERPRETERS = {"python", "python3", "perl", "ruby", "node", "sh", "bash"}


def uinput_users(proc="/proc"):
    """Programs of this user that hold /dev/uinput open: the ones that can make virtual devices.
    (System services run as root and can't be seen from here.)"""
    names = []
    for d in glob.glob(os.path.join(proc, "[0-9]*")):
        try:
            if os.stat(d).st_uid != os.getuid():
                continue
            if not any(os.readlink(os.path.join(d, "fd", fd)) == "/dev/uinput"
                       for fd in os.listdir(os.path.join(d, "fd"))):
                continue
            with open(os.path.join(d, "cmdline"), "rb") as f:
                args = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if not args:
            continue
        prog = os.path.basename(args[0])
        if re.sub(r"[\d.]+$", "", prog) in _INTERPRETERS:   # python3 /usr/bin/scc-daemon -> scc-daemon
            prog = next((os.path.basename(a) for a in args[1:] if not a.startswith("-")), prog)
        if prog not in names:
            names.append(prog)
    return names


class Gamepads:
    """Watch every gamepad/joystick event device; rescans for new ones every few seconds."""

    def __init__(self, devdir="/dev/input", sysroot="/sys/class/input"):
        self.devdir, self.sysroot = devdir, sysroot
        self.open = {}        # fd -> (path, name, {axis: (min, max, last)})
        self.denied = {}      # path -> name (no permission)
        self.scanned = 0.0
        self.last = 0.0       # time of the last real input

    def names(self):
        return sorted({n for _p, n, _a in self.open.values()})

    def details(self):
        """[{"name", "path", "virtual", "makers"}] of the watched devices, for the page."""
        out, makers = [], None
        for p, n, _a in sorted(self.open.values()):
            virtual = is_virtual(p, self.sysroot)
            if virtual and makers is None:
                makers = uinput_users()
            out.append({"name": n, "path": p, "virtual": virtual, "makers": makers if virtual else []})
        return out

    def rescan(self, force=False):
        if not force and time.time() - self.scanned < 3:
            return
        self.scanned = time.time()
        have = {p for p, _n, _a in self.open.values()}
        paths = set(glob.glob(os.path.join(self.devdir, "event*")))
        for fd, (p, _n, _a) in list(self.open.items()):
            if p not in paths:
                self._close(fd)
        for p in sorted(paths - have):
            if not is_gamepad(p, self.sysroot):
                continue
            name = device_name(p, self.sysroot)
            try:
                fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
            except PermissionError:
                self.denied[p] = name
                continue
            except OSError:
                continue
            self.denied.pop(p, None)
            self.open[fd] = (p, name, {})
        for p in list(self.denied):
            if p not in paths:
                del self.denied[p]

    def fds(self):
        return list(self.open)

    def _close(self, fd):
        try:
            os.close(fd)
        except OSError:
            pass
        self.open.pop(fd, None)

    def _axis(self, fd, code):
        axes = self.open[fd][2]
        if code not in axes:
            import fcntl
            buf = bytearray(_ABSINFO.size)
            try:
                fcntl.ioctl(fd, _ioc(2, 0x40 + code, _ABSINFO.size), buf)
                value, lo, hi, _fz, _fl, _r = _ABSINFO.unpack(buf)
            except OSError:   # guess: hats (d-pads) are -1..1, sticks 16-bit
                value, lo, hi = (0, -1, 1) if 0x10 <= code <= 0x17 else (0, -32768, 32767)
            axes[code] = [lo, hi, value]
        return axes[code]

    def read(self, fd):
        """Read what's waiting on fd; True when it was real input (a button, or a stick or
        trigger moving more than a tenth of its range: stick drift doesn't count)."""
        hit = False
        try:
            data = os.read(fd, _EVENT.size * 64)
        except BlockingIOError:
            return False
        except OSError:   # unplugged
            self._close(fd)
            return False
        if not data:
            self._close(fd)
            return False
        for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
            _s, _us, etype, code, value = _EVENT.unpack_from(data, off)
            if etype == EV_KEY and value:
                hit = True
            elif etype == EV_ABS:
                ax = self._axis(fd, code)
                span = max(1, ax[1] - ax[0])
                if span <= 2 or abs(value - ax[2]) * 10 >= span:   # d-pad hats are -1..1
                    ax[2] = value
                    hit = hit or span > 2 or value != 0
        if hit:
            self.last = time.time()
        return hit

    def close(self):
        for fd in list(self.open):
            self._close(fd)


# ---------------------------------------------------------------- X
class XIdle:
    """Screen saver / DPMS control on an X connection (ctypes; libXss and libXext)."""

    def __init__(self, x11, dpy):
        self.x11, self.dpy = x11, dpy
        vp = ctypes.c_void_p
        x11.XResetScreenSaver.argtypes = [vp]
        x11.XFlush.argtypes = [vp]
        self.xss = self.xext = None
        try:
            self.xss = ctypes.CDLL(ctypes.util.find_library("Xss") or "libXss.so.1")
            self.xss.XScreenSaverSuspend.argtypes = [vp, ctypes.c_int]
            self.xss.XScreenSaverQueryExtension.argtypes = [vp] + [ctypes.POINTER(ctypes.c_int)] * 2
            a, b = ctypes.c_int(), ctypes.c_int()
            if not self.xss.XScreenSaverQueryExtension(dpy, ctypes.byref(a), ctypes.byref(b)):
                self.xss = None
        except OSError:
            self.xss = None
        x11.XQueryExtension.argtypes = [vp, ctypes.c_char_p] + [ctypes.POINTER(ctypes.c_int)] * 3
        o, e, er = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        has_dpms = x11.XQueryExtension(dpy, b"DPMS", ctypes.byref(o), ctypes.byref(e), ctypes.byref(er))
        try:
            if not has_dpms:
                raise OSError("no DPMS")
            self.xext = ctypes.CDLL(ctypes.util.find_library("Xext") or "libXext.so.6")
            self.xext.DPMSCapable.argtypes = [vp]
            self.xext.DPMSInfo.argtypes = [vp, ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ubyte)]
            self.xext.DPMSForceLevel.argtypes = [vp, ctypes.c_ushort]
        except (OSError, AttributeError):
            self.xext = None
        self.suspended = False
        self._atoms = {}

    def activity(self):
        """Like a key press: restart the idle timers, and wake a screen that's off."""
        self.x11.XResetScreenSaver(self.dpy)
        if self.xext and self.xext.DPMSCapable(self.dpy):
            level, enabled = ctypes.c_ushort(), ctypes.c_ubyte()
            if self.xext.DPMSInfo(self.dpy, ctypes.byref(level), ctypes.byref(enabled)) and enabled.value \
                    and level.value != 0:
                self.xext.DPMSForceLevel(self.dpy, 0)
        self.x11.XFlush(self.dpy)

    def suspend(self, on):
        """Hold off the screen saver (and so the lock) and DPMS while `on`."""
        on = bool(on)
        if on == self.suspended:
            return
        if self.xss:
            self.xss.XScreenSaverSuspend(self.dpy, 1 if on else 0)
        self.activity()   # off: the timers start over, so the screen doesn't go dark the moment a video ends
        self.x11.XFlush(self.dpy)
        self.suspended = on

    # full-screen check: _NET_ACTIVE_WINDOW has _NET_WM_STATE_FULLSCREEN
    def _atom(self, name):
        if name not in self._atoms:
            self.x11.XInternAtom.restype = ctypes.c_ulong
            self.x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            self._atoms[name] = self.x11.XInternAtom(self.dpy, name.encode(), 0)
        return self._atoms[name]

    def _prop(self, window, name):
        x = self.x11
        x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
                                         ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                         ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                         ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                         ctypes.POINTER(ctypes.c_void_p)]
        x.XFree.argtypes = [ctypes.c_void_p]
        atype, fmt, n, after, data = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), \
            ctypes.c_void_p()
        if x.XGetWindowProperty(self.dpy, window, self._atom(name), 0, 64, 0, 4,   # XA_ATOM=4
                                ctypes.byref(atype), ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(after),
                                ctypes.byref(data)) != 0 or not data.value:
            return []
        try:
            if fmt.value != 32:
                return []
            return list((ctypes.c_ulong * n.value).from_address(data.value))
        finally:
            x.XFree(data)

    def fullscreen(self):
        """Whether the focused window is full screen."""
        try:
            self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
            root = self.x11.XDefaultRootWindow(self.dpy)
            # _NET_ACTIVE_WINDOW is a WINDOW (type 33), read it with AnyPropertyType semantics
            active = self._window_prop(root, "_NET_ACTIVE_WINDOW")
            if not active:
                return False
            return self._atom("_NET_WM_STATE_FULLSCREEN") in self._prop(active, "_NET_WM_STATE")
        except Exception:  # noqa: BLE001
            return False

    def _window_prop(self, window, name):
        x = self.x11
        atype, fmt, n, after, data = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), \
            ctypes.c_void_p()
        x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
                                         ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                         ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                         ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                         ctypes.POINTER(ctypes.c_void_p)]
        if x.XGetWindowProperty(self.dpy, window, self._atom(name), 0, 1, 0, 33,   # XA_WINDOW
                                ctypes.byref(atype), ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(after),
                                ctypes.byref(data)) != 0 or not data.value:
            return 0
        try:
            return ctypes.c_ulong.from_address(data.value).value if n.value and fmt.value == 32 else 0
        finally:
            x.XFree(data)


# ---------------------------------------------------------------- org.freedesktop.ScreenSaver
_XML = """
<node>
  <interface name="org.freedesktop.ScreenSaver">
    <method name="Inhibit">
      <arg type="s" name="application_name" direction="in"/>
      <arg type="s" name="reason_for_inhibit" direction="in"/>
      <arg type="u" name="cookie" direction="out"/>
    </method>
    <method name="UnInhibit"><arg type="u" name="cookie" direction="in"/></method>
    <method name="SimulateUserActivity"/>
    <method name="GetActive"><arg type="b" name="active" direction="out"/></method>
    <method name="GetActiveTime"><arg type="u" name="seconds" direction="out"/></method>
    <method name="GetSessionIdleTime"><arg type="u" name="seconds" direction="out"/></method>
    <method name="SetActive">
      <arg type="b" name="e" direction="in"/><arg type="b" name="result" direction="out"/>
    </method>
  </interface>
</node>
"""


class InhibitService:
    """Answers org.freedesktop.ScreenSaver for apps that want the screen to stay on. Runs on
    GLib's default context; the service loop calls pump() to let it work."""

    def __init__(self, on_activity=None):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.cookies = {}         # cookie -> (sender, app, reason)
        self.watches = {}         # sender -> watch id
        self.next = 1
        self.owned = False
        self.on_activity = on_activity
        self.error = ""
        self.ctx = GLib.MainContext.default()
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            self.bus, self.error = None, e.message
            return
        info = Gio.DBusNodeInfo.new_for_xml(_XML).interfaces[0]
        self.regs = [self.bus.register_object(path, info, self._call, None, None)
                     for path in ("/org/freedesktop/ScreenSaver", "/ScreenSaver")]
        self.owner = Gio.bus_own_name_on_connection(self.bus, "org.freedesktop.ScreenSaver",
                                                    Gio.BusNameOwnerFlags.DO_NOT_QUEUE,
                                                    self._acquired, self._lost)

    def _acquired(self, *_a):
        self.owned = True

    def _lost(self, *_a):
        self.owned = False
        if not self.error:
            self.error = "taken"   # another program (a desktop's power manager) answers instead

    def _call(self, _conn, sender, _path, _iface, method, params, invocation):
        GLib = self.GLib
        if method == "Inhibit":
            app, reason = params.unpack()
            cookie = self.next
            self.next += 1
            self.cookies[cookie] = (sender, app or "?", reason or "")
            if sender not in self.watches:
                self.watches[sender] = self.Gio.bus_watch_name_on_connection(
                    self.bus, sender, self.Gio.BusNameWatcherFlags.NONE, None, self._vanished)
            invocation.return_value(GLib.Variant("(u)", (cookie,)))
        elif method == "UnInhibit":
            (cookie,) = params.unpack()
            self.cookies.pop(cookie, None)
            invocation.return_value(None)
        elif method == "SimulateUserActivity":
            if self.on_activity:
                self.on_activity()
            invocation.return_value(None)
        elif method in ("GetActive", "SetActive"):
            invocation.return_value(GLib.Variant("(b)", (False,)))
        else:
            invocation.return_value(GLib.Variant("(u)", (0,)))

    def _vanished(self, _conn, name):
        for c in [c for c, (s, _a, _r) in self.cookies.items() if s == name]:
            del self.cookies[c]
        wid = self.watches.pop(name, None)
        if wid:
            self.Gio.bus_unwatch_name(wid)

    def pump(self):
        while self.ctx.pending():
            self.ctx.iteration(False)

    def apps(self):
        return sorted({a for _s, a, _r in self.cookies.values()})

    def close(self):
        if self.bus is None:
            return
        self.Gio.bus_unown_name(self.owner)
        for r in self.regs:
            self.bus.unregister_object(r)
        self.pump()


def status_text_parts(st):
    """(reasons the screen is kept on now, gamepad names, gamepads without permission)."""
    a = st.get("awake") or {}
    return a.get("reasons") or [], a.get("gamepads") or [], a.get("denied") or []


def joystick_group_hint():
    """The group that owns the event devices, for the 'no permission' message."""
    for p in glob.glob("/dev/input/event*"):
        try:
            import grp
            return grp.getgrgid(os.stat(p).st_gid).gr_name
        except (OSError, KeyError):
            continue
    return "input"
