"""Date & language: the locale helper (as an unprivileged user so its test hooks apply), the
per-user locale.conf, locale names; timedated/localed when they're reachable."""
import os
import shutil
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
helper = os.path.join(here, "..", "data", "xcontrol-locale-helper")
tmp = tempfile.mkdtemp()
os.chmod(tmp, 0o777)
os.environ.update(XDG_CONFIG_HOME=os.path.join(tmp, "config"), HOME=tmp)
sys.path.insert(0, os.path.join(here, ".."))
from xcontrol import region as R  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


# names
expect("normalize", [R._norm(x) for x in ("pt_BR.utf8", "de_DE.UTF-8", "sr_RS.utf8@latin", "en_US")],
       ["pt_BR.UTF-8", "de_DE.UTF-8", "sr_RS.UTF-8@latin", "en_US"])
locs = os.path.join(tmp, "locales")
os.makedirs(locs)
with open(os.path.join(locs, "pt_BR"), "w") as f:
    f.write('LC_IDENTIFICATION\ntitle "Portuguese locale for Brazil"\nlanguage "Portuguese"\nterritory "Brazil"\n')
expect("describe", R.describe("pt_BR.UTF-8", base=locs), "Portuguese (Brazil)")

# per user
R.write_user_locale({"LANG": "pt_BR.UTF-8", "LC_TIME": "en_GB.UTF-8", "BOGUS": "x"})
expect("user locale", R.user_locale(), {"LANG": "pt_BR.UTF-8", "LC_TIME": "en_GB.UTF-8"})
# a login screen has already set the system language by the time ~/.xprofile runs: it loads ours
with open(R.xprofile_path(), "w") as f:
    f.write("xrdb -merge ~/.Xresources\n")
R.write_user_locale({"LANG": "pt_BR.UTF-8", "LC_TIME": "en_GB.UTF-8"})
R.write_user_locale({"LANG": "pt_BR.UTF-8", "LC_TIME": "en_GB.UTF-8"})     # (once, not twice)
with open(R.xprofile_path()) as f:
    xp = f.read()
expect("xprofile keeps the user's lines, block once", (xp.startswith("xrdb -merge"), xp.count(R.XPROFILE_BEGIN)),
       (True, 1))
out = subprocess.run(["sh", "-c", f". {R.xprofile_path()}; echo $LANG $LC_TIME $LC_NUMERIC"], capture_output=True,
                     text=True, env=dict(os.environ, LANG="en_US.UTF-8", LC_NUMERIC="en_US.UTF-8")).stdout.split()
expect("xprofile wins over what the login screen set", out, ["pt_BR.UTF-8", "en_GB.UTF-8"])
with open(R.environment_d_path()) as f:
    expect("environment.d", f.read().splitlines()[1:], ["LANG=pt_BR.UTF-8", "LC_TIME=en_GB.UTF-8"])
try:
    R.write_user_locale({"LANG": "pt_BR.UTF-8; rm -rf ~"})
    expect("bad value refused", False, True)
except ValueError:
    pass
R.write_user_locale({})
with open(R.xprofile_path()) as f:
    expect("block removed, the rest kept", f.read(), "xrdb -merge ~/.Xresources\n")
expect("environment.d removed", os.path.exists(R.environment_d_path()), False)
os.remove(R.xprofile_path())
R.write_user_locale({"LANG": "pt_BR.UTF-8"})
R.write_user_locale({})
expect("an xprofile only we wrote goes away", os.path.exists(R.xprofile_path()), False)
expect("removed", os.path.exists(R.user_conf_path()), False)

# the helper
prefix = []
if os.geteuid() == 0:
    if not shutil.which("setpriv"):
        print("check_region: helper skipped (root without setpriv)")
        prefix = None
    else:
        prefix = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"]
if prefix is not None:
    gen, sup, log = (os.path.join(tmp, n) for n in ("locale.gen", "SUPPORTED", "gen.log"))
    with open(gen, "w") as f:
        f.write("# en_US.UTF-8 UTF-8\n#  pt_BR.UTF-8 UTF-8\n#pt_BR ISO-8859-1\nde_DE.UTF-8 UTF-8\n")
    with open(sup, "w") as f:
        f.write("en_US.UTF-8 UTF-8\npt_BR.UTF-8 UTF-8\npt_BR ISO-8859-1\nja_JP.UTF-8 UTF-8\nde_DE.UTF-8 UTF-8\n")
    fake = os.path.join(tmp, "fake-locale-gen")
    with open(fake, "w") as f:
        f.write(f"#!/bin/sh\necho ran >> {log}\n")
    for p in (gen, sup, fake):
        os.chmod(p, 0o777)
    env = dict(os.environ, XCONTROL_LOCALE_GEN=gen, XCONTROL_SUPPORTED=sup, XCONTROL_LOCALEGEN_CMD=fake)

    def run(*args):
        return subprocess.run(prefix + ["sh", helper, *args], capture_output=True, text=True, env=env)

    r = run("enable", "pt_BR.UTF-8", "ja_JP.UTF-8", "de_DE.UTF-8")
    expect("enable ok", (r.returncode, r.stderr), (0, ""))
    with open(gen) as f:
        lines = f.read().splitlines()
    expect("locale.gen", lines, ["# en_US.UTF-8 UTF-8", "pt_BR.UTF-8 UTF-8", "#pt_BR ISO-8859-1", "de_DE.UTF-8 UTF-8",
                                 "ja_JP.UTF-8 UTF-8"])
    expect("locale-gen ran", open(log).read(), "ran\n")
    for args, what in ((("enable", "xx_YY.UTF-8"), "unsupported"), (("enable", "pt_BR;rm -rf /"), "shell chars"),
                       (("enable",), "no locale"), (("disable", "pt_BR.UTF-8"), "unknown command")):
        expect(f"refused: {what}", run(*args).returncode != 0, True)

# systemd's services, when this machine has them running
st = R.time_state()
if st:
    expect("time zone reported", bool(st.get("Timezone")), True)
    expect("locale reported", bool(R.system_locale()), True)

print("check_region:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
