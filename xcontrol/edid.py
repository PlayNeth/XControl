"""EDID / CTA-861 parser: what a monitor says about itself.

Covers the base block (identity, size, chromaticity, timings, range limits,
name/serial descriptors) and the CTA-861 extension (audio, YCbCr, HDMI and
HDMI Forum VSDBs, AMD FreeSync VSDB, colorimetry, HDR static metadata).
"""
import math
import os
from dataclasses import dataclass, field

_PNP_FALLBACK = {
    "ACR": "Acer", "AOC": "AOC", "API": "Acer", "APP": "Apple", "AUO": "AU Optronics", "AUS": "ASUS",
    "BNQ": "BenQ", "BOE": "BOE", "CMN": "Chimei Innolux", "CMO": "Chi Mei", "DEL": "Dell", "ENC": "EIZO",
    "GBT": "Gigabyte", "GSM": "LG Electronics", "HKC": "HKC", "HPN": "HP", "HSD": "HannStar", "HWP": "HP",
    "IVM": "Iiyama", "LEN": "Lenovo", "LGD": "LG Display", "LPL": "LG Philips", "MEI": "Panasonic",
    "MSI": "MSI", "MST": "MStar", "NEC": "NEC", "PHL": "Philips", "SAM": "Samsung", "SDC": "Samsung Display",
    "SEC": "Samsung", "SHP": "Sharp", "SNY": "Sony", "TCL": "TCL", "VSC": "ViewSonic", "XMI": "Xiaomi",
}
_PNP_FILES = ("/usr/share/hwdata/pnp.ids", "/usr/share/misc/pnp.ids")
_pnp_cache = None


def vendor_name(code):
    global _pnp_cache
    if _pnp_cache is None:
        _pnp_cache = {}
        for path in _PNP_FILES:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        parts = line.rstrip("\n").split("\t", 1)
                        if len(parts) == 2 and len(parts[0]) == 3:
                            _pnp_cache[parts[0]] = parts[1].strip()
                break
            except OSError:
                continue
    return _pnp_cache.get(code) or _PNP_FALLBACK.get(code) or code


INTERFACES = {1: "DVI", 2: "HDMI", 3: "HDMI", 4: "MDDI", 5: "DisplayPort"}
BIT_DEPTHS = {1: 6, 2: 8, 3: 10, 4: 12, 5: 14, 6: 16}
COLORIMETRY = ["xvYCC 601", "xvYCC 709", "sYCC 601", "opYCC 601", "opRGB",
               "BT.2020 cYCC", "BT.2020 YCC", "BT.2020 RGB"]
EOTFS = ["SDR", "HDR (gamma)", "HDR10 (PQ)", "HLG"]
FRL_RATES = {1: "3 Gbps × 3 lanes", 2: "6 Gbps × 3 lanes", 3: "6 Gbps × 4 lanes",
             4: "8 Gbps × 4 lanes", 5: "10 Gbps × 4 lanes", 6: "12 Gbps × 4 lanes"}
FRL_GBPS = {1: 9, 2: 18, 3: 24, 4: 32, 5: 40, 6: 48}

# CTA-861 Video Identification Codes: VIC -> (width, height, refresh Hz, interlaced).
# Generated from edid-decode's table.
VICS = {
    1: (640, 480, 59.94, False), 2: (720, 480, 59.94, False), 3: (720, 480, 59.94, False),
    4: (1280, 720, 60, False), 5: (1920, 1080, 60, True), 6: (1440, 480, 59.94, True),
    7: (1440, 480, 59.94, True), 8: (1440, 240, 60.054, False), 9: (1440, 240, 60.054, False),
    10: (2880, 480, 59.94, True), 11: (2880, 480, 59.94, True), 12: (2880, 240, 60.054, False),
    13: (2880, 240, 60.054, False), 14: (1440, 480, 59.94, False), 15: (1440, 480, 59.94, False),
    16: (1920, 1080, 60, False), 17: (720, 576, 50, False), 18: (720, 576, 50, False),
    19: (1280, 720, 50, False), 20: (1920, 1080, 50, True), 21: (1440, 576, 50, True),
    22: (1440, 576, 50, True), 23: (1440, 288, 50.08, False), 24: (1440, 288, 50.08, False),
    25: (2880, 576, 50, True), 26: (2880, 576, 50, True), 27: (2880, 288, 50.08, False),
    28: (2880, 288, 50.08, False), 29: (1440, 576, 50, False), 30: (1440, 576, 50, False),
    31: (1920, 1080, 50, False), 32: (1920, 1080, 24, False), 33: (1920, 1080, 25, False),
    34: (1920, 1080, 30, False), 35: (2880, 480, 59.94, False), 36: (2880, 480, 59.94, False),
    37: (2880, 576, 50, False), 38: (2880, 576, 50, False), 39: (1920, 1080, 50, True),
    40: (1920, 1080, 100, True), 41: (1280, 720, 100, False), 42: (720, 576, 100, False),
    43: (720, 576, 100, False), 44: (1440, 576, 100, True), 45: (1440, 576, 100, True),
    46: (1920, 1080, 120, True), 47: (1280, 720, 120, False), 48: (720, 480, 119.88, False),
    49: (720, 480, 119.88, False), 50: (1440, 480, 119.88, True), 51: (1440, 480, 119.88, True),
    52: (720, 576, 200, False), 53: (720, 576, 200, False), 54: (1440, 576, 200, True),
    55: (1440, 576, 200, True), 56: (720, 480, 239.76, False), 57: (720, 480, 239.76, False),
    58: (1440, 480, 239.76, True), 59: (1440, 480, 239.76, True), 60: (1280, 720, 24, False),
    61: (1280, 720, 25, False), 62: (1280, 720, 30, False), 63: (1920, 1080, 120, False),
    64: (1920, 1080, 100, False), 65: (1280, 720, 24, False), 66: (1280, 720, 25, False),
    67: (1280, 720, 30, False), 68: (1280, 720, 50, False), 69: (1280, 720, 60, False),
    70: (1280, 720, 100, False), 71: (1280, 720, 120, False), 72: (1920, 1080, 24, False),
    73: (1920, 1080, 25, False), 74: (1920, 1080, 30, False), 75: (1920, 1080, 50, False),
    76: (1920, 1080, 60, False), 77: (1920, 1080, 100, False), 78: (1920, 1080, 120, False),
    79: (1680, 720, 24, False), 80: (1680, 720, 25, False), 81: (1680, 720, 30, False),
    82: (1680, 720, 50, False), 83: (1680, 720, 60, False), 84: (1680, 720, 100, False),
    85: (1680, 720, 120, False), 86: (2560, 1080, 24, False), 87: (2560, 1080, 25, False),
    88: (2560, 1080, 30, False), 89: (2560, 1080, 50, False), 90: (2560, 1080, 60, False),
    91: (2560, 1080, 100, False), 92: (2560, 1080, 120, False), 93: (3840, 2160, 24, False),
    94: (3840, 2160, 25, False), 95: (3840, 2160, 30, False), 96: (3840, 2160, 50, False),
    97: (3840, 2160, 60, False), 98: (4096, 2160, 24, False), 99: (4096, 2160, 25, False),
    100: (4096, 2160, 30, False), 101: (4096, 2160, 50, False), 102: (4096, 2160, 60, False),
    103: (3840, 2160, 24, False), 104: (3840, 2160, 25, False), 105: (3840, 2160, 30, False),
    106: (3840, 2160, 50, False), 107: (3840, 2160, 60, False), 108: (1280, 720, 48, False),
    109: (1280, 720, 48, False), 110: (1680, 720, 48, False), 111: (1920, 1080, 48, False),
    112: (1920, 1080, 48, False), 113: (2560, 1080, 48, False), 114: (3840, 2160, 48, False),
    115: (4096, 2160, 48, False), 116: (3840, 2160, 48, False), 117: (3840, 2160, 100, False),
    118: (3840, 2160, 120, False), 119: (3840, 2160, 100, False), 120: (3840, 2160, 120, False),
    121: (5120, 2160, 24, False), 122: (5120, 2160, 25, False), 123: (5120, 2160, 30, False),
    124: (5120, 2160, 48, False), 125: (5120, 2160, 50, False), 126: (5120, 2160, 60, False),
    127: (5120, 2160, 100, False), 193: (5120, 2160, 120, False), 194: (7680, 4320, 24, False),
    195: (7680, 4320, 25, False), 196: (7680, 4320, 30, False), 197: (7680, 4320, 48, False),
    198: (7680, 4320, 50, False), 199: (7680, 4320, 60, False), 200: (7680, 4320, 100, False),
    201: (7680, 4320, 120, False), 202: (7680, 4320, 24, False), 203: (7680, 4320, 25, False),
    204: (7680, 4320, 30, False), 205: (7680, 4320, 48, False), 206: (7680, 4320, 50, False),
    207: (7680, 4320, 60, False), 208: (7680, 4320, 100, False), 209: (7680, 4320, 120, False),
    210: (10240, 4320, 24, False), 211: (10240, 4320, 25, False), 212: (10240, 4320, 30, False),
    213: (10240, 4320, 48, False), 214: (10240, 4320, 50, False), 215: (10240, 4320, 60, False),
    216: (10240, 4320, 100, False), 217: (10240, 4320, 120, False), 218: (4096, 2160, 100, False),
    219: (4096, 2160, 120, False),
}


# CIE 1931 xy primaries (red, green, blue)
GAMUTS = {
    "sRGB": [(0.640, 0.330), (0.300, 0.600), (0.150, 0.060)],
    "DCI-P3": [(0.680, 0.320), (0.265, 0.690), (0.150, 0.060)],
    "Rec. 2020": [(0.708, 0.292), (0.170, 0.797), (0.131, 0.046)],
}


@dataclass
class Timing:
    width: int
    height: int
    refresh: float
    pixel_clock_mhz: float
    interlaced: bool = False
    width_mm: int = 0
    height_mm: int = 0


@dataclass
class EdidInfo:
    vendor_id: str = ""
    vendor: str = ""
    product_code: int = 0
    serial: str = ""
    model: str = ""
    week: int = 0
    year: int = 0
    model_year: bool = False
    version: str = ""
    digital: bool = True
    interface: str = ""
    bit_depth: int = 0
    width_cm: int = 0
    height_cm: int = 0
    gamma: float = 0.0
    dpms: list = field(default_factory=list)
    srgb_default: bool = False
    red: tuple = (0, 0)
    green: tuple = (0, 0)
    blue: tuple = (0, 0)
    white: tuple = (0, 0)
    preferred: Timing = None
    timings: list = field(default_factory=list)
    vrange: tuple = None          # (min Hz, max Hz) from range limits
    hrange: tuple = None          # (min kHz, max kHz)
    max_pixel_clock_mhz: int = 0
    texts: list = field(default_factory=list)
    extensions: list = field(default_factory=list)
    # CTA-861
    audio: bool = False
    ycbcr444: bool = False
    ycbcr422: bool = False
    ycbcr420: bool = False
    hdmi: bool = False
    hdmi_forum: bool = False
    max_tmds_mhz: int = 0
    frl: int = 0
    freesync: tuple = None        # (min Hz, max Hz) from the AMD VSDB
    colorimetry: list = field(default_factory=list)
    hdr_eotfs: list = field(default_factory=list)
    max_luminance: float = 0.0
    max_frame_avg: float = 0.0
    min_luminance: float = 0.0
    hdr10plus: bool = False
    dolby_vision: bool = False
    checksum_ok: bool = True

    # ---- derived values
    def display_name(self):
        return self.model or f"{self.vendor} {self.product_code:04X}".strip()

    def size_mm(self):
        p = self.preferred
        if p and p.width_mm and p.height_mm and self.width_cm:
            # trust the detailed timing's size if it agrees with the base block
            if abs(p.width_mm / 10 - self.width_cm) <= 3:
                return p.width_mm, p.height_mm
        if self.width_cm and self.height_cm:
            return self.width_cm * 10, self.height_cm * 10
        return 0, 0

    def diagonal_inches(self):
        w, h = self.size_mm()
        return math.hypot(w, h) / 25.4 if w and h else 0.0

    def ppi(self):
        w, _ = self.size_mm()
        return self.preferred.width / (w / 25.4) if w and self.preferred else 0.0

    def aspect(self):
        p = self.preferred
        if not p or not p.height:
            return ""
        r = p.width / p.height
        for name, val in (("16:9", 16 / 9), ("16:10", 1.6), ("21:9", 64 / 27), ("32:9", 32 / 9),
                          ("4:3", 4 / 3), ("5:4", 1.25), ("3:2", 1.5), ("1:1", 1.0), ("24:10", 2.4)):
            if abs(r - val) < 0.02:
                return name
        return f"{r:.2f}:1"

    def gamut_coverage(self):
        """Share of each reference gamut covered, from the reported primaries."""
        tri = [self.red, self.green, self.blue]
        if any(x <= 0 or y <= 0 for x, y in tri):
            return {}
        area = abs(_area(tri))
        if area < 1e-4:
            return {}
        out = {}
        for name, ref in GAMUTS.items():
            out[name] = abs(_area(_clip(tri, ref))) / abs(_area(ref)) * 100
        return out


# ---- geometry for gamut coverage -------------------------------------------
def _area(poly):
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly))) / 2 if len(poly) >= 3 else 0.0


def _clip(subject, clip):
    """Sutherland–Hodgman: subject polygon clipped by a convex polygon."""
    if _area(clip) < 0:
        clip = clip[::-1]

    def inside(p, a, b):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

    def cross(p, q, a, b):
        dx1, dy1 = q[0] - p[0], q[1] - p[1]
        dx2, dy2 = b[0] - a[0], b[1] - a[1]
        den = dx1 * dy2 - dy1 * dx2
        if abs(den) < 1e-12:
            return q
        t = ((a[0] - p[0]) * dy2 - (a[1] - p[1]) * dx2) / den
        return (p[0] + t * dx1, p[1] + t * dy1)

    out = list(subject)
    for i in range(len(clip)):
        a, b = clip[i], clip[(i + 1) % len(clip)]
        inp, out = out, []
        if not inp:
            break
        for j in range(len(inp)):
            p, q = inp[j - 1], inp[j]
            if inside(q, a, b):
                if not inside(p, a, b):
                    out.append(cross(p, q, a, b))
                out.append(q)
            elif inside(p, a, b):
                out.append(cross(p, q, a, b))
    return out


# ---- parsing ----------------------------------------------------------------
def _dtd(d):
    clock = (d[0] | d[1] << 8) * 10  # kHz
    hact = d[2] | (d[4] & 0xF0) << 4
    hblank = d[3] | (d[4] & 0x0F) << 8
    vact = d[5] | (d[7] & 0xF0) << 4
    vblank = d[6] | (d[7] & 0x0F) << 8
    interlaced = bool(d[17] & 0x80)
    if interlaced:
        vact *= 2
    htotal, vtotal = hact + hblank, (vact // 2 if interlaced else vact) + vblank
    refresh = clock * 1000 / (htotal * vtotal) if htotal and vtotal else 0.0
    return Timing(hact, vact, refresh, clock / 1000, interlaced,
                  d[12] | (d[14] & 0xF0) << 4, d[13] | (d[14] & 0x0F) << 8)


def _text(d):
    raw = bytearray()
    for ch in d[5:18]:
        if ch == 0x0A or ch < 0x20 or ch > 0x7E:  # stop at the newline or any garbage byte
            break
        raw.append(ch)
    return raw.decode("ascii").strip()


def _luminance(cv, maximum=None):
    if maximum is None:
        return 50 * 2 ** (cv / 32)
    return maximum * (cv / 255) ** 2 / 100


def _parse_cta(info, e):
    info.audio |= bool(e[3] & 0x40)
    info.ycbcr444 |= bool(e[3] & 0x20)
    info.ycbcr422 |= bool(e[3] & 0x10)
    dtd_start = e[2] if 4 <= e[2] <= 127 else 4
    i = 4
    while i < dtd_start:
        tag, length = e[i] >> 5, e[i] & 0x1F
        p = e[i + 1:i + 1 + length]
        i += 1 + length
        if len(p) < length:
            break
        if tag == 1:
            info.audio = True
        elif tag == 2:
            for code in p:
                vic = code & 0x7F if 129 <= code <= 192 else code
                if vic in VICS:
                    w, h, hz, il = VICS[vic]
                    info.timings.append(Timing(w, h, hz, 0.0, il))
        elif tag == 3 and length >= 3:
            oui = p[0] | p[1] << 8 | p[2] << 16
            if oui == 0x000C03:
                info.hdmi = True
                if length >= 7 and p[6]:
                    info.max_tmds_mhz = max(info.max_tmds_mhz, p[6] * 5)
            elif oui == 0xC45DD8:
                info.hdmi_forum = info.hdmi = True
                if length >= 5 and p[4]:
                    info.max_tmds_mhz = max(info.max_tmds_mhz, p[4] * 5)
                if length >= 7:
                    info.frl = p[6] >> 4
            elif oui == 0x00001A and length >= 7:  # AMD FreeSync: version, caps, min, max
                lo, hi = p[5], p[6]
                if 0 <= lo < hi:
                    info.freesync = (lo, hi)
            elif oui == 0x90848B:
                info.hdr10plus = True
            elif oui == 0x00D046:
                info.dolby_vision = True
        elif tag == 7 and length >= 1:
            ext = p[0]
            if ext == 0x05 and length >= 2:
                info.colorimetry += [n for b, n in enumerate(COLORIMETRY) if p[1] >> b & 1]
                if length >= 3 and p[2] & 0x80:
                    info.colorimetry.append("DCI-P3")
            elif ext == 0x06 and length >= 2:
                info.hdr_eotfs = [n for b, n in enumerate(EOTFS) if p[1] >> b & 1]
                if length >= 4 and p[3]:
                    info.max_luminance = _luminance(p[3])
                if length >= 5 and p[4]:
                    info.max_frame_avg = _luminance(p[4])
                if length >= 6 and p[5] and info.max_luminance:
                    info.min_luminance = _luminance(p[5], info.max_luminance)
            elif ext == 0x01 and length >= 4:  # vendor-specific video data block
                oui = p[1] | p[2] << 8 | p[3] << 16
                if oui == 0x90848B:
                    info.hdr10plus = True
                elif oui == 0x00D046:
                    info.dolby_vision = True
            elif ext in (0x0E, 0x0F):
                info.ycbcr420 = True
    for j in range(dtd_start, 110, 18):
        d = e[j:j + 18]
        if len(d) == 18 and (d[0] or d[1]):
            info.timings.append(_dtd(d))


def parse(data):
    """Parse raw EDID bytes. Returns EdidInfo, or None if it isn't an EDID."""
    b = bytes(data)
    if len(b) < 128 or b[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    info = EdidInfo()
    info.checksum_ok = sum(b[:128]) % 256 == 0
    v = b[8] << 8 | b[9]
    info.vendor_id = "".join(chr(((v >> s) & 31) + 64) for s in (10, 5, 0))
    info.vendor = vendor_name(info.vendor_id)
    info.product_code = b[10] | b[11] << 8
    serial = b[12] | b[13] << 8 | b[14] << 16 | b[15] << 24
    if serial not in (0, 0x01010101):
        info.serial = str(serial)
    info.week, info.year = b[16], b[17] + 1990
    info.model_year = b[16] == 0xFF
    info.version = f"{b[18]}.{b[19]}"
    info.digital = bool(b[20] & 0x80)
    if info.digital and (b[18], b[19]) >= (1, 4):
        info.bit_depth = BIT_DEPTHS.get(b[20] >> 4 & 7, 0)
        info.interface = INTERFACES.get(b[20] & 0x0F, "")
    elif not info.digital:
        info.interface = "VGA (analog)"
    info.width_cm, info.height_cm = b[21], b[22]
    if b[21] == 0 or b[22] == 0:
        info.width_cm = info.height_cm = 0
    info.gamma = (b[23] + 100) / 100 if b[23] != 0xFF else 0.0
    if b[24] & 0x80:
        info.dpms.append("standby")
    if b[24] & 0x40:
        info.dpms.append("suspend")
    if b[24] & 0x20:
        info.dpms.append("off")
    info.srgb_default = bool(b[24] & 0x04)

    lo1, lo2 = b[25], b[26]

    def c(hi, lo):
        return ((hi << 2) | lo) / 1024

    info.red = (c(b[27], lo1 >> 6 & 3), c(b[28], lo1 >> 4 & 3))
    info.green = (c(b[29], lo1 >> 2 & 3), c(b[30], lo1 & 3))
    info.blue = (c(b[31], lo2 >> 6 & 3), c(b[32], lo2 >> 4 & 3))
    info.white = (c(b[33], lo2 >> 2 & 3), c(b[34], lo2 & 3))

    for off in (54, 72, 90, 108):
        d = b[off:off + 18]
        if d[0] or d[1]:
            t = _dtd(d)
            info.timings.append(t)
            if info.preferred is None:
                info.preferred = t
            continue
        tag = d[3]
        if tag == 0xFC:
            info.model = (info.model + " " + _text(d)).strip() if info.model else _text(d)
        elif tag == 0xFF:
            s = _text(d)
            if s and s.strip("0") and s != "0":
                info.serial = s
        elif tag == 0xFE:
            s = _text(d)
            if s:
                info.texts.append(s)
        elif tag == 0xFD:
            flags = d[4]
            vmin = d[5] + (255 if (flags & 3) == 3 else 0)
            vmax = d[6] + (255 if flags & 2 else 0)
            hmin = d[7] + (255 if (flags >> 2 & 3) == 3 else 0)
            hmax = d[8] + (255 if flags & 8 else 0)
            if 0 < vmin <= vmax:
                info.vrange = (vmin, vmax)
            if 0 < hmin <= hmax:
                info.hrange = (hmin, hmax)
            info.max_pixel_clock_mhz = d[9] * 10

    count = b[126]
    for n in range(1, count + 1):
        e = b[n * 128:(n + 1) * 128]
        if len(e) < 128:
            break
        if e[0] == 0x02:
            info.extensions.append("CTA-861")
            _parse_cta(info, e)
        elif e[0] == 0x70:
            info.extensions.append("DisplayID")
        elif e[0] == 0xF0:
            info.extensions.append("Block map")
        else:
            info.extensions.append(f"0x{e[0]:02X}")
    return info


def parse_hex(text):
    return parse(bytes.fromhex("".join(text.split())))


def read_sysfs():
    """Connected DRM connectors with an EDID: [(connector name, edid bytes)]."""
    return [(conn, data) for _card, conn, data in read_sysfs_full()]


def read_sysfs_full():
    """Connected DRM connectors with an EDID: [(card number, connector name, edid bytes)]."""
    out = []
    base = os.environ.get("XCONTROL_SYSFS_DRM", "/sys/class/drm")  # override for tests
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return out
    for entry in entries:
        if "-" not in entry or not entry.startswith("card"):
            continue
        path = os.path.join(base, entry)
        try:
            with open(os.path.join(path, "status")) as f:
                if f.read().strip() != "connected":
                    continue
            with open(os.path.join(path, "edid"), "rb") as f:
                data = f.read()
        except OSError:
            continue
        if data:
            card, conn = entry.split("-", 1)
            out.append((card[4:], conn, data))
    return out
