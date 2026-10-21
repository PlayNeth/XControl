"""The X server: which one runs (X.Org or XLibre), the modules it loaded, and its options.

- What runs comes from the server's log (Xorg.N.log): its banner, every LoadModule/UnloadModule
  with the module's file, version and ABI class, the screens each video driver drives (and
  the /dev/dri card they're on), and every Option with where its value came from
  ((**) a config file or the command line, (==) a default, (WW) ... is not used).
- What can be set comes from the manuals: the video driver's (man 4 modesetting, amdgpu, ...)
  and xorg.conf's ServerFlags section (man 5 xorg.conf), read from their roff sources.
- XControl's own settings go to one file, /etc/X11/xorg.conf.d/30-xcontrol.conf, through a root
  helper: driver options in an OutputClass section per kernel driver (MatchDriver; X applies
  them to whichever X driver drives that GPU, without touching anyone's Device sections),
  server-wide ones in a ServerFlags section. They take effect the next time X starts.
"""
import glob
import gzip
import lzma
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from . import vrr
from .paths import LIBDIR

HELPER = os.path.join(LIBDIR, "xcontrol-xorg-helper")
CONF_DIR = "/etc/X11/xorg.conf.d"
OUR_FILE = "30-xcontrol.conf"
MAN_DIRS = ["/usr/share/man", "/usr/local/share/man"]
CONFIG_PATHS = ["/etc/X11/xorg.conf", "/etc/X11/xorg.conf.d/*.conf", "/usr/share/X11/xorg.conf.d/*.conf"]
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,47}$")
VALUE = re.compile(r"^[A-Za-z0-9_.,:+-]{0,128}$")
KDRIVER = re.compile(r"^[a-z0-9_-]{1,32}$")
# X screen prefixes that aren't the module's name
PREFIXES = {"modeset": "modesetting"}
# which X drivers suit which GPU kernel drivers (modesetting suits every one)
SUITS = {"amdgpu": {"amdgpu"}, "ati": {"radeon", "amdgpu"}, "radeon": {"radeon"}, "intel": {"i915", "xe"},
         "nouveau": {"nouveau"}, "nvidia": {"nvidia"}}
MODULE_ROOTS = ["/usr/lib/xorg/modules", "/usr/lib64/xorg/modules", "/usr/local/lib/xorg/modules"]
HIDDEN_FLAGS = ("DefaultServerLayout", "AutoAddDevices", "AutoEnableDevices")


@dataclass
class Module:
    name: str
    kind: str = "other"         # video, input, extension, other
    path: str = ""
    version: str = ""
    abi: str = ""
    unloaded: bool = False      # tried, then let go (a video driver that didn't find its hardware)
    screens: list = field(default_factory=list)    # "0", "G0" ... for video drivers in use


@dataclass
class Option:
    name: str
    type: str = ""              # boolean, integer, string ... (as the manual says)
    description: str = ""


@dataclass
class LogInfo:
    server: str = ""            # "X.Org" or "XLibre"
    version: str = ""
    modules: list = field(default_factory=list)
    used: dict = field(default_factory=dict)       # (scope, option) -> (value, source)
    unused: list = field(default_factory=list)     # [(scope, option)]
    cards: dict = field(default_factory=dict)      # video driver -> {"/dev/dri/card1", ...}
    path: str = ""


# "[    22.541] " (X.Org: seconds since it started) or "[2026-10-20 20:48:19] " (XLibre: the time)
_STAMP = re.compile(r"^\[[\d .:-]+\]\s?")
_SCOPED = re.compile(r"^\((\*\*|==|--|II|WW|EE|NI|\?\?)\) (\w+)\((G?\d+)\): (.*)$")
_OPTION = re.compile(r'^Option "([^"]+)"(?: "([^"]*)")?')


def _kind(path, abi):
    a = abi.lower()
    if "video driver" in a or "/drivers/" in path:
        return "video"
    if "xinput" in a or "/input/" in path:
        return "input"
    if "extension" in a or "/extensions/" in path:
        return "extension"
    return "other"


def parse_log(text):
    info = LogInfo()
    mods = {}
    current = loading = None
    modules_started = False      # (unnamed Options after this are input devices', not the server's)
    for raw in text.splitlines():
        line = _STAMP.sub("", raw).rstrip()
        m = re.search(r"\b(X\.Org|XLibre) X Server ([\d.]+)", line)
        if m and not info.server:
            info.server, info.version = m.group(1), m.group(2)
            continue
        m = re.match(r'^\(II\) LoadModule: "([^"]+)"', line)
        if m:
            modules_started = True
            loading = m.group(1)
            mods.setdefault(loading, Module(loading))
            mods[loading].unloaded = False
            continue
        m = re.match(r'^\(II\) Loading (\S+\.so)$', line)
        if m:      # (the file of the module just asked for)
            name = loading or re.sub(r"^lib|(_drv)?\.so$", "", os.path.basename(m.group(1)))
            mods.setdefault(name, Module(name)).path = m.group(1)
            loading = None
            continue
        m = re.match(r'^\(II\) Module (\S+): vendor=', line)
        if m:
            current = mods.setdefault(m.group(1), Module(m.group(1)))
            continue
        if current is not None and raw.lstrip().startswith(("[", "\t")) and not line.startswith("("):
            t = line.strip()
            m = re.search(r"module version = (\S+)", t)
            if m:
                current.version = m.group(1)
            m = re.match(r"ABI class: (.+?), version", t)
            if m:
                current.abi = m.group(1)
            continue
        current = None
        m = re.match(r'^\(II\) UnloadModule: "([^"]+)"', line)
        if m and m.group(1) in mods:
            mods[m.group(1)].unloaded = True
            continue
        m = _SCOPED.match(line)
        if m:
            tag, prefix, screen, rest = m.groups()
            drv = PREFIXES.get(prefix, prefix.lower())
            scope = drv
            if drv in mods and screen not in mods[drv].screens:
                mods[drv].screens.append(screen)
            o = _OPTION.match(rest)
            if o and tag in ("**", "=="):
                info.used[(scope, o.group(1).lower())] = (o.group(2) or "", "config" if tag == "**" else "default")
            u = re.match(r'^Option "([^"]+)" is not used', rest)
            if tag == "WW" and u:
                info.unused.append((scope, u.group(1)))
            c = re.search(r"(/dev/dri/card\d+)", rest)
            if c:
                info.cards.setdefault(drv, set()).add(c.group(1))
            continue
        o = re.match(r'^\((\*\*|==)\) Option "([^"]+)"(?: "([^"]*)")?$', line)
        if o and not modules_started:      # (server-wide: ServerFlags, or the command line)
            src = "config" if o.group(1) == "**" else "default"
            info.used[("server", o.group(2).lower())] = (o.group(3) or "", src)
    for mod in mods.values():
        mod.kind = _kind(mod.path, mod.abi)
    order = ["video", "input", "extension", "other"]
    info.modules = sorted(mods.values(), key=lambda x: (order.index(x.kind), x.name))
    return info


def read_log(path=None):
    path = path or vrr.server_log()
    if not path:
        return None
    try:
        with open(path, errors="replace") as f:
            info = parse_log(f.read())
    except OSError:
        return None
    info.path = path
    return info


def video_drivers(info):
    """The video drivers X is actually using (they drive a screen and weren't unloaded)."""
    return [m for m in info.modules if m.kind == "video" and not m.unloaded and m.screens]


# ---------------------------------------------------------------- the manuals
def _read_man(name, section, dirs=None):
    for d in dirs or MAN_DIRS:
        for path in glob.glob(os.path.join(d, f"man{section}", f"{name}.{section}*")):
            try:
                if path.endswith(".gz"):
                    with gzip.open(path, "rt", errors="replace") as f:
                        return f.read()
                if path.endswith((".xz", ".lzma")):
                    with lzma.open(path, "rt", errors="replace") as f:
                        return f.read()
                if path.endswith(".zst") and shutil.which("zstd"):
                    return subprocess.run(["zstd", "-dc", path], capture_output=True, text=True,
                                          timeout=10).stdout
                with open(path, errors="replace") as f:
                    return f.read()
            except (OSError, EOFError, lzma.LZMAError, subprocess.SubprocessError):
                continue
    return ""


def _plain(roff_lines):
    """Roff to plain text, roughly: enough for an option's description."""
    out = []
    for ln in roff_lines:
        if ln.startswith((".br", ".PP", ".sp", ".P ", ".LP")) or ln in (".P",):
            out.append("\n")
            continue
        if ln.startswith(".\\\"") or ln.startswith("'\\\""):
            continue
        m = re.match(r"^\.(B|I|BR|RB|BI|IB|IR|RI|SM|SB)\s+(.*)$", ln)
        if m:
            parts = re.findall(r'"([^"]*)"|(\S+)', m.group(2))
            ln = "".join(a or b for a, b in parts) if len(m.group(1)) == 2 else " ".join(a or b for a, b in parts)
        elif ln.startswith("."):
            continue
        out.append(ln)
    text = " ".join(out)
    for a, b in (("\\*q", '"'), ("\\-", "-"), ("\\(em", "—"), ("\\(en", "–"), ("\\&", ""), ("\\^", ""),
                 ("\\|", ""), ("\\e", "\\"), ("\\ ", " ")):
        text = text.replace(a, b)
    text = re.sub(r"\\f[BIRP]|\\f\(..|\\s[+-]?\d", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(p.strip() for p in text.split("\n") if p.strip())


_OPT_LINE = re.compile(r'^\.BI\s+"Option \\\*q([A-Za-z0-9_]+)\\\*q\s*\\\*q"\s*(.*?)\s*\\\*q"?\s*$')


def man_options(text, section=None):
    """The Options a manual documents ([Option]); `section`: only those under that .SH heading."""
    lines = text.splitlines()
    if section:
        start = next((i for i, ln in enumerate(lines) if ln.startswith(".SH") and section in ln.upper()), None)
        if start is None:
            return []
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(".SH")), len(lines))
        lines = lines[start + 1:end]
    opts, cur, desc = [], None, []
    for ln in lines + [".TP"]:
        m = _OPT_LINE.match(ln)
        if m or ln.startswith((".TP", ".SH", ".SS", ".IP")):
            if cur is not None:
                cur.description = _plain(desc)
                if not any(o.name == cur.name for o in opts):
                    opts.append(cur)
                cur, desc = None, []
            if m:
                cur = Option(m.group(1), m.group(2).replace("\\-", "-").strip('" '))
            continue
        if cur is not None:
            desc.append(ln)
    return opts


def driver_options(driver, dirs=None):
    return man_options(_read_man(driver, 4, dirs))


def server_flags(dirs=None):
    # (not the ones that could leave X without a keyboard and mouse, or pick another layout)
    return [o for o in man_options(_read_man("xorg.conf", 5, dirs), "SERVERFLAGS")
            if o.name not in HIDDEN_FLAGS]


# ---------------------------------------------------------------- GPUs and config files
def kernel_drivers(sysroot="/sys"):
    """{"/dev/dri/card1": "amdgpu", ...} for every GPU."""
    out = {}
    for card in sorted(glob.glob(os.path.join(sysroot, "class", "drm", "card[0-9]*"))):
        if "-" in os.path.basename(card):
            continue
        drv = os.path.join(card, "device", "driver")
        if os.path.exists(drv):
            out["/dev/dri/" + os.path.basename(card)] = os.path.basename(os.path.realpath(drv))
    return out


def our_path(conf_dir=CONF_DIR):
    return os.path.join(conf_dir, OUR_FILE)


def read_picks(conf_dir=CONF_DIR):
    """The X driver XControl's file picks for each GPU kernel driver: {kernel driver: X driver}."""
    try:
        with open(our_path(conf_dir), errors="replace") as f:
            text = f.read()
    except OSError:
        return {}
    out = {}
    for sec in re.finditer(r'Section "OutputClass"(.*?)EndSection', text, re.S):
        md = re.search(r'MatchDriver\s+"([^"]+)"', sec.group(1))
        dv = re.search(r'^\s*Driver\s+"([^"]+)"', sec.group(1), re.M)
        if md and dv:
            out[md.group(1)] = dv.group(1)
    return out


def read_ours(conf_dir=CONF_DIR):
    """XControl's file: ({kernel driver: {option: value}}, {server option: value}, x driver it was for)."""
    drivers, server, xdriver = {}, {}, ""
    try:
        with open(our_path(conf_dir), errors="replace") as f:
            text = f.read()
    except OSError:
        return drivers, server, xdriver
    m = re.search(r"^# for the X driver: (\S+)", text, re.M)
    xdriver = m.group(1) if m else ""
    for sec in re.finditer(r'Section "(OutputClass|ServerFlags)"(.*?)EndSection', text, re.S):
        body = sec.group(2)
        opts = dict(re.findall(r'^\s*Option\s+"([^"]+)"\s+"([^"]*)"', body, re.M))
        if sec.group(1) == "ServerFlags":
            server.update(opts)
        else:
            md = re.search(r'MatchDriver\s+"([^"]+)"', body)
            if md:
                drivers.setdefault(md.group(1), {}).update(opts)
    return drivers, server, xdriver


def elsewhere(conf_dir=CONF_DIR, patterns=None):
    """Options set in other config files: [(file, section, option, value)], and whether any of
    them has its own ServerFlags section (then X may not read ours)."""
    found, flags = [], []
    paths = []
    for p in patterns or CONFIG_PATHS:
        paths += sorted(glob.glob(p)) if "*" in p else ([p] if os.path.exists(p) else [])
    for path in paths:
        if os.path.basename(path) == OUR_FILE and os.path.dirname(path) == conf_dir:
            continue
        try:
            with open(path, errors="replace") as f:
                text = re.sub(r"#.*", "", f.read())
        except OSError:
            continue
        for sec in re.finditer(r'Section\s+"(\w+)"(.*?)EndSection', text, re.S | re.I):
            if sec.group(1).lower() == "serverflags":
                flags.append(path)
            for name, value in re.findall(r'^\s*Option\s+"([^"]+)"(?:\s+"([^"]*)")?', sec.group(2), re.M):
                found.append((path, sec.group(1), name, value))
    return found, flags


def file_text(drivers, server, xdriver="", picks=None):
    """What XControl's file would hold (the helper writes the same)."""
    picks = picks or {}
    lines = ["# Written by XControl (System > X server). Delete this file to undo everything here.",
             f"# for the X driver: {xdriver or '-'}"]
    for kd in sorted(set(drivers) | set(picks)):
        if not drivers.get(kd) and not picks.get(kd):
            continue
        lines += ["", 'Section "OutputClass"', f'    Identifier "XControl: {kd}"', f'    MatchDriver "{kd}"']
        if picks.get(kd):
            lines.append(f'    Driver "{picks[kd]}"')
        lines += [f'    Option "{k}" "{v}"' for k, v in drivers.get(kd, {}).items()]
        lines.append("EndSection")
    if server:
        lines += ["", 'Section "ServerFlags"'] + [f'    Option "{k}" "{v}"' for k, v in server.items()]
        lines.append("EndSection")
    return "\n".join(lines) + "\n"


def helper_args(drivers, server, xdriver="", picks=None):
    """The root helper's arguments; ValueError for anything it would refuse."""
    args = ["write", xdriver or "-"]
    if xdriver and not KDRIVER.match(xdriver):
        raise ValueError(xdriver)
    for kd, xd in sorted((picks or {}).items()):
        if not xd:
            continue
        if not KDRIVER.match(kd) or not KDRIVER.match(xd):
            raise ValueError(f"{kd}={xd}")
        args.append(f"pick:{kd}:{xd}")
    for kd, opts in sorted(drivers.items()):
        if not KDRIVER.match(kd):
            raise ValueError(kd)
        for k, v in opts.items():
            if not NAME.match(k) or not VALUE.match(v):
                raise ValueError(f"{k}={v}")
            args.append(f"drv:{kd}:{k}={v}")
    for k, v in server.items():
        if not NAME.match(k) or not VALUE.match(v):
            raise ValueError(f"{k}={v}")
        args.append(f"srv:{k}={v}")
    return args


def can_save():
    return bool(shutil.which("pkexec")) and os.path.exists(HELPER)


def save(drivers, server, xdriver="", picks=None):
    """(ok, message): XControl's X options, through the root helper (asks for the password)."""
    try:
        args = helper_args(drivers, server, xdriver, picks)
    except ValueError as e:
        return False, f"not allowed: {e}"
    try:
        r = subprocess.run(["pkexec", HELPER] + args, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if r.returncode in (126, 127) and not r.stderr.strip():
        return False, ""
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-400:]


# ---------------------------------------------------------------- choosing the X driver
def module_root(info, roots=None):
    """The module folder the running server loads from (XLibre: .../modules/xlibre-25)."""
    for m in info.modules if info else []:
        for part in ("/drivers/", "/extensions/", "/input/"):
            if part in m.path:
                return m.path.split(part)[0]
    for m in info.modules if info else []:
        if m.path:
            return os.path.dirname(m.path)
    return next((r for r in roots or MODULE_ROOTS if os.path.isdir(r)), "")


def installed_drivers(root):
    """X video drivers installed in that module folder: ["amdgpu", "modesetting", ...]."""
    found = set()
    for path in glob.glob(os.path.join(root, "drivers", "*_drv.so")):
        found.add(os.path.basename(path)[:-len("_drv.so")])
    return sorted(found)


def other_server_drivers(root, roots=None):
    """Video drivers installed for a different X server (another module folder): {name: folder}."""
    out = {}
    mine = set(installed_drivers(root))
    for base in roots or MODULE_ROOTS:
        for folder in [base] + sorted(glob.glob(os.path.join(base, "*"))):
            if os.path.normpath(folder) == os.path.normpath(root) or not os.path.isdir(os.path.join(folder, "drivers")):
                continue
            for name in installed_drivers(folder):
                if name not in mine:
                    out.setdefault(name, folder)
    return out


def choices(kdriver, installed):
    """The X drivers that can run a GPU with this kernel driver, of the installed ones."""
    out = [d for d in installed if d == "modesetting" or kdriver in SUITS.get(d, ())]
    return sorted(out, key=lambda d: (d != "modesetting", d))


def remembered():
    from . import config
    data = config.load().get("xserver") or {}
    by = data.get("by_driver") if isinstance(data.get("by_driver"), dict) else {}
    return {xd: {kd: dict(o) for kd, o in v.items() if isinstance(o, dict)}
            for xd, v in by.items() if isinstance(v, dict)}


def remember(xdriver, drivers):
    """Keep these options for that X driver, to bring back when switching back to it."""
    from . import config
    data = config.load()
    xs = data.get("xserver") if isinstance(data.get("xserver"), dict) else {}
    by = xs.get("by_driver") if isinstance(xs.get("by_driver"), dict) else {}
    by[xdriver] = drivers
    xs["by_driver"] = by
    data["xserver"] = xs
    config.save(data)
