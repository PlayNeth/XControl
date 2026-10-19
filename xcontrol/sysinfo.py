"""System information: operating system, X session, processor, memory, graphics,
motherboard, storage, network, audio and sensors.

Everything comes from /proc and /sys (no root needed). The slow parts (glxinfo,
vulkaninfo, package counts) are gathered once by `slow()`; `live()` re-reads the values
that change (usage, clocks, temperatures) and is cheap enough to call every few seconds.
Set XCONTROL_SYSROOT to read a fake /proc and /sys tree (used by the tests).
"""
import glob
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from . import i18n

ROOT = os.environ.get("XCONTROL_SYSROOT", "/")
PLACEHOLDERS = {"", "to be filled by o.e.m.", "default string", "system product name", "system manufacturer",
                "o.e.m.", "oem", "not applicable", "not specified", "none", "unknown", "system version",
                "base board product name", "base board manufacturer", "type1productconfigid", "x.x"}
DISK_FS = {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "jfs", "reiserfs", "bcachefs", "zfs", "vfat", "exfat",
           "ntfs", "ntfs3", "fuseblk", "hfsplus", "nilfs2"}


def p(path):
    return os.path.join(ROOT, path.lstrip("/"))


def unroot(path):
    """A path found under ROOT, back to its real-system form (for read())."""
    return "/" + os.path.relpath(path, ROOT) if ROOT != "/" else path


def read(path, default=""):
    try:
        with open(p(path), errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def read_int(path, default=None):
    try:
        return int(read(path, "").split()[0], 0)
    except (ValueError, IndexError):
        return default


def kv_file(path, sep="="):
    out = {}
    for line in read(path).splitlines():
        k, s, v = line.partition(sep)
        if s:
            out[k.strip()] = v.strip().strip('"')
    return out


def clean(text):
    text = (text or "").strip()
    return "" if text.lower() in PLACEHOLDERS else text


# ---------------------------------------------------------------- PCI names
_PCI_CACHE = {}


def pci_names(vendor, device, sub_vendor=None, sub_device=None, ids_path=None):
    """(vendor, device, subsystem, subsystem vendor) names from hwdata's pci.ids; ids as ints."""
    key = (vendor, device, sub_vendor, sub_device)
    if key in _PCI_CACHE:
        return _PCI_CACHE[key]
    paths = [ids_path] if ids_path else [p("/usr/share/hwdata/pci.ids"), p("/usr/share/misc/pci.ids"),
                                         p("/usr/share/pci.ids")]
    v_name = d_name = s_name = ""
    sub_vendor_name = ""
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        want_v, want_d = f"{vendor:04x}", f"{device:04x}"
        want_s = f"{sub_vendor:04x} {sub_device:04x}" if sub_vendor is not None else None
        in_vendor = in_device = False
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip() or line.startswith("#"):
                    continue
                if line.startswith("C "):  # device classes follow; vendors are done
                    break
                if not line.startswith("\t"):
                    if in_vendor and not want_s:
                        break
                    in_vendor = line[:4] == want_v
                    in_device = False
                    if in_vendor:
                        v_name = line[4:].strip()
                    if want_s and sub_vendor is not None and line[:4] == f"{sub_vendor:04x}":
                        sub_vendor_name = line[4:].strip()
                    continue
                if not in_vendor:
                    continue
                if line.startswith("\t\t"):
                    if in_device and want_s and line[2:11] == want_s:
                        s_name = line[11:].strip()
                    continue
                in_device = line[1:5] == want_d
                if in_device:
                    d_name = line[5:].strip()
        break
    _PCI_CACHE[key] = (v_name, d_name, s_name, sub_vendor_name)
    return _PCI_CACHE[key]


def short_vendor(name):
    """'Advanced Micro Devices, Inc. [AMD/ATI]' -> 'AMD'."""
    m = re.search(r"\[([^\]]+)\]", name)
    if m:
        return m.group(1).split("/")[0]
    for long, short in (("Advanced Micro Devices", "AMD"), ("Intel", "Intel"), ("NVIDIA", "NVIDIA"),
                        ("Realtek", "Realtek"), ("MEDIATEK", "MediaTek"), ("Qualcomm", "Qualcomm")):
        if long.lower() in name.lower():
            return short
    words = name.split(",")[0].split()
    while len(words) > 1 and words[-1].rstrip(".").lower() in {"co", "corp", "corporation", "inc", "ltd", "limited",
                                                               "technology", "technologies", "international",
                                                               "computer", "electronics", "semiconductor", "gmbh"}:
        words.pop()
    return " ".join(words)


def device_name(name):
    """'Cezanne [Radeon Vega Series / Radeon Vega Mobile Series]' -> 'Radeon Vega Series (Cezanne)'."""
    m = re.match(r"^(.*?)\s*\[(.+)\]\s*$", name)
    if m:
        marketing = m.group(2).split(" / ")[0]
        return f"{marketing} ({m.group(1)})" if m.group(1) else marketing
    return name


def _pci_dev(devdir):
    def hexid(name):
        v = read(os.path.join(devdir, name))
        try:
            return int(v, 16)
        except ValueError:
            return None
    return hexid("vendor"), hexid("device"), hexid("subsystem_vendor"), hexid("subsystem_device")


def _driver(devdir):
    try:
        return os.path.basename(os.readlink(p(os.path.join(devdir, "driver"))))
    except OSError:
        return ""


# ---------------------------------------------------------------- data
@dataclass
class Gpu:
    card: str
    slot: str = ""
    vendor: str = ""
    name: str = ""
    maker: str = ""
    driver: str = ""
    vbios: str = ""
    vram_total: int = 0
    gtt_total: int = 0
    displays: list = field(default_factory=list)
    hwmon: str = ""
    # live
    busy: int = None
    vram_used: int = None
    sclk: str = ""
    mclk: str = ""
    temp: float = None
    power: float = None
    fan: int = None


@dataclass
class Disk:
    name: str
    model: str = ""
    size: int = 0
    kind: str = ""     # nvme, ssd, hdd, usb, sd, virtual
    removable: bool = False


@dataclass
class Mount:
    target: str
    device: str
    fstype: str
    total: int = 0
    used: int = 0


@dataclass
class Nic:
    name: str
    wireless: bool = False
    model: str = ""
    driver: str = ""
    state: str = ""
    speed: int = None


@dataclass
class Sensor:
    chip: str
    label: str
    kind: str          # temp, fan
    value: float


@dataclass
class Info:
    os: dict = field(default_factory=dict)
    kernel: str = ""
    arch: str = ""
    hostname: str = ""
    user: str = ""
    init: str = ""
    shell: str = ""
    wm: str = ""
    x_server: str = ""
    x_driver: str = ""
    cpu_model: str = ""
    cpu_cores: int = 0
    cpu_threads: int = 0
    cpu_max_mhz: int = 0
    cpu_driver: str = ""
    cpu_governor: str = ""
    cpu_epp: str = ""
    cpu_l2: str = ""
    cpu_l3: str = ""
    microcode: str = ""
    board: dict = field(default_factory=dict)
    uefi: bool = None
    secure_boot: bool = None
    gpus: list = field(default_factory=list)
    disks: list = field(default_factory=list)
    nics: list = field(default_factory=list)
    sound_cards: list = field(default_factory=list)
    sound_server: str = ""
    # slow (filled by slow())
    packages: list = field(default_factory=list)   # [(manager, count)]
    gl: dict = field(default_factory=dict)
    vulkan: list = field(default_factory=list)
    slow_done: bool = False
    # live (filled by live())
    uptime: float = 0
    cpu_usage: float = None
    cpu_mhz: int = None
    cpu_temp: float = None
    mem: dict = field(default_factory=dict)
    mounts: list = field(default_factory=list)
    sensors: list = field(default_factory=list)
    _cpu_prev: tuple = None


# ---------------------------------------------------------------- collection
def os_release():
    return kv_file("/etc/os-release") or kv_file("/usr/lib/os-release")


def _x_server_info():
    """('XLibre X Server 25.1.9', 'modesetting') from the X server's log."""
    from . import vrr
    server, driver = "", ""
    path = vrr.server_log()
    if not path:
        return server, driver
    try:
        with open(path, errors="replace") as f:
            head = f.read(400000)
    except OSError:
        return server, driver
    m = re.search(r"^\s*((?:X\.Org|XLibre|Xlibre)[^\n]*?X Server) ([\d.]+)", head, re.M)
    if m:
        server = f"{m.group(1)} {m.group(2)}"
    names = {"modeset": "modesetting", "AMDGPU": "amdgpu", "RADEON": "radeon", "intel": "intel",
             "NVIDIA": "nvidia", "NOUVEAU": "nouveau", "FBDEV": "fbdev", "VESA": "vesa"}
    for m in re.finditer(r"\((?:II|==|--|\*\*)\) (\w+)\(0\):", head):
        if m.group(1) in names:
            driver = names[m.group(1)]
            if driver == "modesetting" and re.search(r"modeset\(0\): glamor initialized", head):
                driver += " (glamor)"
            break
    return server, driver


def _window_manager():
    try:
        import gi
        gi.require_version("Gdk", "3.0")
        gi.require_version("GdkX11", "3.0")
        from gi.repository import Gdk, GdkX11
        screen = Gdk.Screen.get_default()
        if isinstance(screen, GdkX11.X11Screen):
            name = screen.get_window_manager_name()
            if name and name != "unknown":
                return name
    except (ImportError, ValueError):
        pass
    return os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION", "")


def _cpu_static(info):
    text = read("/proc/cpuinfo")
    blocks = [b for b in text.split("\n\n") if b.strip()]
    cores = set()
    for b in blocks:
        d = {}
        for line in b.splitlines():
            k, _s, v = line.partition(":")
            d[k.strip()] = v.strip()
        info.cpu_model = info.cpu_model or re.sub(r"\s+", " ", d.get("model name", d.get("Model", "")))
        info.microcode = info.microcode or d.get("microcode", "")
        cores.add((d.get("physical id", "0"), d.get("core id", d.get("processor", ""))))
    info.cpu_threads = len(blocks) or os.cpu_count() or 0
    info.cpu_cores = len(cores) or info.cpu_threads
    info.cpu_model = re.sub(r"\s+\d+-Core Processor$", "", info.cpu_model).replace("(R)", "").replace("(TM)", "")
    base = "/sys/devices/system/cpu/cpu0/cpufreq"
    mx = read_int(f"{base}/cpuinfo_max_freq")
    info.cpu_max_mhz = mx // 1000 if mx else 0
    info.cpu_driver = read(f"{base}/scaling_driver")
    info.cpu_governor = read(f"{base}/scaling_governor")
    info.cpu_epp = read(f"{base}/energy_performance_preference")
    for idx in glob.glob(p("/sys/devices/system/cpu/cpu0/cache/index*")):
        rel = unroot(idx)
        level, kind, size = read(f"{rel}/level"), read(f"{rel}/type"), read(f"{rel}/size")
        if level == "2" and kind in ("Unified", "Data"):  # one L2 per core
            size = cache_size(size)
            info.cpu_l2 = f"{size} × {info.cpu_cores}" if info.cpu_cores > 1 else size
        elif level == "3":
            info.cpu_l3 = cache_size(size)


def _gpus():
    out = []
    for card in sorted(glob.glob(p("/sys/class/drm/card[0-9]*")), key=lambda c: c):
        name = os.path.basename(card)
        if "-" in name:
            continue
        dev = f"/sys/class/drm/{name}/device"
        vendor, device, sv, sd = _pci_dev(dev)
        if vendor is None:
            continue
        g = Gpu(card=name)
        try:
            g.slot = os.path.basename(os.path.realpath(p(dev)))
        except OSError:
            pass
        vn, dn, _sn, svn = pci_names(vendor, device, sv, sd)
        g.vendor = short_vendor(vn) if vn else f"{vendor:04x}"
        g.name = device_name(dn) if dn else f"{vendor:04x}:{device:04x}"
        g.maker = short_vendor(svn) if svn and sv != vendor else ""  # e.g. Sapphire, Gigabyte
        g.driver = _driver(dev)
        g.vbios = read(f"{dev}/vbios_version")
        g.vram_total = read_int(f"{dev}/mem_info_vram_total", 0)
        g.gtt_total = read_int(f"{dev}/mem_info_gtt_total", 0)
        for conn in sorted(glob.glob(p(f"/sys/class/drm/{name}-*"))):
            if read(unroot(conn) + "/status") == "connected":
                g.displays.append(os.path.basename(conn)[len(name) + 1:])
        hw = glob.glob(p(f"{dev}/hwmon/hwmon*"))
        if hw:
            g.hwmon = unroot(hw[0])
        out.append(g)
    # the same GPU can appear as several cards (e.g. simpledrm); keep real ones
    real = [g for g in out if g.driver not in ("simple-framebuffer", "simpledrm", "efifb", "vesafb")]
    return real or out


def _disks():
    out = []
    for blk in sorted(glob.glob(p("/sys/block/*"))):
        name = os.path.basename(blk)
        if re.match(r"^(loop|ram|zram|dm-|md|sr|fd|nbd)", name):
            continue
        rel = f"/sys/block/{name}"
        size = (read_int(f"{rel}/size", 0) or 0) * 512
        if not size:
            continue
        d = Disk(name=name, size=size, removable=read(f"{rel}/removable") == "1")
        d.model = re.sub(r"\s+", " ", read(f"{rel}/device/model") or read(f"{rel}/device/name"))
        try:
            path = os.path.realpath(p(rel))
        except OSError:
            path = ""
        if name.startswith("nvme"):
            d.kind = "nvme"
        elif name.startswith("mmcblk"):
            d.kind = "sd"
        elif "/usb" in path:
            d.kind = "usb"
        elif name.startswith(("vd", "xvd")) or "/virtio" in path:
            d.kind = "virtual"
        else:
            d.kind = "hdd" if read(f"{rel}/queue/rotational") == "1" else "ssd"
        out.append(d)
    return out


def _nics():
    out = []
    for dev in sorted(glob.glob(p("/sys/class/net/*"))):
        name = os.path.basename(dev)
        rel = f"/sys/class/net/{name}"
        if name == "lo" or not os.path.exists(os.path.join(dev, "device")):
            continue  # virtual interfaces (bridges, VPNs, containers)
        n = Nic(name=name, wireless=os.path.exists(os.path.join(dev, "wireless")) or
                os.path.exists(os.path.join(dev, "phy80211")))
        n.driver = _driver(f"{rel}/device")
        vendor, device, sv, sd = _pci_dev(f"{rel}/device")
        if vendor is not None:
            vn, dn, _sn, _svn = pci_names(vendor, device)
            if dn:
                n.model = f"{short_vendor(vn)} {device_name(dn)}"
        out.append(n)
    return out


def _sound():
    cards = []
    for line in read("/proc/asound/cards").splitlines():
        m = re.match(r"^\s*\d+\s+\[[^\]]*\]:\s*(.*?)\s+-\s+(.*)$", line)
        if m:
            cards.append(m.group(2).strip())
    server = ""
    comms = set()
    for d in glob.glob("/proc/[0-9]*/comm"):
        try:
            with open(d) as f:
                comms.add(f.read().strip())
        except OSError:
            continue
    if "pipewire-pulse" in comms or ("pipewire" in comms and "pulseaudio" not in comms):
        server = "PipeWire"
    elif "pulseaudio" in comms:
        server = "PulseAudio"
    elif "jackd" in comms or "jackdbus" in comms:
        server = "JACK"
    return cards, server


def collect():
    """Everything that doesn't change while the system runs (fast part)."""
    info = Info()
    info.os = os_release()
    u = os.uname()
    info.kernel = read("/proc/sys/kernel/osrelease") or u.release
    info.arch = u.machine
    info.hostname = read("/proc/sys/kernel/hostname") or u.nodename
    try:
        import pwd
        info.user = pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError):
        info.user = os.environ.get("USER", "")
    info.init = read("/proc/1/comm")
    info.shell = os.path.basename(os.environ.get("SHELL", ""))
    if os.environ.get("DISPLAY"):
        info.wm = _window_manager()
        info.x_server, info.x_driver = _x_server_info()
    _cpu_static(info)
    info.board = {k: clean(read(f"/sys/class/dmi/id/{k}")) for k in
                  ("sys_vendor", "product_name", "product_version", "board_vendor", "board_name", "board_version",
                   "bios_vendor", "bios_version", "bios_date", "chassis_type")}
    info.uefi = os.path.isdir(p("/sys/firmware/efi"))
    if info.uefi:
        sb = glob.glob(p("/sys/firmware/efi/efivars/SecureBoot-*"))
        if sb:
            try:
                with open(sb[0], "rb") as f:
                    data = f.read()
                info.secure_boot = bool(data[-1]) if data else None
            except OSError:
                pass
    info.gpus = _gpus()
    info.disks = _disks()
    info.nics = _nics()
    info.sound_cards, info.sound_server = _sound()
    return info


def _run(args, timeout=10):
    if not shutil.which(args[0]):
        return None
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              env=dict(os.environ, LC_ALL="C")).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def parse_glxinfo(text):
    gl = {}
    for key, pat in (("renderer", r"OpenGL renderer string:\s*(.+)"),
                     ("version", r"OpenGL core profile version string:\s*(.+)"),
                     ("compat", r"OpenGL version string:\s*(.+)"),
                     ("vendor", r"OpenGL vendor string:\s*(.+)"),
                     ("unified", r"Unified memory:\s*(\w+)"),
                     ("video_memory", r"Video memory:\s*(\d+)\s*MB"),
                     ("direct", r"direct rendering:\s*(\w+)")):
        m = re.search(pat, text or "")
        if m:
            gl[key] = m.group(1).strip()
    version = gl.get("version") or gl.get("compat") or ""
    m = re.search(r"\bMesa ([\w.\-~]+)", version)
    if m:
        gl["mesa"] = m.group(1)
    gl["gl"] = version.split(" ")[0] if version else ""
    return gl


def parse_vulkaninfo(text):
    """[{'deviceName':…, 'apiVersion':…, 'driverName':…, 'driverInfo':…, 'deviceType':…}]"""
    devices, cur = [], None
    for line in (text or "").splitlines():
        if re.match(r"^GPU\d+:", line.strip()):
            cur = {}
            devices.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^\s*(\w+)\s*=\s*(.+)$", line)
        if m:
            cur[m.group(1)] = m.group(2).strip()
    return [d for d in devices if d.get("deviceType") != "PHYSICAL_DEVICE_TYPE_CPU"]


def package_counts():
    out = []
    pac = p("/var/lib/pacman/local")
    if os.path.isdir(pac):
        out.append(("pacman", sum(1 for e in os.scandir(pac) if e.is_dir())))
    status = p("/var/lib/dpkg/status")
    if os.path.exists(status):
        with open(status, errors="replace") as f:
            out.append(("dpkg", sum(1 for line in f if line.startswith("Status: install ok installed"))))
    if shutil.which("rpm") and not out:
        o = _run(["rpm", "-qa"])
        if o:
            out.append(("rpm", len(o.split())))
    if shutil.which("xbps-query") and not out:
        o = _run(["xbps-query", "-l"])
        if o:
            out.append(("xbps", len(o.splitlines())))
    flat = 0
    for d in (p("/var/lib/flatpak/app"), os.path.expanduser("~/.local/share/flatpak/app")):
        if os.path.isdir(d):
            flat += sum(1 for e in os.scandir(d) if e.is_dir())
    if flat:
        out.append(("flatpak", flat))
    return out


def slow(info):
    """Things that take a moment (run in a thread): OpenGL, Vulkan, package counts."""
    info.packages = package_counts()
    if os.environ.get("DISPLAY"):
        info.gl = parse_glxinfo(_run(["glxinfo", "-B"]) or "")
    info.vulkan = parse_vulkaninfo(_run(["vulkaninfo", "--summary"]) or "")
    if not info.gl.get("mesa"):
        out = _run(["pacman", "-Q", "mesa"])
        m = re.match(r"^mesa \d*:?([\d.]+)", out or "")
        if m:
            info.gl["mesa"] = m.group(1)
    info.slow_done = True
    return info


def _cpu_times():
    line = read("/proc/stat").splitlines()[:1]
    if not line or not line[0].startswith("cpu "):
        return None
    v = [int(x) for x in line[0].split()[1:]]
    idle = v[3] + (v[4] if len(v) > 4 else 0)
    return sum(v[:8]), idle


def _hwmon_dirs():
    for d in sorted(glob.glob(p("/sys/class/hwmon/hwmon*"))):
        yield unroot(d), read(f"{unroot(d)}/name")


def sensors():
    out = []
    for rel, chip in _hwmon_dirs():
        for f in sorted(glob.glob(p(f"{rel}/temp*_input")) + glob.glob(p(f"{rel}/fan*_input")),
                        key=lambda s: (os.path.basename(s)[:3], int(re.sub(r"\D", "", os.path.basename(s)) or 0))):
            base = os.path.basename(f)[:-len("_input")]
            v = read_int(f"{rel}/{base}_input")
            if v is None:
                continue
            kind = "temp" if base.startswith("temp") else "fan"
            if kind == "temp" and not -40000 < v < 150000:
                continue  # unconnected probe
            label = read(f"{rel}/{base}_label") or base
            out.append(Sensor(chip=chip, label=label, kind=kind, value=v / 1000 if kind == "temp" else v))
    return out


def _cpu_temp(sens):
    for chip, labels in (("k10temp", ("Tctl", "Tdie")), ("zenpower", ("Tdie", "Tctl")),
                         ("coretemp", ("Package id 0",)), ("cpu_thermal", ("temp1",)),
                         ("acpitz", ("temp1",))):
        for label in labels:
            for s in sens:
                if s.chip == chip and s.label == label:
                    return s.value
    return None


def mounts():
    out, seen = [], {}
    for line in read("/proc/self/mounts").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, target, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fstype not in DISK_FS or not dev.startswith("/"):
            continue
        if dev in seen:  # btrfs subvolumes, bind mounts: keep the shortest path
            if len(target) < len(out[seen[dev]].target):
                out[seen[dev]].target = target
            continue
        seen[dev] = len(out)
        out.append(Mount(target=target, device=dev, fstype=fstype))
    for m in out:
        try:
            st = os.statvfs(m.target)
            m.total = st.f_blocks * st.f_frsize
            m.used = (st.f_blocks - st.f_bfree) * st.f_frsize
        except OSError:
            pass
    return [m for m in out if m.total]


def live(info):
    """Refresh the values that change. Call repeatedly; CPU usage needs two calls."""
    try:
        info.uptime = float(read("/proc/uptime").split()[0])
    except (ValueError, IndexError):
        pass
    t = _cpu_times()
    if t and info._cpu_prev:
        total, idle = t[0] - info._cpu_prev[0], t[1] - info._cpu_prev[1]
        info.cpu_usage = max(0.0, min(100.0, 100.0 * (1 - idle / total))) if total > 0 else None
    info._cpu_prev = t
    freqs = [read_int(unroot(f)) for f in glob.glob(p("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"))]
    freqs = [f for f in freqs if f]
    info.cpu_mhz = max(freqs) // 1000 if freqs else None
    mi = {k: int(v.split()[0]) * 1024 for k, v in kv_file("/proc/meminfo", ":").items() if v.split()}
    info.mem = mi
    info.sensors = sensors()
    info.cpu_temp = _cpu_temp(info.sensors)
    for g in info.gpus:
        dev = f"/sys/class/drm/{g.card}/device"
        g.busy = read_int(f"{dev}/gpu_busy_percent")
        g.vram_used = read_int(f"{dev}/mem_info_vram_used")
        g.sclk = _dpm_current(read(f"{dev}/pp_dpm_sclk"))
        g.mclk = _dpm_current(read(f"{dev}/pp_dpm_mclk"))
        if g.hwmon:
            t = read_int(f"{g.hwmon}/temp1_input")
            g.temp = t / 1000 if t is not None else None
            pw = read_int(f"{g.hwmon}/power1_average")
            if pw is None:
                pw = read_int(f"{g.hwmon}/power1_input")
            g.power = pw / 1e6 if pw is not None else None
            g.fan = read_int(f"{g.hwmon}/fan1_input")
            if not g.sclk:
                f = read_int(f"{g.hwmon}/freq1_input")
                g.sclk = f"{f // 1000000} MHz" if f else ""
    info.mounts = mounts()
    return info


def _dpm_current(text):
    for line in text.splitlines():
        if line.rstrip().endswith("*"):
            m = re.search(r"(\d+)\s*Mhz", line, re.I)
            return f"{m.group(1)} MHz" if m else ""
    return ""


# ---------------------------------------------------------------- presentation
def gib(n, tr):
    """Memory and space: GiB, or MiB below 1 GiB."""
    if n < 1024 ** 3:
        return f"{tr.num(n / 1024 ** 2, 0)} MiB"
    return f"{tr.num(n / 1024 ** 3, 1)} GiB"


def size_si(n, tr):
    """Drive sizes the way they're sold: 500 GB, 2 TB."""
    if n >= 1e12:
        v = n / 1e12
        return f"{tr.num(v, 0 if abs(v - round(v)) < 0.05 else 1)} TB"
    if n >= 1e9:
        return f"{tr.num(n / 1e9, 0)} GB"
    return f"{tr.num(n / 1e6, 0)} MB"


def cache_size(text):
    """'2048K' -> '2 MiB', '512K' -> '512 KiB'."""
    m = re.match(r"^(\d+)\s*([KMG])?", text or "")
    if not m:
        return text
    kib = int(m.group(1)) * {None: 1 / 1024, "K": 1, "M": 1024, "G": 1024 ** 2}[m.group(2)]
    return f"{kib // 1024:g} MiB" if kib >= 1024 and kib % 1024 == 0 else f"{kib:g} KiB"


def duration(seconds, tr):
    _ = tr.gettext
    d, rest = divmod(int(seconds), 86400)
    h, rest = divmod(rest, 3600)
    m = rest // 60
    text = _("{h} h {m} min").format(h=h, m=f"{m:02d}") if h else _("{m} min").format(m=m)
    if d:
        text = tr.ngettext("{n} day", "{n} days", d).format(n=d) + ", " + text
    return text


def describe(info, tr=None, private=True):
    """[(section id, title, [(label, value), ...]), ...]. `private` False leaves out the
    host and user names (for copying into bug reports)."""
    tr = tr or i18n.CURRENT
    _ = tr.gettext
    num = tr.num
    checking = _("Checking…")
    sections = []

    # ---- system
    rows = []
    osr = info.os
    distro = osr.get("PRETTY_NAME") or osr.get("NAME") or _("Unknown")
    if osr.get("BUILD_ID") and osr.get("BUILD_ID") != "rolling" and osr.get("BUILD_ID") not in distro:
        distro += f" ({osr['BUILD_ID']})"
    rows.append((_("Distribution"), distro))
    rows.append((_("Kernel"), f"Linux {info.kernel} ({info.arch})"))
    if info.uptime:
        rows.append((_("Running for"), duration(info.uptime, tr)))
    if info.init:
        rows.append((_("Init system"), info.init))
    if info.packages:
        rows.append((_("Packages"), ", ".join(f"{n} ({m})" for m, n in info.packages)))
    elif not info.slow_done:
        rows.append((_("Packages"), checking))
    if private:
        rows.append((_("Computer name"), info.hostname))
        rows.append((_("User"), info.user))
    if info.shell:
        rows.append((_("Shell"), info.shell))
    sections.append(("system", _("System"), rows))

    # ---- session
    rows = []
    if info.wm:
        rows.append((_("Window manager"), info.wm))
    if info.x_server:
        rows.append((_("Display server"), info.x_server))
    if info.x_driver:
        rows.append((_("X driver"), info.x_driver))
    if info.gl.get("renderer"):
        rows.append(("OpenGL", f"{info.gl.get('gl', '')} · {info.gl['renderer']}".strip(" ·")))
    elif not info.slow_done and os.environ.get("DISPLAY"):
        rows.append(("OpenGL", checking))
    elif os.environ.get("DISPLAY") and not shutil.which("glxinfo"):
        rows.append(("OpenGL", _("Install mesa-utils (glxinfo) to show this")))
    if info.gl.get("mesa"):
        rows.append(("Mesa", info.gl["mesa"]))
    for v in info.vulkan:
        driver = v.get("driverName", "")
        rows.append(("Vulkan", f"{v.get('apiVersion', '')} · {driver}".strip(" ·")))
    if info.slow_done and not info.vulkan and not shutil.which("vulkaninfo"):
        rows.append(("Vulkan", _("Install vulkan-tools (vulkaninfo) to show this")))
    if rows:
        sections.append(("session", _("Graphics stack"), rows))

    # ---- processor
    rows = [(_("Model"), info.cpu_model or _("Unknown")),
            (_("Cores"), _("{cores} cores, {threads} threads").format(cores=info.cpu_cores,
                                                                        threads=info.cpu_threads))]
    if info.cpu_usage is not None:
        rows.append((_("Usage"), f"{num(info.cpu_usage, 0)} %"))
    if info.cpu_mhz:
        clock = f"{info.cpu_mhz} MHz"
        if info.cpu_max_mhz:
            clock += " " + _("(max. {mhz} MHz)").format(mhz=info.cpu_max_mhz)
        rows.append((_("Clock"), clock))
    if info.cpu_temp is not None:
        rows.append((_("Temperature"), f"{num(info.cpu_temp, 0)} °C"))
    if info.cpu_l2 or info.cpu_l3:
        rows.append((_("Cache"), ", ".join(x for x in (info.cpu_l2 and f"L2 {info.cpu_l2}",
                                                        info.cpu_l3 and f"L3 {info.cpu_l3}") if x)))
    if info.cpu_driver:
        policy = info.cpu_governor + (f" / {info.cpu_epp}" if info.cpu_epp else "")
        rows.append((_("Frequency driver"), f"{info.cpu_driver} ({policy})" if policy else info.cpu_driver))
    if info.microcode:
        rows.append((_("Microcode"), info.microcode))
    sections.append(("cpu", _("Processor"), rows))

    # ---- memory
    rows = []
    mi = info.mem
    if mi.get("MemTotal"):
        total, avail = mi["MemTotal"], mi.get("MemAvailable", mi.get("MemFree", 0))
        used = total - avail
        rows.append((_("Installed"), gib(total, tr)))
        rows.append((_("In use"), _("{used} ({percent} %)").format(used=gib(used, tr),
                                                                   percent=num(100 * used / total, 0))))
        rows.append((_("Available"), gib(avail, tr)))
        if mi.get("SwapTotal"):
            sw_used = mi["SwapTotal"] - mi.get("SwapFree", 0)
            zram = bool(glob.glob(p("/sys/block/zram*")))
            rows.append((_("Swap"), _("{used} of {total}").format(used=gib(sw_used, tr), total=gib(mi["SwapTotal"], tr))
                         + (" (zram)" if zram else "")))
        else:
            rows.append((_("Swap"), _("None")))
        sections.append(("memory", _("Memory"), rows))

    # ---- graphics cards
    for n, g in enumerate(info.gpus, 1):
        rows = [(_("Model"), f"{g.vendor} {g.name}".strip())]
        if g.maker:
            rows.append((_("Card maker"), g.maker))
        rows.append((_("Kernel driver"), g.driver or _("None")))
        unified = info.gl.get("unified") == "yes" and len(info.gpus) == 1
        if g.vram_total:
            label = _("Video memory (taken from RAM)") if unified else _("Video memory")
            value = gib(g.vram_total, tr)
            if g.vram_used is not None:
                value = _("{used} of {total}").format(used=gib(g.vram_used, tr), total=gib(g.vram_total, tr))
            rows.append((label, value))
        if g.busy is not None:
            rows.append((_("Usage"), f"{g.busy} %"))
        clocks = " / ".join(x for x in (g.sclk, g.mclk and _("memory {clock}").format(clock=g.mclk)) if x)
        if clocks:
            rows.append((_("Clock"), clocks))
        if g.temp is not None:
            rows.append((_("Temperature"), f"{num(g.temp, 0)} °C"))
        if g.power is not None:
            rows.append((_("Power"), f"{num(g.power, 1)} W"))
        if g.fan:
            rows.append((_("Fan"), f"{g.fan} RPM"))
        if g.displays:
            rows.append((_("Connected displays"), ", ".join(g.displays)))
        if g.vbios:
            rows.append(("VBIOS", g.vbios))
        if g.slot:
            rows.append((_("PCI slot"), g.slot))
        title = _("Graphics") if len(info.gpus) == 1 else _("Graphics {n}").format(n=n)
        sections.append((f"gpu{n}", title, rows))

    # ---- motherboard
    b = info.board
    rows = []
    product = " ".join(x for x in (b.get("sys_vendor"), b.get("product_name")) if x)
    board = " ".join(x for x in (b.get("board_vendor"), b.get("board_name")) if x)
    if b.get("board_version"):
        board += f" ({b['board_version']})" if board else ""
    if product and product != board:
        rows.append((_("Computer"), product))
    if board:
        rows.append((_("Motherboard"), board))
    if b.get("bios_version"):
        bios = b["bios_version"] + (" " + _("from {date}").format(date=b["bios_date"]) if b.get("bios_date") else "")
        rows.append(("BIOS", bios))
    if info.uefi is not None:
        mode = "UEFI" if info.uefi else _("Legacy BIOS")
        if info.secure_boot is not None:
            mode += ", " + (_("Secure Boot on") if info.secure_boot else _("Secure Boot off"))
        rows.append((_("Boot mode"), mode))
    if rows:
        sections.append(("board", _("Motherboard"), rows))

    # ---- storage
    kinds = {"nvme": "NVMe SSD", "ssd": _("SATA SSD"), "hdd": _("Hard disk"), "usb": "USB",
             "sd": _("SD card / eMMC"), "virtual": _("Virtual disk")}
    rows = []
    for d in info.disks:
        parts = [d.model, size_si(d.size, tr), kinds.get(d.kind, "")]
        if d.removable and d.kind not in ("usb", "sd"):
            parts.append(_("removable"))
        rows.append((d.name, " · ".join(x for x in parts if x)))
    if rows:
        sections.append(("drives", _("Drives"), rows))
    rows = []
    for m in info.mounts:
        rows.append((m.target, _("{used} of {total} used ({percent} %), {fs}").format(
            used=gib(m.used, tr), total=gib(m.total, tr), percent=num(100 * m.used / m.total, 0), fs=m.fstype)))
    if rows:
        sections.append(("space", _("Disk space"), rows))

    # ---- network
    rows = []
    for nic in info.nics:
        kind = _("Wi-Fi") if nic.wireless else _("Ethernet")
        nic.state = read(f"/sys/class/net/{nic.name}/operstate")
        speed = read_int(f"/sys/class/net/{nic.name}/speed")
        state = _("connected") if nic.state == "up" else _("not connected")
        if nic.state == "up" and speed and speed > 0:
            state += f", {speed} Mb/s"
        rows.append((nic.name, f"{kind} · {nic.model or nic.driver} · {state}"))
    if rows:
        sections.append(("network", _("Network"), rows))

    # ---- audio
    rows = [(_("Device"), c) for c in info.sound_cards]
    if info.sound_server:
        rows.append((_("Sound server"), info.sound_server))
    if rows:
        sections.append(("audio", _("Audio"), rows))

    # ---- sensors
    rows = []
    for s in info.sensors:
        value = f"{num(s.value, 0)} °C" if s.kind == "temp" else f"{int(s.value)} RPM"
        rows.append((f"{s.chip} · {s.label}", value))
    if rows:
        sections.append(("sensors", _("Sensors"), rows))
    return sections


def headline(info):
    osr = info.os
    return osr.get("PRETTY_NAME") or osr.get("NAME") or "Linux"


def as_text(info, english=False):
    from . import __version__
    tr = i18n.ENGLISH if english else i18n.CURRENT
    lines = [f"{headline(info)} — XControl {__version__}, Python {platform.python_version()}"]
    for _id, title, rows in describe(info, tr, private=False):
        if _id == "sensors":
            continue
        lines += ["", title]
        width = max(len(k) for k, _v in rows)
        lines += [f"  {k.ljust(width)}  {v}" for k, v in rows]
    return "\n".join(lines) + "\n"


def snapshot():
    """Collect everything once (for --sysinfo and the tests)."""
    info = collect()
    live(info)
    slow(info)
    time.sleep(0.25)
    live(info)
    return info
