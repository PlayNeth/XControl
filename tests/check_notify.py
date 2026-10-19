"""Notifications (dunst): config generation for old and new dunst, rules, extra lines."""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, ".config"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import desktop as D, notify as N  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def sections(text):
    """{section: {key: value}} (enough to check it)."""
    out, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[") and s.endswith("]"):
            cur = out.setdefault(s[1:-1], {})
        elif "=" in s and cur is not None:
            k, v = s.split("=", 1)
            cur[k.strip()] = v.strip()
    return out


n = N.normalize({"enabled": True, "position": "bottom-right", "offset_x": 20, "offset_y": 30, "max_height": 250,
                 "rules": [{"app": "Spotify", "action": "history_only"}, {"app": "Steam*", "action": "hide"},
                           {"app": "", "action": "hide"}, {"app": "x", "action": "explode"}],
                 "timeouts": {"normal": 7}, "colors": {"critical": ["#111111", "#222222", "#333333"]},
                 "extra": "word_wrap = yes\nfont = Mono 9\n[mine]\nappname = foo\nurgency = low"})
new = sections(N.generate(n, ver=(1, 13), font="Sans 10", icons="Papirus"))
old = sections(N.generate(n, ver=(1, 9), font="Sans 10", icons="Papirus"))
g = new["global"]
expect("origin", g["origin"], "bottom-right")
expect("offset 1.12+", g["offset"], "(20, 30)")
expect("height 1.12+", g["height"], "(0, 250)")
expect("offset old", old["global"]["offset"], "20x30")
expect("height old", old["global"]["height"], "250")
expect("format keeps \\n for dunst", g["format"], '"<b>%s</b>\\n%b"')
expect("extra replaces the font", g["font"], "Mono 9")
expect("extra added", g["word_wrap"], "yes")
expect("icon themes", g["icon_theme"], '"Papirus, Adwaita, hicolor"')
expect("normal timeout", new["urgency_normal"]["timeout"], "7")
expect("critical colors", (new["urgency_critical"]["background"], new["urgency_critical"]["frame_color"]),
       ('"#111111"', '"#333333"'))
expect("critical through do-not-disturb (1.10+)", new["urgency_critical"].get("override_pause_level"), "60")
expect("no pause levels on 1.9", "override_pause_level" in old["urgency_critical"], False)
expect("rules kept (valid ones)", [(new[f"xcontrol_rule_{i}"]["appname"]) for i in (1, 2)], ['"Spotify"', '"Steam*"'])
expect("history only", new["xcontrol_rule_1"].get("skip_display"), "true")
expect("hidden", (new["xcontrol_rule_2"].get("skip_display"), new["xcontrol_rule_2"].get("history_ignore")),
       ("true", "true"))
expect("no third rule", "xcontrol_rule_3" in new, False)
expect("extra section", new["mine"], {"appname": "foo", "urgency": "low"})

# sound: a small script dunst runs
n2 = N.normalize({"enabled": True, "sound": "/usr/share/sounds/x it's.oga"})
N.write(n2, ver=(1, 13), font="Sans 10", icons="")
with open(N.sound_script()) as f:
    script = f.read()
expect("sound script quotes the path", "'/usr/share/sounds/x it'\\''s.oga'" in script, True)
expect("sound rule", '"' + N.sound_script() + '"' in open(N.config_path()).read(), True)
expect("unchanged config isn't rewritten", N.write(n2, ver=(1, 13), font="Sans 10", icons=""), False)

# the desktop service runs it, and notices other notification programs in the i3 config
d = D.normalize({"notify": {"enabled": True}})
expect("wanted", D.wanted(d), True)
os.makedirs(os.path.join(tmp, ".config", "i3"))
with open(os.path.join(tmp, ".config", "i3", "config"), "w") as f:
    f.write("exec --no-startup-id dunst\nexec --no-startup-id nm-applet\n")
expect("conflict", [k for k, _l in D.session_conflicts()], ["notifications"])

print("check_notify:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
