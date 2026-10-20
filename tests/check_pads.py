"""DualShock 4: finding it (fake sysfs), light bar, Bluetooth report, the USB polling helper,
the button mapper, and the service's rumble and report-rate handling (fake devices: pipes)."""
import fcntl
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
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


# ---- a Bluetooth DualShock 4 v2 in a fake /sys
tmp = tempfile.mkdtemp()
os.chmod(tmp, 0o777)
sysroot, devroot = os.path.join(tmp, "sys"), os.path.join(tmp, "dev")
hid = os.path.join(sysroot, "bus", "hid", "devices", "0005:054C:09CC.0003")
os.makedirs(os.path.join(sysroot, "bus", "hid", "drivers", "playstation"))
os.makedirs(hid)
os.symlink(os.path.join(sysroot, "bus", "hid", "drivers", "playstation"), os.path.join(hid, "driver"))
for n, (name, ev) in enumerate((("Wireless Controller", 21), ("Wireless Controller Motion Sensors", 22),
                                ("Wireless Controller Touchpad", 23)), 20):
    put(os.path.join(hid, "input", f"input{n}", "name"), name + "\n")
    put(os.path.join(hid, "input", f"input{n}", "uniq"), "A4:AE:12:34:56:78\n")
    os.makedirs(os.path.join(hid, "input", f"input{n}", f"event{ev}"))
for color in ("red", "green", "blue", "global"):
    put(os.path.join(sysroot, "class", "leds", f"input20:{color}", "brightness"), "0")
os.makedirs(os.path.join(hid, "hidraw", "hidraw4"))
put(os.path.join(hid, "power_supply", "ps-controller-battery-a4:ae:12:34:56:78", "capacity"), "70\n")
put(os.path.join(hid, "power_supply", "ps-controller-battery-a4:ae:12:34:56:78", "status"), "Discharging\n")
# something else Sony makes, and a DS4 another driver holds: ignored
os.makedirs(os.path.join(sysroot, "bus", "hid", "devices", "0003:054C:0CE6.0009"))

pads = P.discover(sysroot, devroot)
expect("one pad", len(pads), 1)
pad = pads[0]
expect("found", (pad.key, pad.name, pad.bus, os.path.basename(pad.gamepad), os.path.basename(pad.sensors),
                 os.path.basename(pad.touchpad), os.path.basename(pad.hidraw)),
       ("a4:ae:12:34:56:78", "DualShock 4 (v2)", "bluetooth", "event21", "event22", "event23", "hidraw4"))
expect("battery", P.battery(pad), (70, "Discharging"))
expect("light bar", P.set_lightbar(pad, "#ff8000", 50), True)
expect("light bar values", [open(os.path.join(pad.leds[c], "brightness")).read() for c in ("red", "green", "blue",
                                                                                           "global")],
       ["128", "64", "0", "1"])
P.set_lightbar(pad, "#ff8000", 0)
expect("light bar off", open(os.path.join(pad.leds["global"], "brightness")).read(), "0")

r = P.bt_report(1)
expect("bt report", (len(r), r[0], r[1], r[3]), (78, 0x11, 0xC1, 0))
expect("bt crc", struct.unpack("<I", r[-4:])[0], zlib.crc32(b"\xa2" + r[:74]) & 0xFFFFFFFF)
expect("bt report clamps", (P.bt_report(100)[1] & 0x3F, P.bt_report(None)[1]), (62, 0xC0))
raw = os.path.join(tmp, "hidraw4")
put(raw)
pad.hidraw = raw
expect("bt poll written", (P.set_bt_poll(pad, 2), open(raw, "rb").read()[:2]), (True, b"\x11\xc2"))

# ---- the USB polling helper, unprivileged so its test hooks apply
prefix = []
if os.geteuid() == 0:
    prefix = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"] if shutil.which("setpriv") else None
if prefix is not None:
    helper = os.path.join(here, "..", "data", "xcontrol-controller-helper")
    hs, etc = os.path.join(tmp, "hsys"), os.path.join(tmp, "etc")
    put(os.path.join(hs, "module", "usbhid", "parameters", "jspoll"), "0")
    drv = os.path.join(hs, "bus", "usb", "drivers", "usbhid")
    dev = os.path.join(hs, "devices", "usb1", "1-2")
    put(os.path.join(dev, "idVendor"), "054c\n")
    put(os.path.join(dev, "idProduct"), "09cc\n")
    os.makedirs(os.path.join(dev, "1-2:1.3"))
    os.makedirs(drv)
    os.symlink(os.path.join(dev, "1-2:1.3"), os.path.join(drv, "1-2:1.3"))
    put(os.path.join(drv, "unbind"))
    put(os.path.join(drv, "bind"))
    for root, dirs, files in os.walk(tmp):
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o777)
        for f in files:
            os.chmod(os.path.join(root, f), 0o666)
    env = dict(os.environ, XCONTROL_SYSROOT=hs, XCONTROL_ETC=etc)

    def run(*args):
        return subprocess.run(prefix + ["sh", helper, *args], capture_output=True, text=True, env=env)

    res = run("usbpoll", "1")
    expect("usbpoll ok", (res.returncode, res.stderr), (0, ""))
    expect("live", open(os.path.join(hs, "module", "usbhid", "parameters", "jspoll")).read().strip(), "1")
    kept = (os.path.exists(os.path.join(etc, "tmpfiles.d", "xcontrol-usbhid.conf")),
            os.path.exists(os.path.join(etc, "modprobe.d", "xcontrol-usbhid.conf")))
    expect("kept for next boots (built-in usbhid)", kept, (True, False))
    expect("reconnected", (open(os.path.join(drv, "unbind")).read().strip(), "reconnected 1-2:1.3" in res.stdout),
           ("1-2:1.3", True))
    put(os.path.join(hs, "module", "usbhid", "initstate"), "live")
    os.chmod(os.path.join(hs, "module", "usbhid", "initstate"), 0o666)
    run("usbpoll", "2")
    with open(os.path.join(etc, "modprobe.d", "xcontrol-usbhid.conf")) as f:
        expect("module: modprobe.d too", f.read().splitlines()[-1], "options usbhid jspoll=2")
    run("usbpoll", "0")
    expect("0 removes them", os.path.exists(os.path.join(etc, "tmpfiles.d", "xcontrol-usbhid.conf")), False)
    for args in (("usbpoll", "99"), ("usbpoll", "1;reboot"), ("rm", "x"), ("usbpoll",)):
        expect(f"refused {args}", run(*args).returncode != 0, True)

# ---- the mapper
m = M.Mapper()
m.feed(M.EV_KEY, M.BTN_SOUTH, 0)
expect("cross is A", m.feed(M.EV_KEY, M.BTN_SOUTH, 1), [(M.EV_KEY, M.BTN_SOUTH, 1)])
expect("square is X (BTN_X)", m.feed(M.EV_KEY, M.BTN_WEST, 1), [(M.EV_KEY, M.BTN_NORTH, 1)])
expect("triangle is Y (BTN_Y)", m.feed(M.EV_KEY, M.BTN_NORTH, 1), [(M.EV_KEY, M.BTN_WEST, 1)])
expect("sticks", [m.feed(M.EV_ABS, M.ABS_Y, v)[0][2] for v in (0, 128, 255)], [-32768, 0, 32767])
expect("analog L2", m.feed(M.EV_ABS, M.ABS_Z, 90), [(M.EV_ABS, M.ABS_Z, 90)])
expect("digital L2 alone does nothing extra", m.feed(M.EV_KEY, M.BTN_TL2, 1), [])
expect("d-pad", m.feed(M.EV_ABS, M.ABS_HAT0X, 1), [(M.EV_ABS, M.ABS_HAT0X, 1)])
m2 = M.Mapper({"cross": "b", "circle": "a", "l2": "lb", "touchpad": "back", "dpad_up": "rt"})
m2.feed(M.EV_KEY, M.BTN_SOUTH, 0)
expect("swapped", m2.feed(M.EV_KEY, M.BTN_EAST, 1), [(M.EV_KEY, M.BTN_SOUTH, 1)])
expect("L2 as LB, no analog", (m2.feed(M.EV_ABS, M.ABS_Z, 255), m2.feed(M.EV_KEY, M.BTN_TL2, 1)),
       ([], [(M.EV_KEY, M.BTN_TL, 1)]))
expect("touchpad click", m2.feed(M.EV_KEY, M.BTN_LEFT, 1), [(M.EV_KEY, M.BTN_SELECT, 1)])
expect("d-pad up as RT", m2.feed(M.EV_ABS, M.ABS_HAT0Y, -1), [(M.EV_ABS, M.ABS_RZ, 255)])
expect("bad map entries ignored", M.normalize_map({"cross": "warp", "nope": "a"})["cross"], "a")
expect("settings normalized",
       (S.normalize({"emulate": "xyz"})["emulate"], S.normalize({"bt_poll_ms": 99})["bt_poll_ms"],
        S.normalize({"lightbar": "red"})["lightbar"]), ("xbox360", 16, "#0044ff"))

# ---- rumble: what a game uploads to the virtual pad reaches the real one
calls = []
real_ioctl = fcntl.ioctl


def fake_ioctl(fd, req, arg=0, *rest):
    calls.append(req)
    if req == S.UI_BEGIN_FF_UPLOAD:
        effect = S.FF_EFFECT.pack(S.FF_RUMBLE, 3, 0, 0, 0, 500, 0, struct.pack("HH", 40000, 20000) + bytes(28))
        arg[8:8 + len(effect)] = effect
        return 0
    if req == S.EVIOCSFF:
        struct.pack_into("h", arg, 2, 7)    # the real device's id for it
        uploaded.append(S.FF_EFFECT.unpack_from(arg)[7][:4])
        return 0
    if req == S.UI_BEGIN_FF_ERASE:
        struct.pack_into("I", arg, 8, 3)
        return 0
    return 0


uploaded = []
fcntl.ioctl = fake_ioctl
try:
    rd, wr = os.pipe()

    class FakeVpad:
        fd = 99
    rum = S.Rumble(FakeVpad(), wr)
    rum.handle(S.EV_UINPUT, S.UI_FF_UPLOAD, 1)
    expect("effect uploaded to the real pad", (rum.ids, uploaded), ({3: 7}, [struct.pack("HH", 40000, 20000)]))
    rum.handle(S.EV_FF, 3, 1)
    ev = S.EVENT.unpack(os.read(rd, S.EVENT.size))
    expect("play forwarded with the real id", ev[2:], (S.EV_FF, 7, 1))
    rum.handle(S.EV_UINPUT, S.UI_FF_ERASE, 2)
    expect("erased", (rum.ids, S.EVIOCRMFF in calls, S.UI_END_FF_ERASE in calls), ({}, True, True))
finally:
    fcntl.ioctl = real_ioctl

# ---- a controller in the service: report rate from the motion sensors, input to the virtual pad
sent = []


class StubVpad:
    fd = -5

    def send(self, events):
        sent.extend(events)

    def close(self):
        pass


c = S.Controller.__new__(S.Controller)
c.pad, c.log, c.error = pad, print, ""
c.vpad, c.mapper, c.rumble = StubVpad(), M.Mapper(), None
c.rate_count, c.rate_since, c.rate = 0, time.monotonic() - 1.0, 0
gp_r, gp_w = os.pipe()
se_r, se_w = os.pipe()
c.fds = {gp_r: "gamepad", se_r: "sensors"}
os.write(gp_w, S.EVENT.pack(0, 0, S.EV_KEY, M.BTN_SOUTH, 1) + S.EVENT.pack(0, 0, S.EV_SYN, 0, 0))
c.read(gp_r)
expect("button reaches the virtual pad", (S.EV_KEY, M.BTN_SOUTH, 1) in sent, True)
os.write(se_w, S.EVENT.pack(0, 0, S.EV_SYN, 0, 0) * 50)
c.rate_since = time.monotonic() - 1.0
c.read(se_r)
expect("report rate counted", c.rate > 0, True)
os.close(gp_w)
expect("unplugged ends it", c.read(gp_r), False)

print("check_pads:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
