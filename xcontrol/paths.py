"""Install locations. `make install` substitutes @LIBDIR@ and @LOCALEDIR@;
when running from a source checkout, the freshly built files in ./build are used."""
import os

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


def config_dir():
    return os.path.join(_config_base(), "xcontrol")


def autostart_file():
    return os.path.join(_config_base(), "autostart", "xcontrol-display.desktop")


def input_autostart_file():
    return os.path.join(_config_base(), "autostart", "xcontrol-input.desktop")
