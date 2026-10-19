#!/usr/bin/env python3
"""A stand-in for `xinput` with a gaming mouse, a touchpad and a keyboard, printing
exactly what xinput 1.6 prints. State lives in $FAKE_XINPUT_STATE (JSON); every
set-prop is logged there. `test-xi2 --root` prints one "device added" event.
Install as `xinput` in a directory put first on PATH.
"""
import json
import os
import sys
import time

MOUSE = "Logitech G Pro Gaming Mouse"
PAD = "SynPS/2 Synaptics TouchPad"

COMMON = [
    ("Device Enabled", 155, "int", ["1"]),
    ("Coordinate Transformation Matrix", 157, "float",
     ["1.000000", "0.000000", "0.000000", "0.000000", "1.000000", "0.000000", "0.000000", "0.000000", "1.000000"]),
]
MOUSE_PROPS = COMMON + [
    ("libinput Natural Scrolling Enabled", 290, "int", ["0"]),
    ("libinput Natural Scrolling Enabled Default", 291, "int", ["0"]),
    ("libinput Scroll Methods Available", 292, "int", ["0", "0", "1"]),
    ("libinput Scroll Method Enabled", 293, "int", ["0", "0", "0"]),
    ("libinput Scroll Method Enabled Default", 294, "int", ["0", "0", "0"]),
    ("libinput Middle Emulation Enabled", 299, "int", ["0"]),
    ("libinput Middle Emulation Enabled Default", 300, "int", ["0"]),
    ("libinput Accel Speed", 303, "float", ["0.000000"]),
    ("libinput Accel Speed Default", 304, "float", ["0.000000"]),
    ("libinput Accel Profiles Available", 305, "int", ["1", "1", "1"]),
    ("libinput Accel Profile Enabled", 306, "int", ["1", "0", "0"]),
    ("libinput Accel Profile Enabled Default", 307, "int", ["1", "0", "0"]),
    ("libinput Accel Custom Fallback Points", 308, "float", []),
    ("libinput Left Handed Enabled", 316, "int", ["0"]),
    ("libinput Left Handed Enabled Default", 317, "int", ["0"]),
    ("Device Node", 321, "str", ['"/dev/input/event5"']),
    ("Device Product ID", 322, "int", ["1133", "49291"]),
    ("libinput Horizontal Scroll Enabled", 324, "int", ["1"]),
    ("libinput Scrolling Factor", 325, "float", ["1.000000"]),
    ("libinput Scrolling Factor Default", 326, "float", ["1.000000"]),
    ("libinput High Resolution Wheel Scroll Enabled", 327, "int", ["1"]),
]
PAD_PROPS = COMMON + [
    ("libinput Tapping Enabled", 280, "int", ["0"]),
    ("libinput Tapping Enabled Default", 281, "int", ["0"]),
    ("libinput Tapping Drag Enabled", 282, "int", ["1"]),
    ("libinput Tapping Drag Enabled Default", 283, "int", ["1"]),
    ("libinput Tapping Drag Lock Enabled", 284, "int", ["0"]),
    ("libinput Tapping Drag Lock Enabled Default", 285, "int", ["0"]),
    ("libinput Natural Scrolling Enabled", 290, "int", ["0"]),
    ("libinput Natural Scrolling Enabled Default", 291, "int", ["0"]),
    ("libinput Disable While Typing Enabled", 296, "int", ["1"]),
    ("libinput Disable While Typing Enabled Default", 297, "int", ["1"]),
    ("libinput Scroll Methods Available", 292, "int", ["1", "1", "0"]),
    ("libinput Scroll Method Enabled", 293, "int", ["1", "0", "0"]),
    ("libinput Scroll Method Enabled Default", 294, "int", ["1", "0", "0"]),
    ("libinput Click Methods Available", 309, "int", ["1", "1"]),
    ("libinput Click Method Enabled", 310, "int", ["1", "0"]),
    ("libinput Click Method Enabled Default", 311, "int", ["1", "0"]),
    ("libinput Middle Emulation Enabled", 299, "int", ["0"]),
    ("libinput Middle Emulation Enabled Default", 300, "int", ["0"]),
    ("libinput Accel Speed", 303, "float", ["0.000000"]),
    ("libinput Accel Speed Default", 304, "float", ["0.000000"]),
    ("libinput Accel Profiles Available", 305, "int", ["1", "1"]),
    ("libinput Accel Profile Enabled", 306, "int", ["1", "0"]),
    ("libinput Accel Profile Enabled Default", 307, "int", ["1", "0"]),
    ("libinput Left Handed Enabled", 316, "int", ["0"]),
    ("libinput Left Handed Enabled Default", 317, "int", ["0"]),
    ("libinput Horizontal Scroll Enabled", 324, "int", ["1"]),
]
KBD_PROPS = COMMON[:1] + [("libinput Send Events Modes Available", 270, "int", ["1", "0"])]

# id, name, role, props   (role as printed by xinput list)
DEVICES = [
    (2, "Virtual core pointer", "master pointer  (3)", []),
    (4, "Virtual core XTEST pointer", "slave  pointer  (2)", COMMON),
    (9, MOUSE, "slave  pointer  (2)", MOUSE_PROPS),
    (13, PAD, "slave  pointer  (2)", PAD_PROPS),
    (3, "Virtual core keyboard", "master keyboard (2)", []),
    (5, "Virtual core XTEST keyboard", "slave  keyboard (3)", COMMON[:1]),
    (10, MOUSE, "slave  keyboard (3)", KBD_PROPS),
    (14, "AT Translated Set 2 keyboard", "slave  keyboard (3)", KBD_PROPS),
]


def load():
    path = os.environ["FAKE_XINPUT_STATE"]
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        state = {"props": {str(i): {n: v for n, _num, _t, v in props} for i, _n, _r, props in DEVICES}, "log": []}
        save(state)
        return state


def save(state):
    with open(os.environ["FAKE_XINPUT_STATE"], "w") as f:
        json.dump(state, f)


def find(arg):
    for d in DEVICES:
        if str(d[0]) == arg or d[1] == arg:
            return d
    sys.exit(f"unable to find device '{arg}'")


def main(argv):
    state = load()
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        for kind in ("pointer", "keyboard"):
            devs = [d for d in DEVICES if kind in d[2]]
            master = devs[0]
            print(("⎡ " if kind == "pointer" else "⎣ ") + f"{master[1]:<40}\tid={master[0]}\t[{master[2]}]")
            for d in devs[1:]:
                lead = "⎜   ↳ " if kind == "pointer" else "    ↳ "
                print(f"{lead}{d[1]:<36}\tid={d[0]}\t[{d[2]}]")
    elif cmd == "list-props":
        d = find(argv[1])
        print(f"Device '{d[1]}':")
        for name, num, _t, _v in d[3]:
            vals = state["props"][str(d[0])][name]
            print(f"\t{name} ({num}):\t" + (", ".join(vals) if vals else "<no items>"))
    elif cmd == "set-prop":
        d = find(argv[1])
        name, vals = argv[2], argv[3:]
        meta = {n: (t, v) for n, _num, t, v in d[3]}
        if name not in meta:
            sys.exit(f"property '{name}' doesn't exist, you need to specify its type and format")
        kind, old = meta[name]
        if len(vals) != len(state["props"][str(d[0])][name]):
            sys.exit(f"unexpected size for property '{name}'")
        if kind == "float":
            vals = [f"{float(v):.6f}" for v in vals]
        state["props"][str(d[0])][name] = vals
        state["log"].append([d[0], name, vals])
        save(state)
    elif cmd == "test-xi2":
        print("EVENT type 11 (HierarchyChanged)")
        print("    time: 1234")
        print("    Changes happened:   [new slave]     [device enabled] ")
        print("    device 15 [slave pointer (2)] is enabled")
        sys.stdout.flush()
        time.sleep(30)
    else:
        sys.exit(f"fake xinput: unsupported {argv}")


if __name__ == "__main__":
    main(sys.argv[1:])
