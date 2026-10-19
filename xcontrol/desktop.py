"""Desktop settings: wallpaper, screen blanking and the screen lock.

The lock screen itself is an existing locker (i3lock, xsecurelock or slock), started by
xss-lock: it locks when X's screen saver kicks in after the idle time, before suspend and
hibernate (holding the sleep until the locker is up), and on `loginctl lock-session`.

`xcontrol --desktop-daemon` runs for the whole session (started at login): it sets the
wallpaper, redraws it when displays change (RandR), applies blanking, and keeps xss-lock
running. SIGHUP makes it re-read the settings.
"""
import ctypes
import ctypes.util
import fcntl
import glob
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time

from . import config, wallpaper

LOCKERS = ["i3lock", "xsecurelock", "slock"]
LOCK_DEFAULT = {"enabled": False, "locker": "i3lock", "image": "wallpaper", "color": "#000000",
                "idle_minutes": 10, "lock_on_sleep": True, "show_failed": True}
BLANK_DEFAULT = {"managed": False, "screen_off_minutes": 15}


def normalize(d):
    d = d if isinstance(d, dict) else {}
    wp = wallpaper.normalize(d.get("wallpaper"))
    wp["enabled"] = bool((d.get("wallpaper") or {}).get("enabled", False))
    lock = dict(LOCK_DEFAULT)
    lock.update({k: v for k, v in (d.get("lock") or {}).items() if k in LOCK_DEFAULT})
    if lock["locker"] not in LOCKERS:
        lock["locker"] = "i3lock"
    if lock["image"] not in ("wallpaper", "color"):
        lock["image"] = "wallpaper"
    for k in ("idle_minutes",):
        lock[k] = max(0, int(lock[k] or 0))
    blank = dict(BLANK_DEFAULT)
    blank.update({k: v for k, v in (d.get("blanking") or {}).items() if k in BLANK_DEFAULT})
    blank["screen_off_minutes"] = max(0, int(blank["screen_off_minutes"] or 0))
    return {"wallpaper": wp, "lock": lock, "blanking": blank}


def load():
    return normalize(config.load().get("desktop"))


def save(desk):
    data = config.load()
    data["desktop"] = desk
    config.save(data)


# ---------------------------------------------------------------- commands
def lock_image_path():
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(cache, "xcontrol", "lock.png")


def installed_lockers():
    return [name for name in LOCKERS if shutil.which(name)]


def locker_command(lock, png=None):
    """The locker, staying in the foreground (xss-lock waits for it to exit)."""
    if lock["locker"] == "i3lock":
        cmd = ["i3lock", "--nofork", "--ignore-empty-password"]
        if lock["image"] == "wallpaper" and png and os.path.exists(png):
            cmd += ["--image", png]
        else:
            cmd += ["--color", lock["color"].lstrip("#")[:6] or "000000"]
        if lock["show_failed"]:
            cmd.append("--show-failed-attempts")
        return cmd
    return [lock["locker"]]


def xss_lock_command(lock, png=None):
    cmd = ["xss-lock"]
    if lock["locker"] in ("i3lock", "xsecurelock"):
        cmd.append("--transfer-sleep-lock")   # suspend waits until the screen is locked
    if not lock["lock_on_sleep"]:
        cmd.append("--ignore-sleep")
    return cmd + ["--"] + locker_command(lock, png)


def xset_commands(desk):
    """xset calls for the idle lock and for turning the screen off."""
    out = []
    lock, blank = desk["lock"], desk["blanking"]
    if lock["enabled"]:
        if lock["idle_minutes"]:
            sec = str(lock["idle_minutes"] * 60)
            out.append(["xset", "s", sec, "5"])   # X's screen saver starts the lock; 5 s cycle
        else:
            out.append(["xset", "s", "off"])
    if blank["managed"]:
        if blank["screen_off_minutes"]:
            out.append(["xset", "+dpms", "dpms", "0", "0", str(blank["screen_off_minutes"] * 60)])
        else:
            out.append(["xset", "-dpms"])
    return out


def wanted(desk):
    """Whether the background service is needed at all."""
    return desk["wallpaper"]["enabled"] or desk["lock"]["enabled"] or desk["blanking"]["managed"]


# ---------------------------------------------------------------- state of the session
def _runtime(name):
    run = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    disp = re.sub(r"[^0-9.]", "", os.environ.get("DISPLAY", "")) or "0"
    return os.path.join(run, f"xcontrol-desktop-{disp}.{name}")


def state():
    """{"daemon": pid, "xss_lock": pid} of the running service, or {}."""
    try:
        with open(_runtime("json")) as f:
            st = json.load(f)
    except (OSError, ValueError):
        return {}
    pid = st.get("daemon")
    if not pid or not os.path.exists(f"/proc/{pid}"):
        return {}
    return st


def _write_state(st):
    tmp = _runtime("json") + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, _runtime("json"))


def _user_procs(name):
    out = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            if os.stat(d).st_uid != os.getuid():
                continue
            with open(os.path.join(d, "comm")) as f:
                if f.read().strip() != name:
                    continue
            with open(os.path.join(d, "cmdline"), "rb") as f:
                out[int(os.path.basename(d))] = " ".join(a.decode(errors="replace")
                                                         for a in f.read().split(b"\0") if a)
        except OSError:
            continue
    return out


def foreign_xss_lock():
    """xss-lock processes not started by XControl: {pid: command line}."""
    ours = state().get("xss_lock")
    return {pid: cmd for pid, cmd in _user_procs("xss-lock").items() if pid != ours}


def session_conflicts():
    """Lines in the i3 config that would fight with these settings: [(kind, line)]."""
    out = []
    for path in (os.path.expanduser("~/.config/i3/config"), os.path.expanduser("~/.i3/config")):
        try:
            with open(path, errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in lines:
            s = line.strip()
            if not s.startswith("exec"):
                continue
            if re.search(r"\b(feh|nitrogen|xwallpaper|hsetroot|xsetroot\s+-solid)\b|\.fehbg", s):
                out.append(("wallpaper", s))
            elif re.search(r"\b(xss-lock|xautolock|xidlehook)\b", s):
                out.append(("lock", s))
        break
    return out


def autostart_runs():
    """None when unknown; False when the session is i3 and nothing in its config runs
    ~/.config/autostart (dex) or XControl's services directly."""
    if not _user_procs("i3"):
        return None
    for path in (os.path.expanduser("~/.config/i3/config"), os.path.expanduser("~/.i3/config")):
        try:
            with open(path, errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        return bool(re.search(r"^\s*exec\S*\s.*\b(dex|xdg-autostart|xcontrol)\b", text, re.M))
    return None


def autostart_file():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", "xcontrol-desktop.desktop")


def sync_autostart(desk):
    path = autostart_file()
    if wanted(desk):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=XControl desktop (wallpaper, screen lock)\n"
                    "Exec=xcontrol --desktop-daemon\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n")
    elif os.path.exists(path):
        os.remove(path)


def notify_daemon(desk):
    """After the settings changed: reload the running service, start it, or stop it."""
    sync_autostart(desk)
    st = state()
    if st.get("daemon"):
        try:
            os.kill(st["daemon"], signal.SIGHUP if wanted(desk) else signal.SIGTERM)
            return "reloaded" if wanted(desk) else "stopped"
        except OSError:
            pass
    if wanted(desk):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [sys.executable, "-c", "import sys; from xcontrol.app import main; "
               "sys.exit(main(['xcontrol', '--desktop-daemon']))"]
        env = dict(os.environ, PYTHONPATH=here + os.pathsep + os.environ.get("PYTHONPATH", ""))
        subprocess.Popen(cmd, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "started"
    return "off"


def lock_now(desk=None):
    """Lock right away: through logind when XControl's xss-lock is running (same locker,
    same settings), otherwise by starting the locker directly."""
    desk = desk or load()
    if state().get("xss_lock") and shutil.which("loginctl"):
        if subprocess.run(["loginctl", "lock-session"], capture_output=True).returncode == 0:
            return True
    lock = desk["lock"]
    if lock["locker"] not in installed_lockers():
        return False
    subprocess.Popen(locker_command(lock, lock_image_path()), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


# ---------------------------------------------------------------- the service
class _RandR:
    """Wait for RandR screen changes on our own X connection (ctypes)."""

    def __init__(self):
        x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        xrr = ctypes.CDLL(ctypes.util.find_library("Xrandr") or "libXrandr.so.2")
        vp, i, ul = ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong
        x11.XOpenDisplay.restype, x11.XOpenDisplay.argtypes = vp, [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype, x11.XDefaultRootWindow.argtypes = ul, [vp]
        x11.XConnectionNumber.argtypes = [vp]
        x11.XPending.argtypes = [vp]
        x11.XNextEvent.argtypes = [vp, vp]
        xrr.XRRQueryExtension.argtypes = [vp, ctypes.POINTER(i), ctypes.POINTER(i)]
        xrr.XRRSelectInput.argtypes = [vp, ul, i]
        self.x11 = x11
        self.dpy = x11.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("cannot open the X display")
        ev, err = i(), i()
        self.base = ev.value if xrr.XRRQueryExtension(self.dpy, ctypes.byref(ev), ctypes.byref(err)) else None
        if self.base is not None:
            xrr.XRRSelectInput(self.dpy, x11.XDefaultRootWindow(self.dpy), 1)  # RRScreenChangeNotifyMask
        self.fd = x11.XConnectionNumber(self.dpy)
        self.event = ctypes.create_string_buffer(256)  # XEvent is 192 bytes

    def changed(self):
        """Drain events; True when the screen layout changed."""
        hit = False
        while self.x11.XPending(self.dpy):
            self.x11.XNextEvent(self.dpy, self.event)
            etype = ctypes.c_int.from_buffer(self.event).value
            if self.base is not None and etype == self.base:  # RRScreenChangeNotify
                hit = True
        return hit


def daemon():
    """xcontrol --desktop-daemon"""
    def log(msg):
        if os.environ.get("XCONTROL_DEBUG"):
            print(f"xcontrol-desktop: {msg}", file=sys.stderr, flush=True)

    try:
        lockf = os.open(_runtime("lock"), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("already running")
        return 0

    flags = {"reload": True, "quit": False}
    signal.signal(signal.SIGHUP, lambda *_a: flags.update(reload=True))
    signal.signal(signal.SIGTERM, lambda *_a: flags.update(quit=True))
    signal.signal(signal.SIGINT, lambda *_a: flags.update(quit=True))

    rr = _RandR()
    st = {"daemon": os.getpid(), "xss_lock": None}
    child, child_cmd, child_started = None, None, 0.0
    desk = None
    redraw_at = None

    def draw():
        wp, lock = desk["wallpaper"], desk["lock"]
        png = lock_image_path() if lock["enabled"] and lock["image"] == "wallpaper" else None
        if not (wp["enabled"] or png):
            return
        try:
            if wp["enabled"]:
                errors = wallpaper.apply(wp, lock_png=png)
            else:  # only the lock image is wanted
                w, h = wallpaper.screen_size()
                surf, errors = wallpaper.compose(wp, wallpaper.monitors(), w, h)
                os.makedirs(os.path.dirname(png), exist_ok=True)
                surf.write_to_png(png)
            for path, err in errors:
                log(f"{path}: {err}")
        except Exception as e:  # noqa: BLE001
            log(f"wallpaper: {e}")

    def stop_child():
        nonlocal child
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                child.kill()
        child = None
        st["xss_lock"] = None

    try:
        while not flags["quit"]:
            if flags["reload"]:
                flags["reload"] = False
                desk = load()
                if not wanted(desk):
                    break
                draw()
                for cmd in xset_commands(desk):
                    subprocess.run(cmd, capture_output=True)
                want = None
                if desk["lock"]["enabled"] and shutil.which("xss-lock") and \
                        desk["lock"]["locker"] in installed_lockers():
                    want = xss_lock_command(desk["lock"], lock_image_path())
                if want != child_cmd:
                    stop_child()
                    child_cmd = want
                    child_started = 0.0
            if child_cmd and (child is None or child.poll() is not None) and time.time() - child_started > 5:
                child = subprocess.Popen(child_cmd, stdin=subprocess.DEVNULL)  # restarted if it dies
                child_started = time.time()
                st["xss_lock"] = child.pid
                log(f"started {' '.join(child_cmd)}")
            _write_state(st)
            try:
                ready, _w, _x = select.select([rr.fd], [], [], 1.0)
            except InterruptedError:
                ready = []
            if ready or rr.x11.XPending(rr.dpy):
                if rr.changed():
                    redraw_at = time.time() + 0.8  # wait for the layout change to settle
            if redraw_at and time.time() >= redraw_at:
                redraw_at = None
                log("screen changed")
                draw()
    finally:
        stop_child()
        try:
            os.remove(_runtime("json"))
        except OSError:
            pass
    return 0
