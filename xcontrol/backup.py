"""Backing up and restoring XControl's settings, plus the files it writes that aren't
regenerated from them (theme, default apps, terminal, language, picture). One JSON file."""
import base64
import datetime
import json
import os

from . import __version__
from .config import _path as settings_path

KIND = "xcontrol-backup"


def _home():
    return os.path.expanduser("~")


def _cfg():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(_home(), ".config")


# (key in the backup, where it lives, binary)
def files():
    c, h = _cfg(), _home()
    return [
        ("config/gtk-3.0/settings.ini", os.path.join(c, "gtk-3.0", "settings.ini"), False),
        ("config/gtk-4.0/settings.ini", os.path.join(c, "gtk-4.0", "settings.ini"), False),
        ("home/.gtkrc-2.0", os.path.join(h, ".gtkrc-2.0"), False),
        ("config/xsettingsd/xsettingsd.conf", os.path.join(c, "xsettingsd", "xsettingsd.conf"), False),
        ("home/.Xresources", os.path.join(h, ".Xresources"), False),
        ("home/.icons/default/index.theme", os.path.join(h, ".icons", "default", "index.theme"), False),
        ("config/qt5ct/qt5ct.conf", os.path.join(c, "qt5ct", "qt5ct.conf"), False),
        ("config/qt6ct/qt6ct.conf", os.path.join(c, "qt6ct", "qt6ct.conf"), False),
        ("config/mimeapps.list", os.path.join(c, "mimeapps.list"), False),
        ("config/xdg-terminals.list", os.path.join(c, "xdg-terminals.list"), False),
        ("config/locale.conf", os.path.join(c, "locale.conf"), False),
        ("home/.face", os.path.join(h, ".face"), True),
    ]


def export(path):
    """Write the backup; returns how many files went in (besides the settings)."""
    try:
        with open(settings_path()) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        settings = {}
    bundle = {"kind": KIND, "version": __version__,
              "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
              "settings": settings, "files": {}}
    for key, src, binary in files():
        try:
            with open(src, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if len(data) > 2_000_000:
            continue
        bundle["files"][key] = ({"base64": base64.b64encode(data).decode()} if binary
                                else {"text": data.decode("utf-8", errors="replace")})
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(bundle, f, indent=1)
    os.replace(tmp, path)
    return len(bundle["files"])


def read(path):
    """The backup's contents, checked. Raises ValueError for anything that isn't one."""
    with open(path) as f:
        bundle = json.load(f)
    if not isinstance(bundle, dict) or bundle.get("kind") != KIND or not isinstance(bundle.get("settings"), dict):
        raise ValueError("not an XControl backup")
    return bundle


def restore(bundle):
    """Put the settings and files back (current files are kept as *.before-restore).
    Returns the list of files written."""
    where = {key: (dest, binary) for key, dest, binary in files()}
    written = []
    os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
    _keep(settings_path())
    with open(settings_path() + ".tmp", "w") as f:
        json.dump(bundle["settings"], f, indent=2)
    os.replace(settings_path() + ".tmp", settings_path())
    for key, entry in (bundle.get("files") or {}).items():
        if key not in where or not isinstance(entry, dict):
            continue   # only the known files, never a path from the backup itself
        dest, binary = where[key]
        data = base64.b64decode(entry["base64"]) if binary and "base64" in entry else \
            entry.get("text", "").encode() if not binary and "text" in entry else None
        if data is None:
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        _keep(dest)
        with open(dest + ".tmp", "wb") as f:
            f.write(data)
        os.replace(dest + ".tmp", dest)
        written.append(dest)
    return written


def _keep(path):
    if os.path.isfile(path):
        try:
            with open(path, "rb") as src, open(path + ".before-restore", "wb") as dst:
                dst.write(src.read())
        except OSError:
            pass


def apply_restored():
    """Make the restored settings take effect without logging out."""
    from . import audio, desktop, i3cfg
    notes = []
    try:
        desktop.notify_daemon(desktop.load())
    except Exception as e:  # noqa: BLE001
        notes.append(str(e))
    try:
        ok, errors = i3cfg.refresh()
        if not ok:
            notes += errors
    except Exception as e:  # noqa: BLE001
        notes.append(str(e))
    try:
        a = audio.load()
        audio.write(a)
        audio.apply_clock_live(a)
    except Exception as e:  # noqa: BLE001
        notes.append(str(e))
    return notes
