"""Is the kernel using our EDID override for a connector, and if not, why?

Looks at what a normal user can read: the installed file, the kernel command
line, the connector's current EDID in sysfs, the mkinitcpio configuration and the
initramfs timestamps. The dialog turns the result into a message.
"""
import glob
import os
import re
from dataclasses import dataclass

FIRMWARE_DIR = "/usr/lib/firmware/edid"

# states
ACTIVE_PERMANENT = "active-permanent"   # installed, parameter set, kernel using it
ACTIVE_TEST_ONLY = "active-test-only"   # kernel using the installed file, but no parameter: gone after reboot
NOT_INSTALLED = "not-installed"         # no file for this connector (a test may still be active)
NO_PARAMETER = "no-parameter"           # file installed, parameter missing
WRONG_PARAMETER = "wrong-parameter"     # parameter names another file or connector
NOT_IN_INITRAMFS = "not-in-initramfs"   # mkinitcpio FILES= lacks the file
STALE_INITRAMFS = "stale-initramfs"     # file is newer than the initramfs
NOT_LOADED = "not-loaded"               # everything looks right, kernel still not using it (reboot pending?)


@dataclass
class Status:
    state: str
    file: str = ""
    parameter: str = ""        # the drm.edid_firmware entry that applies to this connector, if any
    expected: str = ""         # the entry that should be there


def firmware_name(connector):
    return f"mesa-panel-{connector}.bin"


def parameter_entry(cmdline, connector):
    """The drm.edid_firmware entry that applies to `connector`: 'DP-1:edid/x.bin'
    or a bare 'edid/x.bin' (all connectors). The last occurrence wins, like the kernel."""
    found = ""
    for m in re.finditer(r"(?:^|\s)(?:drm|drm_kms_helper)\.edid_firmware=(\S+)", cmdline):
        bare = ""
        specific = ""
        for item in m.group(1).split(","):
            if ":" in item:
                conn, _, path = item.partition(":")
                if conn == connector:
                    specific = item
            elif item:
                bare = item
        if specific or bare:
            found = specific or bare
    return found


def _entry_path(entry):
    return entry.split(":", 1)[1] if ":" in entry else entry


def mkinitcpio_has_file(texts, path):
    """True/False when a mkinitcpio config is present, None when there is none
    (dracut, booster, a UKI built elsewhere: we can't tell)."""
    if not texts:
        return None
    for text in texts:
        for line in text.splitlines():
            line = line.split("#", 1)[0]
            if re.match(r"\s*FILES(\+)?=", line) and path in line:
                return True
        # FILES=( on several lines
        for block in re.finditer(r"FILES\+?=\(([^)]*)\)", re.sub(r"#[^\n]*", "", text)):
            if path in block.group(1):
                return True
    return False


def check(connector, current_edid, *, firmware_dir=FIRMWARE_DIR, cmdline=None,
          mkinitcpio_texts=None, initramfs_mtimes=None):
    name = firmware_name(connector)
    path = os.path.join(firmware_dir, name)
    expected = f"{connector}:edid/{name}"
    try:
        with open(path, "rb") as f:
            installed = f.read()
        installed_mtime = os.stat(path).st_mtime
    except OSError:
        return Status(NOT_INSTALLED, expected=expected)

    if cmdline is None:
        cmdline = _read("/proc/cmdline")
    entry = parameter_entry(cmdline, connector)
    param_ok = bool(entry) and _entry_path(entry) == f"edid/{name}"
    in_use = bool(current_edid) and current_edid == installed
    status = Status("", file=path, parameter=entry, expected=expected)

    if in_use:
        status.state = ACTIVE_PERMANENT if param_ok else ACTIVE_TEST_ONLY
        return status
    if not entry:
        misplaced = re.search(r"(?:drm|drm_kms_helper)\.edid_firmware=\S*?([^\s,]*edid/" + re.escape(name) + ")",
                              cmdline)
        if misplaced:  # our file, but under another connector name
            status.parameter = misplaced.group(1)
            status.state = WRONG_PARAMETER
        else:
            status.state = NO_PARAMETER
        return status
    if not param_ok:
        status.state = WRONG_PARAMETER
        return status

    if mkinitcpio_texts is None:
        mkinitcpio_texts = [_read(p) for p in ["/etc/mkinitcpio.conf", *sorted(glob.glob("/etc/mkinitcpio.conf.d/*.conf"))]
                            if os.path.exists(p)]
    if mkinitcpio_has_file(mkinitcpio_texts, path) is False:
        status.state = NOT_IN_INITRAMFS
        return status
    if initramfs_mtimes is None:
        initramfs_mtimes = []
        for img in glob.glob("/boot/initramfs-*.img"):
            if "fallback" not in img:
                try:
                    initramfs_mtimes.append(os.stat(img).st_mtime)
                except OSError:
                    pass
    if initramfs_mtimes and min(initramfs_mtimes) < installed_mtime:
        status.state = STALE_INITRAMFS
        return status
    status.state = NOT_LOADED
    return status


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""
