"""Night light: warmer colors in the evening, through each display's gamma ramps (RandR).

The ramps are built on top of the gamma set on the Displays page (from the saved layout), so
both work together. The schedule follows the sun at your location (taken from the time zone
unless you set one) or fixed hours, with a gradual change either way.
"""
import ctypes
import ctypes.util
import datetime
import json
import math
import os
import re
import time

DEFAULT = {"enabled": False, "mode": "sun", "night_temp": 3600, "day_temp": 6500, "start": "20:00",
           "end": "07:00", "fade_minutes": 30, "latitude": None, "longitude": None, "outputs": []}
MODES = ["sun", "times", "always"]
TEMP_RANGE = (1500, 6500)


def normalize(n):
    out = dict(DEFAULT)
    if isinstance(n, dict):
        out.update({k: v for k, v in n.items() if k in DEFAULT})
    out["enabled"] = bool(out["enabled"])
    if out["mode"] not in MODES:
        out["mode"] = "sun"
    for k in ("night_temp", "day_temp"):
        try:
            out[k] = max(TEMP_RANGE[0], min(TEMP_RANGE[1], int(out[k])))
        except (TypeError, ValueError):
            out[k] = DEFAULT[k]
    for k in ("start", "end"):
        if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", str(out[k])):
            out[k] = DEFAULT[k]
    try:
        out["fade_minutes"] = max(0, min(180, int(out["fade_minutes"])))
    except (TypeError, ValueError):
        out["fade_minutes"] = DEFAULT["fade_minutes"]
    for k, lim in (("latitude", 90), ("longitude", 180)):
        try:
            out[k] = None if out[k] in (None, "") else max(-lim, min(lim, float(out[k])))
        except (TypeError, ValueError):
            out[k] = None
    out["outputs"] = [str(o) for o in out["outputs"] or []]   # left alone (e.g. a display used for color work)
    return out


# ---------------------------------------------------------------- color
def whitepoint(kelvin):
    """(r, g, b) multipliers for a color temperature, 6500 K = (1, 1, 1). Tanner Helland's fit
    of the blackbody colors, normalized to D65."""
    def raw(k):
        t = k / 100.0
        r = 255.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
        g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
        if t >= 66:
            b = 255.0
        elif t <= 19:
            b = 0.0
        else:
            b = 138.5177312231 * math.log(t - 10) - 305.0447927307
        return [max(0.0, min(255.0, c)) / 255.0 for c in (r, g, b)]
    ref = raw(6500)
    return tuple(min(1.0, c / rc) for c, rc in zip(raw(kelvin), ref))


def ramp(size, mult, gamma=1.0):
    """One channel's gamma ramp: xrandr's --gamma curve (value ** (1/gamma)) times `mult`."""
    if size < 2:
        return [65535] * size
    inv = 1.0 / max(0.1, gamma)
    return [min(65535, int(round(((i / (size - 1)) ** inv) * mult * 65535))) for i in range(size)]


# ---------------------------------------------------------------- where and when
def timezone_name():
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz:
        return tz
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return None
    m = re.search(r"zoneinfo/(.+)$", target)
    return m.group(1) if m else None


def _dms(text, deg_digits):
    sign = -1 if text[0] == "-" else 1
    d = text[1:]
    deg, minutes = int(d[:deg_digits]), int(d[deg_digits:deg_digits + 2])
    sec = int(d[deg_digits + 2:deg_digits + 4]) if len(d) > deg_digits + 2 else 0
    return sign * (deg + minutes / 60 + sec / 3600)


_LOCATIONS = {}   # (tz, tabs) -> location: the schedule asks every second in the desktop service


def location_from_timezone(tz=None, tabs=("/usr/share/zoneinfo/zone1970.tab", "/usr/share/zoneinfo/zone.tab")):
    """(latitude, longitude) of the time zone's main city, e.g. America/Sao_Paulo -> (-23.5, -46.6)."""
    tz = tz or timezone_name()
    if not tz:
        return None
    key = (tz, tuple(tabs))
    if key not in _LOCATIONS:
        _LOCATIONS[key] = _read_location(tz, tabs)
    return _LOCATIONS[key]


def _read_location(tz, tabs):
    for tab in tabs:
        try:
            with open(tab, errors="replace") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 3 and parts[2].strip() == tz:
                        m = re.match(r"^([+-]\d{4,6})([+-]\d{5,7})$", parts[1])
                        if m:
                            return round(_dms(m.group(1), 2), 4), round(_dms(m.group(2), 3), 4)
        except OSError:
            continue
    return None


def sun_elevation(when, lat, lon):
    """The sun's elevation in degrees (NOAA's approximation), `when` an aware datetime."""
    utc = when.astimezone(datetime.timezone.utc)
    day = utc.timetuple().tm_yday
    hour = utc.hour + utc.minute / 60 + utc.second / 3600
    g = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = hour * 60 + eqtime + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cos_zen = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zen))))


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def night_amount(n, now=None, location=None):
    """0 (day) .. 1 (night) by the schedule."""
    now = now or datetime.datetime.now().astimezone()
    if n["mode"] == "always":
        return 1.0
    if n["mode"] == "sun":
        loc = (n["latitude"], n["longitude"]) if n["latitude"] is not None and n["longitude"] is not None \
            else (location or location_from_timezone())
        if not loc:
            return 0.0
        e = sun_elevation(now, *loc)
        return max(0.0, min(1.0, (3.0 - e) / 9.0))   # like redshift: day above 3°, night below -6°
    t = now.hour * 60 + now.minute + now.second / 60
    start, end, fade = _minutes(n["start"]), _minutes(n["end"]), max(n["fade_minutes"], 0.001)

    def since(a):   # minutes since a (0..1440)
        return (t - a) % 1440
    night_len = (end - start) % 1440
    s = since(start)
    if s < night_len:                      # night (fading in during the first `fade` minutes)
        return min(1.0, s / fade) if n["fade_minutes"] else 1.0
    e = since(end)
    if n["fade_minutes"] and e < fade:     # fading out after the end (from where the fade-in got to)
        return max(0.0, min(1.0, night_len / fade) - e / fade)
    return 0.0


def temperature(n, amount):
    return round(n["day_temp"] + (n["night_temp"] - n["day_temp"]) * amount)


def next_change(n, now=None, location=None):
    """When the schedule next goes day->night or night->day (None for 'always'); for the page."""
    if n["mode"] == "always":
        return None
    local = now is None
    now = now or datetime.datetime.now().astimezone()
    if n["mode"] == "sun" and location is None and (n["latitude"] is None or n["longitude"] is None):
        location = location_from_timezone()   # once, not for each step
    was = night_amount(n, now, location) >= 0.5
    for step in range(1, 48 * 6):
        t = now + datetime.timedelta(minutes=5 * step)
        if local:   # astimezone() gave a fixed UTC offset: take a daylight saving change into account
            t = t.astimezone()
        if (night_amount(n, t, location) >= 0.5) != was:
            return t
    return None


# ---------------------------------------------------------------- by hand
def _force_path(runtime):
    return runtime("night")


def forced(runtime, n=None):
    """'on'/'off' when switched by hand (until the schedule next changes), else None."""
    try:
        with open(_force_path(runtime)) as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(st, dict):
        return None
    if st.get("until") and st["until"] <= time.time():
        try:
            os.remove(_force_path(runtime))
        except OSError:
            pass
        return None
    return st.get("force") if st.get("force") in ("on", "off") else None


def set_forced(runtime, how, n):
    """how: on, off, toggle or auto. On/off last until the schedule next changes."""
    path = _force_path(runtime)
    if how == "toggle":
        cur = forced(runtime, n)
        active = cur == "on" if cur else (n["enabled"] and night_amount(n) >= 0.5)
        how = "off" if active else "on"
    if how == "auto":
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    nxt = next_change(n) if n["enabled"] else None
    with open(path + ".tmp", "w") as f:
        json.dump({"force": how, "until": nxt.timestamp() if nxt else 0}, f)
    os.replace(path + ".tmp", path)
    return how


def target(n, runtime, now=None, location=None):
    """The temperature to show now, with the hand switch applied."""
    f = forced(runtime, n)
    if f == "on":
        return n["night_temp"]
    if f == "off" or not n["enabled"]:
        return n["day_temp"] if f == "off" else 6500
    return temperature(n, night_amount(n, now, location))


# ---------------------------------------------------------------- the displays
def saved_gamma(command):
    """{output: gamma} from the saved xrandr layout (the Displays page's gamma)."""
    out, cur = {}, None
    for i, a in enumerate(command or []):
        if a == "--output" and i + 1 < len(command):
            cur = command[i + 1]
        elif a == "--gamma" and cur and i + 1 < len(command):
            try:
                out[cur] = float(command[i + 1].split(":")[0])
            except ValueError:
                pass
    return out


class _Res(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("configTimestamp", ctypes.c_ulong),
                ("ncrtc", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("noutput", ctypes.c_int), ("outputs", ctypes.POINTER(ctypes.c_ulong)),
                ("nmode", ctypes.c_int), ("modes", ctypes.c_void_p)]


class _Crtc(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("width", ctypes.c_uint), ("height", ctypes.c_uint), ("mode", ctypes.c_ulong),
                ("rotation", ctypes.c_ushort), ("noutput", ctypes.c_int),
                ("outputs", ctypes.POINTER(ctypes.c_ulong)), ("rotations", ctypes.c_ushort),
                ("npossible", ctypes.c_int), ("possible", ctypes.POINTER(ctypes.c_ulong))]


class _Output(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("crtc", ctypes.c_ulong), ("name", ctypes.c_char_p),
                ("nameLen", ctypes.c_int)]   # (the rest isn't needed)


class _Gamma(ctypes.Structure):
    _fields_ = [("size", ctypes.c_int), ("red", ctypes.POINTER(ctypes.c_ushort)),
                ("green", ctypes.POINTER(ctypes.c_ushort)), ("blue", ctypes.POINTER(ctypes.c_ushort))]


class Gamma:
    """Sets CRTC gamma ramps on an X connection (ctypes, libXrandr)."""

    def __init__(self, x11, dpy):
        self.x11, self.dpy = x11, dpy
        x = self.xrr = ctypes.CDLL(ctypes.util.find_library("Xrandr") or "libXrandr.so.2")
        vp, ul = ctypes.c_void_p, ctypes.c_ulong
        x11.XDefaultRootWindow.restype, x11.XDefaultRootWindow.argtypes = ul, [vp]
        x11.XFlush.argtypes = [vp]
        x.XRRGetScreenResourcesCurrent.restype = ctypes.POINTER(_Res)
        x.XRRGetScreenResourcesCurrent.argtypes = [vp, ul]
        x.XRRFreeScreenResources.argtypes = [ctypes.POINTER(_Res)]
        x.XRRGetCrtcInfo.restype = ctypes.POINTER(_Crtc)
        x.XRRGetCrtcInfo.argtypes = [vp, ctypes.POINTER(_Res), ul]
        x.XRRFreeCrtcInfo.argtypes = [ctypes.POINTER(_Crtc)]
        x.XRRGetOutputInfo.restype = ctypes.POINTER(_Output)
        x.XRRGetOutputInfo.argtypes = [vp, ctypes.POINTER(_Res), ul]
        x.XRRFreeOutputInfo.argtypes = [ctypes.POINTER(_Output)]
        x.XRRGetCrtcGammaSize.argtypes = [vp, ul]
        x.XRRAllocGamma.restype = ctypes.POINTER(_Gamma)
        x.XRRAllocGamma.argtypes = [ctypes.c_int]
        x.XRRSetCrtcGamma.argtypes = [vp, ul, ctypes.POINTER(_Gamma)]
        x.XRRFreeGamma.argtypes = [ctypes.POINTER(_Gamma)]

    def crtcs(self):
        """[(crtc, [output names])] of the CRTCs that drive a display."""
        x = self.xrr
        res = x.XRRGetScreenResourcesCurrent(self.dpy, self.x11.XDefaultRootWindow(self.dpy))
        if not res:
            return []
        out = []
        try:
            for i in range(res.contents.ncrtc):
                crtc = res.contents.crtcs[i]
                info = x.XRRGetCrtcInfo(self.dpy, res, crtc)
                if not info:
                    continue
                try:
                    if not info.contents.mode:
                        continue
                    names = []
                    for j in range(info.contents.noutput):
                        oi = x.XRRGetOutputInfo(self.dpy, res, info.contents.outputs[j])
                        if oi:
                            names.append(oi.contents.name.decode(errors="replace"))
                            x.XRRFreeOutputInfo(oi)
                    out.append((crtc, names))
                finally:
                    x.XRRFreeCrtcInfo(info)
        finally:
            x.XRRFreeScreenResources(res)
        return out

    def apply(self, kelvin, gammas=None, skip=()):
        """Set every display to `kelvin` on top of its own gamma; returns the outputs changed."""
        x = self.xrr
        mult = whitepoint(kelvin)
        done = []
        for crtc, names in self.crtcs():
            if any(nm in skip for nm in names):
                continue
            g = next(((gammas or {}).get(nm) for nm in names if (gammas or {}).get(nm)), 1.0)
            size = x.XRRGetCrtcGammaSize(self.dpy, crtc)
            if size <= 1:
                continue
            ga = x.XRRAllocGamma(size)
            try:
                for arr, m in ((ga.contents.red, mult[0]), (ga.contents.green, mult[1]), (ga.contents.blue, mult[2])):
                    for i, v in enumerate(ramp(size, m, g)):
                        arr[i] = v
                x.XRRSetCrtcGamma(self.dpy, crtc, ga)
            finally:
                x.XRRFreeGamma(ga)
            done += names
        self.x11.XFlush(self.dpy)
        return done


def conflicting():
    """Other night-light programs running for this user."""
    found = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            if os.stat(f"/proc/{d}").st_uid != os.getuid():
                continue
            with open(f"/proc/{d}/comm") as f:
                name = f.read().strip()
        except OSError:
            continue
        if name in ("redshift", "redshift-gtk", "gammastep", "gammastep-indi", "sct", "xsct", "blugon") \
                and name not in found:
            found.append(name)
    return found
