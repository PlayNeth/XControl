"""System info from a fake /proc and /sys tree (a Ryzen 5 5600G desktop)."""
import os
import shutil
import sys
import tempfile

root = tempfile.mkdtemp()
os.environ["XCONTROL_SYSROOT"] = root
os.environ.pop("DISPLAY", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import i18n, sysinfo as S  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def mk(path, text=""):
    full = os.path.join(root, path.lstrip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)


def link(path, target):
    full = os.path.join(root, path.lstrip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    os.symlink(target, full)


mk("/etc/os-release", 'NAME="Arch Linux"\nPRETTY_NAME="Arch Linux"\nID=arch\nBUILD_ID=rolling\nLOGO=archlinux-logo\n')
mk("/proc/sys/kernel/osrelease", "6.17.4-arch1-1")
mk("/proc/sys/kernel/hostname", "box")
mk("/proc/1/comm", "systemd")
cpu = ""
for n in range(12):
    cpu += (f"processor\t: {n}\nvendor_id\t: AuthenticAMD\nmodel name\t: AMD Ryzen 5 5600G with Radeon Graphics\n"
            f"microcode\t: 0xa50000c\nphysical id\t: 0\ncore id\t\t: {n % 6}\ncpu cores\t: 6\n\n")
mk("/proc/cpuinfo", cpu)
for n in range(12):
    mk(f"/sys/devices/system/cpu/cpu{n}/cpufreq/scaling_cur_freq", str(1400000 + n * 100000))
cf = "/sys/devices/system/cpu/cpu0/cpufreq"
mk(f"{cf}/cpuinfo_max_freq", "4464000")
mk(f"{cf}/scaling_driver", "amd-pstate-epp")
mk(f"{cf}/scaling_governor", "powersave")
mk(f"{cf}/energy_performance_preference", "balance_performance")
for idx, level, kind, size in ((0, 1, "Data", "32K"), (2, 2, "Unified", "512K"), (3, 3, "Unified", "16384K")):
    for k, v in (("level", level), ("type", kind), ("size", size)):
        mk(f"/sys/devices/system/cpu/cpu0/cache/index{idx}/{k}", str(v))
mk("/proc/stat", "cpu  100 0 100 800 0 0 0 0 0 0\n")
mk("/proc/uptime", "93784.12 1000.0\n")
mk("/proc/meminfo", "MemTotal:       15728640 kB\nMemFree:  1000 kB\nMemAvailable:    9437184 kB\n"
   "SwapTotal:       8388608 kB\nSwapFree:        8388608 kB\n")
mk("/sys/block/zram0/size", "0")

# graphics: the Vega 7 iGPU on amdgpu, a CRT on DP-2 (the board's VGA port)
dev = "/sys/devices/pci0000:00/0000:00:08.1/0000:07:00.0"
for k, v in (("vendor", "0x1002"), ("device", "0x1638"), ("subsystem_vendor", "0x1458"),
             ("subsystem_device", "0xd000"), ("vbios_version", "113-CEZANNE-018"),
             ("mem_info_vram_total", str(512 << 20)), ("mem_info_vram_used", str(200 << 20)),
             ("gpu_busy_percent", "3"), ("pp_dpm_sclk", "0: 200Mhz\n1: 400Mhz *\n2: 1900Mhz\n"),
             ("pp_dpm_mclk", "0: 400Mhz\n1: 1600Mhz *\n")):
    mk(f"{dev}/{k}", v)
mk(f"{dev}/hwmon/hwmon3/temp1_input", "41000")
mk(f"{dev}/hwmon/hwmon3/power1_input", "8250000")
mk(f"{dev}/hwmon/hwmon3/name", "amdgpu")
mk("/sys/bus/pci/drivers/amdgpu/.keep")
link(f"{dev}/driver", os.path.join(root, "sys/bus/pci/drivers/amdgpu"))
link("/sys/class/drm/card1/device", os.path.join(root, dev.lstrip("/")))
mk("/sys/class/drm/card1-DP-2/status", "connected")
mk("/sys/class/drm/card1-HDMI-A-1/status", "disconnected")
link("/sys/class/hwmon/hwmon3", os.path.join(root, dev.lstrip("/"), "hwmon/hwmon3"))
mk("/sys/class/hwmon/hwmon1/name", "k10temp")
mk("/sys/class/hwmon/hwmon1/temp1_input", "52125")
mk("/sys/class/hwmon/hwmon1/temp1_label", "Tctl")
mk("/sys/class/hwmon/hwmon2/name", "nvme")
mk("/sys/class/hwmon/hwmon2/temp1_input", "38850")
mk("/sys/class/hwmon/hwmon2/temp1_label", "Composite")
mk("/sys/class/hwmon/hwmon2/temp2_input", "-273150")   # unconnected probe

mk("/usr/share/hwdata/pci.ids",
   "# test\n1002  Advanced Micro Devices, Inc. [AMD/ATI]\n"
   "\t1638  Cezanne [Radeon Vega Series / Radeon Vega Mobile Series]\n"
   "\t\t1458 d000  Cezanne [Radeon Vega Series]\n"
   "10ec  Realtek Semiconductor Co., Ltd.\n\t8168  RTL8111/8168/8211/8411 PCI Express Gigabit Ethernet Controller\n"
   "1458  Gigabyte Technology Co., Ltd\n"
   "C 00  Unclassified device\n")

for k, v in (("sys_vendor", "Gigabyte Technology Co., Ltd."), ("product_name", "B550M DS3H"),
             ("board_vendor", "Gigabyte Technology Co., Ltd."), ("board_name", "B550M DS3H"),
             ("board_version", "Default string"), ("bios_version", "F17"), ("bios_date", "06/20/2023")):
    mk(f"/sys/class/dmi/id/{k}", v)
mk("/sys/firmware/efi/.keep")

mk("/sys/block/nvme0n1/size", str(1000204886016 // 512))
mk("/sys/block/nvme0n1/device/model", "KINGSTON SNV2S1000G                     ")
mk("/sys/block/sda/size", str(2000398934016 // 512))
mk("/sys/block/sda/device/model", "ST2000DM008-2FR1")
mk("/sys/block/sda/queue/rotational", "1")
mk("/sys/block/loop0/size", "1000")

nic = "/sys/devices/pci0000:00/0000:00:02.1/0000:05:00.0"
mk(f"{nic}/vendor", "0x10ec")
mk(f"{nic}/device", "0x8168")
mk("/sys/bus/pci/drivers/r8169/.keep")
link(f"{nic}/driver", os.path.join(root, "sys/bus/pci/drivers/r8169"))
mk("/sys/class/net/enp5s0/operstate", "up")
mk("/sys/class/net/enp5s0/speed", "1000")
link("/sys/class/net/enp5s0/device", os.path.join(root, nic.lstrip("/")))
mk("/sys/class/net/lo/operstate", "unknown")
mk("/sys/class/net/docker0/operstate", "down")       # virtual: no device link
mk("/proc/asound/cards", " 0 [Generic        ]: HDA-Intel - HD-Audio Generic\n"
   "                      HD-Audio Generic at 0xfcc88000 irq 74\n"
   " 1 [Generic_1      ]: HDA-Intel - HD-Audio Generic\n                      HD-Audio Generic at 0xfcc80000\n")
mk("/proc/self/mounts", "/dev/nvme0n1p2 / ext4 rw 0 0\n/dev/nvme0n1p2 /home ext4 rw 0 0\nproc /proc proc rw 0 0\n"
   "tmpfs /tmp tmpfs rw 0 0\n")
os.makedirs(os.path.join(root, "var/lib/pacman/local/linux-6.17.4"))
os.makedirs(os.path.join(root, "var/lib/pacman/local/mesa-1:25.2.5-1"))
mk("/var/lib/pacman/local/ALPM_DB_VERSION", "9")

info = S.collect()
S.live(info)
mk("/proc/stat", "cpu  200 0 200 1400 200 0 0 0 0 0\n")   # +200 busy, +800 idle
S.live(info)
info.packages = S.package_counts()
info.slow_done = True
info.gl = S.parse_glxinfo("""direct rendering: Yes
Extended renderer info (GLX_MESA_query_renderer):
    Vendor: AMD (0x1002)
    Device: AMD Radeon Graphics (radeonsi, renoir, LLVM 20.1.8, DRM 3.64, 6.17.4-arch1-1) (0x1638)
    Version: 25.2.5
    Video memory: 512MB
    Unified memory: yes
OpenGL vendor string: AMD
OpenGL renderer string: AMD Radeon Graphics (radeonsi, renoir, LLVM 20.1.8, DRM 3.64, 6.17.4-arch1-1)
OpenGL core profile version string: 4.6 (Core Profile) Mesa 25.2.5-arch1.1
OpenGL version string: 4.6 (Compatibility Profile) Mesa 25.2.5-arch1.1
""")
info.vulkan = S.parse_vulkaninfo("""Devices:
========
GPU0:
\tapiVersion         = 1.4.318
\tdriverVersion      = 25.2.5
\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU
\tdeviceName         = AMD Radeon Graphics (RADV RENOIR)
\tdriverName         = radv
GPU1:
\tapiVersion         = 1.4.318
\tdeviceType         = PHYSICAL_DEVICE_TYPE_CPU
\tdeviceName         = llvmpipe (LLVM 20.1.8, 256 bits)
\tdriverName         = llvmpipe
""")

sections = {sid: dict(rows) for sid, _t, rows in S.describe(info, i18n.ENGLISH)}
sysrows, cpu_rows, mem, gpu = sections["system"], sections["cpu"], sections["memory"], sections["gpu1"]
expect("distro", sysrows["Distribution"], "Arch Linux")
expect("kernel", sysrows["Kernel"].startswith("Linux 6.17.4-arch1-1"), True)
expect("uptime", sysrows["Running for"], "1 day, 2 h 03 min")
expect("packages", sysrows["Packages"], "2 (pacman)")
expect("init", sysrows["Init system"], "systemd")
expect("cpu model", cpu_rows["Model"], "AMD Ryzen 5 5600G with Radeon Graphics")
expect("cores", cpu_rows["Cores"], "6 cores, 12 threads")
expect("usage", cpu_rows["Usage"], "20 %")
expect("clock", cpu_rows["Clock"], "2500 MHz (max. 4464 MHz)")
expect("cpu temp", cpu_rows["Temperature"], "52 °C")
expect("cache", cpu_rows["Cache"], "L2 512 KiB × 6, L3 16 MiB")
expect("cpufreq", cpu_rows["Frequency driver"], "amd-pstate-epp (powersave / balance_performance)")
expect("memory", (mem["Installed"], mem["In use"], mem["Swap"]), ("15.0 GiB", "6.0 GiB (40 %)", "0 MiB of 8.0 GiB (zram)"))
expect("gpu model", gpu["Model"], "AMD Radeon Vega Series (Cezanne)")
expect("gpu maker", gpu.get("Card maker"), "Gigabyte")
expect("gpu driver", gpu["Kernel driver"], "amdgpu")
expect("apu vram", gpu["Video memory (taken from RAM)"], "200 MiB of 512 MiB")
expect("gpu clocks", gpu["Clock"], "400 MHz / memory 1600 MHz")
expect("gpu temp/power", (gpu["Temperature"], gpu["Power"]), ("41 °C", "8.2 W"))
expect("displays", gpu["Connected displays"], "DP-2")
expect("pci slot", gpu["PCI slot"], "0000:07:00.0")
stack = sections["session"]
expect("opengl", stack["OpenGL"], "4.6 · AMD Radeon Graphics (radeonsi, renoir, LLVM 20.1.8, DRM 3.64, 6.17.4-arch1-1)")
expect("mesa", stack["Mesa"], "25.2.5-arch1.1")
expect("vulkan (no llvmpipe)", stack["Vulkan"], "1.4.318 · radv")
board = sections["board"]
expect("board", board["Motherboard"], "Gigabyte Technology Co., Ltd. B550M DS3H")
expect("no duplicate computer row", "Computer" in board, False)
expect("bios", board["BIOS"], "F17 from 06/20/2023")
expect("uefi", board["Boot mode"], "UEFI")
drives = sections["drives"]
expect("nvme", drives["nvme0n1"], "KINGSTON SNV2S1000G · 1 TB · NVMe SSD")
expect("hdd", drives["sda"], "ST2000DM008-2FR1 · 2 TB · Hard disk")
expect("no loop devices", "loop0" in drives, False)
expect("one mount per device", list(sections["space"]), ["/"])
expect("network", sections["network"], {"enp5s0": "Ethernet · Realtek RTL8111/8168/8211/8411 PCI Express Gigabit "
                                                   "Ethernet Controller · connected, 1000 Mb/s"})
expect("audio", [v for k, v in S.describe(info, i18n.ENGLISH)[-2][2] if k == "Device"],
       ["HD-Audio Generic", "HD-Audio Generic"])
sens = sections["sensors"]
expect("sensors", ("k10temp · Tctl" in sens, "nvme · Composite" in sens, "nvme · temp2" in sens), (True, True, False))
text = S.as_text(info, english=True)
expect("copy leaves out host name", ("box" in text, "Computer name" in text), (False, False))
expect("pci names", S.pci_names(0x1002, 0x1638, ids_path=os.path.join(root, "usr/share/hwdata/pci.ids"))[1],
       "Cezanne [Radeon Vega Series / Radeon Vega Mobile Series]")

print("check_sysinfo:", "FAILED" if bad else "ok")
shutil.rmtree(root, ignore_errors=True)
sys.exit(1 if bad else 0)
