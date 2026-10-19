"""Launcher: FreeSync and vkBasalt settings turn into the right environment and files;
the X log tells whether X allows variable refresh."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import config, launcher as L, vrr  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


base = {"HOME": "/home/u"}
env = L.compose_env({}, base)
for k in ("adaptive_sync", "ENABLE_VKBASALT", "VKBASALT_CONFIG_FILE"):
    expect(f"defaults leave {k} alone", k in env, False)
expect("freesync off", L.compose_env({"freesync": "off"}, base).get("adaptive_sync"), "0")
expect("freesync on", L.compose_env({"freesync": "on"}, base).get("adaptive_sync"), "1")
expect("bad freesync value", config.normalize_settings({"freesync": "maybe"})["freesync"], "app")
expect("sharpen clamped", config.normalize_settings({"sharpen": 400})["sharpen"], 100)

smaa = {"post_aa": "smaa", "sharpen": 50}
env = L.compose_env(smaa, base)
expect("vkbasalt enabled", env.get("ENABLE_VKBASALT"), "1")
path = env.get("VKBASALT_CONFIG_FILE", "")
expect("config under ~/.cache", path.startswith("/home/u/.cache/xcontrol/vkbasalt-"), True)
expect("same settings, same file", L.compose_env(dict(smaa), base)["VKBASALT_CONFIG_FILE"], path)
expect("different settings, different file",
       L.compose_env({"post_aa": "fxaa"}, base)["VKBASALT_CONFIG_FILE"] != path, True)
text = L.vkbasalt_config(smaa)
expect("effects order", "effects = smaa:cas" in text, True)
expect("sharpness", "casSharpness = 0.50" in text, True)
expect("only sharpening", "effects = cas\n" in L.vkbasalt_config({"sharpen": 25}), True)
expect("nothing", L.vkbasalt_config({}), None)

with tempfile.TemporaryDirectory() as home:
    b = {"HOME": home}
    L.write_support_files(smaa, b)
    p = L.compose_env(smaa, b)["VKBASALT_CONFIG_FILE"]
    with open(p) as f:
        expect("file written", f.read(), text)
    L.write_support_files(smaa, b)  # idempotent
    expect("one file", os.listdir(os.path.dirname(p)), [os.path.basename(p)])

X = vrr.x_vrr_enabled
expect("modesetting enabled", X("[  12.3] (**) modesetting(0): VariableRefresh: enabled\n"), True)
expect("amdgpu default", X("[  12.3] (==) AMDGPU(0): VariableRefresh: disabled\n"), False)
expect("no line", X("[  12.3] (II) AMDGPU(0): something else\n"), None)
expect("option only", X('[ 1.0] (**) AMDGPU(0): Option "VariableRefresh" "true"\n'), True)
expect("display number", vrr._display_number(":1.0"), "1")
expect("remote display", vrr._display_number("localhost:10.0"), "10")

print("check_launcher:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
