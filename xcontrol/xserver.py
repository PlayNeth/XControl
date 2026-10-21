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
OUR_FILE = "30-xcontrol.conf"          # options: later classes override earlier ones, so late
DRIVER_FILE = "00-xcontrol-driver.conf"  # the driver: X uses the first Device section it reads
BUSID = re.compile(r"^PCI:\d{1,3}(@\d{1,5})?:\d{1,2}:\d$")
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
    abi_version: str = ""       # "28.1"
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
    names: dict = field(default_factory=dict)      # (scope, option) -> the option as the config spells it
    unused: list = field(default_factory=list)     # [(scope, option)]
    cards: dict = field(default_factory=dict)      # video driver -> {"/dev/dri/card1", ...}
    device: str = ""            # the Device section X used for its screen
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
    info.device = device_used(text)
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
            m = re.match(r"ABI class: (.+?), version ([\d.]+)", t)
            if m:
                current.abi, current.abi_version = m.group(1), m.group(2)
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
                info.names[(scope, o.group(1).lower())] = o.group(1)
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
            info.names[("server", o.group(2).lower())] = o.group(2)
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


def busid(card, sysroot="/sys"):
    """X's BusID for a /dev/dri/cardN on PCI ("PCI:48:0:0", decimal), or ""."""
    dev = os.path.realpath(os.path.join(sysroot, "class", "drm", os.path.basename(card), "device"))
    m = re.match(r"^([0-9a-f]{4}):([0-9a-f]{2}):([0-9a-f]{2})\.([0-7])$", os.path.basename(dev))
    if not m:
        return ""
    dom, bus, slot, fn = (int(x, 16) for x in m.groups())
    return f"PCI:{bus}{'@' + str(dom) if dom else ''}:{slot}:{fn}"


FIRMWARE_FB = ("simpledrm", "efifb", "vgem", "vkms")


def gpus(sysroot="/sys"):
    """[(card, kernel driver, BusID)] for every GPU X could drive. The BusID is only given when there's
    more than one to tell apart: with one GPU a Device section needs none (and XLibre 25 has been
    seen crashing in its bus probe with one)."""
    found = [(card, kd) for card, kd in kernel_drivers(sysroot).items() if kd not in FIRMWARE_FB]
    many = len(found) > 1
    return [(card, kd, busid(card, sysroot) if many else "") for card, kd in found]


def driver_path(conf_dir=CONF_DIR):
    return os.path.join(conf_dir, DRIVER_FILE)


def all_ours(conf_dir=CONF_DIR):
    """Both of XControl's files, as one shell pattern (for "sudo rm ...")."""
    return os.path.join(conf_dir, "*-xcontrol*.conf")


def our_path(conf_dir=CONF_DIR):
    return os.path.join(conf_dir, OUR_FILE)


def read_picks(conf_dir=CONF_DIR):
    """The X driver XControl's driver file picks for each GPU kernel driver: {kernel driver: X driver}."""
    try:
        with open(driver_path(conf_dir), errors="replace") as f:
            text = f.read()
    except OSError:
        return {}
    out = {}
    for sec in re.finditer(r'Section "Device"(.*?)EndSection', text, re.S):
        idn = re.search(r'Identifier\s+"XControl: ([a-z0-9_-]+)', sec.group(1))
        dv = re.search(r'^\s*Driver\s+"([^"]+)"', sec.group(1), re.M)
        if idn and dv:
            out[idn.group(1)] = dv.group(1)
    return out


def device_used(info_text):
    """The Device section X used for its screen (from the log's "|-->Device" line), or ""."""
    m = re.search(r'\|-->Device "([^"]*)"', info_text or "")
    return m.group(1) if m else ""


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


def driver_file_text(picks, gpu_list):
    """What XControl's driver file would hold: a Device section per GPU whose X driver it picks
    (X uses the first Device section it reads for its screen, before guessing a driver)."""
    lines = ["# Written by XControl (System > X server): the X driver for each GPU. Delete this file to",
             "# go back to the automatic choice."]
    for card, kd, bus in gpu_list:
        if not picks.get(kd):
            continue
        lines += ["", 'Section "Device"', f'    Identifier "XControl: {kd}"', f'    Driver "{picks[kd]}"']
        if bus:
            lines.append(f'    BusID "{bus}"')
        lines.append("EndSection")
    return "\n".join(lines) + "\n"


def file_text(drivers, server, xdriver="", modulepath_fix=False):
    """What XControl's file would hold (the helper writes the same). `modulepath_fix`: give each
    OutputClass an empty ModulePath, for XLibre 25.1, which crashes on an OutputClass with neither
    Driver, Modules nor ModulePath (it reads cl->modulepath without checking it); "" just keeps
    the standard module path."""
    lines = ["# Written by XControl (System > X server). Delete this file to undo everything here.",
             f"# for the X driver: {xdriver or '-'}"]
    for kd in sorted(drivers):
        if not drivers.get(kd):
            continue
        lines += ["", 'Section "OutputClass"', f'    Identifier "XControl: {kd}"', f'    MatchDriver "{kd}"']
        if modulepath_fix:
            lines.append('    ModulePath ""')
        lines += [f'    Option "{k}" "{v}"' for k, v in drivers.get(kd, {}).items()]
        lines.append("EndSection")
    if server:
        lines += ["", 'Section "ServerFlags"'] + [f'    Option "{k}" "{v}"' for k, v in server.items()]
        lines.append("EndSection")
    return "\n".join(lines) + "\n"


def needs_modulepath_fix(info):
    """XLibre before its fix (25.x) crashes on an OutputClass without Driver/Modules/ModulePath."""
    return bool(info and info.server == "XLibre")


def helper_args(drivers, server, xdriver="", picks=None, gpu_list=None, modulepath_fix=False):
    """The root helper's arguments; ValueError for anything it would refuse."""
    args = ["write", xdriver or "-"] + (["fix:modulepath"] if modulepath_fix else [])
    if xdriver and not KDRIVER.match(xdriver):
        raise ValueError(xdriver)
    for _card, kd, bus in gpu_list or []:
        xd = (picks or {}).get(kd)
        if not xd:
            continue
        if not KDRIVER.match(kd) or not KDRIVER.match(xd) or (bus and not BUSID.match(bus)):
            raise ValueError(f"{kd}={xd} {bus}")
        args.append(f"pick:{kd}:{xd}:{bus or '-'}")
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


def save(drivers, server, xdriver="", picks=None, gpu_list=None, modulepath_fix=None):
    """(ok, message): XControl's X options, through the root helper (asks for the password)."""
    if modulepath_fix is None:
        modulepath_fix = needs_modulepath_fix(read_log())
    try:
        args = helper_args(drivers, server, xdriver, picks, gpus() if gpu_list is None else gpu_list,
                           modulepath_fix)
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
MODINFO = (0xEF23FDC5).to_bytes(4, "little") + (0x10DC023A).to_bytes(4, "little")


def module_abi(path):
    """The ABI version a module was built for, from its XF86ModuleVersionInfo (found by the
    MODINFOSTRING1/2 marker the X server puts there for this): (major, minor), or None."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    at = data.find(MODINFO)
    if at < 0 or at + 28 > len(data):
        return None
    v = int.from_bytes(data[at + 24:at + 28], "little")       # (abiversion: 24 bytes after the marker)
    return v >> 16, v & 0xFFFF


def server_video_abi(info):
    """The video driver ABI major version the running server takes (from a loaded video driver)."""
    for m in info.modules if info else []:
        if m.kind == "video" and m.abi_version and not m.unloaded:
            try:
                return int(m.abi_version.split(".")[0])
            except ValueError:
                pass
    return None


def search_dirs(info, roots=None):
    """Where the running server looks for modules, in its order. XLibre: its ABI folder
    (xlibre-25), then the older xlibre-25.0, then the plain module folder; X.Org: the plain one."""
    path = next((m.path for m in (info.modules if info else []) if "/drivers/" in m.path), "")
    if not path:
        path = next((m.path for m in (info.modules if info else []) if m.path), "")
    base = tag = ""
    if path:
        m = re.match(r"^(.*?/modules)(?:/(xlibre-[^/]+))?/", path)
        if m:
            base, tag = m.group(1), m.group(2) or ""
    if not base:
        base = next((r for r in roots or MODULE_ROOTS if os.path.isdir(r)), "")
    if not base:
        return []
    dirs = []
    if tag or (info and info.server == "XLibre"):
        if tag:
            dirs.append(os.path.join(base, tag))
        dirs += [d for d in sorted(glob.glob(os.path.join(base, "xlibre-*")), reverse=True) if d not in dirs]
    dirs.append(base)
    return dirs


def find_drivers(dirs):
    """{X driver: (file, (abi major, minor) or None)}: the first of each name in the search order,
    which is the one the server would load."""
    out = {}
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "drivers", "*_drv.so"))):
            name = os.path.basename(path)[:-len("_drv.so")]
            if name not in out:
                out[name] = (path, module_abi(path))
    return out


def loadable(found, server_abi):
    """The drivers the server can load: built for its video driver ABI (or not known)."""
    return sorted(n for n, (_p, abi) in found.items() if server_abi is None or abi is None or abi[0] == server_abi)


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
    kept = by.get(xdriver) if isinstance(by.get(xdriver), dict) else {}
    by[xdriver] = {**kept, **drivers}       # (other GPUs' options for that X driver stay)
    xs["by_driver"] = by
    data["xserver"] = xs
    config.save(data)


def device_sections(conf_dir=CONF_DIR, patterns=None):
    """Device sections in other config files, in the order X reads them: [(file, identifier, driver)],
    and Screen sections that name their own Device: [(file, screen, device)]."""
    order = []
    for p in patterns or ["/usr/share/X11/xorg.conf.d/*.conf", "/etc/X11/xorg.conf.d/*.conf", "/etc/X11/xorg.conf"]:
        order += sorted(glob.glob(p)) if "*" in p else ([p] if os.path.exists(p) else [])
    devices, screens = [], []
    for path in order:
        if os.path.basename(path) in (OUR_FILE, DRIVER_FILE) and os.path.dirname(path) == conf_dir:
            continue
        try:
            with open(path, errors="replace") as f:
                text = re.sub(r"#.*", "", f.read())
        except OSError:
            continue
        for sec in re.finditer(r'Section\s+"(\w+)"(.*?)EndSection', text, re.S | re.I):
            body = sec.group(2)
            idn = re.search(r'Identifier\s+"([^"]*)"', body)
            if sec.group(1).lower() == "device":
                dv = re.search(r'^\s*Driver\s+"([^"]*)"', body, re.M)
                devices.append((path, idn.group(1) if idn else "", dv.group(1) if dv else ""))
            elif sec.group(1).lower() == "screen":
                dev = re.search(r'^\s*Device\s+"([^"]*)"', body, re.M)
                if dev:
                    screens.append((path, idn.group(1) if idn else "", dev.group(1)))
    return devices, screens


def undocumented(info, scope, options):
    """Options X used for this scope (a driver, or "server") that the manual doesn't list, and that
    X didn't report as ignored: [(name, value)]."""
    known = {o.name.lower() for o in options}
    ignored = {n.lower() for sc, n in (info.unused if info else []) if sc == scope}
    out = []
    for (sc, low), (value, src) in sorted((info.used if info else {}).items()):
        if sc == scope and src == "config" and low not in known and low not in ignored:
            out.append((info.names.get((sc, low), low), value))
    return out
