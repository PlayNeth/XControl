"""Scaling and colour properties: CTM fixed-point encoding, parsing xrandr --verbose,
and which --set/--gamma arguments apply, revert and saved layouts get."""
import copy
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import output_props as P, xrandr  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


# identity, exactly as the drivers initialise it (1ULL << 32 on the diagonal)
expect("identity words", P.ctm_encode(P.IDENTITY), [0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1])
# layout = struct drm_color_ctm { __u64 matrix[9]; } on a little-endian machine, sign-magnitude
m = P.saturation_matrix(1.5)
words = P.ctm_encode(m)
raw = struct.pack("<18I", *words)
u = struct.unpack("<9Q", raw)
expect("negative off-diagonal has the sign bit", u[1] >> 63, 1)
expect("magnitude", (u[1] & ((1 << 63) - 1)) / 2**32, round(abs(m[0][1]) * 2**32) / 2**32)
expect("round trip", [[round(v, 9) for v in r] for r in P.ctm_decode(words)], [[round(v, 9) for v in r] for r in m])
expect("signed words as xrandr prints them", P.ctm_decode([w - (1 << 32) if w >= 1 << 31 else w for w in words]) ==
       P.ctm_decode(words), True)
for s in (0.0, 0.35, 1.0, 1.25, 2.0):
    expect(f"saturation {s}", round(P.saturation_of(P.ctm_decode(P.ctm_encode(P.saturation_matrix(s)))), 6), s)
expect("grayscale rows equal luma", [round(v, 4) for v in P.saturation_matrix(0)[2]], [0.2126, 0.7152, 0.0722])
expect("amdgpu 'no CTM' (single 0)", P.ctm_decode(["0"]), P.IDENTITY)
expect("custom matrix", P.saturation_of([[1, 0, 0], [0, 0.9, 0], [0, 0, 1]]), None)

VERBOSE = """Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
DisplayPort-0 connected primary 1920x1080+0+0 (0x56) normal (normal left inverted right x axis y axis) 527mm x 296mm
\tIdentifier: 0x52
\tTimestamp:  12345
\tSubpixel:   unknown
\tGamma:      0.83:0.83:0.83
\tBrightness: 1.0
\tClones:    
\tCRTC:       0
\tCRTCs:      0 1 2 3
\tTransform:  1.000000 0.000000 0.000000
\t            0.000000 1.000000 0.000000
\t            0.000000 0.000000 1.000000
\t           filter: 
\tCTM: 0 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 
\t\t0 1 
\tscaling mode: None 
\t\tsupported: None, Full, Center, Full aspect
\tunderscan: off 
\t\tsupported: off, on, auto
\tunderscan hborder: 0 
\t\trange: (0, 128)
\tunderscan vborder: 0 
\t\trange: (0, 128)
\tmax bpc: 16 
\t\trange: (8, 16)
\tBroadcast RGB: Automatic 
\t\tsupported: Automatic, Full, Limited 16:235
  1920x1080 (0x56) 148.500MHz +HSync +VSync *current +preferred
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  67.50KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  60.00Hz
HDMI-A-0 disconnected (normal left inverted right x axis y axis)
\tscaling mode: None 
\t\tsupported: None, Full, Center, Full aspect
"""
QUERY = """Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
DisplayPort-0 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00*+
HDMI-A-0 disconnected (normal left inverted right x axis y axis)
"""
mons = xrandr.parse(QUERY)
P.attach(mons, xrandr.parse_verbose(VERBOSE))
dp = mons[0]
expect("CTM joined across lines", len(dp.props["CTM"].split()), 18)
expect("enum", dp.props["scaling mode"], "None")
expect("enum choices", dp.choices["scaling mode"], ["None", "Full", "Center", "Full aspect"])
expect("range", dp.ranges["max bpc"], (8, 16))
expect("Broadcast RGB choices", dp.choices["Broadcast RGB"][-1], "Limited 16:235")
expect("gamma (reciprocal of what xrandr prints)", dp.gamma, (1.2, 1.2, 1.2))

dp.gamma = (1.0, 1.0, 1.0)
cmd = xrandr.build_command(mons)
expect("defaults add nothing", [a for a in cmd if a in ("--set", "--gamma")], [])

orig = copy.deepcopy(mons)
dp.props["scaling mode"] = "Full aspect"
P.set_saturation(dp, 1.3)
dp.gamma = (1.1, 1.1, 1.1)
cmd = xrandr.build_command(mons, reference=orig)
i = cmd.index("scaling mode")
expect("set scaling", cmd[i - 1:i + 2], ["--set", "scaling mode", "Full aspect"])
ctm = cmd[cmd.index("CTM") + 1].split(",")
expect("CTM as 18 hex words", (len(ctm), all(w.startswith("0x") for w in ctm)), (18, True))
expect("CTM value decodes to 130 %", round(P.saturation_of(P.ctm_decode([int(w, 16) for w in ctm])), 6), 1.3)
expect("gamma", cmd[cmd.index("--gamma") + 1], "1.1:1.1:1.1")
expect("unchanged defaults stay out", "max bpc" in cmd or "underscan" in cmd, False)

back = xrandr.build_command(orig, reference=mons)  # revert
expect("revert sets scaling back", back[back.index("scaling mode") + 1], "None")
expect("revert sets identity CTM", P.ctm_decode([int(w, 16) for w in back[back.index("CTM") + 1].split(",")]),
       P.IDENTITY)
expect("revert sets gamma back", back[back.index("--gamma") + 1], "1:1:1")

saved = xrandr.build_command(mons)  # saved layout: only non-defaults
expect("saved has scaling", "scaling mode" in saved, True)
night = copy.deepcopy(mons)
night[0].gamma = (1.0, 0.85, 0.7)
expect("night-light gamma never saved", "--gamma" in xrandr.build_command(night), False)

# ---- xrandr 1.5.3 prints and reads CTM as nine decimals
_m = P.saturation_matrix(1.25)
_rows = [" ".join(f"{v:f}" for v in r) for r in _m]  # exactly how xrandr 1.5.3 prints it
V153 = VERBOSE.replace("\tCTM: 0 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 \n\t\t0 1 \n",
                       f"\tCTM: \t{_rows[0]}\n\t\t{_rows[1]}\n\t\t{_rows[2]}\n")
expect("sample has the 1.5.3 format", V153 != VERBOSE, True)
mons = xrandr.parse(QUERY)
P.attach(mons, xrandr.parse_verbose(V153))
dp = mons[0]
expect("decimal CTM parsed", round(P.saturation_of(P.ctm_decode(dp.props["CTM"].split())) or 0, 4), 1.25)
expect("negative decimals keep their sign", P.ctm_decode(dp.props["CTM"].split())[0][1] < 0, True)
P.set_saturation(dp, 0.0)
new_fmt = P.ctm_value(dp, xrandr_version=(1, 5, 3)).split(",")
expect("1.5.3 gets nine decimals", (len(new_fmt), "." in new_fmt[0]), (9, True))
expect("decimals are the grayscale matrix", [round(float(v), 4) for v in new_fmt[:3]], [0.2126, 0.7152, 0.0722])
old_fmt = P.ctm_value(dp, xrandr_version=(1, 5, 2)).split(",")
expect("1.5.2 gets 18 hex words", (len(old_fmt), old_fmt[0].startswith("0x")), (18, True))
# what xrandr 1.5.3 does with the value (ctm_from_string), and what the driver gets
def xrandr153(value):
    vals = [float(v) for v in value.split(",")[:9]]
    words = []
    for v in vals:
        t = int(abs(v) * (1 << 32)) | ((1 << 63) if v < 0 else 0)
        words += [t & 0xFFFFFFFF, t >> 32]
    return words
got = P.ctm_decode(xrandr153(P.ctm_value(dp, xrandr_version=(1, 5, 3))))
expect("round trip through xrandr 1.5.3", round(P.saturation_of(got), 6), 0.0)
mons = xrandr.parse(QUERY)
P.attach(mons, xrandr.parse_verbose(VERBOSE.replace("\tCTM: 0 1", "\tCTM: garbage 1")))
expect("unreadable CTM is left alone", "CTM" in mons[0].props, False)
v = xrandr.parse_verbose("DP-2 connected 640x480+0+0 (0x4a) normal (normal) 0mm x 0mm\n\tscaling mode: None \n"
                         "VIRTUAL1 unknown connection (normal left inverted right x axis y axis)\n"
                         "\tscaling mode: Full \n\t\tsupported: Full\n")
expect("an unknown-connection output keeps its own properties", (v["DP-2"]["props"], v["VIRTUAL1"]["props"]),
       ({"scaling mode": "None"}, {"scaling mode": "Full", "scaling mode (range)": "Full"}))

print("check_output_props:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
