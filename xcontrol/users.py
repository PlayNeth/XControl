"""User accounts: read from /etc/passwd and /etc/group, changed through
xcontrol-user-helper (pkexec). Your own picture (~/.face) is written directly."""
import os
import pwd
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from .paths import LIBDIR

HELPER = os.path.join(LIBDIR, "xcontrol-user-helper")
# same list as the helper; anything else (wheel, the user's own group) is never touched here
OPTIONAL_GROUPS = ["audio", "video", "input", "storage", "optical", "scanner", "lp", "games", "network", "rfkill",
                   "uucp", "kvm", "libvirt", "docker", "wireshark"]
ADMIN_GROUP = "wheel"
NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]*$")


def _path(var, default):
    return os.environ.get(var) or default


def _rows(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n").split(":") for line in f if line.strip() and not line.startswith("#")]
    except OSError:
        return []


def uid_range():
    lo, hi = 1000, 60000
    try:
        with open(_path("XCONTROL_LOGINDEFS", "/etc/login.defs"), errors="replace") as f:
            for line in f:
                m = re.match(r"^\s*(UID_MIN|UID_MAX)\s+(\d+)", line)
                if m:
                    if m.group(1) == "UID_MIN":
                        lo = int(m.group(2))
                    else:
                        hi = int(m.group(2))
    except OSError:
        pass
    return lo, hi


@dataclass
class User:
    name: str
    uid: int
    full_name: str = ""
    home: str = ""
    shell: str = ""
    admin: bool = False
    groups: list = field(default_factory=list)   # optional groups the user is in
    me: bool = False

    def display(self):
        return self.full_name or self.name


def group_members():
    """{group: [members]} and the set of groups that exist."""
    members = {}
    for row in _rows(_path("XCONTROL_GROUP", "/etc/group")):
        if len(row) >= 4:
            members[row[0]] = [m for m in row[3].split(",") if m]
    return members


def list_users():
    lo, hi = uid_range()
    members = group_members()
    out = []
    for row in _rows(_path("XCONTROL_PASSWD", "/etc/passwd")):
        if len(row) < 7:
            continue
        try:
            uid = int(row[2])
        except ValueError:
            continue
        if not lo <= uid <= hi:
            continue
        u = User(name=row[0], uid=uid, full_name=row[4].split(",")[0].strip(), home=row[5], shell=row[6])
        u.admin = u.name in members.get(ADMIN_GROUP, [])
        u.groups = [g for g in OPTIONAL_GROUPS if u.name in members.get(g, [])]
        u.me = uid == os.getuid()
        out.append(u)
    return out


def available_groups():
    existing = group_members()
    return [g for g in OPTIONAL_GROUPS if g in existing]


def shells():
    out = []
    for line in _rows(_path("XCONTROL_SHELLS", "/etc/shells")):
        s = ":".join(line).strip()
        if s.startswith("/") and s not in out:
            out.append(s)
    return out


def check_username(name):
    """None, or 'chars' / 'long'."""
    if len(name) > 32:
        return "long"
    return None if NAME_RE.fullmatch(name) else "chars"


def check_full_name(name):
    if len(name) > 100:
        return "long"
    return "chars" if re.search(r"[:,=\n]", name) else None


def strength(pw):
    """0 empty, 1 weak, 2 fair, 3 good: a rough guide, not a guarantee."""
    if not pw:
        return 0
    classes = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^a-zA-Z0-9]"))
    if len(pw) < 8:
        return 1
    if len(pw) >= 16 or (len(pw) >= 12 and classes >= 3):
        return 3
    return 2


def logged_in(user):
    """Has running processes (then it can't be renamed or deleted)."""
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                if os.stat(f"/proc/{d}").st_uid == user.uid:
                    return True
            except OSError:
                continue
    return False


# ---- pictures
def picture_path(user):
    """The picture login screens use: AccountsService's, else ~/.face."""
    for path in (f"/var/lib/AccountsService/icons/{user.name}", os.path.join(user.home, ".face")):
        try:
            if os.path.isfile(path) and os.access(path, os.R_OK):
                return path
        except OSError:
            continue
    return None


def make_face(src, dest, size=192):
    """Square, scaled PNG for ~/.face (and AccountsService)."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(src).apply_embedded_orientation()
    w, h = pb.get_width(), pb.get_height()
    side = min(w, h)
    pb = pb.new_subpixbuf((w - side) // 2, (h - side) // 2, side, side).scale_simple(
        size, size, GdkPixbuf.InterpType.HYPER)
    tmp = dest + ".tmp"
    pb.savev(tmp, "png", [], [])
    os.replace(tmp, dest)
    return dest


def set_own_picture(path):
    """Your own picture for login screens, through AccountsService: it's allowed to change your
    own account's picture without a password. Returns (ok, message); not ok when AccountsService
    isn't running (then ~/.face, already written, is what greeters fall back to)."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        name = pwd.getpwuid(os.getuid()).pw_name
        obj = bus.call_sync("org.freedesktop.Accounts", "/org/freedesktop/Accounts", "org.freedesktop.Accounts",
                            "FindUserByName", GLib.Variant("(s)", (name,)), None, 0, 5000, None).unpack()[0]
        bus.call_sync("org.freedesktop.Accounts", obj, "org.freedesktop.Accounts.User", "SetIconFile",
                      GLib.Variant("(s)", (path,)), None, Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,
                      30000, None)
    except Exception as e:  # noqa: BLE001 - no AccountsService, or it refused
        return False, str(e)
    return True, ""


# ---- the helper
def can_change():
    return bool(shutil.which("pkexec")) and os.path.exists(HELPER)


def run_helper(*args, stdin=None):
    """(ok, message). The password, when there is one, goes through stdin only."""
    try:
        out = subprocess.run(["pkexec", HELPER, *args], input=stdin, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if out.returncode in (126, 127) and not out.stderr.strip():
        return False, "cancelled"
    text = (out.stdout + out.stderr).strip()
    text = re.sub(r"^xcontrol-user-helper: ", "", text.splitlines()[-1]) if text else ""
    return out.returncode == 0, text
