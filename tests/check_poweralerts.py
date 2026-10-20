"""Power alerts: poweralertd's command line, its place in the desktop service, and finding a
second one started from the i3 config."""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, ".config"), XDG_CACHE_HOME=os.path.join(tmp, ".cache"),
                  XDG_RUNTIME_DIR=tmp)
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
from xcontrol import desktop as D, poweralerts as PA  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


expect("default command", PA.command({}), ["poweralertd", "-s", "-i", "mouse", "-i", "keyboard"])
expect("only the computer", PA.command({"skip_startup": False, "devices": False}), ["poweralertd", "-S"])
expect("groups expand to poweralertd's types",
       PA.command({"skip_startup": False, "ignore": ["gaming", "audio"]}),
       ["poweralertd", "-i", "gaming input", "-i", "headset", "-i", "headphones", "-i", "speakers",
        "-i", "other audio"])
expect("unknown groups dropped, order kept", PA.normalize({"ignore": ["pen", "nope", "mouse"]})["ignore"],
       ["mouse", "pen"])
expect("bad value", PA.normalize({"ignore": "mouse"})["ignore"], [])

desk = D.normalize({})
expect("off by default", ("poweralertd" in D.wanted_children(desk), D.wanted(desk)), (False, False))
desk = D.normalize({"power_alerts": {"enabled": True, "ignore": []}})
real = PA.installed
PA.installed = lambda: True
try:
    expect("run by the service", D.wanted_children(desk).get("poweralertd"), (["poweralertd", "-s"], {}))
    expect("the service is wanted", D.wanted(desk), True)
finally:
    PA.installed = real
expect("a leftover one is stopped too", "poweralertd" in D.CHILD_PROGRAMS, True)

os.makedirs(os.path.join(tmp, ".config", "i3"))
with open(os.path.join(tmp, ".config", "i3", "config"), "w") as f:
    f.write("exec --no-startup-id poweralertd -s\nexec_always dunst\n")
expect("found in the i3 config", [k for k, _line in D.session_conflicts()], ["power_alerts", "notifications"])

print("check_poweralerts:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
