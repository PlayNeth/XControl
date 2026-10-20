"""Session check: polkit agent detection, and that every check runs here without failing."""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, ".config"), XDG_RUNTIME_DIR=tmp)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import health  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


procs = {1: ("i3", ["i3"]), 2: ("polkit-gnome-au", ["/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1"])}
expect("agent found by its path", health.polkit_agent(procs), "polkit-gnome-authentication-agent-1")
expect("no agent", health.polkit_agent({1: ("i3", ["i3"])}), None)
expect("lxpolkit", health.polkit_agent({3: ("lxpolkit", ["lxpolkit"])}), "lxpolkit")
results = health.checks()
expect("checks run", all(r[0] in ("ok", "info", "warn", "error") and r[1] for r in results), True)
levels = [r[0] for r in results]
expect("worst first", levels == sorted(levels, key=["error", "warn", "info", "ok"].index), True)

print("check_health:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
