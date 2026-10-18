"""Read and change the X11 display layout through the xrandr CLI."""
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from .i18n import _, hz

ROTATIONS = ["normal", "left", "right", "inverted"]

_OUTPUT_RE = re.compile(
    r"^(?P<name>\S+) (?P<state>connected|disconnected)(?P<primary> primary)?"
    r"(?: (?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+))?"
    r"(?: (?P<rot>left|right|inverted|normal))?"
    r"(?:.*?\) (?P<mmw>\d+)mm x (?P<mmh>\d+)mm)?"
)
_MODE_RE = re.compile(r"^\s+(?P<mode>\d+x\d+\S*)\s+(?P<rest>.*)$")
_RATE_RE = re.compile(r"(\d+\.\d+)([ *])([ +]?)")


@dataclass
class Monitor:
    name: str
    connected: bool
    primary: bool = False
    enabled: bool = False
    x: int = 0
    y: int = 0
    rotation: str = "normal"
    mode: str = ""
    rate: str = ""
    preferred: str = ""
    modes: dict = field(default_factory=dict)  # mode -> [rates] in xrandr order
    width_mm: int = 0
    height_mm: int = 0

    def mode_size(self, mode=None):
        m = re.match(r"(\d+)x(\d+)", mode or self.mode or "")
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    def size(self):
        """Size on the desktop, taking rotation into account."""
        w, h = self.mode_size()
        return (h, w) if self.rotation in ("left", "right") else (w, h)

    def describe(self):
        if not self.enabled:
            # TRANSLATORS: a display that is connected but turned off, e.g. "HDMI-A-0 (off)"
            return _("{output} (off)").format(output=self.name)
        w, h = self.mode_size()
        return f"{self.name} — {w}×{h} @ {hz(round(float(self.rate or 0)))}"


def available():
    return shutil.which("xrandr") is not None


def session_warning():
    """Why xrandr can't drive the outputs here, or None if it can."""
    if not available():
        return _("The xrandr command was not found. Install the xorg-xrandr package.")
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or (
            os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY")):
        return _("You are in a Wayland session. xrandr only controls X11 outputs, "
                 "so use your desktop's display settings here.")
    if not os.environ.get("DISPLAY"):
        return _("No X11 display found (DISPLAY is not set).")
    return None


def parse(text):
    monitors = []
    cur = None
    for line in text.splitlines():
        m = _OUTPUT_RE.match(line)
        if m:
            cur = Monitor(name=m["name"], connected=m["state"] == "connected",
                          primary=bool(m["primary"]))
            if m["w"]:
                cur.enabled = True
                cur.x, cur.y = int(m["x"]), int(m["y"])
                cur.rotation = m["rot"] or "normal"
            if m["mmw"]:
                cur.width_mm, cur.height_mm = int(m["mmw"]), int(m["mmh"])
            monitors.append(cur)
            continue
        mm = _MODE_RE.match(line)
        if mm and "(0x" in mm["rest"]:
            # a mode in the server's pool that no output uses (printed in the
            # verbose format after all outputs): not part of any output
            cur = None
            continue
        if mm and cur is not None:
            rates = []
            for rate, cur_flag, pref_flag in _RATE_RE.findall(mm["rest"] + "  "):
                if rate not in rates:
                    rates.append(rate)
                if cur_flag == "*":
                    cur.mode, cur.rate = mm["mode"], rate
                if pref_flag == "+" and not cur.preferred:
                    cur.preferred = mm["mode"]
            if mm["mode"] in cur.modes:
                cur.modes[mm["mode"]] += [r for r in rates if r not in cur.modes[mm["mode"]]]
            else:
                cur.modes[mm["mode"]] = rates
        elif not line.startswith(" ") and not line.startswith("\t"):
            cur = None  # "Screen 0: ..." header
    for mon in monitors:
        if mon.enabled and not mon.mode and mon.modes:
            mon.mode = next(iter(mon.modes))
            mon.rate = mon.modes[mon.mode][0] if mon.modes[mon.mode] else ""
    return monitors


def _env():
    env = dict(os.environ)
    env["LC_ALL"] = "C"  # parse and pass numbers the same way in every language
    return env


def query():
    out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=10, env=_env())
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "xrandr failed")
    return parse(out.stdout)


_VMODE_RE = re.compile(r"^  (?P<name>\S+) \(0x[0-9a-f]+\)\s+(?P<clock>[\d.]+)MHz(?P<flags>.*)$")
_VH_RE = re.compile(r"^\s+h: width\s+(\d+) start\s+(\d+) end\s+(\d+) total\s+(\d+)")
_VV_RE = re.compile(r"^\s+v: height\s+(\d+) start\s+(\d+) end\s+(\d+) total\s+(\d+)")


def parse_verbose(text):
    """`xrandr --verbose` -> {output: {"edid": bytes or None, "props": {name: value},
    "modes": [{"name", "clock_khz", "h": (disp, start, end, total), "v": (...), "flags", ...}]}}"""
    out = {}
    cur = None
    in_edid = False
    edid_hex = []
    mode = None
    for line in text.splitlines():
        m = re.match(r"^(\S+) (connected|disconnected)", line)
        if m:
            if cur is not None and edid_hex:
                out[cur]["edid"] = bytes.fromhex("".join(edid_hex))
            cur, in_edid, edid_hex, mode = m.group(1), False, [], None
            out[cur] = {"edid": None, "props": {}, "modes": []}
            continue
        if cur is None:
            continue
        vm = _VMODE_RE.match(line)
        if vm:
            flags = vm.group("flags")
            mode = {"name": vm.group("name"), "clock_khz": round(float(vm.group("clock")) * 1000),
                    "hpos": "+HSync" in flags, "vpos": "+VSync" in flags,
                    "interlaced": "Interlace" in flags or "DoubleScan" in flags,
                    "current": "*current" in flags, "preferred": "+preferred" in flags}
            out[cur]["modes"].append(mode)
            continue
        if mode is not None:
            hm, vv = _VH_RE.match(line), _VV_RE.match(line)
            if hm:
                mode["h"] = tuple(int(x) for x in hm.groups())
                continue
            if vv:
                mode["v"] = tuple(int(x) for x in vv.groups())
                continue
        if in_edid:
            if re.fullmatch(r"\t\t[0-9a-fA-F]+\s*", line):
                edid_hex.append(line.strip())
                continue
            in_edid = False
        pm = re.match(r"^\t([^\t:][^:]*):\s*(.*)$", line)
        if pm:
            key, val = pm.group(1).strip(), pm.group(2).strip()
            if key == "EDID":
                in_edid = True
            else:
                out[cur]["props"][key] = val
            continue
        rm = re.match(r"^\t\t(?:range|supported):\s*(.*)$", line)
        if rm and out[cur]["props"]:
            last = list(out[cur]["props"])[-1]
            out[cur]["props"][last + " (range)"] = rm.group(1).strip()
    if cur is not None and edid_hex:
        out[cur]["edid"] = bytes.fromhex("".join(edid_hex))
    return out


def query_verbose():
    out = subprocess.run(["xrandr", "--verbose"], capture_output=True, text=True, timeout=15, env=_env())
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "xrandr --verbose failed")
    return parse_verbose(out.stdout)


def normalize_positions(monitors):
    """xrandr needs the top-left of the desktop at 0,0."""
    on = [m for m in monitors if m.connected and m.enabled]
    if not on:
        return
    dx, dy = min(m.x for m in on), min(m.y for m in on)
    for m in on:
        m.x -= dx
        m.y -= dy


def build_command(monitors):
    args = ["xrandr"]
    for m in monitors:
        if not m.connected:
            if m.enabled:  # unplugged but still holding a CRTC
                args += ["--output", m.name, "--off"]
            continue
        args += ["--output", m.name]
        if m.enabled and m.mode:
            args += ["--mode", m.mode]
            # --rate makes xrandr pick *any* mode of that size with the closest rate,
            # so only pass it when this mode name really has several rates.
            if m.rate and len(m.modes.get(m.mode, [])) > 1:
                args += ["--rate", m.rate]
            args += ["--pos", f"{m.x}x{m.y}", "--rotate", m.rotation]
            if m.primary:
                args += ["--primary"]
        else:
            args += ["--off"]
    return args


def add_custom_mode(output, modeline):
    """Create the mode (if the server doesn't have it yet) and offer it on an output."""
    try:
        run(["xrandr", "--newmode"] + modeline.xrandr_args())
    except RuntimeError as e:
        if "BadName" not in str(e):  # BadName = a mode with this name already exists
            raise
    run(["xrandr", "--addmode", output, modeline.name])


def remove_custom_mode(output, name):
    run(["xrandr", "--delmode", output, name])
    try:
        run(["xrandr", "--rmmode", name])
    except RuntimeError:
        pass  # still used by another output


def run(args):
    out = subprocess.run(args, capture_output=True, text=True, timeout=30, env=_env())
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"xrandr exited with {out.returncode}")
