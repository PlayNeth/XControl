"""Keeping the screen on: the manual switch, and gamepad input (fake devices: FIFOs with a
made-up sysfs entry, since tests can't create real input devices)."""
import os
import struct
import sys
import tempfile
import time

tmp = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import awake  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def runtime(name):
    return os.path.join(tmp, "rt-" + name)


# by hand
expect("off at first", awake.manual_until(runtime), None)
expect("on", awake.set_manual(runtime, "on"), 0)
expect("still on", awake.manual_until(runtime), 0)
expect("toggle off", awake.set_manual(runtime, "toggle"), None)
until = awake.set_manual(runtime, "30")
expect("30 minutes", round((until - time.time()) / 60), 30)
with open(runtime("awake"), "w") as f:
    f.write('{"until": %f}' % (time.time() - 1))
expect("expired", awake.manual_until(runtime), None)
expect("expired file removed", os.path.exists(runtime("awake")), False)

# gamepads
dev, sysroot = os.path.join(tmp, "dev"), os.path.join(tmp, "sys")
os.makedirs(dev)


def fake(name, label, keys):
    os.mkfifo(os.path.join(dev, name))
    d = os.path.join(sysroot, name, "device")
    os.makedirs(os.path.join(d, "capabilities"))
    with open(os.path.join(d, "name"), "w") as f:
        f.write(label + "\n")
    with open(os.path.join(d, "capabilities", "key"), "w") as f:
        f.write(keys + "\n")


# BTN_GAMEPAD (0x130) is bit 48 of the second 64-bit word; a keyboard has only low keys
fake("event5", "Xbox Wireless Controller", "7fdb000000000000 0 0 0 0")
fake("event2", "AT Translated Set 2 keyboard", "0 0 0 0 0 fffffffffffffffe")
g = awake.Gamepads(devdir=dev, sysroot=sysroot)
writer = None


def opener():
    global writer
    writer = os.open(os.path.join(dev, "event5"), os.O_WRONLY)


import threading  # noqa: E402
t = threading.Thread(target=opener)
t.start()
g.rescan(force=True)
t.join(2)
expect("found the gamepad only", g.names(), ["Xbox Wireless Controller"])
fd = g.fds()[0]
details = g.details()
expect("details", [(d["name"], d["virtual"]) for d in details], [("Xbox Wireless Controller", False)])
expect("details reused while the devices stay", g.details() is details, True)


def send(*events):
    os.write(writer, b"".join(struct.pack("llHHi", 0, 0, *e) for e in events))
    time.sleep(0.05)
    return g.read(fd)


expect("stick drift ignored", send((3, 0, 300), (0, 0, 0)), False)
expect("small wiggle ignored", send((3, 0, 2500), (0, 0, 0)), False)
expect("real stick movement", send((3, 0, 20000), (0, 0, 0)), True)
expect("button press", send((1, 0x130, 1), (0, 0, 0)), True)
expect("button release alone", send((1, 0x130, 0), (0, 0, 0)), False)
expect("d-pad", send((3, 16, -1), (0, 0, 0)), True)
expect("last input time", time.time() - g.last < 2, True)
os.close(writer)
g.read(fd)   # end of file: unplugged
expect("unplugged", g.names(), [])
g.close()

# virtual pads (made through /dev/uinput) and who could have made them
proc = os.path.join(tmp, "proc")
for pid, args, target in (("101", b"python3\0/usr/bin/scc-daemon\0start", "/dev/uinput"),
                          ("102", b"/usr/bin/foo\0", "/dev/null")):
    os.makedirs(os.path.join(proc, pid, "fd"))
    os.symlink(target, os.path.join(proc, pid, "fd", "3"))
    with open(os.path.join(proc, pid, "cmdline"), "wb") as f:
        f.write(args)
expect("uinput users", awake.uinput_users(proc), ["scc-daemon"])
vsys = os.path.join(tmp, "vsys")
os.makedirs(os.path.join(tmp, "devices", "virtual", "input", "input9", "event9"))
os.makedirs(vsys)
os.symlink(os.path.join(tmp, "devices", "virtual", "input", "input9", "event9"), os.path.join(vsys, "event9"))
expect("virtual", awake.is_virtual("/dev/input/event9", vsys), True)
expect("not virtual", awake.is_virtual("/dev/input/event5", sysroot), False)

print("check_awake:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
