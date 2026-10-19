"""Compare xcontrol.modelines against edid-decode's CVT/GTF/DMT calculators.
Needs edid-decode; exits 0 (skipped) without it."""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import modelines as M

RES = [(640, 480), (720, 480), (800, 600), (1024, 768), (1152, 864), (1280, 720), (1280, 800), (1280, 960), (1280, 1024),
       (1366, 768), (1440, 900), (1600, 900), (1600, 1200), (1680, 1050), (1920, 1080), (1920, 1200), (2560, 1080),
       (2560, 1440), (3440, 1440), (3840, 2160), (1024, 600), (1360, 768)]
HZ = [50, 56, 60, 70, 72, 75, 85, 100, 120, 144, 165, 240]
CASES = [("cvt", "--cvt w={w},h={h},fps={hz}"), ("cvt-rb", "--cvt w={w},h={h},fps={hz},rb=1"),
         ("cvt-rb2", "--cvt w={w},h={h},fps={hz},rb=2"), ("gtf", "--gtf w={w},h={h},fps={hz}")]

def ref(arg):
    out = subprocess.run(["edid-decode"] + arg.split(), capture_output=True, text=True).stdout
    m = re.search(r"^\w+:\s+(\d+)x(\d+)\s+([\d.]+) Hz.*?([\d.]+) MHz", out, re.M)
    h = re.search(r"Hfront\s+(\d+) Hsync\s+(\d+) Hback\s+(\d+) Hpol (\w)", out)
    v = re.search(r"Vfront\s+(\d+) Vsync\s+(\d+) Vback\s+(\d+) Vpol (\w)", out)
    if not (m and h and v):
        x = re.search(r'Modeline "[^"]*" ([\d.]+)\s+(\d+) (\d+) (\d+) (\d+)\s+(\d+) (\d+) (\d+) (\d+)\s+(\S+) (\S+)', out)
        if not x:
            return None
        n = [int(t) for t in x.groups()[1:9]]
        return (n[0], n[4], round(float(x.group(1)) * 1000), n[1] - n[0], n[2] - n[1], n[3] - n[2],
                x.group(10)[0] == "+", n[5] - n[4], n[6] - n[5], n[7] - n[6], x.group(11)[0] == "+")
    w, hh, mhz = int(m.group(1)), int(m.group(2)), float(m.group(4))
    return (w, hh, round(mhz * 1000), int(h.group(1)), int(h.group(2)), int(h.group(3)), h.group(4) == "P",
            int(v.group(1)), int(v.group(2)), int(v.group(3)), v.group(4) == "P")

def ours(m):
    return (m.width, m.height, m.clock_khz, m.hsync_start - m.width, m.hsync_end - m.hsync_start, m.htotal - m.hsync_end,
            m.hsync_positive, m.vsync_start - m.height, m.vsync_end - m.vsync_start, m.vtotal - m.vsync_end, m.vsync_positive)

if not shutil.which("edid-decode"):
    print("check_modelines: edid-decode not installed, skipped")
    sys.exit(0)

failed = False
for std, fmt in CASES:
    ok = total = 0
    bad = []
    for (w, h) in RES:
        for hz in HZ:
            r = ref(fmt.format(w=w, h=h, hz=hz))
            if r is None:
                continue
            o = ours(M.generate(std, w, h, hz))
            total += 1
            # RB v2: edid-decode floors an inexact float product (36287.9999 -> 36287 kHz);
            # we use the exact value, which gives the exact requested refresh rate.
            exact_rb2 = std == "cvt-rb2" and o[2] - r[2] == 1 and o[:2] + o[3:] == r[:2] + r[3:]
            if o == r or exact_rb2:
                ok += 1
            elif len(bad) < 3:
                bad.append((w, h, hz, o, r))
    print(f"{std:8s} {ok:4d}/{total} identical to edid-decode")
    failed |= ok != total
    for b in bad:
        print("   ", b[:3], "\n      ours:", b[3], "\n      ref: ", b[4])

bad = 0
for i, (w, h, hz, *_rest) in M.DMT.items():
    out = subprocess.run(["edid-decode", "--dmt", hex(i), "-X"], capture_output=True, text=True).stdout
    x = re.search(r'Modeline "[^"]*" ([\d.]+)\s+(\d+) (\d+) (\d+) (\d+)\s+(\d+) (\d+) (\d+) (\d+)\s+(\S+) (\S+)', out)
    if not x:
        continue
    m = M.dmt(w, h, hz)
    ref = (round(float(x.group(1)) * 1000),) + tuple(int(g) for g in x.groups()[1:9]) + \
          (x.group(10)[0] == "+", x.group(11)[0] == "+")
    got = (m.clock_khz, m.width, m.hsync_start, m.hsync_end, m.htotal, m.height, m.vsync_start,
           m.vsync_end, m.vtotal, m.hsync_positive, m.vsync_positive)
    bad += got != ref
print(f"dmt      {len(M.DMT) - bad:4d}/{len(M.DMT)} identical to edid-decode")
sys.exit(1 if failed or bad else 0)
