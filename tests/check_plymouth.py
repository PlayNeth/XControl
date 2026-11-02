"""Boot splash: themes, settings, the mkinitcpio hook and the kernel command line, and the helper."""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import plymouth as P  # noqa: E402

failed = 0


def expect(what, got, want):
    global failed
    if got != want:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


# ---------------------------------------------------------------- hooks
ARCH = "HOOKS=(base systemd autodetect microcode modconf kms keyboard sd-vconsole block filesystems fsck)"
hk = P.hooks([ARCH])
expect("Arch's default HOOKS", hk[0:3], ["base", "systemd", "autodetect"])
expect("no plymouth yet", P.hook_state(hk), "missing")
expect("goes right after kms", P.format_hooks(P.suggested_hooks(hk)),
       "HOOKS=(base systemd autodetect microcode modconf kms plymouth keyboard sd-vconsole block filesystems fsck)")
enc = P.hooks(["HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block encrypt "
               "filesystems fsck)"])
expect("udev setup, before encrypt", P.suggested_hooks(enc).index("plymouth"), enc.index("kms") + 1)
no_kms = P.hooks(["HOOKS=(base systemd autodetect block sd-encrypt filesystems)"])
expect("without kms: after systemd, before sd-encrypt", P.suggested_hooks(no_kms),
       ["base", "systemd", "plymouth", "autodetect", "block", "sd-encrypt", "filesystems"])
expect("in place", P.hook_state(P.suggested_hooks(hk)), "ok")
expect("too early", P.hook_state(["base", "plymouth", "systemd", "kms"]), "early")
expect("after encrypt", P.hook_state(["base", "systemd", "kms", "sd-encrypt", "plymouth"]), "late")
expect("moved, not doubled", P.suggested_hooks(["base", "plymouth", "systemd", "kms"]),
       ["base", "systemd", "kms", "plymouth"])
expect("unknown (dracut)", P.hook_state(P.hooks([""])), None)
multi = """# HOOKS=(old commented)
HOOKS=(base udev
       autodetect  # a comment
       block filesystems)
"""
expect("multi-line HOOKS with comments", P.hooks([multi]), ["base", "udev", "autodetect", "block", "filesystems"])
expect("a drop-in wins", P.hooks([ARCH, "HOOKS=(base systemd plymouth)"]), ["base", "systemd", "plymouth"])
expect("quoted, appended, a comment with parentheses",
       P.hooks(['HOOKS=("base" \'systemd\' # (see the wiki)\n kms) # end', "HOOKS+=(plymouth)"]),
       ["base", "systemd", "kms", "plymouth"])
expect("a drop-in that extends HOOKS", P.hooks([ARCH, 'HOOKS=("${HOOKS[@]}" plymouth)'])[-2:], ["fsck", "plymouth"])
expect("before kms is fine (kms only adds modules)", P.hook_state(["base", "systemd", "plymouth", "kms"]), "ok")

# ---------------------------------------------------------------- kernel command line
expect("splash there", P.has_splash("root=UUID=x rw quiet splash"), True)
expect("nosplash", P.has_splash("root=UUID=x splash nosplash"), False)
expect("not there", P.has_splash("root=UUID=x rw"), False)
expect("suggested options", P.suggested_cmdline("initrd=\\initramfs-linux.img root=UUID=abc rw nosplash"),
       "root=UUID=abc rw quiet splash")
expect("no doubles", P.suggested_cmdline("root=/dev/sda2 quiet"), "root=/dev/sda2 quiet splash")
expect("quoted values kept as written", P.suggested_cmdline('root=/dev/sda2 acpi_osi="!Windows 2020" it\'s'),
       'root=/dev/sda2 acpi_osi="!Windows 2020" it\'s quiet splash')

# ---------------------------------------------------------------- themes and settings
tmp = tempfile.mkdtemp()
themes = os.path.join(tmp, "themes")
for name, body in (("spinner", "[Plymouth Theme]\nName=Spinner\nName[pt_BR]=Girador\nDescription=A spinner.\n"
                               "ModuleName=two-step\n\n[two-step]\nImageDir=/x\n"),
                   ("text", "[Plymouth Theme]\nName=Text\nDescription=Text mode\nModuleName=text\n"),
                   ("broken", "not a key file\n["),
                   ("odd", "[Something]\nName=x\n"),
                   ("my.theme", "[Plymouth Theme]\nName=Dotted\nModuleName=script\n")):
    os.makedirs(os.path.join(themes, name))
    with open(os.path.join(themes, name, name + ".plymouth"), "w") as f:
        f.write(body)
os.environ["LANG"] = "C"
got = P.themes(themes)
expect("themes found, damaged ones (and names the helper refuses) skipped", [(t.name, t.title, t.module) for t in got],
       [("spinner", "Spinner", "two-step"), ("text", "Text", "text")])
conf = os.path.join(tmp, "plymouthd.conf")
defaults = os.path.join(tmp, "plymouthd.defaults")
with open(defaults, "w") as f:
    f.write("[Daemon]\nTheme=bgrt\nShowDelay=0\n")
expect("distribution default", P.settings(conf, defaults), P.Settings("bgrt", "", ""))
with open(conf, "w") as f:
    f.write("[Daemon]\nTheme=spinner\nShowDelay=2\nDeviceScale=2\n")
expect("own setting wins", P.settings(conf, defaults), P.Settings("spinner", "2", "2"))
os.environ["LANG"] = "pt_BR.UTF-8"
expect("translated name", P.themes(themes)[0].title, "Girador")
os.environ["LANG"] = "C"
expect("cancelled password prompt: no message",
       P._result(subprocess.CompletedProcess([], 126, "",
                                             "Error executing command as another user: Request dismissed\n")),
       (False, None))
expect("a refusal is reported, not taken for a cancel",
       P._result(subprocess.CompletedProcess([], 127, "", "Error executing command as another user: Not authorized\n"
                                             "\nThis incident has been reported.\n"))[1].startswith("Error executing"),
       True)
expect("helper error kept", P._result(subprocess.CompletedProcess([], 1, "", "no such theme: x\n")),
       (False, "no such theme: x"))
expect("pictures shipped for every built-in theme",
       sorted(n for n in ("bgrt", "details", "fade-in", "glow", "script", "solar", "spinfinity", "spinner",
                          "text", "tribar") if not P.picture(n)), [])

# ---------------------------------------------------------------- the helper (test hooks: not as root)
helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "xcontrol-plymouth-helper")
work = tempfile.mkdtemp(prefix="plyhelp", dir="/tmp")
os.makedirs(os.path.join(work, "themes", "spinner"))
os.makedirs(os.path.join(work, "themes", "bgrt"))
for n in ("spinner", "bgrt"):
    open(os.path.join(work, "themes", n, n + ".plymouth"), "w").close()
os.makedirs(os.path.join(work, "etc"))
for root, dirs, files in os.walk(work):
    for d in dirs + files:
        os.chmod(os.path.join(root, d), 0o777)
os.chmod(work, 0o777)
cfile = os.path.join(work, "etc", "plymouthd.conf")


def run(*args):
    env = dict(os.environ, XCONTROL_PLYMOUTH_CONF=cfile, XCONTROL_PLYMOUTH_THEMES=os.path.join(work, "themes"),
               XCONTROL_INITRAMFS="0")
    pre = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"] if os.getuid() == 0 else []
    return subprocess.run(pre + ["sh", helper] + list(args), env=env, capture_output=True, text=True)


def read():
    with open(cfile) as f:
        return f.read()


expect("new file", (run("set", "spinner", "-", "-").returncode, read()), (0, "[Daemon]\nTheme=spinner\n"))
with open(cfile, "w") as f:
    f.write("# mine\n[Daemon]\nShowDelay=5\nTheme=bgrt\nFoo=bar\n\n[Other]\nTheme=keep\n")
os.chmod(cfile, 0o666)
run("set", "spinner", "1.5", "2")
expect("other keys and sections kept", read(),
       "# mine\n[Daemon]\nTheme=spinner\nShowDelay=1.5\nDeviceScale=2\nFoo=bar\n\n[Other]\nTheme=keep\n")
with open(cfile, "w") as f:
    f.write("[Other]\nA=1\n")
run("set", "bgrt", "0", "-")
expect("[Daemon] added at the end", read(), "[Other]\nA=1\n\n[Daemon]\nTheme=bgrt\nShowDelay=0\n")
for bad in (["set", "../x", "-", "-"], ["set", "nope", "-", "-"], ["set", "spinner", "2a", "-"],
            ["set", "spinner", "31", "-"], ["set", "spinner", "-", "5"], ["set", "spinner", ".5", "-"],
            ["set", "-x", "-", "-"], ["preview", "spinner", ":0;id", "-"], ["preview", "../x", ":0", "-"],
            ["set", "spinner", "-"], ["remove", "spinner", "-", "-"]):
    expect(f"refused {bad}", run(*bad).returncode != 0, True)
os.symlink("/etc/passwd", os.path.join(work, "etc", "link.conf"))
env = dict(os.environ, XCONTROL_PLYMOUTH_CONF=os.path.join(work, "etc", "link.conf"),
           XCONTROL_PLYMOUTH_THEMES=os.path.join(work, "themes"), XCONTROL_INITRAMFS="0")
pre = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"] if os.getuid() == 0 else []
expect("a symlinked conf is refused",
       subprocess.run(pre + ["sh", helper, "set", "bgrt", "-", "-"], env=env, capture_output=True).returncode != 0,
       True)
subprocess.run(["rm", "-rf", work])

print("check_plymouth:", "ok" if not failed else f"{failed} failed")
sys.exit(1 if failed else 0)
