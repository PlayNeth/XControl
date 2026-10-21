"""xcontrol-user-helper: what it refuses and what it would run (dry run as a normal user)."""
import os
import shutil
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
helper = os.path.join(here, "..", "data", "xcontrol-user-helper")
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
        print("check_user_helper: skipped (root without setpriv)")
        sys.exit(0)
    prefix = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"]

tmp = tempfile.mkdtemp()
os.chmod(tmp, 0o755)


def write(name, text):
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o644)
    return path


env = dict(os.environ,
           XCONTROL_PASSWD=write("passwd", "root:x:0:0::/root:/bin/bash\nbin:x:1:1::/:/usr/bin/nologin\n"
                                           "leo:x:1000:1000:Leo,,,:/home/leo:/bin/bash\n"
                                           "ana:x:1001:1001:Ana:/home/ana:/bin/zsh\n"),
           XCONTROL_GROUP=write("group", "root:x:0:root\nwheel:x:998:leo\nvideo:x:986:leo,ana\naudio:x:995:\n"
                                         "input:x:994:\nleo:x:1000:\nana:x:1001:\nsecret:x:500:\n"),
           XCONTROL_SHELLS=write("shells", "/bin/sh\n/bin/bash\n/bin/zsh\n/usr/bin/fish\n"),
           XCONTROL_LOGINDEFS=write("login.defs", "UID_MIN   1000\nUID_MAX   60000\n"),
           XCONTROL_ICONDIR=os.path.join(tmp, "as"),
           XCONTROL_CALLER_UID="1000")
png = write("face.png", "")
with open(png, "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)


def run(*args, stdin=""):
    r = subprocess.run(prefix + ["sh", helper, *args], capture_output=True, text=True, env=env, input=stdin)
    return r.returncode, (r.stdout + r.stderr).strip()


def would(*args, stdin=""):
    code, out = run(*args, stdin=stdin)
    return code, [line[len("would run: "):] for line in out.splitlines() if line.startswith("would run: ")]


expect("realname with accents", would("realname", "ana", "Ana Lúcia Mendes"), (0, ["chfn -f Ana Lúcia Mendes ana"])
       if shutil.which("chfn") else (0, ["usermod -c Ana Lúcia Mendes ana"]))
expect("password from stdin", run("password", "ana", stdin="s3cret: with spaces\n")[0], 0)
code, out = run("password", "ana", stdin="")
expect("empty password refused", code != 0, True)
expect("add admin", would("add", "maria", "Maria Silva", "1", stdin="pw\n"),
       (0, ["useradd -m -c Maria Silva -G wheel maria"]))
expect("add normal", would("add", "joao", "João", "0", stdin="pw\n"), (0, ["useradd -m -c João joao"]))
expect("delete other, keep home", would("delete", "ana", "keep"), (0, ["userdel ana"]))
expect("delete other, remove home", would("delete", "ana", "remove"), (0, ["userdel -r ana"]))
expect("admin on", would("admin", "ana", "1"), (0, ["gpasswd -a ana wheel"]))
expect("groups set exactly", would("groups", "ana", "audio", "input"),
       (0, ["gpasswd -a ana audio", "gpasswd -d ana video", "gpasswd -a ana input"]))
expect("shell", would("shell", "leo", "/usr/bin/fish"), (0, ["usermod -s /usr/bin/fish leo"]))
expect("rename other", would("rename", "ana", "anas"),
       (0, ["usermod -l anas -d /home/anas -m ana", "groupmod -n anas ana"]))
expect("icon", would("icon", "leo", png)[0], 0)
os.symlink(png, os.path.join(tmp, "link.png"))
expect("icon through a symlink refused", run("icon", "leo", os.path.join(tmp, "link.png"))[0] != 0, True)
users_dir = os.path.join(tmp, "as", "users")
os.makedirs(users_dir)
write("as/users/ana", "[User]\nIcon=x\n")
icons = os.path.join(tmp, "as", "icons")
expect("rename takes AccountsService's settings along", would("rename", "ana", "anas")[1][2:],
       [f"mv -f {users_dir}/ana {users_dir}/anas",
        f"sed -i s|^Icon={icons}/ana$|Icon={icons}/anas| {users_dir}/anas"])
expect("delete drops them", would("delete", "ana", "keep")[1], ["userdel ana", f"rm -f {users_dir}/ana"])
os.remove(os.path.join(users_dir, "ana"))

for args, why, stdin in (
        (["realname", "root", "x"], "root", ""),
        (["realname", "bin", "x"], "system account", ""),
        (["realname", "ana", "a:b"], "colon in name", ""),
        (["realname", "ana", "a,b"], "comma in name", ""),
        (["realname", "ana", "a\nb"], "newline in name", ""),
        (["realname", "../x", "a"], "path as user", ""),
        (["realname", "-r", "a"], "option as user", ""),
        (["password", "root"], "root password", "x\n"),
        (["add", "ana", "Ana", "0"], "existing user", "pw\n"),
        (["add", "Bad", "x", "0"], "upper case", "pw\n"),
        (["add", "x;rm", "x", "0"], "shell chars", "pw\n"),
        (["add", "new", "x", "2"], "bad admin flag", "pw\n"),
        (["delete", "leo", "keep"], "deleting yourself", ""),
        (["delete", "ana", "maybe"], "bad delete mode", ""),
        (["admin", "leo", "0"], "removing your own admin", ""),
        (["groups", "ana", "wheel"], "wheel via groups", ""),
        (["groups", "ana", "secret"], "not an optional group", ""),
        (["shell", "ana", "/tmp/evil"], "shell not in /etc/shells", ""),
        (["shell", "ana", "bash"], "relative shell", ""),
        (["rename", "leo", "leo2"], "renaming yourself", ""),
        (["rename", "ana", "leo"], "rename onto existing", ""),
        (["icon", "ana", os.path.join(tmp, "passwd")], "icon not an image", ""),
        (["nuke", "ana"], "unknown command", "")):
    code, _out = run(*args, stdin=stdin)
    expect(f"refuses {why}", code != 0, True)

# (as root, the caller comes only from pkexec's PKEXEC_UID; without it the helper refuses to run)

# the Python side
from xcontrol import users as U  # noqa: E402
os.environ.update(XCONTROL_PASSWD=env["XCONTROL_PASSWD"], XCONTROL_GROUP=env["XCONTROL_GROUP"],
                  XCONTROL_SHELLS=env["XCONTROL_SHELLS"], XCONTROL_LOGINDEFS=env["XCONTROL_LOGINDEFS"])
us = U.list_users()
expect("regular users only", [u.name for u in us], ["leo", "ana"])
leo = us[0]
expect("full name from GECOS", leo.full_name, "Leo")
expect("admin", (leo.admin, us[1].admin), (True, False))
expect("groups", us[1].groups, ["video"])
expect("shells", U.shells(), ["/bin/sh", "/bin/bash", "/bin/zsh", "/usr/bin/fish"])
expect("name check", [U.check_username(n) for n in ("maria", "Maria", "1abc", "a" * 33, "ok_name-2")],
       [None, "chars", "chars", "long", None])
expect("full name check", [U.check_full_name(n) for n in ("Ana Lúcia", "a:b", "x" * 101)], [None, "chars", "long"])
expect("strength", [U.strength(p) for p in ("", "abc", "abcdefgh", "Tr0ub4dor&3xyz", "correct horse battery staple")],
       [0, 1, 2, 3, 3])

print("check_user_helper:", "FAILED" if bad else "ok")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
