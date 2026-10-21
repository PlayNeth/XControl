"""Carry saved per-output settings across X output renames.

The same connector has a different X name depending on the X driver:

    kernel     modesetting   amdgpu / radeon   intel
    DP-1       DP-1          DisplayPort-0     DP1 / DP-1
    HDMI-A-1   HDMI-1        HDMI-A-0          HDMI1 / HDMI-1
    VGA-1      VGA-1         VGA-0             VGA1 / VGA-1

Settings are saved under the X name, so switching drivers would orphan them.
migrate() renames saved entries whose output no longer exists to the current
output on the same kernel connector.
"""
import re

# X driver type names -> kernel type names
_TYPES = {
    "DP": "DP", "DisplayPort": "DP", "HDMI": "HDMI-A", "HDMI-A": "HDMI-A", "HDMI-B": "HDMI-B",
    "VGA": "VGA", "DVI-I": "DVI-I", "DVI-D": "DVI-D", "DVI-A": "DVI-A", "DVI": "DVI-D",
    "LVDS": "LVDS", "eDP": "eDP", "Composite": "Composite", "S-video": "SVIDEO", "SVIDEO": "SVIDEO",
    "Component": "Component", "DIN": "DIN", "TV": "TV", "CTV": "TV", "Virtual": "Virtual",
    "DSI": "DSI", "DPI": "DPI", "USB": "USB",
}
# drivers that count from 0 (xf86-video-amdgpu, xf86-video-ati)
_ZERO_BASED = {"DisplayPort", "HDMI-A", "HDMI-B", "DVI-I", "DVI-D", "DVI-A", "VGA", "LVDS", "eDP",
               "S-video", "Composite", "Component", "CTV", "DIN", "TV", "Virtual"}
# names only those drivers use, so never counted from 1
_ONLY_ZERO_BASED = {"DisplayPort", "HDMI-A", "S-video", "CTV"}


def kernel_candidates(name):
    """Kernel connector names an X output name may refer to."""
    m = re.fullmatch(r"(.+?)(-?)(\d+)", name)
    if not m or m.group(1) not in _TYPES:
        return set()
    xtype, dash, n = m.group(1), m.group(2), int(m.group(3))
    ktype = _TYPES[xtype]
    out = set()
    if n >= 1 and xtype not in _ONLY_ZERO_BASED:
        out.add(f"{ktype}-{n}")                    # modesetting, intel: counted from 1
    if dash and xtype in _ZERO_BASED:
        out.add(f"{ktype}-{n + 1}")                # amdgpu / radeon: counted from 0
    return out


def migrate(display, current):
    """Rename entries in config["display"] for outputs that no longer exist.
    `current` maps current X output names to kernel connector names.
    Returns {old: new} for what was renamed."""
    renames = {}
    by_kernel = {}
    for xname, kname in current.items():
        if kname:
            by_kernel.setdefault(kname, []).append(xname)

    for old in sorted(_stored(display)):
        if old in current:
            continue
        targets = {x for k in kernel_candidates(old) for x in by_kernel.get(k, [])}
        if len(targets) != 1:
            continue
        new = targets.pop()
        if new in display["custom_modes"] or new in display["edid_ignored"] or new in renames.values():
            continue  # the new name already has its own settings; leave both alone
        renames[old] = new

    if renames:
        display["custom_modes"] = {renames.get(k, k): v for k, v in display["custom_modes"].items()}
        display["edid_ignored"] = [renames.get(o, o) for o in display["edid_ignored"]]
        cmd = list(display["command"])
        for i in range(1, len(cmd)):
            if cmd[i - 1] == "--output" and cmd[i] in renames:
                cmd[i] = renames[cmd[i]]
        display["command"] = cmd
    return renames


def _command_outputs(cmd):
    return [cmd[i] for i in range(1, len(cmd)) if cmd[i - 1] == "--output"]


def _stored(display):
    """Output names the saved settings refer to."""
    return set(display["custom_modes"]) | set(display["edid_ignored"]) | set(_command_outputs(display["command"]))


def current_outputs():
    """{X output name: kernel connector name} for connected outputs, matched by EDID."""
    from . import monitor_info
    return {r.x_name: r.drm_name for r in monitor_info.collect() if r.x_name}


def migrate_saved(connected=None):
    """Load, migrate and save the config. Returns the renames (may be empty).
    `connected`: the connected X outputs, when known; if every saved name is among them
    there is nothing to rename, which saves reading every monitor's EDID."""
    from . import config
    if connected is not None and _stored(config.load()["display"]) <= set(connected):
        return {}
    try:
        current = current_outputs()
    except Exception:  # noqa: BLE001 - no X, no sysfs: nothing to do
        return {}
    if not current:
        return {}
    data = config.load()
    renames = migrate(data["display"], current)
    if renames:
        config.save(data)
    return renames
