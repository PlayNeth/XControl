"""Build EDID overrides from two real EDIDs (an analog CRT, and an HDMI monitor with a
CTA-861 block) and check them with edid-decode: no new conformance failures, and exactly
the chosen modes listed. Needs edid-decode; exits 0 (skipped) without it."""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import edid, edid_override as O, modelines as M  # noqa: E402

SAMPLES = {
    "analog CRT": bytes.fromhex("00ffffffffffff0005e36016470100001f180103682213782a00259e57529929155054a1080001010101010101010101010101010101662156aa51001e30468f330058c21000001e662150b051001b304070360058c21000001e000000fd0039461e3c09000a202020202020000000fc0031363630770a2020202020202000ac"),
    "HDMI monitor": bytes.fromhex("00ffffffffffff0006b30427010101010d1f0103803c2278ea9325ad4f44a9260d5054bfef00714f81809500d1c0d1e8d1fc01010101565e00a0a0a029503020350054502100001a000000fd0030901edf3c000a202020202020000000fc005647323741514c31410a202020000000ff004d334c4d51533333343331350a0130020349f150900203111213040e0f1d1e221f60613f230907078301000067030c002000384468d85dc40178800302681a000001012890e2e305ff01e6060701737300e2006ae30f00609ee80078a0a067500820980455502100001a6fc200a0a0a055503020350055502100001a5aa000a0a0a046503020350055502100001ad3"),
}
CHOSEN = [M.dmt(1024, 768, 85), M.dmt(800, 600, 85), M.dmt(640, 480, 60), M.cvt(640, 480, 120),
          M.gtf(800, 600, 100), M.dmt(1024, 768, 75), M.gtf(512, 384, 85), M.cvt(320, 240, 120, 1)]


def failures(data):
    out = subprocess.run(["edid-decode", "--check", "-"], input=data, capture_output=True).stdout.decode(errors="replace")
    sec = out.split("\nFailures:")[1] if "\nFailures:" in out else ""
    return {line.strip() for line in sec.splitlines() if line.startswith("  ") and line.strip()}


def listed(data):
    out = subprocess.run(["edid-decode", "-X", "-L", "-"], input=data, capture_output=True).stdout.decode()
    keys = set()
    for x in re.finditer(r'Modeline "[^"]*" ([\d.]+)\s+(\d+) (\d+) (\d+) (\d+)\s+(\d+) (\d+) (\d+) (\d+)\s+(\S+) (\S+)(.*)', out):
        if "nterlace" not in x.group(12):
            n = [int(v) for v in x.groups()[1:9]]
            keys.add(tuple(n) + (x.group(10)[0] == "+", x.group(11)[0] == "+"))
    return keys


# EDID 1.3 has no range offset flags: a mode above 255 Hz caps the range instead of wrapping it
m300 = M.cvt(640, 480, 300, 1)
if edid.parse(O.build(None, [M.dmt(640, 480, 60), m300], M.dmt(640, 480, 60))).vrange != (58, 255):
    print("check_edid_override: FAILED range limits above 255 Hz in EDID 1.3")
    sys.exit(1)
# a CTA block already full of data blocks: no room for the added VCDB, and every block stays 128 bytes
cta = bytearray(128)
cta[0], cta[1] = 0x02, 3
cta[4:127] = (bytes([0x60 | 30]) + bytes(30)) * 3 + bytes([0x60 | 29]) + bytes(29)
cta[2] = 127
base = bytearray(SAMPLES["HDMI monitor"][:128])
base[19], base[126] = 4, 1  # EDID 1.4: the extra DTDs may take more extension blocks
full = O.build(bytes(base) + bytes(cta), CHOSEN, CHOSEN[0])
if len(full) % 128 or full[128 + 2] > 127 or any(sum(full[i:i + 128]) % 256 for i in range(0, len(full), 128)):
    print("check_edid_override: FAILED full CTA block")
    sys.exit(1)

if not shutil.which("edid-decode"):
    print("check_edid_override: edid-decode not installed, skipped")
    sys.exit(0)
bad = 0
for name, original in SAMPLES.items():
    new = O.build(original, CHOSEN, CHOSEN[0])
    new_fail = failures(new) - failures(original)
    exact = listed(new) == {O.timing_key(m) for m in CHOSEN}
    native = edid.parse(new).preferred
    good = not new_fail and exact and (native.width, native.height) == (1024, 768)
    bad += not good
    print(f"check_edid_override: {name:12s} {'ok' if good else 'FAILED'}", *sorted(new_fail))
sys.exit(1 if bad else 0)
