"""Gaming mouse settings over D-Bus against tests/fake_ratbagd.py (a stand-in for
ratbagd on a private session bus). Re-runs itself under dbus-run-session."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if not os.environ.get("XCONTROL_TEST_BUS"):
    if not shutil.which("dbus-run-session"):
        print("check_ratbag: dbus-run-session not installed, skipped")
        sys.exit(0)
    env = dict(os.environ, XCONTROL_TEST_BUS="1")
    sys.exit(subprocess.call(["dbus-run-session", "--", sys.executable, os.path.abspath(__file__)], env=env,
                             stderr=subprocess.DEVNULL if not os.environ.get("XCONTROL_DEBUG") else None))

sys.path.insert(0, os.path.join(HERE, ".."))
tmp = tempfile.mkdtemp()
log_path = os.path.join(tmp, "log.json")
os.environ.update(XCONTROL_RATBAG_BUS="session", FAKE_RATBAG_LOG=log_path)
srv = subprocess.Popen([sys.executable, os.path.join(HERE, "fake_ratbagd.py")], stdout=subprocess.PIPE, text=True)
srv.stdout.readline()

from xcontrol import ratbag as R  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


try:
    expect("available", R.available(), None)
    dev = R.devices()[0]
    p = dev.active_profile()
    expect("name", dev.name, "Logitech G Pro Gaming Mouse")
    expect("profiles", len(dev.profiles), 2)
    expect("report rates", p.report_rates, [125, 250, 500, 1000])
    expect("debounces", p.debounces, [2, 4, 6, 8, 10])
    expect("angle snapping supported", p.angle_snapping, False)
    expect("dpi", [r.dpi for r in p.resolutions], [400, 800, 1600, 3200, 6400])
    expect("active stage", [bool(r.get("IsActive")) for r in p.resolutions], [False, True, False, False, False])
    expect("mappings", [R.describe_mapping(b.mapping) for b in p.buttons],
           [("button", 1), ("button", 2), ("button", 3), ("button", 4), ("button", 5),
            ("special", 7), ("key", 30), ("none", 0)])
    expect("rgb led", (p.leds[0].color_bits, p.leds[0].rgb), (8, (255, 0, 0)))
    expect("mono led", p.leds[1].color_bits, None)

    p.resolutions[2].set_dpi(1800)
    p.resolutions[3].make_active()
    p.set_report_rate(500)
    p.set_debounce(2)
    p.set_angle_snapping(True)
    p.buttons[4].set_special(R.SPECIAL_BASE + 9)
    p.buttons[7].set_button(6)
    p.leds[0].set_color((0, 128, 255))
    p.leds[0].set_mode(R.LED_BREATHING)
    dev.commit()
    time.sleep(0.2)
    q = R.devices()[0].active_profile()
    expect("after", ([r.dpi for r in q.resolutions], [bool(r.get("IsActive")) for r in q.resolutions],
                     q.get("ReportRate"), q.get("Debounce"), q.angle_snapping),
           ([400, 800, 1800, 3200, 6400], [False, False, False, True, False], 500, 2, True))
    expect("mapping after", (R.describe_mapping(q.buttons[4].mapping), q.buttons[7].mapping), (("special", 9), (1, 6)))
    expect("led after", (q.leds[0].rgb, q.leds[0].get("Mode")), ((0, 128, 255), R.LED_BREATHING))
    with open(log_path) as f:
        calls = [e.get("call") or e.get("set") for e in json.load(f)]
    expect("calls end with one commit", (calls[-1], calls.count("Commit")), ("Commit", 1))
    try:
        q.resolutions[0].set_dpi(123)
        expect("invalid dpi rejected", "accepted", "rejected")
    except R.RatbagError:
        pass
finally:
    srv.kill()
    shutil.rmtree(tmp, ignore_errors=True)

print("check_ratbag:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
