"""Which program has the focus: the names a per-game controller layout can match.

For the focused window (_NET_ACTIVE_WINDOW) it gives its WM_CLASS (instance and class, e.g.
"steam_app_1245620") and the program behind it (_NET_WM_PID: its process name, its executable and
its first argument, e.g. "eldenring.exe" for a Proton game). Errors from a window that closes while
being read are ignored (Xlib's default handler would end the program).
"""
import ctypes
import ctypes.util
import fnmatch
import os


def process_names(pid, proc="/proc"):
    """Names a process goes by: its comm, its executable's file name, and its first argument's
    (Windows paths too: "Z:\\games\\Elden Ring\\eldenring.exe" -> "eldenring.exe")."""
    names = []

    def add(n):
        n = (n or "").strip()
        if n and n not in names:
            names.append(n)
    try:
        with open(os.path.join(proc, str(pid), "comm"), errors="replace") as f:
            add(f.read())
    except OSError:
        pass
    try:
        add(os.path.basename(os.readlink(os.path.join(proc, str(pid), "exe"))))
    except OSError:
        pass
    try:
        with open(os.path.join(proc, str(pid), "cmdline"), "rb") as f:
            argv0 = f.read().split(b"\0")[0].decode(errors="replace")
        add(argv0.replace("\\", "/").rsplit("/", 1)[-1])
    except OSError:
        pass
    return names


def matches(patterns, names):
    """Whether any of the names fits any pattern (case doesn't matter; * and ? work)."""
    lowered = [n.lower() for n in names if n]
    return any(fnmatch.fnmatchcase(n, p.strip().lower()) for p in patterns if p.strip() for n in lowered)


class Focus:
    """A connection to X for reading the focused window. `names()` is [] when there's none."""

    def __init__(self, display=None):
        self.dpy = None
        lib = ctypes.util.find_library("X11")
        if not lib or not (display or os.environ.get("DISPLAY")):
            return
        x = ctypes.CDLL(lib)
        vp, ul, i = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int
        for fn, res, args in (("XOpenDisplay", vp, [ctypes.c_char_p]), ("XCloseDisplay", i, [vp]),
                              ("XDefaultRootWindow", ul, [vp]), ("XInternAtom", ul, [vp, ctypes.c_char_p, i]),
                              ("XGetWindowProperty", i, [vp, ul, ul, ctypes.c_long, ctypes.c_long, i, ul,
                                                         ctypes.POINTER(ul), ctypes.POINTER(i), ctypes.POINTER(ul),
                                                         ctypes.POINTER(ul), ctypes.POINTER(vp)]),
                              ("XGetClassHint", i, [vp, ul, vp]), ("XFree", i, [vp]),
                              ("XSetErrorHandler", vp, [vp])):
            f = getattr(x, fn)
            f.restype, f.argtypes = res, args
        self.x = x
        self._handler = ctypes.CFUNCTYPE(i, vp, vp)(lambda d, e: 0)
        x.XSetErrorHandler(ctypes.cast(self._handler, vp))
        self.dpy = x.XOpenDisplay(display.encode() if display else None)
        if self.dpy:
            self.root = x.XDefaultRootWindow(self.dpy)
            self.atoms = {n: x.XInternAtom(self.dpy, n, 0) for n in (b"_NET_ACTIVE_WINDOW", b"_NET_WM_PID")}

    def _card(self, window, atom, xtype):
        x = self.x
        t, fmt, n, after, data = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), \
            ctypes.c_void_p()
        if x.XGetWindowProperty(self.dpy, window, atom, 0, 1, 0, xtype, ctypes.byref(t), ctypes.byref(fmt),
                                ctypes.byref(n), ctypes.byref(after), ctypes.byref(data)) != 0 or not data.value:
            return 0
        try:
            return ctypes.c_ulong.from_address(data.value).value if n.value and fmt.value == 32 else 0
        finally:
            x.XFree(data)

    def names(self):
        if not self.dpy:
            return []
        win = self._card(self.root, self.atoms[b"_NET_ACTIVE_WINDOW"], 0)    # (any type: WINDOW, as WMs set it)
        if not win:
            return []
        out = []

        class Hint(ctypes.Structure):
            _fields_ = [("name", ctypes.c_void_p), ("klass", ctypes.c_void_p)]
        h = Hint()
        if self.x.XGetClassHint(self.dpy, win, ctypes.byref(h)):
            for p in (h.name, h.klass):
                if p:
                    s = ctypes.string_at(p).decode(errors="replace")
                    if s and s not in out:
                        out.append(s)
                    self.x.XFree(p)
        pid = self._card(win, self.atoms[b"_NET_WM_PID"], 0)
        if pid:
            out += [n for n in process_names(pid) if n not in out]
        return out

    def close(self):
        if self.dpy:
            self.x.XCloseDisplay(self.dpy)
            self.dpy = None
