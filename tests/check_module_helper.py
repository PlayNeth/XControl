"""xcontrol-module-helper: validation, the file it writes, live changes, removal.
Run as an unprivileged user so the test hooks apply (when the tests run as root, drop to
nobody with setpriv)."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
helper = os.path.join(here, "..", "data", "xcontrol-module-helper")
sys.path.insert(0, os.path.join(here, ".."))

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


prefix = []
if os.geteuid() == 0:
    if not shutil.which("setpriv"):
        print("check_module_helper: skipped (root without setpriv)")
        sys.exit(0)
    prefix = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"]

tmp = tempfile.mkdtemp()
os.chmod(tmp, 0o777)
conf, sysmod = os.path.join(tmp, "modprobe.d"), os.path.join(tmp, "module")
for path, mode in (("amdgpu/initstate", 0o644), ("amdgpu/parameters/ppfeaturemask", 0o444),
                   ("amdgpu/parameters/dc", 0o444), ("snd_hda_intel/initstate", 0o644),
                   ("snd_hda_intel/parameters/power_save", 0o666), ("printk/parameters/time", 0o666)):
    full = os.path.join(sysmod, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write("0\n")
    os.chmod(full, mode)
os.makedirs(conf)
os.chmod(conf, 0o777)
env = dict(os.environ, XCONTROL_MODPROBE_DIR=conf, XCONTROL_SYSMODULE=sysmod, XCONTROL_INITRAMFS="0")


def run(*args):
    r = subprocess.run(prefix + ["sh", helper, *args], capture_output=True, text=True, env=env)
    return r.returncode, (r.stdout + r.stderr).strip()


def read(name):
    with open(os.path.join(conf, name)) as f:
        return f.read()


code, out = run("apply", "--initramfs", "amdgpu", "ppfeaturemask=0xfff7bfff", "dc=1")
expect("apply ok", code, 0)
expect("file", read("xcontrol-amdgpu.conf").splitlines()[-1], "options amdgpu ppfeaturemask=0xfff7bfff dc=1")
expect("initramfs step reached", "initramfs: skipped (test)" in out, True)
expect("file mode", stat.S_IMODE(os.stat(os.path.join(conf, "xcontrol-amdgpu.conf")).st_mode), 0o644)

code, out = run("apply", "--live", "snd_hda_intel", "power_save=1")
expect("live ok", (code, "live: power_save=1" in out), (0, True))
with open(os.path.join(sysmod, "snd_hda_intel/parameters/power_save")) as f:
    expect("live value written", f.read(), "1")
code, out = run("apply", "--live", "amdgpu", "dc=0")
expect("read-only param not written live", "can't change while running" in out, True)

for args, why in ((["apply", "amdgpu", "dc=1;reboot"], "shell characters"),
                  (["apply", "amdgpu", "dc=1 2"], "space"),
                  (["apply", "amdgpu", 'dc="1"'], "quotes"),
                  (["apply", "amdgpu", "nosuch=1"], "unknown parameter"),
                  (["apply", "../etc", "dc=1"], "module path"),
                  (["apply", "AMDGPU", "dc=1"], "upper case module"),
                  (["apply", "nosuchmod", "x=1"], "missing module"),
                  (["apply", "printk", "time=1"], "built-in"),
                  (["apply", "amdgpu", "dc"], "no value"),
                  (["apply", "--force", "amdgpu"], "unknown option"),
                  (["rm", "amdgpu"], "unknown command")):
    code, _out = run(*args)
    expect(f"refuses {why}", code != 0, True)
expect("nothing else written", sorted(os.listdir(conf)), ["xcontrol-amdgpu.conf", "xcontrol-snd_hda_intel.conf"])

code, out = run("apply", "amdgpu")
expect("remove", (code, os.path.exists(os.path.join(conf, "xcontrol-amdgpu.conf"))), (0, False))

# the Python side builds the same arguments and validates by type
from xcontrol import kmods as K  # noqa: E402
expect("helper args", K.helper_args("snd-hda-intel", {"power_save": "1", "enable": ""}, live=True),
       ["apply", "--live", "snd_hda_intel", "power_save=1"])
for value, typ, want in (("0xfff7bfff", "hexint", None), ("-1", "int", None), ("-1", "uint", "type"),
                         ("Y", "bool", None), ("off", "bool", None), ("maybe", "bool", "type"),
                         ("1,0,1", "array of int", None), ("300", "byte", "type"), ("a b", "charp", "chars"),
                         ("/lib/firmware/x.bin", "charp", None), ("", "int", None)):
    expect(f"check {value!r} as {typ}", K.check_value(value, typ), want)
expect("cmdline values", K.cmdline_values("amdgpu", "root=/dev/x amdgpu.ppfeaturemask=0xffffffff "
                                                    "snd_hda_intel.power_save=0 amdgpu.dc=1 -- amdgpu.x=1"),
       {"ppfeaturemask": "0xffffffff", "dc": "1"})

print("check_module_helper:", "FAILED" if bad else "ok")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
