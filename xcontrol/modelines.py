"""Video timing generators for custom resolutions.

  cvt      VESA CVT 1.2, standard (CRT-style) blanking
  cvt-rb   CVT reduced blanking v1   (LCD/flat panels, lower pixel clock)
  cvt-rb2  CVT reduced blanking v2   (exact refresh rate, high refresh rates)
  gtf      VESA GTF, the older CRT formula
  dmt      VESA DMT table (the classic fixed modes: 640x480@60 = 25.175 MHz, ...)
  manual   a modeline typed or pasted by the user

The results are checked against edid-decode in the test suite.
"""
import math
import re
from dataclasses import dataclass


@dataclass
class Modeline:
    width: int
    height: int
    clock_khz: int
    hsync_start: int
    hsync_end: int
    htotal: int
    vsync_start: int
    vsync_end: int
    vtotal: int
    hsync_positive: bool
    vsync_positive: bool
    standard: str = "cvt"
    requested_hz: float = 0.0

    @property
    def refresh(self):
        return self.clock_khz * 1000.0 / (self.htotal * self.vtotal)

    @property
    def hfreq_khz(self):
        return self.clock_khz / self.htotal

    @property
    def name(self):
        """Mode name, unique per timing so different standards never collide."""
        tag = {"cvt": "", "cvt-rb": "R", "cvt-rb2": "R2", "gtf": "G", "dmt": "D", "manual": "M"}[self.standard]
        hz = self.requested_hz or self.refresh
        return f"{self.width}x{self.height}_{hz:.2f}{tag}"

    def xrandr_args(self):
        """Arguments for `xrandr --newmode`."""
        return [self.name, f"{self.clock_khz / 1000:.3f}",
                str(self.width), str(self.hsync_start), str(self.hsync_end), str(self.htotal),
                str(self.height), str(self.vsync_start), str(self.vsync_end), str(self.vtotal),
                "+hsync" if self.hsync_positive else "-hsync",
                "+vsync" if self.vsync_positive else "-vsync"]

    def modeline(self):
        a = self.xrandr_args()
        flags = " ".join(f[0] + f[1:].replace("hsync", "HSync").replace("vsync", "VSync") for f in a[10:])
        return f'Modeline "{a[0]}" ' + " ".join(a[1:10]) + " " + flags

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


MIN_V_BPORCH = 7  # as in edid-decode's CVT implementation


def _vsync_width(w, h):
    """CVT vertical sync width encodes the aspect ratio."""
    for num, den, lines in ((4, 3, 4), (16, 9, 5), (16, 10, 6), (5, 4, 7), (15, 9, 7)):
        if h % den == 0 and h * num // den == w:
            return lines
    return 10


def cvt(w, h, hz, reduced=0):
    """VESA CVT 1.2. reduced: 0 = standard blanking, 1 = RB v1, 2 = RB v2."""
    if reduced == 2:
        h_pixels = w  # RB v2 has 1-pixel granularity
        v_sync = 8
        h_period = (1e6 / hz - 460.0) / h
        vbi = math.floor(460.0 / h_period) + 1
        vbi = max(vbi, 1 + v_sync + 6)  # RB v2: fixed 6-line back porch
        v_back = 6
        v_front = vbi - v_sync - v_back
        vtotal = h + vbi
        htotal = h_pixels + 80
        clock_khz = math.floor(hz * vtotal * htotal / 1000.0)  # 1 kHz steps
        return Modeline(h_pixels, h, clock_khz, h_pixels + 8, h_pixels + 8 + 32, htotal,
                        h + v_front, h + v_front + v_sync, vtotal, True, False, "cvt-rb2", hz)

    # Blanking is computed on the width rounded to 8 pixels, but the full
    # requested width stays active (1366x768 stays 1366, as in edid-decode).
    h_pixels = w - w % 8
    v_sync = _vsync_width(h_pixels, h)
    if reduced == 1:
        h_period = (1e6 / hz - 460.0) / h
        vbi = math.floor(460.0 / h_period) + 1
        vbi = max(vbi, 3 + v_sync + MIN_V_BPORCH)
        vtotal = h + vbi
        clock_khz = math.floor(hz * vtotal * (h_pixels + 160) / 1000.0)
        clock_khz -= clock_khz % 250
        htotal = w + 160
        return Modeline(w, h, clock_khz, w + 48, w + 48 + 32, htotal,
                        h + 3, h + 3 + v_sync, vtotal, True, False, "cvt-rb", hz)

    h_period = (1e6 / hz - 550.0) / (h + 3)
    v_sync_bp = math.floor(550.0 / h_period) + 1
    v_sync_bp = max(v_sync_bp, v_sync + MIN_V_BPORCH)
    vtotal = h + v_sync_bp + 3
    duty = 30.0 - 300.0 * h_period / 1000.0
    duty = max(duty, 20.0)
    h_blank = math.floor(h_pixels * duty / (100.0 - duty) / 16) * 16
    htotal = h_pixels + h_blank
    clock_khz = math.floor(htotal * 1000.0 / h_period)
    clock_khz -= clock_khz % 250
    h_sync = math.floor(8.0 * htotal / 100.0 / 8) * 8
    h_back = h_blank // 2
    h_front = h_blank - h_back - h_sync
    htotal = w + h_blank
    return Modeline(w, h, clock_khz, w + h_front, w + h_front + h_sync, htotal,
                    h + 3, h + 3 + v_sync, vtotal, False, True, "cvt", hz)


def gtf(w, h, hz):
    """VESA GTF with the default parameters (M=600, C=40, K=128, J=20)."""
    def rnd(x):
        return math.floor(x + 0.5)

    h_pixels = rnd(w / 8) * 8
    h_period_est = (1.0 / hz - 550e-6) / (h + 1) * 1e6
    v_sync_bp = rnd(550.0 / h_period_est)
    vtotal = h + v_sync_bp + 1
    v_field_est = 1e6 / h_period_est / vtotal
    h_period = h_period_est / (hz / v_field_est)
    duty = 30.0 - 300.0 * h_period / 1000.0
    h_blank = rnd(h_pixels * duty / (100.0 - duty) / 16) * 16
    htotal = h_pixels + h_blank
    clock_khz = round(htotal / h_period * 1000)
    h_sync = rnd(0.08 * htotal / 8) * 8
    h_front = h_blank // 2 - h_sync
    return Modeline(h_pixels, h, clock_khz, h_pixels + h_front, h_pixels + h_front + h_sync, htotal,
                    h + 1, h + 4, vtotal, False, True, "gtf", hz)


# VESA DMT table, generated from edid-decode --dmt (borders folded into the porches).
# id: (width, height, refresh, clock_khz, hfront, hsync, hback, hpos, vfront, vsync, vback, vpos, reduced)
DMT = {
    0x01: (640, 350, 85.08, 31500, 32, 64, 96, True, 32, 3, 60, False, False),
    0x02: (640, 400, 85.08, 31500, 32, 64, 96, False, 1, 3, 41, True, False),
    0x03: (720, 400, 85.039, 35500, 36, 72, 108, False, 1, 3, 42, True, False),
    0x04: (640, 480, 59.94, 25175, 16, 96, 48, False, 10, 2, 33, False, False),
    0x05: (640, 480, 72.809, 31500, 24, 40, 128, False, 9, 3, 28, False, False),
    0x06: (640, 480, 75, 31500, 16, 64, 120, False, 1, 3, 16, False, False),
    0x07: (640, 480, 85.008, 36000, 56, 56, 80, False, 1, 3, 25, False, False),
    0x08: (800, 600, 56.25, 36000, 24, 72, 128, True, 1, 2, 22, True, False),
    0x09: (800, 600, 60.317, 40000, 40, 128, 88, True, 1, 4, 23, True, False),
    0x0a: (800, 600, 72.188, 50000, 56, 120, 64, True, 37, 6, 23, True, False),
    0x0b: (800, 600, 75, 49500, 16, 80, 160, True, 1, 3, 21, True, False),
    0x0c: (800, 600, 85.061, 56250, 32, 64, 152, True, 1, 3, 27, True, False),
    0x0d: (800, 600, 119.972, 73250, 48, 32, 80, True, 3, 4, 29, False, True),
    0x0e: (848, 480, 60, 33750, 16, 112, 112, True, 6, 8, 23, True, False),
    0x10: (1024, 768, 60.004, 65000, 24, 136, 160, False, 3, 6, 29, False, False),
    0x11: (1024, 768, 70.069, 75000, 24, 136, 144, False, 3, 6, 29, False, False),
    0x12: (1024, 768, 75.029, 78750, 16, 96, 176, True, 1, 3, 28, True, False),
    0x13: (1024, 768, 84.997, 94500, 48, 96, 208, True, 1, 3, 36, True, False),
    0x14: (1024, 768, 119.989, 115500, 48, 32, 80, True, 3, 4, 38, False, True),
    0x15: (1152, 864, 75, 108000, 64, 128, 256, True, 1, 3, 32, True, False),
    0x55: (1280, 720, 60, 74250, 110, 40, 220, True, 5, 5, 20, True, False),
    0x16: (1280, 768, 59.995, 68250, 48, 32, 80, True, 3, 7, 12, False, True),
    0x17: (1280, 768, 59.87, 79500, 64, 128, 192, False, 3, 7, 20, True, False),
    0x18: (1280, 768, 74.893, 102250, 80, 128, 208, False, 3, 7, 27, True, False),
    0x19: (1280, 768, 84.837, 117500, 80, 136, 216, False, 3, 7, 31, True, False),
    0x1a: (1280, 768, 119.798, 140250, 48, 32, 80, True, 3, 7, 35, False, False),
    0x1b: (1280, 800, 59.91, 71000, 48, 32, 80, True, 3, 6, 14, False, True),
    0x1c: (1280, 800, 59.81, 83500, 72, 128, 200, False, 3, 6, 22, True, False),
    0x1d: (1280, 800, 74.934, 106500, 80, 128, 208, False, 3, 6, 29, True, False),
    0x1e: (1280, 800, 84.88, 122500, 80, 136, 216, False, 3, 6, 34, True, False),
    0x1f: (1280, 800, 119.909, 146250, 48, 32, 80, True, 3, 6, 38, False, True),
    0x20: (1280, 960, 60, 108000, 96, 112, 312, True, 1, 3, 36, True, False),
    0x21: (1280, 960, 85.002, 148500, 64, 160, 224, True, 1, 3, 47, True, False),
    0x22: (1280, 960, 119.838, 175500, 48, 32, 80, True, 3, 4, 50, False, True),
    0x23: (1280, 1024, 60.02, 108000, 48, 112, 248, True, 1, 3, 38, True, False),
    0x24: (1280, 1024, 75.025, 135000, 16, 144, 248, True, 1, 3, 38, True, False),
    0x25: (1280, 1024, 85.024, 157500, 64, 160, 224, True, 1, 3, 44, True, False),
    0x26: (1280, 1024, 119.958, 187250, 48, 32, 80, True, 3, 7, 50, False, True),
    0x27: (1360, 768, 60.015, 85500, 64, 112, 256, True, 3, 6, 18, True, False),
    0x28: (1360, 768, 119.967, 148250, 48, 32, 80, True, 3, 5, 37, False, True),
    0x51: (1366, 768, 59.79, 85500, 70, 143, 213, True, 3, 3, 24, True, False),
    0x56: (1366, 768, 60, 72000, 14, 56, 64, True, 1, 3, 28, True, True),
    0x29: (1400, 1050, 59.948, 101000, 48, 32, 80, True, 3, 4, 23, False, True),
    0x2a: (1400, 1050, 59.978, 121750, 88, 144, 232, False, 3, 4, 32, True, False),
    0x2b: (1400, 1050, 74.867, 156000, 104, 144, 248, False, 3, 4, 42, True, False),
    0x2c: (1400, 1050, 84.96, 179500, 104, 152, 256, False, 3, 4, 48, True, False),
    0x2d: (1400, 1050, 119.904, 208000, 48, 32, 80, True, 3, 4, 55, False, True),
    0x2e: (1440, 900, 59.901, 88750, 48, 32, 80, True, 3, 6, 17, False, True),
    0x2f: (1440, 900, 59.887, 106500, 80, 152, 232, False, 3, 6, 25, True, False),
    0x30: (1440, 900, 74.984, 136750, 96, 152, 248, False, 3, 6, 33, True, False),
    0x31: (1440, 900, 84.842, 157000, 104, 152, 256, False, 3, 6, 39, True, False),
    0x32: (1440, 900, 119.852, 182750, 48, 32, 80, True, 3, 6, 44, False, True),
    0x53: (1600, 900, 60, 108000, 24, 80, 96, True, 1, 3, 96, True, True),
    0x33: (1600, 1200, 60, 162000, 64, 192, 304, True, 1, 3, 46, True, False),
    0x34: (1600, 1200, 65, 175500, 64, 192, 304, True, 1, 3, 46, True, False),
    0x35: (1600, 1200, 70, 189000, 64, 192, 304, True, 1, 3, 46, True, False),
    0x36: (1600, 1200, 75, 202500, 64, 192, 304, True, 1, 3, 46, True, False),
    0x37: (1600, 1200, 85, 229500, 64, 192, 304, True, 1, 3, 46, True, False),
    0x38: (1600, 1200, 119.917, 268250, 48, 32, 80, True, 3, 4, 64, False, True),
    0x39: (1680, 1050, 59.883, 119000, 48, 32, 80, True, 3, 6, 21, False, True),
    0x3a: (1680, 1050, 59.954, 146250, 104, 176, 280, False, 3, 6, 30, True, False),
    0x3b: (1680, 1050, 74.892, 187000, 120, 176, 296, False, 3, 6, 40, True, False),
    0x3c: (1680, 1050, 84.941, 214750, 128, 176, 304, False, 3, 6, 46, True, False),
    0x3d: (1680, 1050, 119.986, 245500, 48, 32, 80, True, 3, 6, 53, False, True),
    0x3e: (1792, 1344, 60, 204750, 128, 200, 328, False, 1, 3, 46, True, False),
    0x3f: (1792, 1344, 74.997, 261000, 96, 216, 352, False, 1, 3, 69, True, False),
    0x40: (1792, 1344, 119.974, 333250, 48, 32, 80, True, 3, 4, 72, False, True),
    0x41: (1856, 1392, 59.995, 218250, 96, 224, 352, False, 1, 3, 43, True, False),
    0x42: (1856, 1392, 75, 288000, 128, 224, 352, False, 1, 3, 104, True, False),
    0x43: (1856, 1392, 120.051, 356500, 48, 32, 80, True, 3, 4, 74, False, True),
    0x52: (1920, 1080, 60, 148500, 88, 44, 148, True, 4, 5, 36, True, False),
    0x44: (1920, 1200, 59.95, 154000, 48, 32, 80, True, 3, 6, 26, False, True),
    0x45: (1920, 1200, 59.885, 193250, 136, 200, 336, False, 3, 6, 36, True, False),
    0x46: (1920, 1200, 74.93, 245250, 136, 208, 344, False, 3, 6, 46, True, False),
    0x47: (1920, 1200, 84.932, 281250, 144, 208, 352, False, 3, 6, 53, True, False),
    0x48: (1920, 1200, 119.909, 317000, 48, 32, 80, True, 3, 6, 62, False, True),
    0x49: (1920, 1440, 60, 234000, 128, 208, 344, False, 1, 3, 56, True, False),
    0x4a: (1920, 1440, 75, 297000, 144, 224, 352, False, 1, 3, 56, True, False),
    0x4b: (1920, 1440, 120.113, 380500, 48, 32, 80, True, 2, 3, 78, False, True),
    0x54: (2048, 1152, 60, 162000, 26, 80, 96, True, 1, 3, 44, True, True),
    0x4c: (2560, 1600, 59.972, 268500, 48, 32, 80, True, 3, 6, 37, False, True),
    0x4d: (2560, 1600, 59.987, 348500, 192, 280, 472, False, 3, 6, 49, True, False),
    0x4e: (2560, 1600, 74.972, 443250, 208, 280, 488, False, 3, 6, 63, True, False),
    0x4f: (2560, 1600, 84.951, 505250, 208, 280, 488, False, 3, 6, 73, True, False),
    0x50: (2560, 1600, 119.963, 552750, 48, 32, 80, True, 3, 6, 85, False, True),
    0x57: (4096, 2160, 60, 556744, 8, 32, 40, True, 48, 8, 6, False, True),
    0x58: (4096, 2160, 59.94, 556188, 8, 32, 40, True, 48, 8, 6, False, True),
}


def dmt_modes(w=None, h=None):
    """DMT entries, optionally for one resolution: [(refresh, Modeline)]."""
    out = []
    for (mw, mh, hz, clk, hf, hs, hb, hp, vf, vs, vb, vp, _rb) in DMT.values():
        if (w is None or mw == w) and (h is None or mh == h):
            out.append((hz, Modeline(mw, mh, clk, mw + hf, mw + hf + hs, mw + hf + hs + hb,
                                     mh + vf, mh + vf + vs, mh + vf + vs + vb, hp, vp, "dmt", hz)))
    return sorted(out, key=lambda x: x[0])


def dmt(w, h, hz):
    """The DMT mode closest to the requested refresh rate, or None."""
    modes = dmt_modes(w, h)
    if not modes:
        return None
    return min(modes, key=lambda m: abs(m[0] - hz))[1]


_MODELINE_RE = re.compile(
    r'^\s*(?:modeline\s+)?(?:"[^"]*"\s+|\S*[a-z_]\S*\s+)?'
    r"(?P<clock>\d+(?:\.\d+)?)\s+"
    r"(?P<h>\d+)\s+(?P<hss>\d+)\s+(?P<hse>\d+)\s+(?P<ht>\d+)\s+"
    r"(?P<v>\d+)\s+(?P<vss>\d+)\s+(?P<vse>\d+)\s+(?P<vt>\d+)(?P<flags>.*)$", re.I)


def parse_modeline(text):
    """Parse 'Modeline "name" 25.175 640 656 752 800 480 490 492 525 -HSync -VSync'
    (the name and the word Modeline are optional). Raises ValueError."""
    m = _MODELINE_RE.match(text.strip())
    if not m:
        raise ValueError("expected: clock hdisp hsyncstart hsyncend htotal vdisp vsyncstart vsyncend vtotal [flags]")
    g = {k: int(v) for k, v in m.groupdict().items() if k not in ("clock", "flags")}
    if not (g["h"] < g["hss"] <= g["hse"] <= g["ht"] and g["v"] < g["vss"] <= g["vse"] <= g["vt"]):
        raise ValueError("timings must satisfy display < sync start <= sync end <= total")
    flags = m.group("flags").lower()
    if "interlace" in flags or "doublescan" in flags or "dblscan" in flags:
        raise ValueError("interlaced and doublescan modes are not supported")
    # no polarity flag means negative (what X and the kernel do with such a modeline)
    return Modeline(g["h"], g["v"], round(float(m.group("clock")) * 1000), g["hss"], g["hse"], g["ht"],
                    g["vss"], g["vse"], g["vt"], "+hsync" in flags, "+vsync" in flags, "manual")


def generate(standard, w, h, hz):
    """The mode for this standard, None if DMT has no such mode. Raises ValueError when the
    formula gives timings no display can use (GTF at low line counts: negative front porch)."""
    if standard == "cvt":
        m = cvt(w, h, hz, 0)
    elif standard == "cvt-rb":
        m = cvt(w, h, hz, 1)
    elif standard == "cvt-rb2":
        m = cvt(w, h, hz, 2)
    elif standard == "gtf":
        m = gtf(w, h, hz)
    elif standard == "dmt":
        return dmt(w, h, hz)
    else:
        raise ValueError(standard)
    if not (m.width <= m.hsync_start <= m.hsync_end <= m.htotal
            and m.height <= m.vsync_start <= m.vsync_end <= m.vtotal):
        raise ValueError("timings must satisfy display < sync start <= sync end <= total")
    return m
