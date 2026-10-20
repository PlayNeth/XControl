"""The X server tab: reading the server's log (server, modules, drivers in use, options and
where they came from), the drivers' manuals, XControl's config file and its root helper."""
import os
import shutil
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
from xcontrol import xserver as X  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


LOG = """[    22.541] (--) Log file renamed from "/home/me/.local/share/xorg/Xorg.pid-812.log" to "/home/me/.local/share/xorg/Xorg.0.log"
[    22.541]
XLibre X Server 25.0.0.14
X Protocol Version 11, Revision 0
[    22.541] Current Operating System: Linux arch 6.17.2-arch1-1 #1 SMP PREEMPT_DYNAMIC x86_64
[    22.555] (==) Using config directory: "/etc/X11/xorg.conf.d"
[    22.556] (II) LoadModule: "glx"
[    22.557] (II) Loading /usr/lib/xorg/modules/extensions/libglx.so
[    22.560] (II) Module glx: vendor="X.Org Foundation"
[    22.560] \tcompiled for 25.0.0.14, module version = 1.0.0
[    22.560] \tABI class: X.Org Server Extension, version 10.0
[    22.560] (II) LoadModule: "modesetting"
[    22.560] (II) Loading /usr/lib/xorg/modules/drivers/modesetting_drv.so
[    22.561] (II) Module modesetting: vendor="X.Org Foundation"
[    22.561] \tcompiled for 25.0.0.14, module version = 25.0.0
[    22.561] \tModule class: X.Org Video Driver
[    22.561] \tABI class: X.Org Video Driver, version 28.0
[    22.561] (II) LoadModule: "fbdev"
[    22.561] (II) Loading /usr/lib/xorg/modules/drivers/fbdev_drv.so
[    22.562] (II) Module fbdev: vendor="X.Org Foundation"
[    22.562] \tcompiled for 1.21.1.4, module version = 0.5.0
[    22.562] \tABI class: X.Org Video Driver, version 25.2
[    22.563] (II) modeset(0): using drv /dev/dri/card1
[    22.563] (II) UnloadModule: "fbdev"
[    22.563] (II) Unloading fbdev
[    22.564] (**) Option "Debug" "dmabuf_capable"
[    22.570] (**) modeset(0): Option "TearFree" "true"
[    22.570] (**) modeset(0): Option "Atomic" "true"
[    22.570] (==) modeset(0): RGB weight 888
[    22.571] (WW) modeset(0): Option "Atomc" is not used
[    22.575] (II) LoadModule: "glamoregl"
[    22.575] (II) Loading /usr/lib/xorg/modules/libglamoregl.so
[    22.576] (II) Module glamoregl: vendor="X.Org Foundation"
[    22.576] \tcompiled for 25.0.0.14, module version = 1.0.1
[    22.576] \tABI class: X.Org ANSI C Emulation, version 0.4
[    22.580] (II) LoadModule: "libinput"
[    22.580] (II) Loading /usr/lib/xorg/modules/input/libinput_drv.so
[    22.581] (II) Module libinput: vendor="X.Org Foundation"
[    22.581] \tcompiled for 1.21.1.8, module version = 1.4.0
[    22.581] \tModule class: X.Org XInput Driver
[    22.581] \tABI class: X.Org XInput driver, version 24.4
[    22.590] (**) Logitech G502: Option "AccelProfile" "flat"
"""
info = X.parse_log(LOG.replace("\\t", "\t"))
expect("server", (info.server, info.version), ("XLibre", "25.0.0.14"))
expect("modules", [(m.name, m.kind, m.version, m.unloaded) for m in info.modules],
       [("fbdev", "video", "0.5.0", True), ("modesetting", "video", "25.0.0", False),
        ("libinput", "input", "1.4.0", False), ("glx", "extension", "1.0.0", False),
        ("glamoregl", "other", "1.0.1", False)])
expect("libinput's file (not 'input')", next(m.path for m in info.modules if m.name == "libinput"),
       "/usr/lib/xorg/modules/input/libinput_drv.so")
expect("driver in use", [(m.name, m.screens) for m in X.video_drivers(info)], [("modesetting", ["0"])])
expect("its GPU", info.cards, {"modesetting": {"/dev/dri/card1"}})
expect("options and where from", (info.used[("modesetting", "tearfree")], info.used[("server", "debug")]),
       (("true", "config"), ("dmabuf_capable", "config")))
expect("ignored", info.unused, [("modesetting", "Atomc")])
expect("an input device's option isn't a server option", ("server", "accelprofile") in info.used, False)
expect("X.Org's banner", X.parse_log("X.Org X Server 1.21.1.18\n").server, "X.Org")

# the manuals (XLibre's, gzipped as installed)
man = tempfile.mkdtemp()
os.makedirs(os.path.join(man, "man4"))
os.makedirs(os.path.join(man, "man5"))
shutil.copy(os.path.join(here, "data", "modesetting.4.gz"), os.path.join(man, "man4"))
shutil.copy(os.path.join(here, "data", "xorg.conf.5.gz"), os.path.join(man, "man5"))
opts = X.driver_options("modesetting", [man])
names = [o.name for o in opts]
expect("modesetting's options", ("TearFree" in names, "Atomic" in names, "SWcursor" in names, len(opts) >= 12),
       (True, True, True, True))
atomic = next(o for o in opts if o.name == "Atomic")
expect("type and description", (atomic.type, atomic.description),
       ("boolean", "Enable atomic modesetting when supported. The default is off."))
expect("roff quotes", next(o for o in opts if o.name == "AccelMethod").description.startswith('One of "glamor"'), True)
flags = X.server_flags([man])
fnames = [o.name for o in flags]
expect("server flags", ("Debug" in fnames, "DontZap" in fnames, "AutoAddDevices" in fnames, "MaxClients" in fnames),
       (True, True, False, True))
expect("no manual", X.driver_options("nonexistent", [man]), [])

# the GPUs' kernel drivers
sysroot = tempfile.mkdtemp()
for card, drv in (("card1", "amdgpu"), ("card0", "simpledrm")):
    os.makedirs(os.path.join(sysroot, "bus", drv))
    os.makedirs(os.path.join(sysroot, "class", "drm", card, "device"))
    os.symlink(os.path.join(sysroot, "bus", drv), os.path.join(sysroot, "class", "drm", card, "device", "driver"))
os.makedirs(os.path.join(sysroot, "class", "drm", "card1-DP-2"))
expect("kernel drivers", X.kernel_drivers(sysroot), {"/dev/dri/card0": "simpledrm", "/dev/dri/card1": "amdgpu"})

# the helper (unprivileged, so its test hook applies) writes what XControl reads back
conf = tempfile.mkdtemp()
os.chmod(conf, 0o777)
prefix = []
if os.geteuid() == 0:
    prefix = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"] if shutil.which("setpriv") else None
if prefix is not None:
    helper = os.path.join(here, "..", "data", "xcontrol-xorg-helper")
    env = dict(os.environ, XCONTROL_XORG_DIR=conf)

    def run(*args):
        return subprocess.run(prefix + ["sh", helper, *args], capture_output=True, text=True, env=env)

    drivers, server = {"amdgpu": {"TearFree": "true", "Atomic": "true"}}, {"Debug": "dmabuf_capable"}
    res = run(*X.helper_args(drivers, server, "modesetting"))
    expect("written", (res.returncode, res.stderr), (0, ""))
    with open(os.path.join(conf, X.OUR_FILE)) as f:
        expect("same as XControl expects", f.read(), X.file_text(drivers, server, "modesetting"))
    expect("read back", X.read_ours(conf), (drivers, server, "modesetting"))
    for args in (("write", "modesetting", 'drv:amdgpu:Tear"Free=true'), ("write", "modesetting", "drv:amdgpu:X=a b"),
                 ("write", "modesetting", "drv:AMD GPU:X=1"), ("write", "modesetting", "srv:X=$(reboot)"),
                 ("write", "x;y"), ("rm",), ("write", "modesetting", "srv:9x=1"), ("write", "modesetting", "nope")):
        expect(f"refused {args}", run(*args).returncode != 0, True)
    run("write", "modesetting")
    expect("nothing left: removed", os.path.exists(os.path.join(conf, X.OUR_FILE)), False)
for bad_args in (({"amdgpu": {"X": "a b"}}, {}), ({"amd gpu": {"X": "1"}}, {}), ({}, {"X\"": "1"})):
    try:
        X.helper_args(*bad_args)
        expect(f"refused before pkexec {bad_args}", False, True)
    except ValueError:
        pass

# other files' options, and a ServerFlags section of their own
other = os.path.join(conf, "20-mine.conf")
with open(other, "w") as f:
    f.write('Section "Device"\n  Identifier "gpu"\n  Driver "modesetting"\n  Option "PageFlip" "false" # x\n'
            'EndSection\nSection "ServerFlags"\n  Option "BlankTime" "0"\nEndSection\n')
found, flag_files = X.elsewhere(conf, [os.path.join(conf, "*.conf")])
expect("found elsewhere", (found, flag_files),
       ([(other, "Device", "PageFlip", "false"), (other, "ServerFlags", "BlankTime", "0")], [other]))

print("check_xserver:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
