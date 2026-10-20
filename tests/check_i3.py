"""i3 config: generation (checked by the real `i3 -C` when installed), import, backup and restore."""
import os
import shutil
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, ".config"))
os.environ.pop("DISPLAY", None)   # no live i3 to reload here
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import i3cfg as I  # noqa: E402,E741

bad = 0
HAVE_I3 = bool(shutil.which("i3"))


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def valid(what, c, bar=False):
    if HAVE_I3:
        ok, errors = I.validate(I.generate(c, bar))
        expect(what + " accepted by i3", (ok, errors), (True, []))


# defaults: i3's stock keys with $mod = Super, the session line, i3bar only without XControl's bar
c = I.normalize({})
text = I.generate(c)
expect("mod", "set $mod Mod4" in text, True)
expect("session line", I.SESSION_LINE in text, True)
expect("terminal key", "bindsym $mod+Return exec i3-sensible-terminal" in text, True)
expect("resize mode", 'mode "resize" {' in text, True)
expect("i3bar without our bar", "bar {" in text, True)
expect("no i3bar with our bar", "bar {" in I.generate(c, True), False)
expect("no clashes in the defaults", I.clashes(c["bindings"], "Mod4"), {})
valid("defaults", c)

c = I.normalize({"mod": "Mod1", "gaps_inner": 8, "gaps_outer": 4, "smart_gaps": "on", "smart_borders": "no_gaps",
                 "border": "none", "float_border": "pixel", "hide_edge_borders": "smart", "title_align": "center",
                 "focus_follows_mouse": False, "back_and_forth": True, "focus_wrapping": "workspace",
                 "workspaces": [{"name": "1:web", "output": "DP-2"}, {"name": "chat \"x\""}],
                 "startup": [{"command": "nm-applet"},
                             {"command": "~/bin/x.sh", "always": True, "no_startup_id": False}],
                 "rules": [{"kind": "for_window", "criteria": 'class="Steam"', "action": "floating enable"},
                           {"kind": "assign", "criteria": '[class="discord"]', "action": "number 2"}],
                 "bindings": [{"keys": "$mod+p", "command": "exec flameshot gui"},
                              {"keys": "Print", "command": "exec scrot", "release": True},
                              {"keys": "Escape", "command": 'mode "default"', "mode": "launch apps"}],
                 "extra": "for_window [title=\"pip\"] sticky enable"})
text = I.generate(c, True)
for line in ('set $ws1 "1:web"', 'set $ws2 "chat \\"x\\""', "workspace $ws1 output DP-2", "smart_borders no_gaps",
             "default_border none", "focus_follows_mouse no", "workspace_auto_back_and_forth yes",
             "exec --no-startup-id nm-applet", "exec_always ~/bin/x.sh", 'for_window [class="Steam"] floating enable',
             'assign [class="discord"] number 2', "bindsym --release Print exec scrot", 'mode "launch apps" {',
             'for_window [title="pip"] sticky enable'):
    expect(f"line {line!r}", line in text, True)
valid("everything set", c, True)
sb = I.normalize({"smart_borders": "no_gaps", "popup_fullscreen": "all"})
new, old = I.generate(sb, ver=(4, 24)), I.generate(sb, ver=(4, 23))
expect("4.24: smart_borders becomes hide_edge_borders", ("smart_borders" in new, "hide_edge_borders smart_no_gaps" in new),
       (False, True))
expect("4.23 keeps smart_borders", ("smart_borders no_gaps" in old, "hide_edge_borders none" in old), (True, True))
expect("popup 'all' only from 4.24", ("popup_during_fullscreen all" in new, "popup_during_fullscreen smart" in old),
       (True, True))
expect("smart_borders off is left out", "smart_borders" in I.generate(I.normalize({})), False)

# clashes: same keys in the same mode, whatever the spelling
cl = I.clashes([{"keys": "$mod+Shift+a", "command": "x", "mode": "default", "code": False, "release": False},
                {"keys": "Shift+Mod4+A", "command": "y", "mode": "default", "code": False, "release": False},
                {"keys": "$mod+Shift+a", "command": "z", "mode": "resize", "code": False, "release": False}], "Mod4")
expect("clash", cl, {1: [0], 0: [1]})

# a broken extra line is caught and named
if HAVE_I3:
    ok, errors = I.validate(I.generate(I.normalize({"extra": "frobnicate 1"})))
    expect("bad extra rejected", ok, False)
    expect("error names the line", any("frobnicate 1" in e for e in errors), True)

# import
user = r"""
# my config
set $mod Mod4
set $term alacritty
set $ws1 "1:term"
set $ws2 "2:web"
font pango:JetBrains Mono 9
default_border pixel 3
gaps inner 10px
gaps outer 2
client.focused #111111 #222222 #333333 #444444 #555555
focus_follows_mouse no
workspace $ws2 output HDMI-1
bindsym $mod+Return exec $term
bindsym $mod+Shift+q kill
bindsym --release $mod+x exec --no-startup-id xcontrol --lock
bindcode 107 exec scrot
mode "resize" {
    bindsym h resize shrink width 10 px
    bindsym Escape mode "default"
}
exec --no-startup-id nm-applet
exec_always --no-startup-id ~/.config/polybar/launch.sh
exec --no-startup-id picom -b
exec --no-startup-id feh --bg-scale ~/w.png
exec_always --no-startup-id autotiling
for_window [class="Pavucontrol"] floating enable
assign [class="Firefox"] $ws2
no_focus [window_role="pop-up"]
bar {
    status_command i3status
    position top
}
"""
c, skipped = I.import_config(user, managed={"bar", "picom", "wallpaper"})
expect("import mod", c["mod"], "Mod4")
expect("import font", c["font"], "JetBrains Mono 9")
expect("import border", (c["border"], c["border_width"]), ("pixel", 3))
expect("import gaps", (c["gaps_inner"], c["gaps_outer"]), (10, 2))
expect("import colors", c["colors"]["focused"], ["#111111", "#222222", "#333333", "#444444", "#555555"])
expect("import ffm", c["focus_follows_mouse"], False)
expect("import workspaces", c["workspaces"][:2], [{"name": "1:term", "output": ""},
                                                  {"name": "2:web", "output": "HDMI-1"}])
expect("import bindings", [(b["keys"], b["command"], b["mode"], b["code"], b["release"]) for b in c["bindings"]], [
    ("$mod+Return", "exec alacritty", "default", False, False),
    ("$mod+Shift+q", "kill", "default", False, False),
    ("$mod+x", "exec --no-startup-id xcontrol --lock", "default", False, True),
    ("107", "exec scrot", "default", True, False),
    ("h", "resize shrink width 10 px", "resize", False, False),
    ("Escape", 'mode "default"', "resize", False, False)])
expect("import startup", c["startup"], [{"command": "nm-applet", "always": False, "no_startup_id": True},
                                        {"command": "autotiling", "always": True, "no_startup_id": True}])
expect("import skipped", len(skipped), 4)   # polybar, picom, feh, bar { }
expect("import rules", [(r["kind"], r["criteria"], r["action"]) for r in c["rules"]],
       [("for_window", '[class="Pavucontrol"]', "floating enable"), ("assign", '[class="Firefox"]', "$ws2")])
expect("import extra", c["extra"], 'no_focus [window_role="pop-up"]')
valid("imported", c)
# nothing managed by XControl: those startup lines and the bar stay
c2, skipped2 = I.import_config(user, managed=set())
expect("unmanaged kept", [x["command"] for x in c2["startup"]],
       ["nm-applet", "~/.config/polybar/launch.sh", "picom -b", "feh --bg-scale ~/w.png", "autotiling"])
expect("own bar kept", ("bar {" in c2["extra"], "    position top" in c2["extra"], c2["i3bar"]), (True, True, False))
valid("imported, nothing managed", c2)

if HAVE_I3:
    stock, _s = I.import_config(open("/etc/i3/config").read())
    valid("i3's stock config imported", stock)

# take over, rewrite, restore
cfg = I.target()
os.makedirs(os.path.dirname(cfg), exist_ok=True)
with open(cfg, "w") as f:
    f.write("# mine\n")
os.makedirs(os.path.join(tmp, ".i3"))
with open(os.path.join(tmp, ".i3", "config"), "w") as f:
    f.write("# older\n")
expect("previous before", I.previous(), os.path.join(tmp, ".i3", "config"))
ok, _e = I.write(I.normalize({}))
expect("written", (ok, I.is_ours(), I.loaded_path()), (True, True, cfg))
expect("backups", (open(cfg + ".before-xcontrol").read(), open(os.path.join(tmp, ".i3/config.before-xcontrol")).read()),
       ("# mine\n", "# older\n"))
expect("previous after", I.previous(), os.path.join(tmp, ".i3", "config.before-xcontrol"))
I.write(I.normalize({"gaps_inner": 3}))
expect("backup kept once", open(cfg + ".before-xcontrol").read(), "# mine\n")
if HAVE_I3:
    ok, _e = I.write(I.normalize({"gaps_inner": 5, "extra": "nonsense here"}))
    expect("bad config not written", (ok, "gaps inner 3" in open(cfg).read()), (False, True))
expect("restore", I.restore(), True)
expect("restored", (open(cfg).read(), open(os.path.join(tmp, ".i3/config")).read(), I.can_restore()),
       ("# mine\n", "# older\n", False))
expect("ours kept", os.path.exists(cfg + ".xcontrol"), True)

shutil.rmtree(tmp, ignore_errors=True)
if bad:
    sys.exit(1)
print("i3: ok" + ("" if HAVE_I3 else " (i3 not installed: configs not checked by i3)"))
