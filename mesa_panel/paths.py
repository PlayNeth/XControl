"""Install locations. `make install` substitutes @LIBDIR@ and @LOCALEDIR@;
when running from a source checkout, the freshly built files in ./build are used."""
import os

_LIBDIR = "@LIBDIR@"
if _LIBDIR.startswith("@"):
    _LIBDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")

LIBDIR = os.environ.get("MESAPANEL_LIBDIR", _LIBDIR)

_LOCALEDIR = "@LOCALEDIR@"
if _LOCALEDIR.startswith("@"):
    _LOCALEDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "locale")

LOCALEDIR = os.environ.get("MESAPANEL_LOCALEDIR", _LOCALEDIR)
GL_SHIM = os.path.join(LIBDIR, "libmesapanel_gl.so")


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "mesa-panel")


def autostart_file():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", "mesa-panel-display.desktop")
