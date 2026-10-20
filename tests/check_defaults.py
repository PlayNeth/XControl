"""Default apps: groups set through GIO into mimeapps.list, broken entries, the terminal (fake apps)."""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
apps = os.path.join(tmp, "share", "applications")
os.makedirs(apps)
os.makedirs(os.path.join(tmp, "config"))
os.makedirs(os.path.join(tmp, "sys"))
if os.path.isdir("/usr/share/mime"):   # the MIME database, without the system's apps
    os.symlink("/usr/share/mime", os.path.join(tmp, "sys", "mime"))
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, "config"), XDG_DATA_HOME=os.path.join(tmp, "share"),
                  XDG_DATA_DIRS=os.path.join(tmp, "sys"), XDG_CONFIG_DIRS=os.path.join(tmp, "none"))
os.environ.pop("BROWSER", None)


bindir = os.path.join(tmp, "bin")
os.makedirs(bindir)
os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")


def app(name, mime, extra=""):
    exe = os.path.join(bindir, name)
    with open(exe, "w") as f:
        f.write("#!/bin/sh\n")
    os.chmod(exe, 0o755)
    with open(os.path.join(apps, name + ".desktop"), "w") as f:
        f.write(f"[Desktop Entry]\nType=Application\nName={name.title()}\nExec={name} %U\nMimeType={mime}\n{extra}")


app("firefox", "text/html;x-scheme-handler/http;x-scheme-handler/https;")
app("chromium", "text/html;x-scheme-handler/http;x-scheme-handler/https;")
app("imv", "image/png;image/jpeg;image/gif;image/webp;")
app("gimp", "image/png;image/x-xcf;")
app("alacritty", "", "Categories=System;TerminalEmulator;\n")
app("kitty", "", "Categories=System;TerminalEmulator;\n")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import defaults as DF  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


cats = {c: t for c, _l, t in DF.CATEGORIES}
expect("own apps' cache rebuilt", DF.refresh_user_apps(), True)
expect("not again when fresh", DF.refresh_user_apps(), False)
expect("browsers offered", sorted(a.get_id() for a in DF.apps_for(cats["browser"])),
       ["chromium.desktop", "firefox.desktop"])
expect("image apps, best match first", [a.get_id() for a in DF.apps_for(cats["images"])][:1], ["imv.desktop"])
done = DF.set_default("browser", cats["browser"], "chromium.desktop")
expect("browser: every web type", set(done) >= {"x-scheme-handler/http", "x-scheme-handler/https", "text/html"}, True)
expect("current browser", DF.current(cats["browser"]), "chromium.desktop")
done = DF.set_default("images", cats["images"], "gimp.desktop")
expect("pictures: only what gimp opens", sorted(done), ["image/png", "image/x-xcf"])
with open(DF.mimeapps_path()) as f:
    text = f.read()
expect("written to mimeapps.list", "x-scheme-handler/http=chromium.desktop;" in text, True)

with open(DF.mimeapps_path()) as f:
    text = f.read()
with open(DF.mimeapps_path(), "w") as f:
    f.write(text.replace("[Default Applications]\n", "[Default Applications]\napplication/pdf=gone.desktop;\n"
                         "video/mp4=gone.desktop;imv.desktop;\n"))
expect("broken entries", DF.broken(), {"application/pdf": ["gone.desktop"], "video/mp4": ["gone.desktop"]})
expect("cleaned", DF.clean_broken(), 2)
with open(DF.mimeapps_path()) as f:
    text = f.read()
expect("broken removed, good kept", ("gone.desktop" in text, "video/mp4=imv.desktop;" in text,
                                     "x-scheme-handler/http=chromium.desktop;" in text), (False, True, True))

expect("terminals", [t for t, _n in DF.terminals()], ["alacritty.desktop", "kitty.desktop"])
expect("no terminal yet", DF.terminal(), None)
DF.set_terminal("kitty.desktop")
DF.set_terminal("alacritty.desktop")
expect("terminal chosen", DF.terminal(), "alacritty.desktop")
with open(DF.terminals_list_path()) as f:
    lines = [ln.strip() for ln in f if not ln.startswith("#")]
expect("previous one kept as fallback", lines, ["alacritty.desktop", "kitty.desktop"])
expect("terminal command", DF.terminal_command(), "alacritty")

print("check_defaults:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
