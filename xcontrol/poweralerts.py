"""Power alerts: poweralertd, run by XControl's desktop service.

poweralertd watches every battery and power supply UPower knows (the computer's battery and
charger, a UPS, and the batteries of mice, keyboards, controllers, headsets...) and sends a
notification when one starts or stops charging, gets low or critical, or is disconnected.
Its options: -s skips what it finds at startup, -S keeps to the computer's own power
supplies, -i TYPE ignores a kind of device (once per kind).
"""
import shutil
import subprocess

DEFAULT = {"enabled": False, "skip_startup": True, "devices": True,
           "ignore": ["mouse", "keyboard"]}

# groups shown on the page -> poweralertd's device type names (upower.c)
GROUPS = {
    "mouse": ["mouse"],
    "keyboard": ["keyboard"],
    "gaming": ["gaming input"],
    "audio": ["headset", "headphones", "speakers", "other audio"],
    "phone": ["phone", "tablet", "media player", "pda", "wearable"],
    "pen": ["pen", "touchpad"],
    "other": ["remote control", "toy", "camera", "printer", "scanner", "video", "modem", "network",
              "bluetooth generic", "monitor"],
}
GROUP_ORDER = ["mouse", "keyboard", "gaming", "audio", "phone", "pen", "other"]
SERVICE = "poweralertd.service"


def normalize(c):
    out = dict(DEFAULT)
    if isinstance(c, dict):
        out.update({k: v for k, v in c.items() if k in DEFAULT})
    for k in ("enabled", "skip_startup", "devices"):
        out[k] = bool(out[k])
    ignore = out["ignore"] if isinstance(out["ignore"], list) else []
    out["ignore"] = [g for g in GROUP_ORDER if g in ignore]
    return out


def installed():
    return bool(shutil.which("poweralertd"))


def command(c):
    c = normalize(c)
    cmd = ["poweralertd"]
    if c["skip_startup"]:
        cmd.append("-s")
    if not c["devices"]:
        cmd.append("-S")
    else:
        for g in c["ignore"]:
            for t in GROUPS[g]:
                cmd += ["-i", t]
    return cmd


def service_state():
    """poweralertd's own systemd user service: (enabled, active)."""
    def ask(verb):
        try:
            r = subprocess.run(["systemctl", "--user", verb, "--quiet", SERVICE], capture_output=True, timeout=5)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    if not shutil.which("systemctl"):
        return False, False
    return ask("is-enabled"), ask("is-active")


def disable_service():
    """Turn off poweralertd's own user service, so it doesn't run twice. (ok, message)"""
    try:
        r = subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE], capture_output=True, text=True,
                           timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return r.returncode == 0, (r.stderr or "").strip()
