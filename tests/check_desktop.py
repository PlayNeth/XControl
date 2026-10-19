"""Desktop: wallpaper geometry and drawing, lock and blanking commands, conflicts."""
import os
import shutil
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, ".config"), XDG_CACHE_HOME=os.path.join(tmp, ".cache"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cairo  # noqa: E402
from xcontrol import desktop as D, wallpaper as W  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


# ---- placement inside a 1280x1024 display, for a 1920x1080 picture
expect("fill crops the sides", W.placement(1920, 1080, 1280, 1024, "fill"), (1820, 1024, -270, 0))
expect("fit leaves bars", W.placement(1920, 1080, 1280, 1024, "fit"), (1280, 720, 0, 152))
expect("center", W.placement(800, 600, 1280, 1024, "center"), (800, 600, 240, 212))
expect("stretch", W.placement(800, 600, 1280, 1024, "stretch"), (1280, 1024, 0, 0))

mons = [("DP-2", 0, 0, 1280, 1024), ("HDMI-A-1", 1280, 0, 1920, 1080)]
wp = W.normalize({"file": "a.png", "mode": "fit", "layout": "same"})
expect("same: one area per display", [a[:4] for a in W.areas(wp, mons, 3200, 1080)],
       [(0, 0, 1280, 1024), (1280, 0, 1920, 1080)])
wp["layout"] = "span"
expect("span: one area over all", [a[:4] for a in W.areas(wp, mons, 3200, 1080)], [(0, 0, 3200, 1080)])
wp = W.normalize({"layout": "separate", "file": "a.png", "monitors": {"HDMI-A-1": {"file": "b.png", "mode": "tile"}}})
expect("separate: own picture, others the shared one", [(a[4], a[5]) for a in W.areas(wp, mons, 3200, 1080)],
       [("a.png", "fill"), ("b.png", "tile")])
expect("no monitors: whole screen", W.areas(W.normalize({}), [], 800, 600), [(0, 0, 800, 600, "", "fill")])
expect("bad values normalized", (W.normalize({"layout": "x", "mode": "y"})["layout"],
                                 W.normalize({"mode": "y"})["mode"]), ("same", "fill"))

# ---- drawing: a red picture "fit" on a 200x100 screen leaves blue bars
pic = os.path.join(tmp, "red.png")
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 50, 50)
cr = cairo.Context(s)
cr.set_source_rgb(1, 0, 0)
cr.paint()
s.write_to_png(pic)
surf, errors = W.compose(W.normalize({"file": pic, "mode": "fit", "color": "#0000ff"}), [("X", 0, 0, 200, 100)],
                         200, 100)


def pixel(surface, x, y):
    data = surface.get_data()
    i = y * surface.get_stride() + x * 4
    b, g, r = data[i], data[i + 1], data[i + 2]
    return r, g, b


expect("draw ok", errors, [])
expect("bar is the color", pixel(surf, 10, 50), (0, 0, 255))
expect("middle is the picture", pixel(surf, 100, 50), (255, 0, 0))
_s, errors = W.compose(W.normalize({"file": os.path.join(tmp, "nope.png")}), [], 10, 10)
expect("missing file reported", len(errors), 1)

# ---- lock and blanking commands
desk = D.normalize({"lock": {"enabled": True, "locker": "i3lock", "idle_minutes": 5, "color": "#112233",
                             "image": "color"},
                    "blanking": {"managed": True, "screen_off_minutes": 20}})
expect("xss-lock + i3lock", D.xss_lock_command(desk["lock"]),
       ["xss-lock", "--transfer-sleep-lock", "--", "i3lock", "--nofork", "--ignore-empty-password",
        "--color", "112233", "--show-failed-attempts"])
desk["lock"].update(image="wallpaper")
open(os.path.join(tmp, "lock.png"), "wb").close()
expect("lock image used when present", "--image" in D.locker_command(desk["lock"], os.path.join(tmp, "lock.png")),
       True)
expect("no image yet: color", "--color" in D.locker_command(desk["lock"], os.path.join(tmp, "missing.png")), True)
desk["lock"].update(locker="slock", lock_on_sleep=False)
expect("slock, not on sleep", D.xss_lock_command(desk["lock"]), ["xss-lock", "--ignore-sleep", "--", "slock"])
desk["lock"].update(locker="xsecurelock", lock_on_sleep=True)
expect("xsecurelock", D.xss_lock_command(desk["lock"]), ["xss-lock", "--transfer-sleep-lock", "--", "xsecurelock"])
expect("xset", D.xset_commands(desk), [["xset", "s", "300", "5"], ["xset", "+dpms", "dpms", "0", "0", "1200"]])
desk["lock"]["idle_minutes"] = 0
desk["blanking"]["screen_off_minutes"] = 0
expect("never", D.xset_commands(desk), [["xset", "s", "off"], ["xset", "-dpms"]])
expect("nothing managed: nothing touched", D.xset_commands(D.normalize({})), [])
expect("service only when needed", (D.wanted(D.normalize({})), D.wanted(desk)), (False, True))

# ---- the i3 config
os.makedirs(os.path.join(tmp, ".config", "i3"))
with open(os.path.join(tmp, ".config", "i3", "config"), "w") as f:
    f.write("exec --no-startup-id ~/.fehbg\n# exec feh --bg-fill old.png\nexec_always nitrogen --restore\n"
            "exec --no-startup-id xss-lock --transfer-sleep-lock -- i3lock --nofork\n"
            "bindsym $mod+Return exec i3-sensible-terminal\n")
expect("conflicts", [k for k, _line in D.session_conflicts()], ["wallpaper", "wallpaper", "lock"])

# ---- autostart entry follows the settings
D.sync_autostart(desk)
expect("autostart written", os.path.exists(D.autostart_file()), True)
D.sync_autostart(D.normalize({}))
expect("autostart removed", os.path.exists(D.autostart_file()), False)

print("check_desktop:", "FAILED" if bad else "ok")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
