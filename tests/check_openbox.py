"""Openbox: reading an rc.xml and autostart, writing them back, keys, rules, files on disk."""
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, "config"), XDG_DATA_HOME=os.path.join(tmp, "share"),
                  XDG_DATA_DIRS=os.path.join(tmp, "sys"), XDG_CONFIG_DIRS=os.path.join(tmp, "xdg"))
os.environ.pop("DISPLAY", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import obcfg as O  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


RC = """<?xml version="1.0" encoding="UTF-8"?>
<!-- my config -->
<openbox_config xmlns="http://openbox.org/3.4/rc" xmlns:xi="http://www.w3.org/2001/XInclude">
  <resistance><strength>15</strength><screen_edge_strength>30</screen_edge_strength></resistance>
  <focus><focusNew>no</focusNew><followMouse>yes</followMouse><focusLast>yes</focusLast>
    <underMouse>no</underMouse><focusDelay>300</focusDelay><raiseOnFocus>yes</raiseOnFocus></focus>
  <placement><policy>UnderMouse</policy><center>no</center><monitor>Mouse</monitor><primaryMonitor>1</primaryMonitor>
  </placement>
  <theme><name>Onyx</name><titleLayout>LIMC</titleLayout><keepBorder>no</keepBorder>
    <animateIconify>no</animateIconify>
    <font place="ActiveWindow"><name>DejaVu Sans</name><size>10</size><weight>Bold</weight><slant>Normal</slant></font>
    <font place="InactiveWindow"><name>DejaVu Sans</name><size>10</size><weight>Bold</weight><slant>Normal</slant></font>
    <font place="MenuItem"><name>Noto Sans</name><size>9</size><weight>Normal</weight><slant>Italic</slant></font>
    <font place="ActiveOnScreenDisplay"><name>sans</name><size>9</size></font>
  </theme>
  <desktops><number>3</number><firstdesk>1</firstdesk><names><name>web</name><name>chat</name></names>
    <popupTime>500</popupTime></desktops>
  <margins><top>0</top><bottom>24</bottom><left>0</left><right>0</right></margins>
  <dock><position>TopLeft</position></dock>
  <keyboard>
    <chainQuitKey>C-g</chainQuitKey>
    <keybind key="W-e"><action name="Execute"><command>thunar</command></action></keybind>
    <keybind key="A-F4"><action name="Close"/></keybind>
    <keybind key="C-a"><keybind key="t"><action name="Execute"><command>xterm</command></action></keybind></keybind>
    <keybind key="A-Escape"><action name="Lower"/><action name="FocusToBottom"/></keybind>
    <keybind key="Mod4-E"><action name="Execute"><command>other</command></action></keybind>
  </keyboard>
  <mouse>
    <context name="Frame">
      <mousebind button="W-Left" action="Drag"><action name="Move"/></mousebind>
      <mousebind button="W-Right" action="Drag"><action name="Resize"/></mousebind>
      <mousebind button="C-W-Up" action="Click"><action name="GoToDesktop"><to>previous</to></action></mousebind>
    </context>
    <context name="Titlebar">
      <mousebind button="Left" action="DoubleClick"><action name="ToggleShade"/></mousebind>
    </context>
    <context name="Root"><mousebind button="Right" action="Press"><action name="ShowMenu"><menu>root-menu</menu>
      </action></mousebind></context>
  </mouse>
  <menu><file>my-menu.xml</file></menu>
  <applications>
    <application class="Steam" type="normal">
      <desktop>2</desktop><decor>no</decor>
      <position force="yes"><x>center</x><y>0</y></position>
      <skip_pager>yes</skip_pager>
      <size><width>800</width></size>
    </application>
    <application title="Picture-in-Picture"><layer>above</layer></application>
  </applications>
</openbox_config>
"""
AUTOSTART = """# my autostart
nm-applet &
feh --bg-scale ~/wall.png &
xcontrol --session &
if [ -x /usr/bin/foo ]; then
  foo &
fi
"""

c, skipped = O.import_config(RC, startup_text=AUTOSTART, managed={"wallpaper"})
expect("theme", (c["theme"], c["title_layout"], c["keep_border"], c["animate_iconify"]), ("Onyx", "LIMC", False, False))
expect("title font", c["title_font"], {"name": "DejaVu Sans", "size": 10, "weight": "bold", "slant": "normal"})
expect("menu font", c["menu_font"], {"name": "Noto Sans", "size": 9, "weight": "normal", "slant": "italic"})
expect("focus", (c["follow_mouse"], c["focus_delay"], c["raise_on_focus"], c["focus_new"]), (True, 300, True, False))
expect("placement", (c["placement"], c["center"], c["placement_monitor"]), ("UnderMouse", False, "Mouse"))
expect("resistance", (c["resist_windows"], c["resist_edges"]), (15, 30))
expect("desktops", (c["desktops"], c["desktop_names"], c["desktop_popup"]), (3, ["web", "chat"], 500))
expect("drag with Super", c["drag_mod"], "W")
expect("double-click", c["double_click"], "ToggleShade")
expect("bindings", [b["keys"] for b in c["bindings"]], ["W-e", "A-F4", "C-a", "A-Escape", "Mod4-E"])
expect("binding xml", c["bindings"][0]["xml"], '<action name="Execute"><command>thunar</command></action>')
expect("chain kept", "<keybind key=\"t\">" in c["bindings"][2]["xml"], True)
expect("rules", [r["match"] for r in c["rules"]], [{"class": "Steam", "type": "normal"}, {"title": "Picture-in-Picture"}])
expect("rule settings", c["rules"][0]["settings"],
       {"desktop": "2", "decor": "no", "x": "center", "y": "0", "skip_pager": "yes"})
expect("rule raw", c["rules"][0]["raw"], "<size><width>800</width></size>")
expect("autostart", [s["command"] for s in c["startup"]],
       ["nm-applet", "if [ -x /usr/bin/foo ]; then", "foo", "fi"])
expect("skipped", skipped, ["feh --bg-scale ~/wall.png &", "xcontrol --session &"])

# ---- writing it back
c["drag_mod"], c["double_click"], c["desktops"] = "A", "none", 2
c["bindings"].append({"keys": "W-Return", "xml": O.action_xml("Execute", "alacritty")})
text = O.generate(c)
root = ET.fromstring(text)
ns = "{http://openbox.org/3.4/rc}"
expect("default namespace", root.tag, ns + "openbox_config")
expect("marked as XControl's", O.MARK.strip() in text[:600], True)
expect("unmanaged kept: dock, margins, menu file",
       (root.findtext(f"{ns}dock/{ns}position"), root.findtext(f"{ns}margins/{ns}bottom"),
        root.findtext(f"{ns}menu/{ns}file")), ("TopLeft", "24", "my-menu.xml"))
expect("unmanaged kept: primaryMonitor, OSD font; MenuHeader added",
       (root.findtext(f"{ns}placement/{ns}primaryMonitor"), [f.get("place") for f in root.iter(ns + "font")]),
       ("1", ["ActiveWindow", "InactiveWindow", "MenuItem", "ActiveOnScreenDisplay", "MenuHeader"]))
frame = [m.get("button") for ctx in root.iter(ns + "context") if ctx.get("name") == "Frame"
         for m in ctx.iter(ns + "mousebind")]
expect("drag modifier switched, other modifiers kept", frame, ["A-Left", "A-Right", "C-A-Up"])
expect("double-click removed", [m.get("action") for ctx in root.iter(ns + "context") if ctx.get("name") == "Titlebar"
                                for m in ctx.iter(ns + "mousebind")], [])
expect("names written", [n.text for n in root.iter(ns + "name") if n.text in ("web", "chat")], ["web", "chat"])
expect("new binding", any(k.get("key") == "W-Return" for k in root.iter(ns + "keybind")), True)
expect("chain written nested", [k.get("key") for k in root.iter(ns + "keybind")][:4], ["W-e", "A-F4", "C-a", "t"])
expect("no stray namespaces", "ns0:" in text or 'xmlns=""' in text, False)
again, _s = O.import_config(text)
for key in ("theme", "title_font", "menu_font", "follow_mouse", "placement", "drag_mod", "double_click",
            "desktops", "bindings", "rules"):
    expect(f"round trip {key}", again[key], O.normalize(c)[key])
expect("written twice is the same", O.generate(again), text)
expect("one mark only", text.count(O.MARK.strip()), 1)

# double-click added where there was none
c2 = O.normalize(dict(c, double_click="Iconify"))
c2["base"] = O.generate(dict(c, double_click="none"))
expect("double-click added back", O.import_config(O.generate(c2))[0]["double_click"], "Iconify")

# a double-click the page has no word for (maximize one way only) stays as it is
vert = RC.replace('<action name="ToggleShade"/>',
                  '<action name="ToggleMaximize"><direction>vertical</direction></action>')
expect("double-click's own arguments kept", "<direction>vertical</direction>" in O.generate(O.import_config(vert)[0]),
       True)
# windows matched by their group
group = RC.replace('<application title="Picture-in-Picture">', '<application groupclass="Gimp" groupname="gimp">')
expect("group matches kept", O.import_config(O.generate(O.import_config(group)[0]))[0]["rules"][1]["match"],
       {"groupclass": "Gimp", "groupname": "gimp"})

# clicking the desktop: the menus come and go
expect("menus imported", (c["root_menu"], c["root_window_list"]), (True, False))
off = O.import_config(O.generate(O.normalize(dict(c, root_menu=False, root_window_list=False))))[0]
expect("menus off", (off["root_menu"], off["root_window_list"]), (False, False))
on = O.normalize(dict(off, root_menu=True, root_window_list=True))
back = O.import_config(O.generate(on))[0]
expect("menus back on", (back["root_menu"], back["root_window_list"]), (True, True))

desk_ctx = RC.replace('<context name="Root">', '<context name="Desktop">')
expect("menu in the Desktop context", O.import_config(desk_ctx)[0]["root_menu"], True)
expect("removed from there too", O.import_config(O.generate(O.normalize(dict(O.import_config(desk_ctx)[0],
                                                                                root_menu=False))))[0]["root_menu"],
       False)

# no namespace at all (very old rc.xml) still works
old = RC.replace(' xmlns="http://openbox.org/3.4/rc"', "")
expect("no namespace", O.import_config(O.generate(O.import_config(old)[0]))[0]["theme"], "Onyx")
try:
    O.import_config("<openbox_config><theme>")
    expect("broken XML", "no error", "ValueError")
except ValueError:
    pass

# ---- autostart
auto = O.generate_autostart(c)
lines = auto.splitlines()
expect("autostart session first", lines[3].startswith(O.SESSION_LINE), True)
expect("autostart lines", lines[4:], ["nm-applet &", "if [ -x /usr/bin/foo ]; then", "foo &", "fi"])
expect("autostart line kept as is", [O.autostart_line(x) for x in ("a &", "export X=1", "b; \\", "x=1")],
       ["a &", "export X=1", "b; \\", "x=1"])

# what would break the script, or wait for ever, when sent to the background or not
expect("autostart: programs go to the background, shell syntax doesn't",
       [O.autostart_line(x) for x in ("firefox", "dolphin --daemon", "foo # note", "[ -x /bin/foo ] &&", "a |",
                                      "laptop)", "X=1 foo", 'X="a b"', "sleep 2", "foo $(bar)", "x='two", "fi",
                                      "sleep 3 && conky", "sleep 1; tint2", "exec nm-applet", "cd ~/bin && ./panel.sh",
                                      "set -x", "eval $(ssh-agent)")],
       ["firefox &", "dolphin --daemon &", "foo &   # note", "[ -x /bin/foo ] &&", "a |",
        "laptop)", "X=1 foo &", 'X="a b"', "sleep 2", "foo $(bar) &", "x='two", "fi",
        "sleep 3 && conky &", "sleep 1; tint2 &", "exec nm-applet &", "cd ~/bin && ./panel.sh &",
        "set -x", "eval $(ssh-agent)"])
expect("autostart: && at the end of a line isn't a &", O.import_autostart("[ -x /bin/foo ] &&\n  foo &\nbar&\n", set()),
       ([{"command": "[ -x /bin/foo ] &&"}, {"command": "foo"}, {"command": "bar"}], []))

# ---- keys
expect("key id", (O.key_id("W-S-e"), O.key_id("S-W-E"), O.key_id("Mod4-shift-e"), O.key_id("C-a t")),
       ("S-W-e", "S-W-e", "S-W-e", "C-a"))
expect("clash Mod4-E and W-e", O.clashes(c["bindings"]), {0: [4], 4: [0]})
chain = [{"keys": "C-a", "xml": '<keybind key="t"><action name="Close"/></keybind>'},
         {"keys": "C-a b", "xml": '<action name="Close"/>'}, {"keys": "c-A", "xml": '<keybind key="B"/>'},
         {"keys": "C-a", "xml": '<action name="Close"/>'}]
expect("chains clash when one starts the other", (O.clashes(chain[:2]), O.clashes(chain[:3]), O.clashes(chain)[0]),
       ({}, {1: [2], 2: [1]}, [3]))
expect("valid keys", [O.valid_keys(k) for k in ("W-e", "C-a t", "F1", "W-", "", "C-a -", "-x")],
       [True, True, True, False, False, False, False])
expect("simple action", (O.simple_action(c["bindings"][0]["xml"]), O.simple_action(c["bindings"][1]["xml"]),
                         O.simple_action(c["bindings"][3]["xml"]), O.simple_action(c["bindings"][2]["xml"])),
       (("Execute", "thunar"), ("Close", ""), None, None))
expect("action xml escapes", O.action_xml("Execute", 'sh -c "a < b"'),
       '<action name="Execute"><command>sh -c "a &lt; b"</command></action>')
expect("check actions", (O.check_actions('<action name="Close"/>'), O.check_actions("<action>") is not None,
                         O.check_actions("<command>x</command>") is not None, O.check_actions("") is not None),
       (None, True, True, True))
try:
    O.generate(dict(c, bindings=[{"keys": "W-x", "xml": "<action"}]))
    expect("bad binding", "no error", "ValueError")
except ValueError:
    pass
expect("write refuses a bad binding", O.write(O.normalize(dict(c, bindings=[{"keys": "W-x", "xml": "<action"}])))[0],
       False)

# ---- rules as text
expect("parse match", (O.parse_match('class="Steam" title="A b"'), O.parse_match("firefox"),
                       O.parse_match("role=browser"), O.parse_match("nonsense here"),
                       O.parse_match('title="a class=b"'), O.parse_match(O.match_text({"title": 'say "hi"'}))),
       ({"class": "Steam", "title": "A b"}, {"class": "firefox"}, {"role": "browser"}, {},
        {"title": "a class=b"}, {"title": 'say "hi"'}))
expect("parse settings", O.parse_settings("desktop=2, decor=no skip-taskbar=yes size=3"),
       ({"desktop": "2", "decor": "no", "skip_taskbar": "yes"}, ["size"]))
expect("match text", O.match_text({"class": "Steam", "title": "A b"}), 'class="Steam" title="A b"')

# ---- normalize
n = O.normalize({"desktops": 99, "title_layout": "nlimcx", "placement": "Nope", "focus_delay": "x",
                 "rules": [{"match": {}}, {"match": {"class": "a"}, "settings": {"bogus": "1", "decor": "no"}}]})
expect("normalize", (n["desktops"], n["title_layout"], n["placement"], n["focus_delay"], n["rules"]),
       (10, "NLIMC", "Smart", 200, [{"match": {"class": "a"}, "settings": {"decor": "no"}, "raw": ""}]))
n = O.normalize({"placement": "undermouse", "double_click": "toggleshade", "rules": [{"match": ["a"]}, "x"]})
expect("normalize: case as Openbox reads it, odd rules", (n["placement"], n["double_click"], n["rules"]),
       ("UnderMouse", "ToggleShade", []))
expect("defaults don't share lists", O.normalize({})["rules"] is O.DEFAULT["rules"], False)

# ---- files on disk: taking over, writing, restoring
os.makedirs(O.config_dir())
with open(O.target(), "w") as f:
    f.write(RC)
with open(O.autostart_path(), "w") as f:
    f.write(AUTOSTART)
expect("previous before", O.previous(), (O.target(), O.autostart_path()))
cfg = O.normalize(dict(c, enabled=True))
expect("write", O.write(cfg), (True, []))
expect("ours now", (O.is_ours(), O.is_ours(O.autostart_path())), (True, True))
expect("backups kept", [open(p + ".before-xcontrol").read() for p in (O.target(), O.autostart_path())],
       [RC, AUTOSTART])
expect("previous after", O.previous(), (O.target() + ".before-xcontrol", O.autostart_path() + ".before-xcontrol"))
mtime = os.stat(O.target()).st_mtime_ns
O.write(cfg)
expect("unchanged: not rewritten", os.stat(O.target()).st_mtime_ns, mtime)
expect("restore", O.restore(), True)
expect("restored", (open(O.target()).read(), open(O.autostart_path()).read()), (RC, AUTOSTART))
expect("ours kept aside", os.path.exists(O.target() + ".xcontrol"), True)
os.remove(O.target())
os.remove(O.autostart_path())
O.write(cfg)
expect("restore without a previous config: Openbox's defaults", (O.restore(), os.path.exists(O.target())),
       (True, False))

# an rc.xml that isn't UTF-8 is read in its own encoding; desktops are only sent to a running Openbox
with open(O.target(), "wb") as f:
    f.write(RC.replace("UTF-8", "ISO-8859-1").replace("<name>web</name>", "<name>caf\xe9</name>").encode("latin-1"))
expect("Latin-1 rc.xml", O.import_config(O.read_rc(O.target()))[0]["desktop_names"], ["caf\xe9", "chat"])
expect("desktops in a file", (O._desktops_in(O.target()), O._desktops_in(O.target() + ".none")),
       ((3, ["caf\xe9", "chat"]), None))
expect("no display: desktops not sent", O.set_desktops(2, ["a"]), False)
os.remove(O.target())

# ---- Openbox's own rc.xml as the defaults
os.makedirs(os.path.join(tmp, "xdg", "openbox"))
with open(os.path.join(tmp, "xdg", "openbox", "rc.xml"), "w") as f:
    f.write(RC.replace("Onyx", "Syscfg"))
expect("system rc.xml", O.defaults()["theme"], "Syscfg")
os.remove(os.path.join(tmp, "xdg", "openbox", "rc.xml"))
expect("built-in fallback", (O.defaults()["theme"], len(O.defaults()["bindings"]) > 5), ("Clearlooks", True))

# ---- themes
for d, name in ((os.path.join(tmp, ".themes"), "Mine"), (os.path.join(tmp, "sys", "themes"), "Bear2"),
                (os.path.join(tmp, "sys", "themes"), "GtkOnly")):
    os.makedirs(os.path.join(d, name, "openbox-3" if name != "GtkOnly" else "gtk-3.0"))
    if name != "GtkOnly":
        open(os.path.join(d, name, "openbox-3", "themerc"), "w").close()
expect("themes", O.themes(), ["Bear2", "Mine"])

# ---- the settings survive saving and loading (and other parts of XControl saving theirs)
from xcontrol import config  # noqa: E402
O.save(O.normalize(dict(c, enabled=True, theme="Saved")))
data = config.load()
data["global"]["msaa"] = 4
config.save(data)
expect("saved settings kept", (O.load()["enabled"], O.load()["theme"]), (True, "Saved"))

if bad:
    sys.exit(1)
print("check_openbox: ok")
