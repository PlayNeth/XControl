"""Default applications: which program opens links, folders, pictures, PDFs...

Written to ~/.config/mimeapps.list through GIO, the same file xdg-open, file managers and
browsers read. The terminal has no such standard: it's kept in ~/.config/xdg-terminals.list
(xdg-terminal-exec, which GLib uses for apps that run in a terminal) and used by XControl's
i3 config for the terminal key.
"""
import configparser
import glob
import os
import re
import shutil
import subprocess

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

CATEGORIES = [   # id, label, MIME types (the first decides what's shown as the current choice)
    ("browser", "Web browser", ["x-scheme-handler/http", "x-scheme-handler/https", "text/html",
                                "application/xhtml+xml", "x-scheme-handler/about", "x-scheme-handler/unknown"]),
    ("mail", "Email", ["x-scheme-handler/mailto", "message/rfc822"]),
    ("files", "Files and folders", ["inode/directory"]),
    ("text", "Text files", ["text/plain", "text/markdown", "text/x-log", "application/x-shellscript", "text/x-csrc",
                            "text/x-python", "application/json", "application/xml", "text/csv", "application/toml",
                            "application/x-yaml"]),
    ("images", "Pictures", ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff",
                            "image/svg+xml", "image/avif", "image/heic", "image/x-xcf", "image/jxl"]),
    ("video", "Videos", ["video/mp4", "video/x-matroska", "video/webm", "video/quicktime", "video/x-msvideo",
                         "video/mpeg", "video/ogg", "video/x-flv", "video/3gpp", "video/mp2t"]),
    ("music", "Music", ["audio/mpeg", "audio/flac", "audio/x-flac", "audio/ogg", "audio/x-vorbis+ogg",
                        "audio/opus", "audio/x-wav", "audio/wav", "audio/aac", "audio/mp4", "audio/x-m4a",
                        "audio/x-ms-wma", "audio/x-mpegurl", "audio/x-scpls"]),
    ("pdf", "PDF documents", ["application/pdf", "application/epub+zip", "image/vnd.djvu",
                              "application/postscript"]),
    ("archives", "Archives", ["application/zip", "application/x-tar", "application/x-compressed-tar",
                              "application/x-xz-compressed-tar", "application/x-zstd-compressed-tar",
                              "application/x-bzip2-compressed-tar", "application/gzip", "application/x-7z-compressed",
                              "application/vnd.rar", "application/x-rar", "application/x-xz", "application/zstd"]),
    ("office", "Office documents", ["application/vnd.oasis.opendocument.text",
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    "application/msword", "application/vnd.oasis.opendocument.spreadsheet",
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    "application/vnd.ms-excel", "application/vnd.oasis.opendocument.presentation",
                                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                    "application/rtf"]),
]
ALWAYS_ALL = {"browser"}   # set for every type in the group, even ones the app doesn't list


def _app(app_id):
    """The installed app with this desktop id, or None."""
    try:
        return Gio.DesktopAppInfo.new(app_id)
    except TypeError:   # PyGObject raises when the constructor returns NULL
        return None


def config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def mimeapps_path():
    return os.path.join(config_home(), "mimeapps.list")


def user_apps_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "applications")


def refresh_user_apps():
    """GIO only knows which file types your own apps (~/.local/share/applications: AppImages, Wine,
    Steam games, hand-made launchers) open from that folder's mimeinfo.cache, which nothing
    updates there. Rebuild it when it's missing or older than the launchers. True if rebuilt."""
    d = user_apps_dir()
    files = [f for f in glob.glob(os.path.join(d, "**", "*.desktop"), recursive=True)]
    if not files or not shutil.which("update-desktop-database"):
        return False
    cache = os.path.join(d, "mimeinfo.cache")
    try:
        cache_t = os.path.getmtime(cache)
    except OSError:
        cache_t = 0
    if cache_t and max(os.path.getmtime(f) for f in files) <= cache_t and os.path.getmtime(d) <= cache_t:
        return False
    try:
        subprocess.run(["update-desktop-database", d], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def apps_for(types):
    """Apps that open any of `types` (most types first), by desktop id."""
    count, apps = {}, {}
    for t in types:
        for a in Gio.AppInfo.get_all_for_type(t):
            aid = a.get_id()
            if not aid or not a.should_show() and not _openable(a):
                continue
            apps[aid] = a
            count[aid] = count.get(aid, 0) + 1
    return sorted(apps.values(), key=lambda a: (-count[a.get_id()], a.get_display_name().lower()))


def _openable(a):
    try:
        return bool(a.get_commandline())
    except Exception:  # noqa: BLE001
        return False


def current(types):
    a = Gio.AppInfo.get_default_for_type(types[0], False)
    return a.get_id() if a else None


def set_default(cat_id, types, app_id):
    """Make app_id the default for the group. Returns the types set."""
    app = _app(app_id)
    if app is None:
        raise ValueError(f"{app_id} isn't installed")
    supported = set(app.get_supported_types() or [])
    done = []
    for t in types:
        if cat_id in ALWAYS_ALL or t in supported or t == types[0]:
            app.set_as_default_for_type(t)
            done.append(t)
    return done


def set_default_type(mime, app_id):
    app = _app(app_id)
    if app is None:
        raise ValueError(f"{app_id} isn't installed")
    app.set_as_default_for_type(mime)


def all_types():
    """[(type, description, default app name)] of every registered type some app opens."""
    out = []
    for t in sorted(Gio.content_types_get_registered()):
        if "/" not in t or t.startswith(("application/x-extension-", "x-content/")):
            continue
        if not Gio.AppInfo.get_all_for_type(t):
            continue
        d = Gio.AppInfo.get_default_for_type(t, False)
        out.append((t, Gio.content_type_get_description(t), d.get_display_name() if d else ""))
    return out


# ---------------------------------------------------------------- broken entries
def _read(path):
    cp = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",))
    cp.optionxform = str
    try:
        cp.read(path)
    except configparser.Error:
        pass
    return cp


def broken():
    """{type: [desktop ids]} in ~/.config/mimeapps.list's defaults that aren't installed."""
    cp = _read(mimeapps_path())
    out = {}
    if not cp.has_section("Default Applications"):
        return out
    for t, value in cp.items("Default Applications"):
        missing = [a for a in value.split(";") if a.strip() and _app(a.strip()) is None]
        if missing:
            out[t] = missing
    return out


def clean_broken():
    """Remove defaults that point to apps no longer installed; returns how many types changed."""
    path = mimeapps_path()
    bad = broken()
    if not bad:
        return 0
    with open(path, errors="replace") as f:
        lines = f.read().splitlines()
    out, section = [], ""
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1]
        elif section == "Default Applications" and "=" in s:
            t, value = s.split("=", 1)
            t = t.strip()
            if t in bad:
                keep = [a for a in value.split(";") if a.strip() and a.strip() not in bad[t]]
                if not keep:
                    continue
                line = f"{t}={';'.join(keep)};"
        out.append(line)
    with open(path + ".tmp", "w") as f:
        f.write("\n".join(out) + "\n")
    os.replace(path + ".tmp", path)
    return len(bad)


def browser_env():
    """$BROWSER overrides the choice for xdg-open (and many programs); None when unset."""
    return os.environ.get("BROWSER") or None


# ---------------------------------------------------------------- terminal
def terminals():
    """Installed terminal emulators (desktop id, name)."""
    out = []
    for a in Gio.AppInfo.get_all():
        if not isinstance(a, Gio.DesktopAppInfo):
            continue
        cats = (a.get_categories() or "").split(";")
        if "TerminalEmulator" in cats and a.get_id():
            out.append((a.get_id(), a.get_display_name()))
    return sorted(set(out), key=lambda x: x[1].lower())


def terminals_list_path():
    return os.path.join(config_home(), "xdg-terminals.list")


def terminal():
    """The chosen terminal's desktop id (first line of xdg-terminals.list), or None."""
    try:
        with open(terminals_list_path(), errors="replace") as f:
            for line in f:
                s = line.split("#", 1)[0].strip()
                if s and not s.startswith("-"):
                    return s.split(":", 1)[0]
    except OSError:
        pass
    return None


def set_terminal(app_id):
    path = terminals_list_path()
    rest = []
    try:
        with open(path, errors="replace") as f:
            rest = [ln.rstrip("\n") for ln in f if ln.split("#", 1)[0].strip()
                    and ln.split("#", 1)[0].strip().split(":", 1)[0] != app_id]
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write("# Preferred terminals, first one wins (set by XControl's Default Apps page)\n")
        f.write("\n".join([app_id] + [r for r in rest if not r.startswith("#")]) + "\n")
    os.replace(path + ".tmp", path)


def terminal_command(app_id=None):
    """The command to start the chosen terminal (for the i3 config), or None."""
    app_id = app_id or terminal()
    if not app_id:
        return None
    a = _app(app_id)
    if a is None:
        return None
    cmd = a.get_commandline() or a.get_executable() or ""
    cmd = re.sub(r"\s%[fFuUdDnNickvm]", "", cmd).strip()
    return cmd or None
