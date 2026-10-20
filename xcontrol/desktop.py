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

from . import awake, bar, compositor, config, night, notify, power, poweralerts, wallpaper

LOCKERS = ["i3lock", "xsecurelock", "slock"]
LOCK_DEFAULT = {"enabled": False, "locker": "i3lock", "image": "wallpaper", "color": "#000000",
                "idle_minutes": 10, "lock_on_sleep": True, "show_failed": True}
BLANK_DEFAULT = {"managed": False, "screen_off_minutes": 15}
AWAKE_DEFAULT = {"gamepads": False, "apps": False, "fullscreen": False}


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
    awake = {k: bool((d.get("awake") or {}).get(k, v)) for k, v in AWAKE_DEFAULT.items()}
    return {"wallpaper": wp, "lock": lock, "blanking": blank, "awake": awake, "notify": notify.normalize(d.get("notify")),
            "night": night.normalize(d.get("night")),
            "power": power.normalize(d.get("power")), "power_alerts": poweralerts.normalize(d.get("power_alerts")),
            "bar": bar.normalize(d.get("bar")), "picom": compositor.normalize(d.get("picom"))}


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


def _controllers():
    from . import pad_service
    return pad_service.load()


def wanted(desk):
    """Whether the background service is needed at all."""
    return bool(desk["wallpaper"]["enabled"] or desk["lock"]["enabled"] or desk["blanking"]["managed"]
                or desk["bar"]["enabled"] or desk["picom"]["enabled"] or any(desk["awake"].values())
                or desk["notify"]["enabled"] or desk["power_alerts"]["enabled"] or desk["night"]["enabled"]
                or desk["power"]["sleep_minutes"]
                or night.forced(_runtime) is not None or _controllers()["enabled"]
                or awake.manual_until(_runtime) is not None)


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
    return foreign(["xss-lock"])


def session_conflicts():
    """Lines in the i3 config that would fight with these settings: [(kind, line)], kinds
    wallpaper, lock, bar, compositor and i3bar (an i3 `bar { }` block)."""
    out = []
    for path in (os.path.expanduser("~/.config/i3/config"), os.path.expanduser("~/.i3/config")):
        try:
            with open(path, errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in lines:
            s = line.strip()
            if re.match(r"^bar\s*\{", s):
                out.append(("i3bar", s))
                continue
            if not s.startswith("exec"):
                continue
            if "xcontrol" in s:
                continue
            if re.search(r"\b(feh|nitrogen|xwallpaper|hsetroot|xsetroot\s+-solid)\b|\.fehbg", s):
                out.append(("wallpaper", s))
            elif re.search(r"\b(xss-lock|xautolock|xidlehook)\b", s):
                out.append(("lock", s))
            elif re.search(r"\bpolybar\b|launch\.sh", s):
                out.append(("bar", s))
            elif re.search(r"\b(picom|compton|xcompmgr)\b", s):
                out.append(("compositor", s))
            elif re.search(r"\b(dunst|xfce4-notifyd|notify-osd|notification-daemon|deadd-notification-center|"
                           r"lxqt-notificationd|twmnd)\b", s):
                out.append(("notifications", s))
            elif re.search(r"\bpoweralertd\b", s):
                out.append(("power_alerts", s))
        break
    return out


def foreign(names):
    """Running programs (by name) that XControl's service didn't start: {pid: command line}."""
    ours = set((state().get("children") or {}).values())
    out = {}
    for name in names:
        out.update({pid: cmd for pid, cmd in _user_procs(name).items() if pid not in ours})
    return out


def stop_foreign(names):
    """Stop bars or compositors started elsewhere so XControl's can run."""
    for pid in foreign(names):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def child_errors():
    """{child: last error line} for programs that exited right after starting."""
    return state().get("errors") or {}


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


def set_awake(how):
    """xcontrol --awake on|off|toggle|MINUTES: keep the screen on by hand (the service holds it)."""
    until = awake.manual_until(_runtime) if how == "status" else awake.set_manual(_runtime, how)
    if how != "status":
        notify_daemon(load())
    return until


def set_night(how):
    """xcontrol --night on|off|toggle|auto (on/off last until the schedule next changes)."""
    desk = load()
    if how == "status":
        return night.forced(_runtime, desk["night"])
    result = night.set_forced(_runtime, how, desk["night"])
    notify_daemon(desk)   # a reload looks at the night light right away
    return result


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


class _Child:
    """A program the service keeps running: restarted when it dies (not faster than every
    5 s), its stderr kept so the page can say why it stopped."""

    def __init__(self, key, cmd, env=None):
        self.key, self.cmd, self.env = key, cmd, env or {}
        self.proc = None
        self.started = 0.0
        self.error = ""

    def log_path(self):
        return _runtime(re.sub(r"[^A-Za-z0-9_.-]", "_", self.key) + ".log")

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def ensure(self):
        if self.alive():
            return
        if self.proc is not None:  # it exited: keep the reason
            self.error = self._last_error()
            if time.time() - self.started > 30:
                self.error = ""  # ran fine for a while; just restart it
        if time.time() - self.started < 5:
            return
        try:
            log = open(self.log_path(), "w")
        except OSError:
            log = subprocess.DEVNULL
        env = dict(os.environ, **self.env)
        try:
            self.proc = subprocess.Popen(self.cmd, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                         start_new_session=True, preexec_fn=_die_with_parent)
        except OSError as e:
            self.proc, self.error = None, str(e)
        self.started = time.time()
        if log is not subprocess.DEVNULL:
            log.close()

    def _last_error(self):
        try:
            with open(self.log_path(), errors="replace") as f:
                lines = [ln.strip() for ln in f if re.search(r"error|fatal|failed|cannot|could not", ln, re.I)]
        except OSError:
            lines = []
        if not lines:
            return f"exited with status {self.proc.returncode}"
        # the first error says why; later ones are usually "exiting..."; drop picom/polybar prefixes
        return re.sub(r"^\[[^\]]*\]\s*|^\w+\|\w+:\s*", "", lines[0])[:200]

    def stop(self):
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def _primary():
    from . import xrandr
    try:
        mons = [m for m in xrandr.query() if m.enabled]
    except Exception:  # noqa: BLE001
        return []
    return [m.name for m in mons if m.primary][:1] or [m.name for m in mons][:1]


def wanted_children(desk):
    """{key: (command, env)} of everything the service should be running now."""
    out = {}
    lock = desk["lock"]
    if lock["enabled"] and shutil.which("xss-lock") and lock["locker"] in installed_lockers():
        out["xss-lock"] = (xss_lock_command(lock, lock_image_path()), {})
    if desk["picom"]["enabled"] and shutil.which("picom"):
        out["picom"] = (compositor.command(), {})
    pads_cfg = _controllers()
    if pads_cfg["enabled"]:
        from . import pad_service
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out["pads"] = ([sys.executable, "-c", "import sys; from xcontrol.app import main; "
                        "sys.exit(main(['xcontrol', '--pads']))"],
                       {"PYTHONPATH": here + os.pathsep + os.environ.get("PYTHONPATH", ""),
                        # a different value restarts it with the new settings
                        "XCONTROL_PADS": json.dumps({k: v for k, v in pads_cfg.items()
                                                     if k not in pad_service.LIVE},
                                                    sort_keys=True)})
    if desk["notify"]["enabled"] and shutil.which("dunst"):
        out["dunst"] = (notify.command(), {})
    if desk["power_alerts"]["enabled"] and poweralerts.installed():
        out["poweralertd"] = (poweralerts.command(desk["power_alerts"]), {})
    b = desk["bar"]
    if b["enabled"] and shutil.which("polybar"):
        names = _primary() if b["displays"] == "primary" else [m[0] for m in wallpaper.monitors()]
        for name in names or [""]:
            cmd, env = bar.command(name)
            out[f"bar:{name}"] = (cmd, env)
    return out


_PR_SET_PDEATHSIG = 1


try:
    _prctl = ctypes.CDLL(None).prctl   # looked up now: after fork, the child only calls it
except (OSError, AttributeError):
    _prctl = None


def _die_with_parent():
    """In a child: get SIGTERM when the service goes away, however it ends (so a bar or a
    compositor never outlives it and then runs twice)."""
    if _prctl is not None:
        _prctl(_PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0)


# (the controller service ties itself to us too)
CHILD_PROGRAMS = {"polybar", "picom", "dunst", "xss-lock", "poweralertd"}


def _stop_leftovers():
    """Children a previous service left running (it was killed, or was an older XControl
    that didn't tie them to itself): stop them before starting our own."""
    try:
        with open(_runtime("json")) as f:
            old = json.load(f)
    except (OSError, ValueError):
        return []
    stopped = []
    for key, pid in (old.get("children") or {}).items():
        try:
            if os.stat(f"/proc/{pid}").st_uid != os.getuid():
                continue
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
        except (OSError, TypeError):
            continue
        if comm in CHILD_PROGRAMS:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped.append(key)
            except OSError:
                pass
    return stopped


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
    left = _stop_leftovers()
    if left:
        log(f"stopped what an earlier service left running: {', '.join(left)}")
        time.sleep(0.5)

    flags = {"reload": True, "quit": False}
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)   # (older XControl versions sent it; never die of it)
    signal.signal(signal.SIGHUP, lambda *_a: flags.update(reload=True))
    signal.signal(signal.SIGTERM, lambda *_a: flags.update(quit=True))
    signal.signal(signal.SIGINT, lambda *_a: flags.update(quit=True))

    rr = _RandR()
    children = {}
    desk = None
    redraw_at = None
    xidle = awake.XIdle(rr.x11, rr.dpy)
    pads = None          # awake.Gamepads while gamepads count as activity
    inhibit = None       # awake.InhibitService while apps may keep the screen on
    aw = {"reset": 0.0, "full_check": 0.0, "fullscreen": False}
    sleeper = power.IdleSleep()
    try:
        gamma = night.Gamma(rr.x11, rr.dpy)
    except (OSError, AttributeError) as e:
        gamma = None
        log(f"night light: {e}")
    nl = {"shown": 6500, "applied_at": 0.0, "gammas": {}, "touched": False, "now": False}

    def night_step(force_apply=False):
        """Move the displays' color toward what the night light wants (gradually: 300 K a second)."""
        if gamma is None:
            return
        n = desk["night"]
        want = night.target(n, _runtime)
        active = n["enabled"] or night.forced(_runtime, n) is not None
        if not active and not nl["touched"]:
            return
        cur = nl["shown"]
        step = want if abs(want - cur) <= 300 else cur + (300 if want > cur else -300)
        stale = time.time() - nl["applied_at"] >= 30    # something else (xrandr) may have reset the ramps
        if step != cur or force_apply or stale or nl["now"]:
            nl["now"] = False
            try:
                gamma.apply(step, nl["gammas"], skip=set(n["outputs"]))
            except Exception as e:  # noqa: BLE001
                log(f"night light: {e}")
            nl["shown"], nl["applied_at"], nl["touched"] = step, time.time(), True
            if not active and step == 6500:
                nl["touched"] = False   # back to normal: stop touching the ramps

    def keep_awake():
        """Why the screen should stay on now: [{"kind": ..., "name": ...}]."""
        reasons = []
        until = awake.manual_until(_runtime)
        if until is not None:
            reasons.append({"kind": "manual", "until": until})
        if inhibit:
            reasons += [{"kind": "app", "name": a} for a in inhibit.apps()]
        if desk["awake"]["fullscreen"]:
            if time.time() - aw["full_check"] >= 2:
                aw["full_check"] = time.time()
                aw["fullscreen"] = xidle.fullscreen()
            if aw["fullscreen"]:
                reasons.append({"kind": "fullscreen"})
        return reasons

    def awake_setup():
        nonlocal pads, inhibit
        a = desk["awake"]
        if a["gamepads"] and pads is None:
            pads = awake.Gamepads()
        elif not a["gamepads"] and pads is not None:
            pads.close()
            pads = None
        if a["apps"] and inhibit is None:
            try:
                inhibit = awake.InhibitService(on_activity=xidle.activity)
            except Exception as e:  # noqa: BLE001
                log(f"screensaver service: {e}")
        elif not a["apps"] and inhibit is not None:
            inhibit.close()
            inhibit = None

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

    def reconcile(restart=()):
        """Start, stop or restart children to match the settings (keys in `restart` are
        restarted even when unchanged, e.g. picom after its config changed)."""
        want = wanted_children(desk)
        for key in list(children):
            c = children[key]
            if key not in want or (want[key][0], want[key][1]) != (c.cmd, c.env) or key in restart:
                c.stop()
                del children[key]
                log(f"stopped {key}")
        for key, (cmd, env) in want.items():
            if key not in children:
                children[key] = _Child(key, cmd, env)

    def write_configs():
        changed = set()
        if desk["picom"]["enabled"] and compositor.write(desk["picom"]):
            changed.add("picom")      # picom reads its config once; polybar reloads by itself
        if desk["bar"]["enabled"]:
            bar.write(desk["bar"])
        if desk["notify"]["enabled"] and notify.write(desk["notify"]):
            changed.add("dunst")      # dunst reads its config when it starts
        return changed

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
                reconcile(restart=write_configs())
                awake_setup()
                nl["gammas"] = night.saved_gamma(config.load()["display"]["command"])
                night_step(force_apply=True)
            for c in children.values():
                c.ensure()
            if inhibit:
                inhibit.pump()
            if pads:
                pads.rescan()
            night_step()
            reasons = keep_awake()
            if desk["power"]["sleep_minutes"] and time.time() - aw.get("sleep_check", 0) >= 5:
                aw["sleep_check"] = time.time()
                if sleeper.check(desk["power"], xidle.idle_ms(), bool(reasons), time.time()):
                    log("idle: suspending")
                    power.suspend()
            xidle.suspend(bool(reasons))
            st = {"daemon": os.getpid(),
                  "children": {k: c.proc.pid for k, c in children.items() if c.alive()},
                  "errors": {k: c.error for k, c in children.items() if c.error},
                  "awake": {"reasons": reasons, "gamepads": pads.details() if pads else [],
                            "denied": sorted(set(pads.denied.values())) if pads else [],
                            "last_gamepad": pads.last if pads else 0,
                            "service": ("" if inhibit is None else "ok" if inhibit.owned else
                                        inhibit.error or "starting")},
                  "night": {"shown": nl["shown"], "forced": night.forced(_runtime, desk["night"])}}
            st["xss_lock"] = st["children"].get("xss-lock")
            if st != aw.get("written"):
                _write_state(st)
                aw["written"] = st
            pad_fds = pads.fds() if pads else []
            try:
                ready, _w, _x = select.select([rr.fd] + pad_fds, [], [], 1.0)
            except InterruptedError:
                ready = []
            moved = False
            for fd in ready:
                if fd in pad_fds and pads.read(fd):
                    moved = True
            if moved and time.time() - aw["reset"] >= 10:   # a gamepad counts like a key press
                aw["reset"] = time.time()
                xidle.activity()
            if rr.fd in ready or rr.x11.XPending(rr.dpy):
                if rr.changed():
                    redraw_at = time.time() + 0.8  # wait for the layout change to settle
            if redraw_at and time.time() >= redraw_at:
                redraw_at = None
                log("screen changed")
                draw()
                night_step(force_apply=True)   # new displays get the current color too
                # bars follow the displays: restart them on any layout change
                reconcile(restart={k for k in children if k.startswith("bar:")})
    finally:
        for c in children.values():
            c.stop()
        if pads:
            pads.close()
        if inhibit:
            inhibit.close()
        if gamma is not None and nl["touched"]:
            try:
                gamma.apply(6500, nl["gammas"], skip=set(desk["night"]["outputs"]) if desk else ())
            except Exception:  # noqa: BLE001
                pass
        try:
            os.remove(_runtime("json"))
        except OSError:
            pass
    return 0
