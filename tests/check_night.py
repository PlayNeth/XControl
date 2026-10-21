"""Night light: color math, location from the time zone, the schedule, the saved gamma."""
import datetime
import os
import sys
import tempfile
import time

tmp = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import night as N  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


expect("6500 K is neutral", N.whitepoint(6500), (1.0, 1.0, 1.0))
r, g, b = N.whitepoint(3400)
expect("3400 K is warm", (r == 1.0, 0.6 < g < 0.85, 0.35 < b < 0.65), (True, True, True))
expect("ramp ends", (N.ramp(256, 1.0)[0], N.ramp(256, 1.0)[-1], N.ramp(256, 0.5)[-1]), (0, 65535, 32768))
expect("ramp gamma like xrandr", N.ramp(3, 1.0, 2.0)[1], round(0.5 ** 0.5 * 65535))

tab = os.path.join(tmp, "zone1970.tab")
with open(tab, "w") as f:
    f.write("# comment\nBR\t-2332-04637\tAmerica/Sao_Paulo\tS & SE Brazil\n"
            "DE,DK,NO,SE,SJ\t+5230+01322\tEurope/Berlin\tmost of Germany\n")
expect("location", N.location_from_timezone("America/Sao_Paulo", tabs=(tab,)), (-23.5333, -46.6167))
expect("unknown zone", N.location_from_timezone("Mars/Base", tabs=(tab,)), None)

tz = datetime.timezone(datetime.timedelta(hours=-3))
sp = (-23.53, -46.62)
sun = N.normalize({"enabled": True})
expect("noon is day", N.night_amount(sun, datetime.datetime(2026, 10, 19, 12, 0, tzinfo=tz), sp), 0.0)
expect("midnight is night", N.night_amount(sun, datetime.datetime(2026, 10, 19, 0, 0, tzinfo=tz), sp), 1.0)
dusk = N.night_amount(sun, datetime.datetime(2026, 10, 19, 18, 0, tzinfo=tz), sp)
expect("dusk is in between", 0 < dusk < 1, True)
nxt = N.next_change(sun, datetime.datetime(2026, 10, 19, 12, 0, tzinfo=tz), sp)
expect("sunset around 18:20 in São Paulo", (nxt.hour, 10 <= nxt.minute <= 35), (18, True))

hours = N.normalize({"enabled": True, "mode": "times", "start": "22:30", "end": "06:00", "fade_minutes": 30})


def at(hm):
    h, m = map(int, hm.split(":"))
    return N.night_amount(hours, datetime.datetime(2026, 10, 19, h, m, tzinfo=tz))


expect("hours", [at(t) for t in ("22:00", "22:45", "23:00", "03:00", "06:15", "06:30", "12:00")],
       [0.0, 0.5, 1.0, 1.0, 0.5, 0.0, 0.0])
short = N.normalize({"enabled": True, "mode": "times", "start": "22:00", "end": "22:10", "fade_minutes": 30})
expect("night shorter than the fade: no jump at the end",
       [round(N.night_amount(short, datetime.datetime(2026, 10, 19, 22, m, tzinfo=tz)), 3) for m in (9, 10, 11, 40)],
       [0.3, 0.333, 0.3, 0.0])
expect("temperature halfway", N.temperature(hours, 0.5), 5050)
expect("bad times fixed", N.normalize({"start": "25:00", "end": "7"})["start"], "20:00")

expect("saved gamma", N.saved_gamma(["xrandr", "--output", "DP-2", "--mode", "640x480", "--gamma", "1.2:1.2:1.2",
                                     "--output", "HDMI-1", "--off"]), {"DP-2": 1.2})


def runtime(name):
    return os.path.join(tmp, "rt-" + name)


expect("not forced", N.forced(runtime), None)
N.set_forced(runtime, "on", sun)
expect("forced on", (N.forced(runtime), N.target(sun, runtime)), ("on", sun["night_temp"]))
N.set_forced(runtime, "auto", sun)
expect("auto again", N.forced(runtime), None)
with open(runtime("night"), "w") as f:
    f.write('{"force": "off", "until": %f}' % (time.time() - 5))
expect("expires at the next change", N.forced(runtime), None)
expect("off when disabled", N.target(N.normalize({}), runtime), 6500)

print("check_night:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
