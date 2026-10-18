"""Build a replacement EDID that lists exactly the chosen modes.

Identity (manufacturer, product, serial, name), size, colour data and input type
come from the display's real EDID. The mode list is replaced:
  - a mode identical to an "established timing" sets that bit,
  - every other mode becomes a detailed timing descriptor (exact timings),
    two in the base block and up to six per CTA-861 extension block,
  - standard timings are cleared, and so is the "continuous frequency / GTF"
    feature bit, so the kernel does not infer extra modes from the range limits,
  - the range-limits descriptor is widened to cover every chosen mode.
If the real EDID has a CTA-861 extension, its non-video data blocks (HDMI, audio,
colorimetry, HDR) are kept; its video modes are dropped.
"""
import math

from . import edid as edid_parser
from .modelines import Modeline

# EDID established timings, generated from edid-decode -X -L:
# (byte, bit, clock_khz, hdisp, hsync_start, hsync_end, htotal, vdisp, vsync_start, vsync_end, vtotal, hpos, vpos)
ESTABLISHED = [
    (35, 7, 28320, 720, 738, 846, 900, 400, 421, 423, 449, False, True),
    (35, 6, 35500, 720, 738, 846, 900, 400, 412, 414, 449, False, True),
    (35, 5, 25175, 640, 656, 752, 800, 480, 490, 492, 525, False, False),
    (35, 4, 30240, 640, 704, 768, 864, 480, 483, 486, 525, False, False),
    (35, 3, 31500, 640, 664, 704, 832, 480, 489, 492, 520, False, False),
    (35, 2, 31500, 640, 656, 720, 840, 480, 481, 484, 500, False, False),
    (35, 1, 36000, 800, 824, 896, 1024, 600, 601, 603, 625, True, True),
    (35, 0, 40000, 800, 840, 968, 1056, 600, 601, 605, 628, True, True),
    (36, 7, 50000, 800, 856, 976, 1040, 600, 637, 643, 666, True, True),
    (36, 6, 49500, 800, 816, 896, 1056, 600, 601, 604, 625, True, True),
    (36, 5, 57284, 832, 864, 928, 1152, 624, 625, 628, 667, False, False),
    (36, 3, 65000, 1024, 1048, 1184, 1344, 768, 771, 777, 806, False, False),
    (36, 2, 75000, 1024, 1048, 1184, 1328, 768, 771, 777, 806, False, False),
    (36, 1, 78750, 1024, 1040, 1136, 1312, 768, 769, 772, 800, True, True),
    (36, 0, 135000, 1280, 1296, 1440, 1688, 1024, 1025, 1028, 1066, True, True),
    (37, 7, 100000, 1152, 1200, 1328, 1456, 870, 873, 876, 915, True, True),
]

DTDS_PER_CTA_BLOCK = 6

# standard timing aspect codes; 16:10 is 0 only from EDID 1.3 on
_STD_ASPECTS = {(16, 10): 0, (4, 3): 1, (5, 4): 2, (16, 9): 3}


class OverrideError(ValueError):
    pass


def timing_key(m):
    return (m.width, m.hsync_start, m.hsync_end, m.htotal, m.height, m.vsync_start, m.vsync_end, m.vtotal,
            m.hsync_positive, m.vsync_positive)


def established_bit(m):
    """(byte, bit) if this mode is exactly an established timing."""
    for (byte, bit, clk, *timing) in ESTABLISHED:
        if tuple(timing) == timing_key(m) and abs(clk - m.clock_khz) <= 10:
            return byte, bit
    return None


def standard_timing(m):
    """2-byte standard timing for a mode that is exactly a VESA DMT timing, else None.
    The receiver expands a standard timing to the DMT mode of that size and rate."""
    from .modelines import DMT
    for (w, h, hz, clk, hf, hs, hb, hp, vf, vs, vb, vp, rb) in DMT.values():
        timing = (w, w + hf, w + hf + hs, w + hf + hs + hb, h, h + vf, h + vf + vs, h + vf + vs + vb, hp, vp)
        if rb or timing != timing_key(m) or abs(clk - m.clock_khz) > 10:
            continue
        rate = round(hz)
        if w % 8 or not (256 <= w <= 2288) or not (60 <= rate <= 123):
            return None
        for (an, ad), code in _STD_ASPECTS.items():
            if w * ad == h * an:
                return bytes([w // 8 - 31, (code << 6) | (rate - 60)])
        return None
    return None


def encode_dtd(m, width_mm=0, height_mm=0):
    clock = round(m.clock_khz / 10)  # 10 kHz units
    hblank, vblank = m.htotal - m.width, m.vtotal - m.height
    hfp, hsw = m.hsync_start - m.width, m.hsync_end - m.hsync_start
    vfp, vsw = m.vsync_start - m.height, m.vsync_end - m.vsync_start
    limits = [(clock, 1, 65535), (m.width, 1, 4095), (hblank, 1, 4095), (m.height, 1, 4095), (vblank, 1, 4095),
              (hfp, 0, 1023), (hsw, 1, 1023), (vfp, 0, 63), (vsw, 1, 63)]
    if not all(lo <= v <= hi for v, lo, hi in limits):
        raise OverrideError(f"{m.width}x{m.height} cannot be stored in an EDID detailed timing")
    wmm, hmm = min(width_mm, 4095), min(height_mm, 4095)
    d = bytearray(18)
    d[0], d[1] = clock & 0xFF, clock >> 8
    d[2], d[3], d[4] = m.width & 0xFF, hblank & 0xFF, ((m.width >> 8) << 4) | (hblank >> 8)
    d[5], d[6], d[7] = m.height & 0xFF, vblank & 0xFF, ((m.height >> 8) << 4) | (vblank >> 8)
    d[8], d[9] = hfp & 0xFF, hsw & 0xFF
    d[10] = ((vfp & 0x0F) << 4) | (vsw & 0x0F)
    d[11] = ((hfp >> 8) << 6) | ((hsw >> 8) << 4) | ((vfp >> 4) << 2) | (vsw >> 4)
    d[12], d[13], d[14] = wmm & 0xFF, hmm & 0xFF, ((wmm >> 8) << 4) | (hmm >> 8)
    d[17] = 0x18 | (0x04 if m.vsync_positive else 0) | (0x02 if m.hsync_positive else 0)
    return bytes(d)


def _text_descriptor(tag, text):
    raw = text.encode("ascii", "replace")[:13]
    if len(raw) < 13:
        raw += b"\n" + b" " * (12 - len(raw))
    return bytes([0, 0, 0, tag, 0]) + raw


def _range_descriptor(modes, version_14):
    vmin = math.floor(min(m.refresh for m in modes)) - 1
    vmax = math.ceil(max(m.refresh for m in modes)) + 1
    hmin = math.floor(min(m.hfreq_khz for m in modes)) - 1
    hmax = math.ceil(max(m.hfreq_khz for m in modes)) + 1
    clock = math.ceil(max(m.clock_khz for m in modes) / 10000.0) * 10
    vmin, hmin = max(1, vmin), max(1, hmin)
    flags = 0
    if vmax > 255:
        flags |= 0x02
        vmax -= 255
        if vmin > 255:
            flags |= 0x01
            vmin -= 255
    if hmax > 255:
        flags |= 0x08
        hmax -= 255
        if hmin > 255:
            flags |= 0x04
            hmin -= 255
    if clock > 2550:
        raise OverrideError("pixel clock above 2550 MHz")
    # 1.4: 0x01 = range limits only (no GTF/CVT); 1.3: 0x00 = no secondary GTF
    support = 0x01 if version_14 else 0x00
    return bytes([0, 0, 0, 0xFD, flags if version_14 else 0, vmin, vmax, hmin, hmax, clock // 10, support,
                  0x0A, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20])


def _cta_blocks(original_blocks, dtds):
    """CTA-861 blocks carrying the extra DTDs. Non-video data blocks of an
    existing CTA extension are preserved in the first one."""
    blocks = []
    kept_data, flags, rev = b"", 0, 3
    for e in original_blocks:
        if e[0] != 0x02:
            continue
        rev, flags = max(3, e[1]), e[3] & 0xF0
        dtd_start = e[2] if 4 <= e[2] <= 127 else 4
        i = 4
        out = bytearray()
        while i < dtd_start:
            tag, length = e[i] >> 5, e[i] & 0x1F
            block = e[i:i + 1 + length]
            ext_tag = e[i + 1] if length >= 1 else None
            # drop video data blocks and the YCbCr 4:2:0 video/capability blocks
            if not (tag == 2 or (tag == 7 and ext_tag in (0x0E, 0x0F))):
                out += block
            i += 1 + length
        kept_data = bytes(out)
        break
    if not _has_vcdb(kept_data):
        # Video Capability Data Block, RGB quantization range selectable (QS=1)
        kept_data += bytes([0xE2, 0x00, 0x40])
    if not dtds and not any(e[0] == 0x02 for e in original_blocks):
        return []
    remaining = list(dtds)
    first = True
    while remaining or (first and kept_data):
        e = bytearray(128)
        e[0], e[1] = 0x02, rev
        data = kept_data if first else b""
        e[4:4 + len(data)] = data
        dtd_off = 4 + len(data)
        e[2] = dtd_off
        e[3] = flags
        room = (127 - dtd_off) // 18
        chunk, remaining = remaining[:room], remaining[room:]
        for n, d in enumerate(chunk):
            e[dtd_off + 18 * n:dtd_off + 18 * (n + 1)] = d
        e[127] = (-sum(e[:127])) % 256
        blocks.append(bytes(e))
        first = False
        if not remaining:
            break
    return blocks


def _has_vcdb(data):
    i = 0
    while i < len(data):
        tag, length = data[i] >> 5, data[i] & 0x1F
        if tag == 7 and length >= 1 and data[i + 1] == 0x00:
            return True
        i += 1 + length
    return False


def build(original, modes, preferred):
    """original: the display's EDID bytes (or None); modes: [Modeline];
    preferred: the Modeline to mark as native. Returns the new EDID bytes."""
    if not modes:
        raise OverrideError("choose at least one mode")
    if preferred not in modes:
        raise OverrideError("the preferred mode must be one of the chosen modes")
    info = edid_parser.parse(original) if original else None
    base = bytearray(original[:128]) if info else _blank_base()
    version_14 = (base[18], base[19]) >= (1, 4)

    width_mm, height_mm = info.size_mm() if info else (0, 0)
    base[24] &= ~0x01          # no continuous frequency / default GTF: no inferred modes
    base[24] |= 0x02           # first detailed timing is the preferred mode
    base[35] = base[36] = base[37] = 0
    base[38:54] = b"\x01" * 16  # no standard timings

    dtd_modes = [preferred]
    std_slots = []
    for m in modes:
        if m is preferred:
            continue
        bit = established_bit(m)
        std = standard_timing(m) if len(std_slots) < 8 else None
        if bit:
            base[bit[0]] |= 1 << bit[1]
        elif std and std not in std_slots:
            std_slots.append(std)
        else:
            dtd_modes.append(m)
    for n, std in enumerate(std_slots):
        base[38 + 2 * n:40 + 2 * n] = std
    # skip duplicates (same timing chosen twice)
    seen, unique = set(), []
    for m in dtd_modes:
        k = timing_key(m)
        if k not in seen:
            seen.add(k)
            unique.append(m)
    dtds = [encode_dtd(m, width_mm, height_mm) for m in unique]

    # keep the display's own name; if it has none, keep its text label instead of inventing one
    if info and info.model:
        name_descriptor = _text_descriptor(0xFC, info.model)
    elif info and info.texts:
        name_descriptor = _text_descriptor(0xFE, info.texts[-1])
    elif info:
        name_descriptor = bytes([0, 0, 0, 0x10] + [0] * 14)
    else:
        name_descriptor = _text_descriptor(0xFC, "mesa-panel")
    serial = info.serial if info and info.serial and not info.serial.isdigit() else ""
    descriptors = [dtds[0]]
    extra = dtds[1:]
    if extra:
        descriptors.append(extra.pop(0))
    elif serial:
        descriptors.append(_text_descriptor(0xFF, serial))
    else:
        descriptors.append(bytes([0, 0, 0, 0x10] + [0] * 14))  # dummy descriptor
    descriptors.append(_range_descriptor(modes, version_14))
    descriptors.append(name_descriptor)
    for n, d in enumerate(descriptors):
        base[54 + 18 * n:72 + 18 * n] = d

    original_ext = [bytes(original[128 * n:128 * (n + 1)]) for n in range(1, len(original) // 128)] if info else []
    ext = _cta_blocks(original_ext, extra)
    if len(ext) > 1 and not version_14:
        # EDID 1.3 would need a block map for more than one extension block
        room = (127 - ext[0][2]) // 18
        err = OverrideError(f"too many non-standard modes for this display's EDID: remove {len(extra) - room} "
                            f"custom timing(s), or use DMT timings, which take less space")
        err.excess = len(extra) - room
        raise err
    if len(ext) > 254:
        raise OverrideError("too many modes")
    base[126] = len(ext)
    base[127] = (-sum(base[:127])) % 256
    return bytes(base) + b"".join(ext)


def _blank_base():
    b = bytearray(128)
    b[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    b[8], b[9] = 0x36, 0x8C  # "MPN" (mesa panel), a made-up PNP id
    b[16], b[17], b[18], b[19] = 1, 36, 1, 3
    b[20] = 0x80
    b[23] = 120  # gamma 2.2
    b[24] = 0x0A
    return b


def modes_from_verbose(entry, names):
    """Modelines for an output from parse_verbose(), limited to mode names that
    `xrandr --query` lists for it (unattached server modes are excluded)."""
    out = []
    for vm in entry.get("modes", []):
        if vm["name"] not in names or vm.get("interlaced") or "h" not in vm or "v" not in vm:
            continue
        h, v = vm["h"], vm["v"]
        m = Modeline(h[0], v[0], vm["clock_khz"], h[1], h[2], h[3], v[1], v[2], v[3],
                     vm["hpos"], vm["vpos"], "manual")
        m.source_name = vm["name"]
        m.current = vm.get("current", False)
        m.preferred = vm.get("preferred", False)
        out.append(m)
    return out
