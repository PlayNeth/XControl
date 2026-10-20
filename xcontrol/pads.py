"""DualShock 4 controllers: finding them, their light bar, battery and Bluetooth report rate.

The kernel's driver (hid-playstation, or hid-sony on old kernels) gives each controller three
input devices (the gamepad, its motion sensors and its touchpad), four LEDs for the light bar
(inputN:red/green/blue/global), a battery, and a hidraw node for raw reports.
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
        if vendor != SONY or product not in DS4_PRODUCTS:
            continue
        driver = os.path.basename(os.path.realpath(os.path.join(hid, "driver")))
        if driver not in DRIVERS:
            continue
        pad = Pad(key="", name=DS4_PRODUCTS[product], bus="bluetooth" if bus == BUS_BT else "usb", hid=hid)
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
                for led in glob.glob(os.path.join(sysroot, "class", "leds", os.path.basename(inp) + ":*")):
                    color = led.rsplit(":", 1)[-1]
                    if color in ("red", "green", "blue", "global"):
                        pad.leds[color] = led
        for led in glob.glob(os.path.join(hid, "leds", "*")):    # (also reachable from the HID device)
            color = led.rsplit(":", 1)[-1]
            if color in ("red", "green", "blue", "global") and color not in pad.leds:
                pad.leds[color] = led
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


def battery(pad):
    """(percent, status) or (None, "")."""
    if not pad.battery:
        return None, ""
    cap = _read(os.path.join(pad.battery, "capacity"))
    return (int(cap) if cap.isdigit() else None), _read(os.path.join(pad.battery, "status"))


# ---------------------------------------------------------------- light bar
def lightbar_writable(pad):
    return bool(pad.leds) and all(os.access(os.path.join(d, "brightness"), os.W_OK) for d in pad.leds.values())


def set_lightbar(pad, color, brightness=100):
    """Color "#rrggbb" at brightness 0..100 (0 turns it off), through the kernel's LEDs, so
    the driver keeps it (rumble doesn't reset it). Returns False when the LEDs can't be written."""
    if not lightbar_writable(pad):
        return False
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    scale = max(0, min(100, brightness)) / 100
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
    if pad.bus != "bluetooth" or not (pad.hidraw or fd is not None):
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
