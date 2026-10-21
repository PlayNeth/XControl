"""Input settings against a fake `xinput` (tests/fake_xinput.py) and the system's
XKB rule list: reading devices, live changes, saved settings coming back after a
replug, the hotplug watcher, and keyboard command lines."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

tmp = tempfile.mkdtemp()
bindir = os.path.join(tmp, "bin")
os.makedirs(bindir)
shutil.copy(os.path.join(HERE, "fake_xinput.py"), os.path.join(bindir, "xinput"))
os.chmod(os.path.join(bindir, "xinput"), 0o755)
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
os.environ["FAKE_XINPUT_STATE"] = os.path.join(tmp, "xinput.json")
os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
os.environ["XDG_RUNTIME_DIR"] = tmp
os.environ["DISPLAY"] = ":79"  # (no X server there: the watcher falls back to xinput test-xi2)

from xcontrol import input_devices as D, keyboard as K  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def state():
    with open(os.environ["FAKE_XINPUT_STATE"]) as f:
        return json.load(f)


def replug():
    """X forgets the settings when a device is unplugged."""
    os.remove(os.environ["FAKE_XINPUT_STATE"])


# ---- parsing
ptrs = D.pointers()
expect("pointers", [(d.id, d.name) for d in ptrs],
       [(9, "Logitech G Pro Gaming Mouse"), (13, "SynPS/2 Synaptics TouchPad")])
mouse, pad = ptrs
expect("mouse is no touchpad", (mouse.is_touchpad, pad.is_touchpad), (False, True))
expect("profile", mouse.get("accel_profile"), "adaptive")
expect("profiles offered", mouse.choices("accel_profile"), ["adaptive", "flat", "custom"])
expect("touchpad profiles (older driver, 2 values)", pad.choices("accel_profile"), ["adaptive", "flat"])
expect("speed", mouse.get("accel_speed"), 0.0)
expect("scroll methods", pad.choices("scroll_method"), ["twofinger", "edge", "none"])
expect("click method", pad.get("click_method"), "buttonareas")
expect("mouse has no tapping", mouse.has("tapping"), False)
expect("empty list prop", mouse.props["libinput Accel Custom Fallback Points"], [])
kbds = [d for d in D.list_devices(with_props=False) if d.kind == "keyboard"]
expect("keyboards (no masters, no XTEST)", [d.id for d in kbds], [10, 14])

# ---- live changes
D.apply(mouse, "accel_profile", "flat")
D.apply(mouse, "accel_speed", -0.35)
D.apply(pad, "accel_profile", "flat")      # 2-value property on this device
D.apply(pad, "tapping", True)
D.apply(pad, "scroll_method", "edge")
log = state()["log"]
expect("set-prop calls", log, [
    [9, "libinput Accel Profile Enabled", ["0", "1", "0"]],
    [9, "libinput Accel Speed", ["-0.350000"]],
    [13, "libinput Accel Profile Enabled", ["0", "1"]],
    [13, "libinput Tapping Enabled", ["1"]],
    [13, "libinput Scroll Method Enabled", ["0", "1", "0"]],
])
again = {d.name: d for d in D.pointers()}
expect("read back", (again[mouse.name].get("accel_profile"), again[mouse.name].get("accel_speed")), ("flat", -0.35))
expect("default unchanged", again[mouse.name].get("accel_profile", default=True), "adaptive")

# ---- saved settings come back after a replug
D.save_setting(mouse.name, "accel_profile", "flat")
D.save_setting(mouse.name, "accel_speed", -0.35)
D.save_setting(pad.name, "tapping", True)
D.save_setting("Some Unplugged Mouse", "accel_speed", 0.5)
replug()
expect("after replug", {d.name: d for d in D.pointers()}[mouse.name].get("accel_profile"), "adaptive")
n = D.apply_saved()
expect("re-applied count", n, 3)
after = {d.name: d for d in D.pointers()}
expect("restored", (after[mouse.name].get("accel_profile"), after[mouse.name].get("accel_speed"),
                    after[pad.name].get("tapping")), ("flat", -0.35, True))
expect("nothing to do the second time", D.apply_saved(), 0)

# ---- the watcher applies on start and on a hotplug event
replug()
p = subprocess.Popen([sys.executable, "-c", "import sys; sys.path.insert(0, %r); "
                      "from xcontrol import input_devices as D; sys.exit(D.watch())" % os.path.join(HERE, "..")],
                     env=dict(os.environ, XCONTROL_DEBUG="1"), stderr=subprocess.PIPE, text=True)
import time  # noqa: E402
time.sleep(2.5)
expect("watcher holds the lock", D.watcher_running(), True)
p.kill()
err = p.stderr.read()
expect("watcher applied at start and on hotplug", err.count("applied 3 pointer settings") >= 1 and "device added" in err,
       True)
expect("lock released", D.watcher_running(), False)

# ---- keyboard
lists = K.load_lists()
if lists.layouts:
    expect("layouts", lists.layouts.get("br"), "Portuguese (Brazil)")
    expect("variants", "dvorak" in lists.variants.get("br", {}), True)
    expect("caps options", "caps:escape" in lists.options.get("caps", {}), True)
    expect("group names", "grp" in lists.groups, True)
q = K.parse_query("rules:      evdev\nmodel:      pc105\nlayout:     us,br\nvariant:    ,abnt2\n"
                  "options:    grp:alt_shift_toggle,caps:escape\n")
expect("query", (q["layout"], q["variant"], q["options"]), ("us,br", ",abnt2", ["grp:alt_shift_toggle", "caps:escape"]))
expect("xset", K.parse_xset("Keyboard Control:\n  auto repeat delay:  250    repeat rate:  40\n"), (250, 40))
expect("split", K.split_layouts("us,br", ",abnt2"), [("us", ""), ("br", "abnt2")])
expect("join", K.join_layouts([("br", "abnt2"), ("us", "")]), ("br,us", "abnt2,"))
expect("join without variants", K.join_layouts([("us", "")]), ("us", ""))
expect("replace option", K.with_option(["grp:alt_shift_toggle", "caps:escape"], "caps", "caps:ctrl_modifier"),
       ["grp:alt_shift_toggle", "caps:ctrl_modifier"])
expect("remove option", K.with_option(["caps:escape"], "caps", ""), [])
expect("setxkbmap args", K.xkb_args("br", "abnt2", ["caps:escape"]),
       ["setxkbmap", "-layout", "br", "-variant", "abnt2", "-option", "", "-option", "caps:escape"])
expect("xset args", K.repeat_args(250, 40), ["xset", "r", "rate", "250", "40"])

print("check_input:", "FAILED" if bad else "ok")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
