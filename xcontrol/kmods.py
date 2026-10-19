"""Kernel modules in use: what's loaded, what uses it, the devices it drives, its
parameters and their current values, and options set in modprobe.d.

Read from /proc/modules, /sys/module and modinfo; no root needed (a few parameters are
only readable by root and are shown as such). Honors XCONTROL_SYSROOT like sysinfo.
"""
import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from .paths import LIBDIR
from .sysinfo import _pci_dev, device_name, p, pci_names, read, short_vendor, unroot

HELPER = os.path.join(LIBDIR, "xcontrol-module-helper")
OUR_DIR = "/etc/modprobe.d"
VALUE_RE = re.compile(r"^[A-Za-z0-9_.,:+/-]{0,256}$")
GPU_DRIVERS = {"amdgpu", "radeon", "i915", "xe", "nouveau", "nvidia", "nvidia_drm", "nvidia_modeset"}

MODPROBE_DIRS = ("/etc/modprobe.d", "/run/modprobe.d", "/usr/local/lib/modprobe.d", "/usr/lib/modprobe.d",
                 "/lib/modprobe.d")
NOT_DEVICES = {"bind", "unbind", "new_id", "remove_id", "uevent", "module"}
UNREADABLE = object()


@dataclass
class Module:
    name: str
    size: int = 0
    refs: int = 0
    used_by: list = field(default_factory=list)
    state: str = "Live"
    builtin: bool = False


@dataclass
class Param:
    name: str
    value: object          # str, or UNREADABLE
    description: str = ""
    type: str = ""


@dataclass
class Details:
    name: str
    description: str = ""
    version: str = ""
    author: str = ""
    license: str = ""
    filename: str = ""
    depends: list = field(default_factory=list)
    firmware: list = field(default_factory=list)
    params: list = field(default_factory=list)
    devices: list = field(default_factory=list)    # (bus, address, description)
    options: list = field(default_factory=list)    # (file, line)
    holders: list = field(default_factory=list)


def norm(name):
    return name.replace("-", "_")


def parse_proc_modules(text):
    """'amdgpu 16019456 34 - Live 0x0000000000000000' -> Module."""
    out = []
    for line in text.splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        used = [u for u in f[3].split(",") if u and u != "-"]
        try:
            size, refs = int(f[1]), int(f[2])
        except ValueError:
            continue
        out.append(Module(name=f[0], size=size, refs=refs, used_by=used, state=f[4]))
    return out


def loaded():
    return parse_proc_modules(read("/proc/modules"))


def builtins(loaded_names):
    """Built-in parts of the kernel that show up in /sys/module with parameters."""
    out = []
    for d in sorted(glob.glob(p("/sys/module/*"))):
        name = os.path.basename(d)
        if name in loaded_names or not os.path.isdir(os.path.join(d, "parameters")):
            continue
        if os.path.exists(os.path.join(d, "initstate")):
            continue  # a loadable module after all
        out.append(Module(name=name, builtin=True, state="built-in"))
    return out


def modules(include_builtin=False):
    mods = loaded()
    if include_builtin:
        mods += builtins({m.name for m in mods})
    return sorted(mods, key=lambda m: m.name)


def params(name):
    out = []
    base = p(f"/sys/module/{norm(name)}/parameters")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(base, n), errors="replace") as f:
                value = f.read().strip()
        except PermissionError:
            value = UNREADABLE
        except OSError:
            value = UNREADABLE
        out.append(Param(name=n, value=value))
    return out


def parse_modinfo(text):
    """`modinfo NAME` output -> dict (lists for keys that repeat)."""
    info = {"parm": {}, "firmware": [], "depends": []}
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if key == "parm":
            pm = re.match(r"^(\w+):(.*?)(?:\s*\((\w+)\))?$", value)
            if pm:
                info["parm"][pm.group(1)] = (pm.group(2).strip(), pm.group(3) or "")
        elif key == "firmware":
            info["firmware"].append(value)
        elif key == "depends":
            info["depends"] = [d for d in value.split(",") if d]
        elif key not in info:
            info[key] = value
    return info


def modinfo(name):
    if not shutil.which("modinfo"):
        return {"parm": {}, "firmware": [], "depends": []}
    try:
        out = subprocess.run(["modinfo", name], capture_output=True, text=True, timeout=5,
                             env=dict(os.environ, LC_ALL="C")).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    return parse_modinfo(out)


def modprobe_options(name):
    """Lines in modprobe.d that concern this module: options, blacklist, install, softdep."""
    want = norm(name)
    files = {}
    for d in MODPROBE_DIRS:
        for f in sorted(glob.glob(p(f"{d}/*.conf"))):
            files.setdefault(os.path.basename(f), f)  # /etc overrides /usr/lib with the same name
    out = []
    for base in sorted(files):
        path = files[base]
        try:
            with open(path, errors="replace") as f:
                text = f.read().replace("\\\n", " ")
        except OSError:
            continue
        for line in text.splitlines():
            words = line.split("#", 1)[0].split()
            if len(words) >= 2 and words[0] in ("options", "blacklist", "install", "softdep", "remove") \
                    and norm(words[1]) == want:
                out.append((unroot(path), " ".join(words)))
    return out


def devices(name):
    """Devices bound to the module's drivers: [(bus, address, description)]."""
    out = []
    for drv in sorted(glob.glob(p(f"/sys/module/{norm(name)}/drivers/*"))):
        bus, _s, _driver = os.path.basename(drv).partition(":")
        try:
            entries = sorted(os.listdir(drv))
        except OSError:
            continue
        for e in entries:
            path = os.path.join(drv, e)
            if e in NOT_DEVICES or not os.path.islink(path):
                continue
            desc = ""
            if bus == "pci":
                vendor, device, _sv, _sd = _pci_dev(unroot(path))
                if vendor is not None:
                    vn, dn, _x, _y = pci_names(vendor, device)
                    desc = f"{short_vendor(vn)} {device_name(dn)}".strip() if dn else f"{vendor:04x}:{device:04x}"
            elif bus == "usb":
                prod = read(f"{unroot(path)}/product")
                maker = read(f"{unroot(path)}/manufacturer")
                desc = " ".join(x for x in (maker, prod) if x)
            elif bus == "hid":
                m = re.match(r"^\w+:(\w+):(\w+)\.", e)
                desc = read(f"{unroot(path)}/uevent").partition("HID_NAME=")[2].split("\n")[0] or \
                    (f"{m.group(1)}:{m.group(2)}" if m else "")
            out.append((bus, e, desc))
    return out


def holders(name):
    try:
        return sorted(os.listdir(p(f"/sys/module/{norm(name)}/holders")))
    except OSError:
        return []


def details(name):
    info = modinfo(name)
    d = Details(name=name, description=info.get("description", ""), version=info.get("version", ""),
                author=info.get("author", ""), license=info.get("license", ""),
                filename=info.get("filename", ""), depends=info.get("depends", []),
                firmware=info.get("firmware", []))
    d.version = d.version or read(f"/sys/module/{norm(name)}/version")
    d.params = params(name)
    for prm in d.params:
        desc, typ = info["parm"].get(prm.name, ("", ""))
        prm.description, prm.type = desc, typ
    d.devices = devices(name)
    d.options = modprobe_options(name)
    d.holders = holders(name)
    return d


def cmdline():
    return read("/proc/cmdline")


def as_text(d, english=False):
    """One module's details as plain text."""
    from . import i18n
    tr = i18n.ENGLISH if english else i18n.CURRENT
    _ = tr.gettext
    lines = [d.name + (f" — {d.description}" if d.description else "")]
    if d.filename:
        lines.append(f"  {d.filename}")
    if d.devices:
        lines += ["", _("Devices")] + [f"  {bus} {addr}  {desc}".rstrip() for bus, addr, desc in d.devices]
    if d.params:
        lines += ["", _("Parameters")]
        width = max(len(prm.name) for prm in d.params)
        for prm in d.params:
            value = _("(only readable by root)") if prm.value is UNREADABLE else prm.value
            lines.append(f"  {prm.name.ljust(width)}  {value}")
    if d.options:
        lines += ["", _("Set in modprobe.d")] + [f"  {line}    ({path})" for path, line in d.options]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- changing parameters
def our_file(name):
    return f"{OUR_DIR}/xcontrol-{norm(name)}.conf"


def our_values(name):
    """{param: value} from XControl's own modprobe.d file for this module."""
    out = {}
    for path, line in modprobe_options(name):
        if path == our_file(name) and line.startswith("options "):
            for item in line.split()[2:]:
                k, sep, v = item.partition("=")
                if sep:
                    out[k] = v
    return out


def other_values(name):
    """{param: (value, file)} set by other modprobe.d files."""
    out = {}
    for path, line in modprobe_options(name):
        if path != our_file(name) and line.startswith("options "):
            for item in line.split()[2:]:
                k, sep, v = item.partition("=")
                if sep:
                    out[k] = (v, path)
    return out


def cmdline_values(name, text=None):
    """{param: value} for MODULE.PARAM=VALUE on the kernel command line (these win)."""
    want = norm(name)
    out = {}
    for tok in (cmdline() if text is None else text).split():
        if tok == "--":
            break
        key, sep, value = tok.partition("=")
        mod, dot, param = key.rpartition(".")
        if sep and dot and norm(mod) == want:
            out[param] = value.strip('"')
    return out


def live_writable(name, param):
    """The kernel lets root change this one while the module runs (mode u+w)."""
    try:
        return bool(os.stat(p(f"/sys/module/{norm(name)}/parameters/{param}")).st_mode & 0o200)
    except OSError:
        return False


def is_builtin(name):
    return os.path.isdir(p(f"/sys/module/{norm(name)}")) and not os.path.exists(
        p(f"/sys/module/{norm(name)}/initstate"))


def initramfs_tool():
    for tool in ("mkinitcpio", "dracut", "update-initramfs"):
        if shutil.which(tool):
            return tool
    return None


def _mkinitcpio_conf():
    text = read("/etc/mkinitcpio.conf")
    for f in sorted(glob.glob(p("/etc/mkinitcpio.conf.d/*.conf"))):
        text += "\n" + read(unroot(f))
    return text


def loads_early(name):
    """Best guess whether the module loads from the initramfs, where modprobe.d is a copy
    made when the initramfs was built (so it has to be rebuilt)."""
    want = norm(name)
    tool = initramfs_tool()
    if tool == "mkinitcpio":
        conf = _mkinitcpio_conf()
        for m in re.finditer(r"^\s*MODULES\s*=\s*\(([^)]*)\)", conf, re.M):
            if want in {norm(x.strip("'\"")) for x in m.group(1).split()}:
                return True
        hooks = " ".join(m.group(1) for m in re.finditer(r"^\s*HOOKS\s*=\s*\(([^)]*)\)", conf, re.M))
        return want in GPU_DRIVERS and "kms" in hooks.split()
    if tool in ("dracut", "update-initramfs"):
        return want in GPU_DRIVERS
    return False


_INT = {"int": r"-?\d+", "short": r"-?\d+", "long": r"-?\d+", "llong": r"-?\d+",
        "uint": r"\d+", "ushort": r"\d+", "ulong": r"\d+", "ullong": r"\d+", "byte": r"\d+",
        "hexint": r"(0[xX][0-9a-fA-F]+|\d+)"}
_BOOL = r"([yYnN01]|on|off|true|false)"


def check_value(value, typ):
    """None when `value` is fine for a parameter of modinfo type `typ`, else a reason code:
    'chars' (not allowed here at all) or 'type'. Empty means "the module's default"."""
    if value == "":
        return None
    if not VALUE_RE.match(value):
        return "chars"
    t = (typ or "").strip()
    array = t.startswith("array of ")
    t = t[len("array of "):] if array else t
    pattern = _INT.get(t) or (_BOOL if t in ("bool", "invbool", "bint") else None)
    if pattern is None:
        return None  # charp, string or unknown: anything allowed by VALUE_RE
    full = rf"^{pattern}(,{pattern})*$" if array else rf"^{pattern}$"
    if t == "byte" and not array:
        return None if re.match(full, value) and int(value) < 256 else "type"
    return None if re.match(full, value, re.I if pattern == _BOOL else 0) else "type"


def helper_args(name, values, live=False, initramfs=False):
    """Arguments for the helper; `values` maps param -> value ('' entries are left out)."""
    args = ["apply"]
    if live:
        args.append("--live")
    if initramfs:
        args.append("--initramfs")
    args.append(norm(name))
    args += [f"{k}={v}" for k, v in sorted(values.items()) if v != ""]
    return args
