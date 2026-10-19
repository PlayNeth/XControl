"""Wallpaper without feh: draw the picture(s) with cairo and make them the X root window's
background the way feh/Esetroot do, so compositors (picom) and pseudo-transparent terminals
see it too.

The root background is a pixmap that has to outlive the program that made it: it's created
on a connection set to RetainPermanent and published in _XROOTPMAP_ID and ESETROOT_PMAP_ID.
The previous one is freed with XKillClient when it was published the same way.
"""
import ctypes
import ctypes.util
import os

import cairo
import gi
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf  # noqa: E402

MODES = ["fill", "fit", "center", "tile", "stretch"]
LAYOUTS = ["same", "span", "separate"]   # same picture on each display / one across all / one per display
DEFAULT = {"layout": "same", "file": "", "mode": "fill", "color": "#202020", "monitors": {}}


def normalize(w):
    out = dict(DEFAULT)
    if isinstance(w, dict):
        out.update({k: v for k, v in w.items() if k in DEFAULT})
    if out["layout"] not in LAYOUTS:
        out["layout"] = "same"
    if out["mode"] not in MODES:
        out["mode"] = "fill"
    mons = out.get("monitors") if isinstance(out.get("monitors"), dict) else {}
    out["monitors"] = {str(k): {"file": str(v.get("file", "")),
                                "mode": v.get("mode") if v.get("mode") in MODES else "fill"}
                       for k, v in mons.items() if isinstance(v, dict)}
    return out


def parse_color(text):
    text = (text or "").lstrip("#")
    try:
        if len(text) == 6:
            return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        pass
    return (0.125, 0.125, 0.125)


# ---------------------------------------------------------------- geometry
def placement(img_w, img_h, w, h, mode):
    """Where the picture goes inside a w×h area: (draw_w, draw_h, x, y) relative to the
    area's corner. Areas outside the picture show the background color; fill crops."""
    if mode == "stretch":
        return w, h, 0, 0
    if mode in ("center", "tile"):
        return img_w, img_h, (w - img_w) // 2 if mode == "center" else 0, (h - img_h) // 2 if mode == "center" else 0
    sx, sy = w / img_w, h / img_h
    s = max(sx, sy) if mode == "fill" else min(sx, sy)
    dw, dh = max(1, round(img_w * s)), max(1, round(img_h * s))
    return dw, dh, (w - dw) // 2, (h - dh) // 2


def areas(wp, monitors, screen_w, screen_h):
    """[(x, y, w, h, file, mode)] for the enabled displays (monitors: [(name, x, y, w, h)])."""
    if not monitors:
        monitors = [("", 0, 0, screen_w, screen_h)]
    if wp["layout"] == "span":
        x0 = min(m[1] for m in monitors)
        y0 = min(m[2] for m in monitors)
        x1 = max(m[1] + m[3] for m in monitors)
        y1 = max(m[2] + m[4] for m in monitors)
        return [(x0, y0, x1 - x0, y1 - y0, wp["file"], wp["mode"])]
    out = []
    for name, x, y, w, h in monitors:
        if wp["layout"] == "separate" and name in wp["monitors"]:
            m = wp["monitors"][name]
            out.append((x, y, w, h, m["file"], m["mode"]))
        else:
            out.append((x, y, w, h, wp["file"], wp["mode"]))
    return out


_PIXBUFS = {}


def _load(path, size=None):
    """Pixbuf for `path` (EXIF rotation applied), scaled to `size` when given; cached."""
    key = (path, os.path.getmtime(path), size)
    pb = _PIXBUFS.get(key)
    if pb is None:
        base_key = (path, key[1], None)
        base = _PIXBUFS.get(base_key)
        if base is None:
            base = GdkPixbuf.Pixbuf.new_from_file(path).apply_embedded_orientation()
            _PIXBUFS.clear()
            _PIXBUFS[base_key] = base
        pb = base if size is None or size == (base.get_width(), base.get_height()) else \
            base.scale_simple(size[0], size[1], GdkPixbuf.InterpType.BILINEAR)
        _PIXBUFS[key] = pb
    return pb


def compose(wp, monitors, screen_w, screen_h, scale=1.0):
    """The whole root window as a cairo RGB24 surface (scale < 1 for previews).
    Returns (surface, [errors])."""
    sw, sh = max(1, round(screen_w * scale)), max(1, round(screen_h * scale))
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, sw, sh)
    cr = cairo.Context(surf)
    cr.set_source_rgb(*parse_color(wp["color"]))
    cr.paint()
    errors = []
    for x, y, w, h, path, mode in areas(wp, monitors, screen_w, screen_h):
        if not path:
            continue
        try:
            base = _load(path)
        except Exception as e:  # noqa: BLE001
            errors.append((path, str(e)))
            continue
        ax, ay = round(x * scale), round(y * scale)
        aw, ah = max(1, round((x + w) * scale) - ax), max(1, round((y + h) * scale) - ay)
        iw, ih = base.get_width(), base.get_height()
        cr.save()
        cr.rectangle(ax, ay, aw, ah)
        cr.clip()
        if mode == "tile":
            tw, th = max(1, round(iw * scale)), max(1, round(ih * scale))
            Gdk.cairo_set_source_pixbuf(cr, _load(path, (tw, th) if scale != 1 else None), ax, ay)
            cr.get_source().set_extend(cairo.EXTEND_REPEAT)
            cr.paint()
        else:
            dw, dh, ox, oy = placement(iw, ih, w, h, mode)
            dw, dh = max(1, round(dw * scale)), max(1, round(dh * scale))
            Gdk.cairo_set_source_pixbuf(cr, _load(path, (dw, dh)), ax + round(ox * scale), ay + round(oy * scale))
            cr.paint()
        cr.restore()
    surf.flush()
    return surf, errors


# ---------------------------------------------------------------- the X root window
class _X:
    """The few Xlib calls needed, through ctypes."""

    def __init__(self):
        name = ctypes.util.find_library("X11") or "libX11.so.6"
        x = ctypes.CDLL(name)
        vp, ul, i, ui = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
        for fn, res, args in (
                ("XOpenDisplay", vp, [ctypes.c_char_p]), ("XCloseDisplay", i, [vp]),
                ("XDefaultScreen", i, [vp]), ("XRootWindow", ul, [vp, i]),
                ("XDefaultDepth", i, [vp, i]), ("XDefaultVisual", vp, [vp, i]),
                ("XDisplayWidth", i, [vp, i]), ("XDisplayHeight", i, [vp, i]),
                ("XCreatePixmap", ul, [vp, ul, ui, ui, ui]),
                ("XCreateImage", vp, [vp, vp, ui, i, i, ctypes.c_char_p, ui, ui, i, i]),
                ("XCreateGC", vp, [vp, ul, ul, vp]), ("XFreeGC", i, [vp, vp]),
                ("XPutImage", i, [vp, ul, vp, vp, i, i, i, i, ui, ui]),
                ("XInternAtom", ul, [vp, ctypes.c_char_p, i]),
                ("XGetWindowProperty", i, [vp, ul, ul, ctypes.c_long, ctypes.c_long, i, ul,
                                           ctypes.POINTER(ul), ctypes.POINTER(i), ctypes.POINTER(ul),
                                           ctypes.POINTER(ul), ctypes.POINTER(vp)]),
                ("XChangeProperty", i, [vp, ul, ul, ul, i, i, vp, i]),
                ("XSetWindowBackgroundPixmap", i, [vp, ul, ul]), ("XClearWindow", i, [vp, ul]),
                ("XKillClient", i, [vp, ul]), ("XSetCloseDownMode", i, [vp, i]),
                ("XFree", i, [vp]), ("XFlush", i, [vp]), ("XSync", i, [vp, i]),
                ("XSetErrorHandler", vp, [vp])):
            f = getattr(x, fn)
            f.restype, f.argtypes = res, args
        self.x = x
        # a stale pixmap id in the properties must not kill us with BadPixmap/BadValue
        self._handler = ctypes.CFUNCTYPE(i, vp, vp)(lambda d, e: 0)
        x.XSetErrorHandler(ctypes.cast(self._handler, vp))

    def get_pixmap_prop(self, dpy, root, atom):
        x = self.x
        typ, fmt = ctypes.c_ulong(), ctypes.c_int()
        n, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        XA_PIXMAP = 20
        if x.XGetWindowProperty(dpy, root, atom, 0, 1, 0, XA_PIXMAP, ctypes.byref(typ), ctypes.byref(fmt),
                                ctypes.byref(n), ctypes.byref(after), ctypes.byref(data)) != 0:
            return 0
        try:
            if typ.value == XA_PIXMAP and fmt.value == 32 and n.value == 1 and data.value:
                return ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0]
            return 0
        finally:
            if data.value:
                x.XFree(data)


def screen_size(display=None):
    X = _X()
    dpy = X.x.XOpenDisplay(display.encode() if display else None)
    if not dpy:
        raise RuntimeError("cannot open the X display")
    try:
        scr = X.x.XDefaultScreen(dpy)
        return X.x.XDisplayWidth(dpy, scr), X.x.XDisplayHeight(dpy, scr)
    finally:
        X.x.XCloseDisplay(dpy)


def set_root(surface, display=None):
    """Make `surface` (RGB24, the root window's size) the desktop background."""
    X = _X()
    x = X.x
    dpy = x.XOpenDisplay(display.encode() if display else None)
    if not dpy:
        raise RuntimeError("cannot open the X display")
    try:
        scr = x.XDefaultScreen(dpy)
        root = x.XRootWindow(dpy, scr)
        depth = x.XDefaultDepth(dpy, scr)
        if depth not in (24, 32):
            raise RuntimeError(f"unsupported screen depth {depth}")
        w, h = surface.get_width(), surface.get_height()
        stride = surface.get_stride()
        buf = ctypes.create_string_buffer(bytes(surface.get_data()), stride * h)
        img = x.XCreateImage(dpy, x.XDefaultVisual(dpy, scr), depth, 2, 0, buf, w, h, 32, stride)  # ZPixmap
        if not img:
            raise RuntimeError("XCreateImage failed")
        pix = x.XCreatePixmap(dpy, root, w, h, depth)
        gc = x.XCreateGC(dpy, pix, 0, None)
        x.XPutImage(dpy, pix, gc, img, 0, 0, 0, 0, w, h)
        x.XFreeGC(dpy, gc)
        x.XFree(img)  # the struct only; buf belongs to Python

        a_root = x.XInternAtom(dpy, b"_XROOTPMAP_ID", 0)
        a_eset = x.XInternAtom(dpy, b"ESETROOT_PMAP_ID", 0)
        old_root, old_eset = X.get_pixmap_prop(dpy, root, a_root), X.get_pixmap_prop(dpy, root, a_eset)
        if old_root and old_root == old_eset:
            x.XKillClient(dpy, old_root)  # frees the previous background (Esetroot convention)
            x.XSync(dpy, 0)
        val = ctypes.c_ulong(pix)
        for atom in (a_root, a_eset):
            x.XChangeProperty(dpy, root, atom, 20, 32, 0, ctypes.byref(val), 1)  # XA_PIXMAP, replace
        x.XSetWindowBackgroundPixmap(dpy, root, pix)
        x.XClearWindow(dpy, root)
        x.XSetCloseDownMode(dpy, 1)  # RetainPermanent: the pixmap stays after we disconnect
        x.XSync(dpy, 0)
    finally:
        x.XCloseDisplay(dpy)


# ---------------------------------------------------------------- from the saved settings
def monitors():
    """[(name, x, y, w, h)] of the enabled displays, from xrandr."""
    from . import xrandr
    try:
        return [(m.name, m.x, m.y, *m.size()) for m in xrandr.query() if m.enabled and m.size()[0]]
    except Exception:  # noqa: BLE001
        return []


def apply(wp, lock_png=None):
    """Draw and set the wallpaper; optionally also save it as a PNG (the lock screen image).
    Returns errors [(file, message)]."""
    w, h = screen_size()
    surf, errors = compose(wp, monitors(), w, h)
    set_root(surf)
    if lock_png:
        os.makedirs(os.path.dirname(lock_png), exist_ok=True)
        surf.write_to_png(lock_png + ".tmp")
        os.replace(lock_png + ".tmp", lock_png)
    return errors


def has_picture(wp):
    if wp["layout"] == "separate":
        return bool(wp["file"]) or any(m["file"] for m in wp["monitors"].values())
    return bool(wp["file"])
