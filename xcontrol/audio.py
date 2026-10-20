"""Sound beyond the volume: PipeWire and WirePlumber.

Live changes go through pactl (default devices, profiles, ports) and PipeWire's "settings"
metadata (sample rate, buffer size). What has to last is written to drop-in files that only
XControl writes:
  ~/.config/pipewire/pipewire.conf.d/50-xcontrol.conf          sample rate, buffer size
  ~/.config/pipewire/pipewire-pulse.conf.d/50-xcontrol.conf    the same for PulseAudio programs
  ~/.config/wireplumber/wireplumber.conf.d/50-xcontrol.conf    names, hidden devices, no sleeping
      (WirePlumber 0.5; 0.4 gets main.lua.d/51-xcontrol.lua instead)
"""
import json
import os
import re
import shutil
import subprocess

from . import config

RATES = [44100, 48000, 88200, 96000, 176400, 192000]
LATENCY = {   # id: (quantum, min, max), in samples at 48 kHz
    "default": (None, None, None),
    "safe": (2048, 1024, 8192),
    "low": (256, 64, 1024),
    "lowest": (64, 32, 512),
}
DEFAULT = {"rate": 0, "follow_rate": False, "latency": "default", "no_suspend": False, "devices": {}}


def normalize(a):
    out = dict(DEFAULT)
    if isinstance(a, dict):
        out.update({k: v for k, v in a.items() if k in DEFAULT})
    try:
        out["rate"] = int(out["rate"]) if int(out["rate"]) in RATES else 0
    except (TypeError, ValueError):
        out["rate"] = 0
    out["follow_rate"] = bool(out["follow_rate"])
    out["no_suspend"] = bool(out["no_suspend"])
    if out["latency"] not in LATENCY:
        out["latency"] = "default"
    devs = {}
    for name, d in (out["devices"] or {}).items():
        if not isinstance(d, dict) or not re.match(r"^[\w.:+-]+$", str(name)):
            continue
        entry = {"name": str(d.get("name") or "").strip()[:80], "hidden": bool(d.get("hidden")),
                 "no_suspend": bool(d.get("no_suspend")), "priority": d.get("priority")}
        if entry["priority"] is not None:
            try:
                entry["priority"] = max(0, min(10000, int(entry["priority"])))
            except (TypeError, ValueError):
                entry["priority"] = None
        if entry["name"] or entry["hidden"] or entry["no_suspend"] or entry["priority"] is not None:
            devs[str(name)] = entry
    out["devices"] = devs
    return out


def load():
    return normalize(config.load().get("audio"))


def save(a):
    data = config.load()
    data["audio"] = a
    config.save(data)


# ---------------------------------------------------------------- what's running
def _run(args, timeout=10):
    # in the C locale: pactl prints numbers the local way (0,5 in pt_BR, which breaks its JSON)
    # and translates the field names of `pactl info`
    env = dict(os.environ, LC_ALL="C", LANGUAGE="")
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def server():
    """(name, pipewire version or None) of the sound server, or None when none answers."""
    out = _run(["pactl", "info"])
    if out is None:
        return None
    m = re.search(r"^Server Name:\s*(.+)$", out, re.M)
    name = m.group(1).strip() if m else "?"
    v = re.search(r"on PipeWire ([\d.]+)", name)
    return name, (v.group(1) if v else None)


def wireplumber_version():
    out = _run(["wireplumber", "--version"]) or ""
    m = re.search(r"libwireplumber (\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _json(kind):
    out = _run(["pactl", "-f", "json", "list", kind])
    try:
        return json.loads(out) if out else []
    except ValueError:
        return []


def outputs():
    return [d for d in _json("sinks")]


def inputs():
    return [d for d in _json("sources") if not d.get("monitor_source") and not d["name"].endswith(".monitor")]


def cards():
    return _json("cards")


def default(kind):
    return (_run(["pactl", f"get-default-{kind}"]) or "").strip()


def set_default(kind, name):
    return _run(["pactl", f"set-default-{kind}", name]) is not None


def set_profile(card, profile):
    return _run(["pactl", "set-card-profile", card, profile]) is not None


def set_port(kind, name, port):
    return _run(["pactl", f"set-{kind}-port", name, port]) is not None


def test_sound(sink):
    """Play a short sound on one output."""
    sounds = ["/usr/share/sounds/freedesktop/stereo/audio-test-signal.oga",
              "/usr/share/sounds/freedesktop/stereo/bell.oga", "/usr/share/sounds/alsa/Front_Center.wav"]
    snd = next((s for s in sounds if os.path.exists(s)), None)
    if snd and shutil.which("paplay"):
        subprocess.Popen(["paplay", f"--device={sink}", snd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    if shutil.which("pactl"):   # no sound file: a short beep through a sine source isn't available everywhere
        return False
    return False


def clock():
    """PipeWire's clock now: {"rate", "quantum", "allowed"} from the settings metadata."""
    out = _run(["pw-metadata", "-n", "settings"]) or ""
    vals = dict(re.findall(r"key:'clock\.([\w-]+)' value:'([^']*)'", out))
    try:
        return {"rate": int(vals.get("rate", 0)), "quantum": int(vals.get("quantum", 0)),
                "force_quantum": int(vals.get("force-quantum", 0)), "allowed": vals.get("allowed-rates", "")}
    except ValueError:
        return {}


# ---------------------------------------------------------------- files
def _cfg(*parts):
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, *parts)


def pipewire_path():
    return _cfg("pipewire", "pipewire.conf.d", "50-xcontrol.conf")


def pulse_path():
    return _cfg("pipewire", "pipewire-pulse.conf.d", "50-xcontrol.conf")


def wireplumber_path(ver=None):
    ver = ver or wireplumber_version() or (0, 5)
    if ver >= (0, 5):
        return _cfg("wireplumber", "wireplumber.conf.d", "50-xcontrol.conf")
    return _cfg("wireplumber", "main.lua.d", "51-xcontrol.lua")


HEADER = "# Written by XControl (Sound page); rewritten on every change.\n"


def pipewire_conf(a):
    rate = a["rate"] or None
    allowed = RATES if a["follow_rate"] else ([rate] if rate else None)
    q, qmin, qmax = LATENCY[a["latency"]]
    props = []
    if rate:
        props.append(f"    default.clock.rate = {rate}")
    if allowed:
        base = [rate or 48000] + [r for r in allowed if r != (rate or 48000)]
        props.append(f"    default.clock.allowed-rates = [ {' '.join(map(str, base))} ]")
    if q:
        props += [f"    default.clock.quantum = {q}", f"    default.clock.min-quantum = {qmin}",
                  f"    default.clock.max-quantum = {qmax}"]
    if not props:
        return None
    return HEADER + "context.properties = {\n" + "\n".join(props) + "\n}\n"


def pulse_conf(a):
    q, qmin, _qmax = LATENCY[a["latency"]]
    if not q:
        return None
    rate = a["rate"] or 48000
    return (HEADER + "pulse.properties = {\n"
            f"    pulse.min.req = {qmin}/{rate}\n    pulse.default.req = {q}/{rate}\n"
            f"    pulse.min.frag = {qmin}/{rate}\n    pulse.min.quantum = {qmin}/{rate}\n}}\n")


def _rules(a):
    """[(match key, match value or pattern, {prop: value})]."""
    rules = []
    if a["no_suspend"]:
        for prefix in ("alsa_output.", "alsa_input."):
            rules.append(("node.name", prefix + "*", {"session.suspend-timeout-seconds": 0}))
    for name, d in sorted(a["devices"].items()):
        key = "device.name" if name.startswith("alsa_card.") else "node.name"
        props = {}
        if d["name"]:
            props["device.description" if key == "device.name" else "node.description"] = d["name"]
        if d["hidden"]:
            props["device.disabled" if key == "device.name" else "node.disabled"] = True
        if d["no_suspend"] and key == "node.name":
            props["session.suspend-timeout-seconds"] = 0
        if d["priority"] is not None and key == "node.name":
            props["priority.session"] = d["priority"]
        if props:
            rules.append((key, name, props))
    return rules


def _spa(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def wireplumber_conf(a, ver=None):
    rules = _rules(a)
    if not rules:
        return None
    ver = ver or wireplumber_version() or (0, 5)
    if ver >= (0, 5):
        L = [HEADER.rstrip("\n"), "monitor.alsa.rules = ["]
        for key, value, props in rules:
            match = f'"~{value}"' if value.endswith("*") else _spa(value)
            L += ["  {", f"    matches = [ {{ {key} = {match} }} ]", "    actions = {", "      update-props = {"]
            L += [f"        {k} = {_spa(v)}" for k, v in props.items()]
            L += ["      }", "    }", "  }"]
        return "\n".join(L + ["]"]) + "\n"
    L = [HEADER.replace("#", "--", 1).rstrip("\n")]
    for key, value, props in rules:
        if value.endswith("*"):
            match = f'{{ "{key}", "matches", "{value}" }}'
        else:
            match = f'{{ "{key}", "equals", {_spa(value)} }}'
        L += ["table.insert(alsa_monitor.rules, {", f"  matches = {{ {{ {match}, }}, }},", "  apply_properties = {"]
        L += [f'    ["{k}"] = {_spa(v)},' for k, v in props.items()]
        L += ["  },", "})"]
    return "\n".join(L) + "\n"


def _put(path, text):
    """Write `text` (None removes the file). True when something changed."""
    try:
        with open(path) as f:
            old = f.read()
    except OSError:
        old = None
    if old == text:
        return False
    if text is None:
        os.remove(path)
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)
    return True


def write(a, ver=None):
    """Write the drop-ins; returns which parts changed: {"pipewire", "pulse", "wireplumber"}."""
    changed = set()
    if _put(pipewire_path(), pipewire_conf(a)):
        changed.add("pipewire")
    if _put(pulse_path(), pulse_conf(a)):
        changed.add("pulse")
    if _put(wireplumber_path(ver), wireplumber_conf(a, ver)):
        changed.add("wireplumber")
    return changed


def apply_clock_live(a):
    """Rate and buffer size take effect right away through PipeWire's settings metadata."""
    if not shutil.which("pw-metadata"):
        return False
    rate = a["rate"] or 48000
    allowed = RATES if a["follow_rate"] else [rate]
    q, qmin, qmax = LATENCY[a["latency"]]
    q, qmin, qmax = q or 1024, qmin or 32, qmax or 2048
    ok = True
    for key, value in (("clock.rate", rate), ("clock.allowed-rates", "[ " + " ".join(map(str, allowed)) + " ]"),
                       ("clock.min-quantum", qmin), ("clock.max-quantum", qmax), ("clock.quantum", q)):
        ok = _run(["pw-metadata", "-n", "settings", "0", key, str(value)]) is not None and ok
    return ok


def restart(parts):
    """Restart what reads the changed files (WirePlumber for the device rules)."""
    units = ["wireplumber"] if "wireplumber" in parts else []
    if not units:
        return True
    if shutil.which("systemctl") and _run(["systemctl", "--user", "restart", *units], timeout=30) is not None:
        return True
    return False
