"""Backups: what goes in, that restoring only writes known files, and keeps the old ones."""
import json
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, ".config"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import backup, config  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def put(path, data, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(data)


cfg = os.path.join(tmp, ".config")
config.save({"desktop": {"night": {"enabled": True}}, "future_section": {"x": 1}})
put(os.path.join(cfg, "mimeapps.list"), "[Default Applications]\ntext/html=firefox.desktop;\n")
put(os.path.join(tmp, ".face"), b"\x89PNG fake", "wb")
out = os.path.join(tmp, "b.json")
expect("files in the backup", backup.export(out), 2)
bundle = backup.read(out)
expect("settings kept whole (even sections this version doesn't know)", bundle["settings"]["future_section"], {"x": 1})

# change things, then restore
config.save({"desktop": {}})
put(os.path.join(cfg, "mimeapps.list"), "changed\n")
os.remove(os.path.join(tmp, ".face"))
bundle["files"]["home/../../etc/evil"] = {"text": "no"}          # unknown keys are ignored
bundle["files"]["config/locale.conf"] = {"text": 5}               # and damaged entries skipped
bundle["files"]["config/xdg-terminals.list"] = {"text": "kitty.desktop\n"}
bundle["files"]["home/.face"], face = {"base64": "abc"}, bundle["files"]["home/.face"]
expect("a damaged picture is skipped, the rest restored", [os.path.relpath(p, tmp) for p in backup.restore(bundle)],
       [".config/mimeapps.list", ".config/xdg-terminals.list"])
del bundle["files"]["config/xdg-terminals.list"]
os.remove(os.path.join(cfg, "xdg-terminals.list"))
os.remove(os.path.join(cfg, "mimeapps.list.before-restore"))
put(os.path.join(cfg, "mimeapps.list"), "changed\n")
bundle["files"]["home/.face"] = face
written = backup.restore(bundle)
expect("restored files", sorted(os.path.relpath(p, tmp) for p in written), [".config/mimeapps.list", ".face"])
with open(os.path.join(cfg, "mimeapps.list")) as f:
    expect("mimeapps back", f.read(), "[Default Applications]\ntext/html=firefox.desktop;\n")
with open(os.path.join(tmp, ".face"), "rb") as f:
    expect("picture back", f.read(), b"\x89PNG fake")
expect("old kept", open(os.path.join(cfg, "mimeapps.list.before-restore")).read(), "changed\n")
with open(config._path()) as f:
    expect("settings back", json.load(f)["desktop"], {"night": {"enabled": True}})
try:
    put(os.path.join(tmp, "x.json"), '{"kind": "something else"}')
    backup.read(os.path.join(tmp, "x.json"))
    expect("not a backup refused", False, True)
except ValueError:
    pass
put(os.path.join(tmp, "y.json"), '{"kind": "xcontrol-backup", "settings": {}, "files": ["x"]}')
expect("files that aren't a table are dropped", backup.read(os.path.join(tmp, "y.json"))["files"], {})
# a backup from 0.30 (no Openbox section, one bar) loads as it is; Openbox's bar starts as a copy of i3's
old = {"kind": "xcontrol-backup", "version": "0.30.0", "files": {},
       "settings": {"i3": {"enabled": False}, "desktop": {"bar": {"enabled": True, "height": 31}}}}
backup.restore(old)
from xcontrol import desktop  # noqa: E402
loaded = desktop.load()
expect("old backup: the bar's settings", (loaded["bar"]["height"], loaded["bar_openbox"]["height"]), (31, 31))
expect("old backup: no Openbox section invented", "openbox" in config.load(), False)

print("check_backup:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
