"""Theming: theme discovery and the files written for each toolkit (other settings kept)."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, ".config"),
                  XDG_DATA_HOME=os.path.join(tmp, ".local", "share"),
                  XDG_DATA_DIRS=os.path.join(tmp, "usr", "share"))
os.environ.pop("DISPLAY", None)  # no X: nothing is started or merged
from xcontrol import theming as T  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def mk(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


sysdata = os.path.join(tmp, "usr", "share")
mk(f"{sysdata}/themes/Arc-Dark/gtk-2.0/gtkrc")
mk(f"{sysdata}/themes/Arc-Dark/gtk-3.0/gtk.css")
mk(f"{sysdata}/themes/Arc-Dark/gtk-4.0/gtk.css")
mk(f"{sysdata}/themes/Arc-Dark/index.theme", "[Desktop Entry]\nName=Arc Dark\n")
mk(f"{sysdata}/themes/Emacs/gtk-3.0/gtk-keys.css")             # keybindings only
mk(f"{sysdata}/themes/Raleigh/gtk-2.0/gtkrc")
mk(f"{tmp}/.themes/Arc-Dark/gtk-3.0/gtk.css")                     # user copy shadows the system one
mk(f"{sysdata}/icons/Papirus/index.theme", "[Icon Theme]\nName=Papirus\nDirectories=16x16/apps\n")
mk(f"{sysdata}/icons/hicolor/index.theme", "[Icon Theme]\nName=Hicolor\nDirectories=16x16/apps\n")
mk(f"{sysdata}/icons/Breeze_Snow/index.theme", "[Icon Theme]\nName=Breeze Snow\n")
mk(f"{sysdata}/icons/Breeze_Snow/cursors/left_ptr")
mk(f"{sysdata}/icons/default/index.theme", "[Icon Theme]\nInherits=Breeze_Snow\n")

themes = {t.name: t.toolkits for t in T.gtk_themes()}
expect("user theme wins", themes.get("Arc-Dark"), ["gtk3"])
expect("keybinding theme skipped", "Emacs" in themes, False)
expect("gtk2-only theme listed", themes.get("Raleigh"), ["gtk2"])
expect("built-in Adwaita", "gtk3" in themes.get("Adwaita", []), True)
expect("icon themes", [t.name for t in T.icon_themes()], ["Papirus"])
expect("cursor themes", [(t.name, t.title) for t in T.cursor_themes()], [("Breeze_Snow", "Breeze Snow")])
expect("current cursor from default/index.theme", T.current().cursor_theme, "Breeze_Snow")

# ---- existing user files with other settings that must survive
mk(f"{tmp}/.config/gtk-3.0/settings.ini",
   "[Settings]\ngtk-theme-name=Adwaita\ngtk-enable-animations=0\n\n[Other]\nkeep=1\n")
mk(f"{tmp}/.gtkrc-2.0", '# my rc\ngtk-theme-name="Adwaita"\ngtk-menu-images=1\n')
mk(f"{tmp}/.Xresources", "XTerm*faceName: Monospace\n")
mk(f"{tmp}/.config/xsettingsd/xsettingsd.conf", "Xft/DPI 98304\nNet/ThemeName \"Adwaita\"\n")

look = T.Look(gtk_theme="Arc-Dark", icon_theme="Papirus", cursor_theme="Breeze_Snow", cursor_size=32,
              font="Inter 10", prefer_dark=True, hint_style="hintfull", subpixel="rgb")
notes = T.apply(look, qt=False, start_xsettingsd=False)

g3 = read(f"{tmp}/.config/gtk-3.0/settings.ini")
expect("gtk3 theme", "gtk-theme-name=Arc-Dark" in g3, True)
expect("gtk3 keeps other keys", "gtk-enable-animations=0" in g3 and "[Other]\nkeep=1" in g3, True)
expect("gtk3 dark", "gtk-application-prefer-dark-theme=true" in g3, True)
expect("gtk3 cursor", "gtk-cursor-theme-name=Breeze_Snow" in g3 and "gtk-cursor-theme-size=32" in g3, True)
g4 = read(f"{tmp}/.config/gtk-4.0/settings.ini")
expect("gtk4 has no xft keys", ("gtk-theme-name=Arc-Dark" in g4, "gtk-xft" in g4), (True, False))
rc2 = read(f"{tmp}/.gtkrc-2.0")
expect("gtk2", ('gtk-theme-name="Arc-Dark"' in rc2, "gtk-menu-images=1" in rc2, rc2.startswith("# my rc")),
       (True, True, True))
expect("cursor default", read(f"{tmp}/.icons/default/index.theme"), "[Icon Theme]\nInherits=Breeze_Snow\n")
xr = read(f"{tmp}/.Xresources")
expect("xresources keeps the rest", xr.startswith("XTerm*faceName: Monospace\n"), True)
expect("xresources cursor", "Xcursor.theme: Breeze_Snow" in xr and "Xcursor.size: 32" in xr, True)
xs = read(f"{tmp}/.config/xsettingsd/xsettingsd.conf")
expect("xsettingsd keeps DPI", "Xft/DPI 98304" in xs, True)
expect("xsettingsd theme", 'Net/ThemeName "Arc-Dark"' in xs and xs.count("Net/ThemeName") == 1, True)
expect("no X: told that open apps won't update", notes, ["no-xsettingsd"])

# applying again replaces, never duplicates
look.gtk_theme, look.cursor_size = "Adwaita", 24
T.apply(look, qt=False, start_xsettingsd=False)
xr = read(f"{tmp}/.Xresources")
expect("one xresources block", xr.count(T.BLOCK_START), 1)
expect("updated size", "Xcursor.size: 24" in xr, True)
g3 = read(f"{tmp}/.config/gtk-3.0/settings.ini")
expect("one theme line", g3.count("gtk-theme-name="), 1)

real = T.gtk4_version
T.gtk4_version = lambda: (4, 24)
expect("gtk 4.20+ dark variant", T.gtk_ini_values(T.Look(prefer_dark=True), gtk4=True)
       .get("gtk-interface-color-scheme"), "dark")
expect("gtk 4.20+ default", T.gtk_ini_values(T.Look(), gtk4=True).get("gtk-interface-color-scheme"), "default")
T.gtk4_version = lambda: (4, 14)
expect("older gtk 4: key left out", "gtk-interface-color-scheme" in T.gtk_ini_values(T.Look(), gtk4=True), False)
expect("gtk 3 never gets it", "gtk-interface-color-scheme" in T.gtk_ini_values(T.Look(prefer_dark=True)), False)
T.gtk4_version = real

expect("qt font", T.qt_font("Noto Sans 10.5"), '"Noto Sans,10.5,-1,5,50,0,0,0,0,0"')

# a leftover ~/.config/gtk-4.0/gtk.css overrides every theme in GTK 4 apps
from xcontrol import appcheck  # noqa: E402
mk(f"{tmp}/.config/gtk-3.0/gtk.css", "/* nothing but a comment */\n")
mk(f"{tmp}/.config/gtk-4.0/gtk.css", "@define-color accent_bg_color #e01b24;\n")
os.makedirs(f"{tmp}/.config/gtk-4.0/assets")
expect("user css found", (bool(appcheck.user_css("gtk4")), bool(appcheck.user_css("gtk3"))), (True, False))
appcheck.disable_user_css()
expect("user css renamed", sorted(os.listdir(f"{tmp}/.config/gtk-4.0")),
       ["assets.xcontrol-disabled", "gtk.css.xcontrol-disabled", "settings.ini"])
expect("comment-only css kept", os.path.exists(f"{tmp}/.config/gtk-3.0/gtk.css"), True)

print("check_theming:", "FAILED" if bad else "ok")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
