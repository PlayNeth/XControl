"""edid_override_status: tell whether the kernel uses our override, and why not."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import edid_override_status as S  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


P = S.parameter_entry
expect("none", P("quiet splash", "DP-1"), "")
expect("specific", P("drm.edid_firmware=DP-1:edid/a.bin", "DP-1"), "DP-1:edid/a.bin")
expect("other conn", P("drm.edid_firmware=HDMI-A-1:edid/a.bin", "DP-1"), "")
expect("bare", P("drm.edid_firmware=edid/a.bin quiet", "DP-1"), "edid/a.bin")
expect("list", P("drm.edid_firmware=HDMI-A-1:edid/h.bin,DP-1:edid/d.bin", "DP-1"), "DP-1:edid/d.bin")
expect("old name", P("drm_kms_helper.edid_firmware=DP-1:edid/x.bin", "DP-1"), "DP-1:edid/x.bin")
expect("last wins", P("drm.edid_firmware=DP-1:edid/a.bin drm.edid_firmware=DP-1:edid/b.bin", "DP-1"),
       "DP-1:edid/b.bin")

F = "/usr/lib/firmware/edid/xcontrol-DP-1.bin"
H = S.mkinitcpio_has_file
expect("no conf", H([], F), None)
expect("one line", H([f"MODULES=()\nFILES=({F})\n"], F), True)
expect("append", H([f"FILES+=({F})\n"], F), True)
expect("multi line", H([f"FILES=(\n  /etc/foo\n  {F}\n)\n"], F), True)
expect("commented", H([f"#FILES=({F})\nFILES=()\n"], F), False)
expect("missing", H(["FILES=()\n"], F), False)

with tempfile.TemporaryDirectory() as fw:
    good, old = b"\x00\xff\xff\xff\xff\xff\xff\x00" + b"\x01" * 120, b"\x00\xff\xff\xff\xff\xff\xff\x00" + b"\x02" * 120
    param = "drm.edid_firmware=DP-1:edid/xcontrol-DP-1.bin"
    conf = [f"FILES=({fw}/xcontrol-DP-1.bin)"]

    def st(current, cmdline=param, texts=conf, mtimes=(4e9,)):
        return S.check("DP-1", current, firmware_dir=fw, cmdline=cmdline,
                       mkinitcpio_texts=list(texts), initramfs_mtimes=list(mtimes)).state

    expect("not installed", st(good), S.NOT_INSTALLED)
    with open(os.path.join(fw, "xcontrol-DP-1.bin"), "wb") as f:
        f.write(good)
    expect("permanent", st(good), S.ACTIVE_PERMANENT)
    expect("test only", st(good, cmdline="quiet"), S.ACTIVE_TEST_ONLY)
    expect("no parameter", st(old, cmdline="quiet"), S.NO_PARAMETER)
    expect("wrong parameter", st(old, cmdline="drm.edid_firmware=DP-1:edid/other.bin"), S.WRONG_PARAMETER)
    expect("wrong connector name", st(old, cmdline="drm.edid_firmware=DP-2:edid/xcontrol-DP-1.bin"),
           S.WRONG_PARAMETER)
    r = S.check("DP-1", old, firmware_dir=fw, mkinitcpio_texts=conf, initramfs_mtimes=[4e9],
                cmdline="drm.edid_firmware=HDMI-A-1:edid/h.bin,DisplayPort-0:edid/xcontrol-DP-1.bin")
    expect("misplaced entry", r.parameter, "DisplayPort-0:edid/xcontrol-DP-1.bin")
    expect("not in initramfs", st(old, texts=["FILES=()"]), S.NOT_IN_INITRAMFS)
    expect("stale initramfs", st(old, mtimes=(1.0,)), S.STALE_INITRAMFS)
    expect("not loaded", st(old), S.NOT_LOADED)
    expect("no mkinitcpio (dracut)", st(old, texts=[]), S.NOT_LOADED)

print("check_override_status:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
