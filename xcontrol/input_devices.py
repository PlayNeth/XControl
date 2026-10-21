"""Mice, touchpads and other pointers through the X libinput driver (xinput).

Settings are libinput's X device properties. They take effect at once, but X
forgets them when a device is unplugged or the session ends, so XControl saves
them per device name and puts them back at login and when a device is plugged
in (see watch()).
"""
import fcntl
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field

from . import config

PROFILE_NAMES = ["adaptive", "flat", "custom"]        # order of "libinput Accel Profile Enabled"
SCROLL_NAMES = ["twofinger", "edge", "button"]         # order of "libinput Scroll Method Enabled"
CLICK_NAMES = ["buttonareas", "clickfinger"]           # order of "libinput Click Method Enabled"

# setting -> (property, kind); kind: bool, float, or a one-hot list of names
SETTINGS = {
    "accel_profile": ("libinput Accel Profile Enabled", PROFILE_NAMES),
    "accel_speed": ("libinput Accel Speed", "float"),
    "natural_scroll": ("libinput Natural Scrolling Enabled", "bool"),
    "left_handed": ("libinput Left Handed Enabled", "bool"),
    "middle_emulation": ("libinput Middle Emulation Enabled", "bool"),
    "scroll_factor": ("libinput Scrolling Factor", "float"),
    "horizontal_scroll": ("libinput Horizontal Scroll Enabled", "bool"),
    "tapping": ("libinput Tapping Enabled", "bool"),
    "tap_drag": ("libinput Tapping Drag Enabled", "bool"),
    "tap_drag_lock": ("libinput Tapping Drag Lock Enabled", "bool"),
    "disable_while_typing": ("libinput Disable While Typing Enabled", "bool"),
    "scroll_method": ("libinput Scroll Method Enabled", SCROLL_NAMES),
    "click_method": ("libinput Click Method Enabled", CLICK_NAMES),
}
# one-hot settings: which choices this device offers
AVAILABLE = {
    "accel_profile": "libinput Accel Profiles Available",
    "scroll_method": "libinput Scroll Methods Available",
    "click_method": "libinput Click Methods Available",
}


@dataclass
class Device:
    id: int
    name: str
    kind: str                      # "pointer" or "keyboard"
    props: dict = field(default_factory=dict)   # property name -> [values as strings]

    @property
    def is_libinput(self):
        return any(p.startswith("libinput ") for p in self.props)

    @property
    def is_touchpad(self):
        return "libinput Tapping Enabled" in self.props

    def has(self, key):
        return SETTINGS[key][0] in self.props

    def get(self, key, default=False):
        """Current value of a setting, or the device's default with default=True."""
        prop, kind = SETTINGS[key]
        if default:
            prop += " Default"
        values = self.props.get(prop)
        if values is None:
            return None
        return decode(kind, values)

    def choices(self, key):
        """The one-hot choices this device supports, e.g. ["adaptive", "flat"]."""
        kind = SETTINGS[key][1]
        avail = self.props.get(AVAILABLE[key])
        if avail is None:
            return []
        out = [n for n, v in zip(kind, avail) if v.strip() == "1"]
        if key in ("scroll_method", "click_method"):
            out.append("none")
        return out


def decode(kind, values):
    if kind == "bool":
        return values[0].strip() == "1"
    if kind == "float":
        return float(values[0])
    for name, v in zip(kind, values):  # one-hot list
        if v.strip() == "1":
            return name
    return "none"


def encode(kind, value, count):
    """xinput set-prop arguments for a value; `count` is how many values the
    property has on this device (the accel profile list grew from 2 to 3)."""
    if kind == "bool":
        return ["1" if value else "0"]
    if kind == "float":
        return [f"{float(value):.6f}"]
    return ["1" if name == value else "0" for name in kind[:count]]


# ---- reading
_LIST_RE = re.compile(r"^[^A-Za-z0-9]*(?P<name>.+?)\s+id=(?P<id>\d+)\s+\[(?P<role>[^\]]*)\]")
_PROP_RE = re.compile(r"^\t(?P<name>.+?) \((?P<num>\d+)\):\t(?P<values>.*)$")


def available():
    return shutil.which("xinput") is not None and bool(os.environ.get("DISPLAY"))


def _run(args, timeout=10):
    out = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                         env=dict(os.environ, LC_ALL="C"))
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"{args[0]} exited with {out.returncode}")
    return out.stdout


def parse_list(text):
    """`xinput list` -> [Device] for the real slave devices (no masters, no XTEST)."""
    devices = []
    for line in text.splitlines():
        m = _LIST_RE.match(line)
        if not m:
            continue
        role = m["role"]
        name = m["name"].strip()
        if "master" in role or "XTEST" in name:
            continue
        kind = "keyboard" if "keyboard" in role else "pointer"
        devices.append(Device(int(m["id"]), name, kind))
    return devices


def parse_props(text):
    props = {}
    for line in text.splitlines():
        m = _PROP_RE.match(line)
        if m:
            vals = m["values"]
            props[m["name"]] = [] if vals == "<no items>" else [v.strip() for v in vals.split(",")]
    return props


def _load_props(d):
    try:
        d.props = parse_props(_run(["xinput", "list-props", str(d.id)]))
    except (RuntimeError, OSError, subprocess.SubprocessError):
        d.props = {}


def list_devices(with_props=True):
    devices = parse_list(_run(["xinput", "list"]))
    if with_props:
        for d in devices:
            _load_props(d)
    return devices


def pointers():
    """libinput pointer devices (mice, touchpads, trackballs), one per name."""
    seen, out = set(), []
    for d in list_devices():
        if d.kind == "pointer" and d.is_libinput and d.name not in seen:
            seen.add(d.name)
            out.append(d)
    return out


# ---- writing
def set_args(device, key, value):
    prop, kind = SETTINGS[key]
    count = len(device.props.get(prop, [])) or 1
    return ["xinput", "set-prop", str(device.id), prop, *encode(kind, value, count)]


def apply(device, key, value):
    """Change one setting on every connected device with this device's name
    (a mouse often shows up as several pointer devices)."""
    for d in list_devices(with_props=False):
        if d.name == device.name and d.kind == device.kind:
            _load_props(d)   # (only these: one xinput call per device)
            if d.has(key):
                _run(set_args(d, key, value))


def apply_saved(devices=None, log=None):
    """Put the saved settings back on every connected device that has them."""
    saved = config.load()["input"]["devices"]
    if not saved:
        return 0
    if devices is None:
        devices = [d for d in list_devices(with_props=False) if d.name in saved]
        for d in devices:
            _load_props(d)
    count = 0
    for d in devices:
        for key, value in saved.get(d.name, {}).items():
            if key in SETTINGS and d.has(key) and d.get(key) != value:
                try:
                    _run(set_args(d, key, value))
                    count += 1
                except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                    if log:
                        log(f"{d.name}: {key}: {e}")
    return count


def save_setting(name, key, value):
    data = config.load()
    data["input"]["devices"].setdefault(name, {})[key] = value
    config.save(data)


def forget_device(name):
    data = config.load()
    data["input"]["devices"].pop(name, None)
    config.save(data)


# ---- keeping settings across hotplug
def _lock_path():
    run = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    disp = re.sub(r"[^0-9.]", "", os.environ.get("DISPLAY", "")) or "0"
    return os.path.join(run, f"xcontrol-input-{disp}.lock")


def watcher_running():
    try:
        fd = os.open(_lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def start_watcher():
    """Start the background helper that re-applies settings on hotplug, unless running."""
    if watcher_running() or not available():
        return
    exe = shutil.which("xcontrol") or sys.argv[0]
    try:
        subprocess.Popen([exe, "--watch-input"], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def watch(apply_keyboard=None):
    """xcontrol --watch-input: apply saved settings now and whenever X reports a new
    input device (XI2 HierarchyChanged). Exits when the X server goes away."""
    def log(msg):
        if os.environ.get("XCONTROL_DEBUG"):
            print(f"xcontrol-input: {msg}", file=sys.stderr)

    try:
        lock = os.open(_lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("already running")
        return 0

    def apply_all():
        try:
            n = apply_saved(log=log)
            log(f"applied {n} pointer settings")
        except Exception as e:  # noqa: BLE001
            log(f"apply failed: {e}")
        if apply_keyboard:
            try:
                apply_keyboard()
            except Exception as e:  # noqa: BLE001
                log(f"keyboard: {e}")

    apply_all()
    events = _xi2_hotplug() or _xinput_hotplug()
    for _added in events or ():
        log("device added")
        apply_all()
    return 0


# XI2: XIAllDevices, XI_HierarchyChanged, GenericEvent; flags XISlaveAdded | XISlaveAttached | XIDeviceEnabled
_XI_ALL_DEVICES, _XI_HIERARCHY_CHANGED, _GENERIC_EVENT = 0, 11, 35
_XI_ADDED = (1 << 2) | (1 << 4) | (1 << 6)


def _xi2_hotplug():
    """Hotplug events straight from X (libX11 and libXi through ctypes), selecting only
    HierarchyChanged on the root window: `xinput test-xi2 --root` also selects every key
    press and mouse motion, which would wake this helper hundreds of times a second.
    A generator yielding once per device added; None when X or libXi can't be used.
    When the X server goes away, Xlib ends the process."""
    import ctypes
    import ctypes.util
    try:
        x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        xi = ctypes.CDLL(ctypes.util.find_library("Xi") or "libXi.so.6")
    except OSError:
        return None
    vp, ci, cul = ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong

    class Cookie(ctypes.Structure):     # XGenericEventCookie
        _fields_ = [("type", ci), ("serial", cul), ("send_event", ci), ("display", vp), ("extension", ci),
                    ("evtype", ci), ("cookie", ctypes.c_uint), ("data", vp)]

    class Event(ctypes.Union):          # XEvent
        _fields_ = [("cookie", Cookie), ("pad", ctypes.c_long * 24)]

    class Hierarchy(ctypes.Structure):  # XIHierarchyEvent (the start of it)
        _fields_ = [("type", ci), ("serial", cul), ("send_event", ci), ("display", vp), ("extension", ci),
                    ("evtype", ci), ("time", cul), ("flags", ci)]

    class Mask(ctypes.Structure):       # XIEventMask
        _fields_ = [("deviceid", ci), ("mask_len", ci), ("mask", ctypes.POINTER(ctypes.c_ubyte))]

    x11.XOpenDisplay.restype = vp
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = cul
    x11.XDefaultRootWindow.argtypes = [vp]
    x11.XQueryExtension.argtypes = [vp, ctypes.c_char_p] + [ctypes.POINTER(ci)] * 3
    x11.XNextEvent.argtypes = [vp, ctypes.POINTER(Event)]
    x11.XPending.argtypes = x11.XFlush.argtypes = x11.XCloseDisplay.argtypes = [vp]
    x11.XGetEventData.argtypes = x11.XFreeEventData.argtypes = [vp, ctypes.POINTER(Cookie)]
    xi.XIQueryVersion.argtypes = [vp, ctypes.POINTER(ci), ctypes.POINTER(ci)]
    xi.XISelectEvents.argtypes = [vp, cul, ctypes.POINTER(Mask), ci]
    dpy = x11.XOpenDisplay(None)
    if not dpy:
        return None
    opcode, ev_base, err_base, major, minor = ci(), ci(), ci(), ci(2), ci(0)
    if not x11.XQueryExtension(dpy, b"XInputExtension", ctypes.byref(opcode), ctypes.byref(ev_base),
                               ctypes.byref(err_base)) \
            or xi.XIQueryVersion(dpy, ctypes.byref(major), ctypes.byref(minor)) != 0:
        x11.XCloseDisplay(dpy)
        return None
    bits = (ctypes.c_ubyte * 2)()
    bits[_XI_HIERARCHY_CHANGED >> 3] = 1 << (_XI_HIERARCHY_CHANGED & 7)
    mask = Mask(_XI_ALL_DEVICES, len(bits), ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte)))
    xi.XISelectEvents(dpy, x11.XDefaultRootWindow(dpy), ctypes.byref(mask), 1)
    x11.XFlush(dpy)

    def added(ev):
        x11.XNextEvent(dpy, ctypes.byref(ev))
        c = ev.cookie
        if c.type != _GENERIC_EVENT or c.extension != opcode.value or not x11.XGetEventData(dpy, ctypes.byref(c)):
            return False
        try:
            return c.evtype == _XI_HIERARCHY_CHANGED and bool(
                ctypes.cast(c.data, ctypes.POINTER(Hierarchy)).contents.flags & _XI_ADDED)
        finally:
            x11.XFreeEventData(dpy, ctypes.byref(c))

    def events():
        ev = Event()
        while True:
            if added(ev):
                time.sleep(0.5)          # let the driver finish setting the device up
                while x11.XPending(dpy):  # one plug brings several events: apply once
                    added(ev)
                yield True
    return events()


def _xinput_hotplug():
    """The same from `xinput test-xi2 --root` (no libXi); ends when the X server goes away."""
    if not shutil.which("xinput"):
        return None

    def events():
        proc = subprocess.Popen(["xinput", "test-xi2", "--root"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, bufsize=1)
        try:
            for line in proc.stdout:
                # "    Changes happened:  [new slave] ... [device enabled]" (xinput test-xi2)
                if line.lstrip().startswith("Changes happened:") and any(
                        f in line for f in ("[new slave]", "[device enabled]", "[slave attached]")):
                    time.sleep(0.5)  # let the driver finish setting the device up
                    yield True
        finally:
            proc.kill()
            proc.wait()
    return events()
