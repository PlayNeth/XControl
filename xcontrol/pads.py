"""PlayStation controllers (DualShock 4, DualSense): finding them, their light bar, player
lights, battery, Bluetooth report rate (DualShock 4) and adaptive triggers (DualSense).

The kernel's driver (hid-playstation, or hid-sony for the DualShock 4 on old kernels) gives each
controller three input devices (the gamepad, its motion sensors and its touchpad), LEDs for the
light bar (DualShock 4: inputN:red/green/blue/global; DualSense: one inputN:rgb:indicator, plus
inputN:white:player-1..5), a battery, and a hidraw node for raw reports.
"""
import glob
import os
import re
import shutil
import struct
import subprocess
import zlib
from dataclasses import dataclass, field

from .paths import LIBDIR

HELPER = os.path.join(LIBDIR, "xcontrol-controller-helper")
HIDE_HELPER = os.path.join(LIBDIR, "xcontrol-controller-hide")

SONY = 0x054C
DS4_PRODUCTS = {0x05C4: "DualShock 4", 0x09CC: "DualShock 4 (v2)", 0x0BA0: "DualShock 4 USB adapter"}
DUALSENSE_PRODUCTS = {0x0CE6: "DualSense", 0x0DF2: "DualSense Edge"}
PRODUCTS = {**DS4_PRODUCTS, **DUALSENSE_PRODUCTS}
DRIVERS = ("playstation", "sony")
BUS_USB, BUS_BT = 0x0003, 0x0005

# Bluetooth output report 0x11 (78 bytes); see hid-playstation.c
BT_REPORT_ID, BT_REPORT_SIZE = 0x11, 78
HWCTL_HID, HWCTL_CRC32, POLL_MASK = 0x80, 0x40, 0x3F
CRC_SEED = 0xA2
USB_REPORT_ID, USB_REPORT_SIZE = 0x05, 32
FLAG_LED = 0x02
BT_DRIVER_POLL_MS = 4      # what the kernel driver asks for when the controller connects


@dataclass
class Pad:
    key: str                 # the controller's MAC address (the same over USB and Bluetooth)
    name: str
    bus: str                 # "usb" or "bluetooth"
    hid: str                 # /sys/bus/hid/devices/<id>
    gamepad: str = ""        # /dev/input/eventN
    joystick: str = ""       # /dev/input/jsN (the old joystick interface of the gamepad)
    sensors: str = ""
    touchpad: str = ""
    hidraw: str = ""         # /dev/hidrawN
    leds: dict = field(default_factory=dict)   # red/green/blue/global -> sysfs dir
    battery: str = ""        # sysfs power_supply dir
    model: str = "ds4"       # "ds4" or "dualsense"
    edge: bool = False       # a DualSense Edge (Fn buttons and back paddles)
    players: list = field(default_factory=list)   # DualSense player light LED dirs, left to right


def _read(path, default=""):
    try:
        with open(path, errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def discover(sysroot="/sys", devroot="/dev"):
    """Every connected DualShock 4."""
    pads = []
    for hid in sorted(glob.glob(os.path.join(sysroot, "bus", "hid", "devices", "*"))):
        m = re.match(r"^([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})\.", os.path.basename(hid))
        if not m:
            continue
        bus, vendor, product = (int(x, 16) for x in m.groups())
        if vendor != SONY or product not in PRODUCTS:
            continue
        driver = os.path.basename(os.path.realpath(os.path.join(hid, "driver")))
        if driver not in DRIVERS:
            continue
        pad = Pad(key="", name=PRODUCTS[product], bus="bluetooth" if bus == BUS_BT else "usb", hid=hid,
                  model="dualsense" if product in DUALSENSE_PRODUCTS else "ds4", edge=product == 0x0DF2)
        for inp in sorted(glob.glob(os.path.join(hid, "input", "input*"))):
            name = _read(os.path.join(inp, "name"))
            pad.key = pad.key or _read(os.path.join(inp, "uniq")).lower()
            events = sorted(glob.glob(os.path.join(inp, "event*")))
            if not events:
                continue
            node = os.path.join(devroot, "input", os.path.basename(events[0]))
            if name.endswith("Motion Sensors"):
                pad.sensors = node
            elif name.endswith("Touchpad"):
                pad.touchpad = node
            else:
                pad.gamepad = node
                js = sorted(glob.glob(os.path.join(inp, "js*")))
                if js:
                    pad.joystick = os.path.join(devroot, "input", os.path.basename(js[0]))
                _leds(pad, glob.glob(os.path.join(sysroot, "class", "leds", os.path.basename(inp) + ":*")))
        _leds(pad, glob.glob(os.path.join(hid, "leds", "*")))    # (also reachable from the HID device)
        raw = sorted(glob.glob(os.path.join(hid, "hidraw", "hidraw*")))
        if raw:
            pad.hidraw = os.path.join(devroot, os.path.basename(raw[0]))
        bat = sorted(glob.glob(os.path.join(hid, "power_supply", "*")))
        if bat:
            pad.battery = bat[0]
        pad.key = pad.key or os.path.basename(hid)
        if pad.gamepad:
            pads.append(pad)
    return pads


def _leds(pad, dirs):
    players = {}
    for led in dirs:
        parts = os.path.basename(led).split(":")
        if len(parts) == 2 and parts[1] in ("red", "green", "blue", "global"):
            pad.leds.setdefault(parts[1], led)
        elif len(parts) == 3 and parts[1:] == ["rgb", "indicator"]:
            pad.leds.setdefault("rgb", led)
        elif len(parts) == 3 and re.fullmatch(r"player-[1-5]", parts[2]):
            players[int(parts[2][-1])] = led
    if players and not pad.players:
        pad.players = [players[i] for i in sorted(players)]


def battery(pad):
    """(percent, status) or (None, "")."""
    if not pad.battery:
        return None, ""
    cap = _read(os.path.join(pad.battery, "capacity"))
    return (int(cap) if cap.isdigit() else None), _read(os.path.join(pad.battery, "status"))


# ---------------------------------------------------------------- light bar
def _led_files(pad):
    if "rgb" in pad.leds:
        return [os.path.join(pad.leds["rgb"], f) for f in ("multi_intensity", "brightness")]
    return [os.path.join(d, "brightness") for k, d in pad.leds.items() if k in ("red", "green", "blue", "global")]


def lightbar_writable(pad):
    files = _led_files(pad)
    return bool(files) and all(os.access(f, os.W_OK) for f in files)


def set_lightbar(pad, color, brightness=100):
    """Color "#rrggbb" at brightness 0..100 (0 turns it off), through the kernel's LEDs, so
    the driver keeps it (rumble doesn't reset it). Returns False when the LEDs can't be written."""
    if not lightbar_writable(pad):
        return False
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    scale = max(0, min(100, brightness)) / 100
    if "rgb" in pad.leds:     # DualSense: one multicolor LED (color, then overall brightness)
        try:
            with open(os.path.join(pad.leds["rgb"], "multi_intensity"), "w") as f:
                f.write(f"{r} {g} {b}")
            with open(os.path.join(pad.leds["rgb"], "brightness"), "w") as f:
                f.write(str(round(255 * scale) if (r or g or b) else 0))
        except OSError:
            return False
        return True
    try:
        for name, value in (("red", r), ("green", g), ("blue", b)):
            with open(os.path.join(pad.leds[name], "brightness"), "w") as f:
                f.write(str(round(value * scale)))
        if "global" in pad.leds:
            with open(os.path.join(pad.leds["global"], "brightness"), "w") as f:
                f.write("1" if brightness > 0 and (r or g or b) else "0")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- player lights (DualSense)
# the patterns the PlayStation uses for players 1..4 (5 LEDs, left to right)
PLAYER_PATTERNS = {1: (0, 0, 1, 0, 0), 2: (0, 1, 0, 1, 0), 3: (1, 0, 1, 0, 1), 4: (1, 1, 0, 1, 1)}


def set_player_lights(pad, player):
    """Player number 1..4, or 0 for off. False when they can't be written (or there are none)."""
    if len(pad.players) != 5:
        return False
    pattern = PLAYER_PATTERNS.get(player, (0, 0, 0, 0, 0))
    try:
        for led, on in zip(pad.players, pattern):
            with open(os.path.join(led, "brightness"), "w") as f:
                f.write("1" if on else "0")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- adaptive triggers (DualSense)
# Trigger effects as the PS5 sets them; 10 zones along the trigger's travel (0 = at rest),
# strength and amplitude 1..8. Formats as documented by Nielk1 (used by Steam and DSX).
TRIGGER_MODES = ["off", "resistance", "weapon", "vibration"]
TRIGGER_DEFAULT = {"mode": "off", "start": 3, "end": 6, "strength": 5, "frequency": 30}
DS_USB_REPORT_ID, DS_USB_REPORT_SIZE = 0x02, 63
DS_BT_REPORT_ID, DS_BT_REPORT_SIZE, DS_BT_TAG = 0x31, 78, 0x10
FLAG0_RIGHT_TRIGGER, FLAG0_LEFT_TRIGGER = 0x04, 0x08
RIGHT_TRIGGER_AT, LEFT_TRIGGER_AT = 10, 21        # in the report's common part


def normalize_trigger(t):
    out = dict(TRIGGER_DEFAULT)
    if isinstance(t, dict):
        out.update({k: v for k, v in t.items() if k in TRIGGER_DEFAULT})
    if out["mode"] not in TRIGGER_MODES:
        out["mode"] = "off"
    for k, lo, hi in (("start", 0, 9), ("end", 1, 9), ("strength", 1, 8), ("frequency", 1, 255)):
        try:
            out[k] = max(lo, min(hi, int(out[k])))
        except (TypeError, ValueError):
            out[k] = TRIGGER_DEFAULT[k]
    return out


def trigger_effect(t):
    """The 11 bytes of one trigger's effect."""
    t = normalize_trigger(t)
    e = bytearray(11)
    mode, strength = t["mode"], t["strength"] - 1
    if mode in ("resistance", "vibration"):
        zones, force = 0, 0
        for i in range(t["start"], 10):
            zones |= 1 << i
            force |= strength << (3 * i)
        e[0] = 0x21 if mode == "resistance" else 0x26
        e[1:3] = zones.to_bytes(2, "little")
        e[3:7] = force.to_bytes(4, "little")
        if mode == "vibration":
            e[9] = t["frequency"]
    elif mode == "weapon":
        start = max(2, min(7, t["start"]))
        end = max(start + 1, min(8, t["end"]))
        e[0] = 0x25
        e[1:3] = ((1 << start) | (1 << end)).to_bytes(2, "little")
        e[3] = strength
    else:
        e[0] = 0x05
    return bytes(e)


def ds_trigger_report(bus, left, right, seq=0):
    """A DualSense output report setting both triggers' effects and nothing else (the driver's
    own reports leave them alone, so they stay)."""
    common = bytearray(47)
    common[0] = FLAG0_RIGHT_TRIGGER | FLAG0_LEFT_TRIGGER
    common[RIGHT_TRIGGER_AT:RIGHT_TRIGGER_AT + 11] = trigger_effect(right)
    common[LEFT_TRIGGER_AT:LEFT_TRIGGER_AT + 11] = trigger_effect(left)
    if bus != "bluetooth":
        data = bytearray(DS_USB_REPORT_SIZE)
        data[0] = DS_USB_REPORT_ID
        data[1:48] = common
        return bytes(data)
    data = bytearray(DS_BT_REPORT_SIZE)
    data[0], data[1], data[2] = DS_BT_REPORT_ID, (seq & 0x0F) << 4, DS_BT_TAG
    data[3:50] = common
    crc = zlib.crc32(bytes([CRC_SEED]) + bytes(data[:DS_BT_REPORT_SIZE - 4])) & 0xFFFFFFFF
    data[DS_BT_REPORT_SIZE - 4:] = struct.pack("<I", crc)
    return bytes(data)


def set_triggers(pad, left, right, fd=None, seq=0):
    """Adaptive trigger effects on a DualSense, through its hidraw node (or an open `fd`)."""
    if pad.model != "dualsense" or not (pad.hidraw or fd is not None):
        return False
    own = fd is None
    if own:
        try:
            fd = os.open(pad.hidraw, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            return False
    try:
        os.write(fd, ds_trigger_report(pad.bus, left, right, seq))
        return True
    except OSError:
        return False
    finally:
        if own:
            os.close(fd)


# ---------------------------------------------------------------- report rate (Bluetooth)
def bt_report(poll_ms=None, lightbar=None):
    """A Bluetooth output report: sets the report interval (1..62 ms) and nothing else unless
    `lightbar` (r, g, b) is given."""
    data = bytearray(BT_REPORT_SIZE)
    data[0] = BT_REPORT_ID
    data[1] = HWCTL_HID | HWCTL_CRC32 | (max(1, min(62, int(poll_ms))) & POLL_MASK if poll_ms else 0)
    if lightbar is not None:
        data[3] = FLAG_LED
        data[8:11] = bytes(lightbar)
    crc = zlib.crc32(bytes([CRC_SEED]) + bytes(data[:BT_REPORT_SIZE - 4])) & 0xFFFFFFFF
    data[BT_REPORT_SIZE - 4:] = struct.pack("<I", crc)
    return bytes(data)


def set_bt_poll(pad, ms, fd=None):
    """Ask a Bluetooth DualShock 4 to report every `ms` milliseconds (1 = 1000 Hz). The hidraw
    node needs to be writable (steam-devices or XControl's udev rules give it to you), or pass
    an already open `fd` of it."""
    if pad.model != "ds4" or pad.bus != "bluetooth" or not (pad.hidraw or fd is not None):
        return False
    ms = int(ms) or BT_DRIVER_POLL_MS     # 0: back to the driver's own rate
    own = fd is None
    if own:
        try:
            fd = os.open(pad.hidraw, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            return False
    try:
        os.write(fd, bt_report(ms))
        return True
    except OSError:
        return False
    finally:
        if own:
            os.close(fd)


def hidraw_writable(pad):
    return bool(pad.hidraw) and os.access(pad.hidraw, os.W_OK)


# ---------------------------------------------------------------- USB polling (usbhid jspoll)
def usb_jspoll(sysroot="/sys"):
    """usbhid's joystick polling override in ms (0 = the device's own interval), or None."""
    v = _read(os.path.join(sysroot, "module", "usbhid", "parameters", "jspoll"))
    return int(v) if v.isdigit() else None


def can_set_usb_poll():
    return bool(shutil.which("pkexec")) and os.path.exists(HELPER)


def set_usb_poll(ms):
    """(ok, message): usbhid's joystick polling through the root helper (asks for the password)."""
    try:
        r = subprocess.run(["pkexec", HELPER, "usbpoll", str(int(ms))], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if r.returncode in (126, 127) and not r.stderr.strip():
        return False, ""
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-400:]


# ---------------------------------------------------------------- hiding it from games
def hide_nodes(pad):
    """The device files games could find the DualShock 4 through."""
    return [n for n in (pad.gamepad, pad.joystick, pad.sensors, pad.touchpad, pad.hidraw) if n]


def set_hidden(nodes, hidden):
    """(ok, message): take away (or give back) the user's access to these device files, through
    the root helper (no password for the active session). Open files stay usable."""
    nodes = [n for n in nodes if os.path.exists(n)]
    if not nodes:
        return True, ""
    if not shutil.which("pkexec") or not os.path.exists(HIDE_HELPER):
        return False, "xcontrol-controller-hide isn't installed"
    try:
        r = subprocess.run(["pkexec", HIDE_HELPER, "hide" if hidden else "show", *nodes],
                           capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if r.returncode == 0:
        return True, ""
    return False, (r.stderr or r.stdout).strip()[-300:] or f"pkexec exit {r.returncode}"
