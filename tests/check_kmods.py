"""Kernel modules from a fake /proc and /sys tree."""
import os
import shutil
import sys
import tempfile

root = tempfile.mkdtemp()
os.environ["XCONTROL_SYSROOT"] = root
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import kmods as K  # noqa: E402

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
    os.symlink(os.path.join(root, target.lstrip("/")), full)


mk("/proc/modules",
   "amdgpu 16019456 34 - Live 0x0000000000000000\n"
   "drm_exec 12288 1 amdgpu, Live 0x0000000000000000\n"
   "snd_hda_intel 69632 3 - Live 0x0000000000000000\n"
   "hid_logitech_hidpp 81920 0 - Live 0x0000000000000000\n"
   "bad line\n")
mk("/sys/module/amdgpu/initstate", "live")
mk("/sys/module/amdgpu/parameters/ppfeaturemask", "0xfff7bfff")
mk("/sys/module/amdgpu/parameters/dc", "-1")
mk("/sys/module/amdgpu/parameters/secret", "x")
os.chmod(os.path.join(root, "sys/module/amdgpu/parameters/secret"), 0)
mk("/sys/module/amdgpu/holders/.keep")
os.makedirs(os.path.join(root, "sys/module/drm_exec/holders"), exist_ok=True)
mk("/sys/module/drm_exec/initstate", "live")
os.makedirs(os.path.join(root, "sys/module/drm_exec/holders/amdgpu"))
mk("/sys/module/drm_kms_helper/parameters/poll", "Y")      # built in: no initstate
mk("/sys/module/printk/parameters/time", "Y")

dev = "/sys/devices/pci0000:00/0000:00:08.1/0000:07:00.0"
mk(f"{dev}/vendor", "0x1002")
mk(f"{dev}/device", "0x1638")
mk("/sys/bus/pci/drivers/amdgpu/bind")
link("/sys/module/amdgpu/drivers/pci:amdgpu", "/sys/bus/pci/drivers/amdgpu")
link("/sys/bus/pci/drivers/amdgpu/0000:07:00.0", dev)
link("/sys/bus/pci/drivers/amdgpu/module", "/sys/module/amdgpu")
mk("/usr/share/hwdata/pci.ids", "1002  Advanced Micro Devices, Inc. [AMD/ATI]\n"
   "\t1638  Cezanne [Radeon Vega Series / Radeon Vega Mobile Series]\nC 00  Unclassified\n")

mk("/usr/lib/modprobe.d/amdgpu.conf", "options amdgpu si_support=1\n")
mk("/etc/modprobe.d/amdgpu.conf", "# mine\noptions amdgpu ppfeaturemask=0xfff7bfff  # overclocking\n")
mk("/etc/modprobe.d/other.conf", "blacklist radeon\noptions snd-hda-intel power_save=0\n"
   "options amdgpu \\\n  dc=1\n")

mods = K.modules()
expect("loaded", [m.name for m in mods], ["amdgpu", "drm_exec", "hid_logitech_hidpp", "snd_hda_intel"])
expect("used by", next(m for m in mods if m.name == "drm_exec").used_by, ["amdgpu"])
expect("built-ins only on request", [m.name for m in K.modules(include_builtin=True) if m.builtin],
       ["drm_kms_helper", "printk"])
prm = {x.name: x.value for x in K.params("amdgpu")}
expect("params", (prm["ppfeaturemask"], prm["dc"]), ("0xfff7bfff", "-1"))
if os.geteuid() != 0:   # root reads anything
    expect("root-only param", prm["secret"] is K.UNREADABLE, True)
expect("devices", K.devices("amdgpu"), [("pci", "0000:07:00.0", "AMD Radeon Vega Series (Cezanne)")])
expect("holders", K.holders("drm_exec"), ["amdgpu"])
expect("modprobe.d: /etc overrides same-named file, line continuation, comments",
       [line for _f, line in K.modprobe_options("amdgpu")],
       ["options amdgpu ppfeaturemask=0xfff7bfff", "options amdgpu dc=1"])
expect("dash/underscore", [line for _f, line in K.modprobe_options("snd_hda_intel")],
       ["options snd-hda-intel power_save=0"])

info = K.parse_modinfo("""filename:       /lib/modules/6.17.4-arch1-1/kernel/drivers/gpu/drm/amd/amdgpu/amdgpu.ko.zst
license:        GPL and additional rights
description:    AMD GPU
author:         AMD linux driver team
firmware:       amdgpu/green_sardine_dmcub.bin
firmware:       amdgpu/renoir_ta.bin
depends:        drm_exec,gpu-sched,drm_buddy
parm:           ppfeaturemask:all power features enabled (default)) (uint)
parm:           dc:Display Core driver (1 = enable, 0 = disable, -1 = auto (default)) (int)
parm:           vramlimit:Restrict VRAM for testing, in megabytes (int)
""")
expect("modinfo", (info["description"], info["depends"], len(info["firmware"])),
       ("AMD GPU", ["drm_exec", "gpu-sched", "drm_buddy"], 2))
expect("modinfo parm", info["parm"]["dc"],
       ("Display Core driver (1 = enable, 0 = disable, -1 = auto (default))", "int"))

d = K.details("amdgpu")
text = K.as_text(d, english=True)
expect("text", ("ppfeaturemask  0xfff7bfff" in text, "pci 0000:07:00.0" in text, "dc=1" in text), (True, True, True))

print("check_kmods:", "FAILED" if bad else "ok")
shutil.rmtree(root, ignore_errors=True)
sys.exit(1 if bad else 0)
