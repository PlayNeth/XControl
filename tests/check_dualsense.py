"""DualSense: finding it (fake sysfs), its light bar and player lights, adaptive trigger reports,
and the service setting them (and putting them back when it closes)."""
import os
import struct
import sys
import tempfile
import zlib

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
from xcontrol import pad_service as S, padmap as M, pads as P  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


tmp = tempfile.mkdtemp()
sysroot, devroot = os.path.join(tmp, "sys"), os.path.join(tmp, "dev")
hid = os.path.join(sysroot, "bus", "hid", "devices", "0005:054C:0DF2.0007")
os.makedirs(os.path.join(sysroot, "bus", "hid", "drivers", "playstation"))
os.makedirs(hid)
os.symlink(os.path.join(sysroot, "bus", "hid", "drivers", "playstation"), os.path.join(hid, "driver"))
for n, (name, ev) in enumerate((("DualSense Edge Wireless Controller", 30),
                                ("DualSense Edge Wireless Controller Motion Sensors", 31),
                                ("DualSense Edge Wireless Controller Touchpad", 32)), 40):
    put(os.path.join(hid, "input", f"input{n}", "name"), name + "\n")
    put(os.path.join(hid, "input", f"input{n}", "uniq"), "e8:47:3a:00:11:22\n")
    os.makedirs(os.path.join(hid, "input", f"input{n}", f"event{ev}"))
put(os.path.join(sysroot, "class", "leds", "input40:rgb:indicator", "multi_intensity"), "0 0 255")
put(os.path.join(sysroot, "class", "leds", "input40:rgb:indicator", "brightness"), "255")
for i in (3, 1, 5, 2, 4):
    put(os.path.join(sysroot, "class", "leds", f"input40:white:player-{i}", "brightness"), "0")
os.makedirs(os.path.join(hid, "hidraw", "hidraw6"))

pads = P.discover(sysroot, devroot)
expect("found", [(p.name, p.model, p.edge, p.bus) for p in pads], [("DualSense Edge", "dualsense", True, "bluetooth")])
pad = pads[0]
expect("player lights in order", [os.path.basename(x)[-1] for x in pad.players], ["1", "2", "3", "4", "5"])
expect("light bar", (P.set_lightbar(pad, "#ff8000", 50),
                     read(os.path.join(pad.leds["rgb"], "multi_intensity")),
                     read(os.path.join(pad.leds["rgb"], "brightness"))), (True, "255 128 0", "128"))
expect("player 2", (P.set_player_lights(pad, 2), [read(os.path.join(x, "brightness")) for x in pad.players]),
       (True, ["0", "1", "0", "1", "0"]))
P.set_player_lights(pad, 0)
expect("player lights off", [read(os.path.join(x, "brightness")) for x in pad.players], ["0"] * 5)
expect("no Bluetooth rate for the DualSense", P.set_bt_poll(pad, 1), False)

# trigger effects (Nielk1's formats)
expect("off", P.trigger_effect({"mode": "off"}), bytes([0x05]) + bytes(10))
e = P.trigger_effect({"mode": "resistance", "start": 7, "strength": 8})
expect("resistance zones 7-9", (e[0], int.from_bytes(e[1:3], "little")), (0x21, 0b1110000000))
expect("resistance force 7 in zones 7-9", int.from_bytes(e[3:7], "little"), (7 << 21) | (7 << 24) | (7 << 27))
e = P.trigger_effect({"mode": "weapon", "start": 3, "end": 6, "strength": 5})
expect("weapon", (e[0], int.from_bytes(e[1:3], "little"), e[3]), (0x25, (1 << 3) | (1 << 6), 4))
e = P.trigger_effect({"mode": "weapon", "start": 0, "end": 9, "strength": 5})
expect("weapon kept in its range (2-7, to 8)", int.from_bytes(e[1:3], "little"), (1 << 2) | (1 << 8))
e = P.trigger_effect({"mode": "vibration", "start": 0, "strength": 2, "frequency": 40})
expect("vibration", (e[0], int.from_bytes(e[1:3], "little"), e[3] & 7, e[9]), (0x26, 0x3FF, 1, 40))

left, right = {"mode": "resistance", "start": 2, "strength": 4}, {"mode": "weapon", "start": 3, "end": 6}
usb = P.ds_trigger_report("usb", left, right)
expect("usb report", (len(usb), usb[0], usb[1], usb[2]), (63, 0x02, 0x0C, 0))
expect("usb: right then left", (usb[1 + 10:1 + 21], usb[1 + 21:1 + 32]), (P.trigger_effect(right),
                                                                          P.trigger_effect(left)))
bt = P.ds_trigger_report("bluetooth", left, right, seq=5)
expect("bt report", (len(bt), bt[0], bt[1], bt[2], bt[3]), (78, 0x31, 0x50, 0x10, 0x0C))
expect("bt crc", struct.unpack("<I", bt[-4:])[0], zlib.crc32(b"\xa2" + bt[:74]) & 0xFFFFFFFF)
expect("bt: right trigger", bt[3 + 10:3 + 21], P.trigger_effect(right))

# the service: triggers and player lights applied; triggers back to normal when it closes
raw = os.path.join(tmp, "hidraw6")
put(raw)
pad.hidraw = raw
written = []
real_write = os.write


def spy(fd, data):
    if len(data) == 78 and data[0] == 0x31:
        written.append(bytes(data))
    return real_write(fd, data)


os.write = spy
try:
    st = S.normalize({"enabled": True, "emulate": "off", "triggers": {"l2": left, "r2": right},
                      "player_lights": "auto"})
    c = S.Controller(pad, st, lambda m: None, player=3)
    expect("triggers set", (len(written), written[0][3 + 10:3 + 21] if written else b""), (1, P.trigger_effect(right)))
    expect("player 3", [read(os.path.join(x, "brightness")) for x in pad.players], ["1", "0", "1", "0", "1"])
    c.apply(S.normalize(dict(st, player_lights="off", triggers={"l2": left, "r2": {"mode": "off"}})))
    expect("changed in place", (written[-1][3 + 10], [read(os.path.join(x, "brightness")) for x in pad.players]),
           (0x05, ["0"] * 5))
    expect("sequence counts up", [w[1] >> 4 for w in written], [0, 1])
    c.close()
    expect("back to normal on close", (written[-1][3 + 10], written[-1][3 + 21]), (0x05, 0x05))
finally:
    os.write = real_write

# the Edge's extra buttons can be mapped (none by default)
m = M.Mapper({"paddle_left": "a"})
m.feed(M.EV_KEY, M.BTN_SOUTH, 0)
expect("left paddle as A", m.feed(M.EV_KEY, M.BTN_TRIGGER_HAPPY1 + 2, 1), [(M.EV_KEY, M.BTN_SOUTH, 1)])
m = M.Mapper()
m.feed(M.EV_KEY, M.BTN_SOUTH, 0)
expect("Fn unmapped by default", m.feed(M.EV_KEY, M.BTN_TRIGGER_HAPPY1, 1), [])
expect("settings: bad trigger mode", S.normalize({"triggers": {"l2": {"mode": "laser"}}})["triggers"]["l2"]["mode"],
       "off")

print("check_dualsense:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
