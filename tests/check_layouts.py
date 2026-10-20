"""Per-game layouts: saved settings, picking the layout for the program in front, merging it
over the defaults, the controller switching to it in place, and naming the program in front."""
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
from xcontrol import focus as F, pad_service as S, padmap as M, pads as P  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


c = S.normalize({"lightbar": "#0000ff", "map": {"cross": "a"}, "profiles": [
    {"name": "Elden Ring", "match": ["steam_app_1245620", " eldenring.exe ", ""],
     "settings": {"lightbar": "#ff4400", "map": {"cross": "b", "circle": "a"}, "emulate": "off", "bt_poll_ms": 8}},
    {"name": "", "match": ["Steam_App_*"], "settings": {"gyro": {"output": "mouse"}}},
    "junk", {"name": "Nothing to match", "match": []}]})
expect("kept and cleaned", [(p["name"], p["match"]) for p in c["profiles"]],
       [("Elden Ring", ["steam_app_1245620", "eldenring.exe"]), ("?", ["Steam_App_*"]), ("Nothing to match", [])])
expect("only what a layout can change", sorted(c["profiles"][0]["settings"]), ["lightbar", "map"])
expect("its settings normalized", c["profiles"][0]["settings"]["map"]["circle"], "a")

expect("by program name, any case", S.choose(c, ["steam_app_9", "EldenRing.exe"]), 0)
expect("first match wins", S.choose(c, ["steam_app_1245620"]), 0)
expect("by pattern", S.choose(c, ["steam_app_570", "dota2"]), 1)
expect("no match", S.choose(c, ["firefox", "Navigator"]), None)
expect("a layout matching nothing never applies", S.choose(c, []), None)

e = S.effective(c, 0)
expect("merged", (e["lightbar"], e["map"]["cross"], e["emulate"], e["bt_poll_ms"]),
       ("#ff4400", "b", c["emulate"], c["bt_poll_ms"]))
expect("default untouched", (S.effective(c, None)["lightbar"], c["lightbar"]), ("#0000ff", "#0000ff"))
expect("XControl's own window doesn't switch layouts", (S._ours(["xcontrol", "Xcontrol", "python3"]),
                                                        S._ours(["steam_app_1", "game.exe"])), (True, False))
expect("layouts change without a restart", "profiles" in S.LIVE and "map" in S.LIVE, True)

# a controller switches its button layout in place
lit = []
real = P.set_lightbar
P.set_lightbar = lambda pad, color, brightness: lit.append(color) or True
try:
    pad = P.Pad(key="k", name="DS4", bus="usb", hid="/x")
    ctl = S.Controller(pad, S.effective(c, None), lambda m: None)
    ctl.mapper = M.Mapper(c["map"])
    ctl.apply(S.effective(c, 0))
    ctl.mapper.feed(M.EV_KEY, M.BTN_EAST, 0)
    expect("cross is B in the game", ctl.mapper.feed(M.EV_KEY, M.BTN_SOUTH, 1), [(M.EV_KEY, M.BTN_EAST, 1)])
    expect("its light bar", lit[-1], "#ff4400")
    ctl.apply(S.effective(c, None))
    expect("back to the default", (lit[-1], ctl.mapper.map["cross"]), ("#0000ff", "a"))
    ctl.close()
finally:
    P.set_lightbar = real

# the program in front: a Proton game (wine process, Windows path)
proc = tempfile.mkdtemp()
os.makedirs(os.path.join(proc, "4242"))
with open(os.path.join(proc, "4242", "comm"), "w") as f:
    f.write("eldenring.exe\n")
with open(os.path.join(proc, "4242", "cmdline"), "wb") as f:
    f.write(b"Z:\\home\\me\\Games\\ELDEN RING\\Game\\eldenring.exe\0-flag\0")
os.symlink("/usr/bin/wine64-preloader", os.path.join(proc, "4242", "exe"))
expect("process names", F.process_names(4242, proc), ["eldenring.exe", "wine64-preloader"])
expect("no X: no names", F.Focus(display=None).names() if not os.environ.get("DISPLAY") else [], [])

print("check_layouts:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
