"""Install locations. `make install` substitutes @LIBDIR@ and @LOCALEDIR@;
when running from a source checkout, the freshly built files in ./build are used."""
import os
import shutil

_LIBDIR = "@LIBDIR@"
if _LIBDIR.startswith("@"):
    _LIBDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")

LIBDIR = os.environ.get("XCONTROL_LIBDIR", _LIBDIR)

_LOCALEDIR = "@LOCALEDIR@"
if _LOCALEDIR.startswith("@"):
    _LOCALEDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "locale")

LOCALEDIR = os.environ.get("XCONTROL_LOCALEDIR", _LOCALEDIR)
GL_SHIM = os.path.join(LIBDIR, "libxcontrol_gl.so")


def _config_base():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


_migrated = False


def migrate_legacy():
    """XControl used to be called mesa-panel: carry its settings over once, and
    point its login entry at the new command."""
    global _migrated
    if _migrated:
        return
    _migrated = True
    base = _config_base()
    old, new = os.path.join(base, "mesa-panel"), os.path.join(base, "xcontrol")
    try:
        if os.path.isdir(old) and not os.path.exists(new):
            shutil.copytree(old, new)
        old_auto = os.path.join(base, "autostart", "mesa-panel-display.desktop")
        if os.path.exists(old_auto):
            new_auto = autostart_file()
            if not os.path.exists(new_auto):
                with open(old_auto) as f:
                    text = f.read()
                with open(new_auto, "w") as f:
                    f.write(text.replace("mesa-panel --apply-display", "xcontrol --apply-display")
                                .replace("Mesa Panel", "XControl"))
            os.remove(old_auto)
    except OSError:
        pass  # best effort; the user can still set things up again


def config_dir():
    migrate_legacy()
    return os.path.join(_config_base(), "xcontrol")


def autostart_file():
    return os.path.join(_config_base(), "autostart", "xcontrol-display.desktop")


def input_autostart_file():
    return os.path.join(_config_base(), "autostart", "xcontrol-input.desktop")
