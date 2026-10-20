"""Power: the logind helper (unprivileged, so its test hooks apply), when idle sleep happens,
and power profiles when power-profiles-daemon answers."""
import os
import shutil
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
helper = os.path.join(here, "..", "data", "xcontrol-power-helper")
sys.path.insert(0, os.path.join(here, ".."))
from xcontrol import power as P  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


# when to sleep
p = P.normalize({"sleep_minutes": 30, "not_while_sound": False})
s = P.IdleSleep()
expect("not idle long enough", s.check(p, 29 * 60_000, False, 10_000.0), False)
expect("kept awake", s.check(p, 31 * 60_000, True, 10_000.0), False)
expect("sleeps", s.check(p, 31 * 60_000, False, 10_000.0), True)
expect("not again right after waking", s.check(p, 31 * 60_000, False, 10_060.0), False)
expect("off", P.IdleSleep().check(P.normalize({}), 10 ** 9, False, 0.0), False)
s2 = P.IdleSleep()
s2.sound, s2.sound_checked = True, 10_000.0
expect("not while sound plays", s2.check(P.normalize({"sleep_minutes": 10}), 11 * 60_000, False, 10_001.0), False)
expect("bad values", P.normalize({"sleep_minutes": "x"})["sleep_minutes"], 0)

# the helper
prefix = []
if os.geteuid() == 0:
    prefix = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"] if shutil.which("setpriv") else None
if prefix is not None:
    tmp = tempfile.mkdtemp()
    os.chmod(tmp, 0o777)
    conf = os.path.join(tmp, "logind.conf.d")
    env = dict(os.environ, XCONTROL_LOGIND_DIR=conf, XCONTROL_LOGIND_RELOAD="0")

    def run(*args):
        return subprocess.run(prefix + ["sh", helper, *args], capture_output=True, text=True, env=env)

    r = run("logind", "HandlePowerKey=suspend", "HandleLidSwitch=lock")
    expect("saved", (r.returncode, r.stderr), (0, ""))
    with open(os.path.join(conf, "50-xcontrol.conf")) as f:
        expect("file", f.read().splitlines()[1:], ["[Login]", "HandlePowerKey=suspend", "HandleLidSwitch=lock"])
    for args, what in ((("logind", "KillUserProcesses=yes"), "other keys"),
                       (("logind", "HandlePowerKey=rm -rf"), "bad action"),
                       (("logind", "HandlePowerKey"), "no action"), (("restart",), "unknown command")):
        expect(f"refused: {what}", run(*args).returncode != 0, True)
    expect("all defaults removes it", (run("logind").returncode, os.path.exists(os.path.join(conf, "50-xcontrol.conf"))),
           (0, False))

# power-profiles-daemon, when this machine runs it
info = P.profiles()
if info:
    import gi
    gi.require_version("GLib", "2.0")
    from gi.repository import GLib
    loop = GLib.MainLoop()
    result = {}
    target = "power-saver" if info[0] != "power-saver" else "balanced"
    P.set_profile(target, lambda err: (result.update(err=err), loop.quit()))
    GLib.timeout_add_seconds(10, loop.quit)
    loop.run()
    expect("profile switched", (result.get("err"), P.profiles()[0]), (None, target))
    P.set_profile(info[0], lambda err: loop.quit())
    loop.run()

print("check_power:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
