"""Launcher: FreeSync and vkBasalt settings turn into the right environment and files;
the X log tells whether X allows variable refresh."""
import os
import sys
import tempfile
import time

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

# profiles.json damaged or hand-edited into the wrong shapes: defaults, never an exception
# (xcontrol-run loads it before every game starts)
with tempfile.TemporaryDirectory() as cfg:
    old = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = cfg
    os.makedirs(os.path.join(cfg, "xcontrol"))
    for text in ("[]", "7", "{bad", '{"games": 5, "display": [], "input": "x"}',
                 '{"games": [{"name": "g", "match": "abc", "settings": {"fps_limit": 1e999}}],'
                 ' "display": {"command": "xrandr", "custom_modes": [], "edid_ignored": 3},'
                 ' "input": {"devices": [], "keyboard": 2}}'):
        with open(os.path.join(cfg, "xcontrol", "profiles.json"), "w") as f:
            f.write(text)
        try:
            d = config.load()
            got = (d["display"]["command"], [g["match"] for g in d["games"]],
                   [g["settings"]["fps_limit"] for g in d["games"]])
            want = ([], [[]], [0]) if '"g"' in text else ([], [], [])
            expect(f"damaged config {text[:20]!r}", got, want)
        except Exception as e:  # noqa: BLE001
            expect(f"damaged config {text[:20]!r}", repr(e), "no exception")
    config.save({"global": {}, "games": []})
    expect("save leaves no temporary file", os.listdir(os.path.join(cfg, "xcontrol")), ["profiles.json"])
    if old is None:
        del os.environ["XDG_CONFIG_HOME"]
    else:
        os.environ["XDG_CONFIG_HOME"] = old

X = vrr.x_vrr_enabled
expect("modesetting enabled", X("[  12.3] (**) modesetting(0): VariableRefresh: enabled\n"), True)
expect("amdgpu default", X("[  12.3] (==) AMDGPU(0): VariableRefresh: disabled\n"), False)
expect("no line", X("[  12.3] (II) AMDGPU(0): something else\n"), None)
expect("option only", X('[ 1.0] (**) AMDGPU(0): Option "VariableRefresh" "true"\n'), True)
expect("display number", vrr._display_number(":1.0"), "1")
expect("remote display", vrr._display_number("localhost:10.0"), "10")

# the server's log: ~/.local/state (XLibre 25.2+), ~/.local/share (before, and X.Org) or /var/log
with tempfile.TemporaryDirectory() as home:
    saved = {k: os.environ.pop(k, None) for k in ("XDG_STATE_HOME", "XDG_DATA_HOME")}
    saved_log_dir, vrr.LOG_DIR = vrr.LOG_DIR, os.path.join(home, "var-log")

    def log(*parts, age):
        path = os.path.join(home, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        os.utime(path, (time.time() - age,) * 2)
        return path

    expect("no log anywhere", vrr.server_log(":0", home), None)
    share = log(".local", "share", "xorg", "Xorg.0.log", age=500)
    log(".local", "share", "xorg", "Xorg.1.log", age=0)
    expect("log in ~/.local/share", vrr.server_log(":0", home), share)
    state = log(".local", "state", "xorg", "Xorg.0.log", age=100)
    expect("log in ~/.local/state, older one in share left behind", vrr.server_log(":0", home), state)
    os.utime(share, None)
    expect("back on a server that logs in share", vrr.server_log(":0", home), share)
    os.environ["XDG_STATE_HOME"] = os.path.join(home, "st")
    moved = log("st", "xorg", "Xorg.0.log", age=-50)
    expect("XDG_STATE_HOME is followed", vrr.server_log(":0", home), moved)
    root = log("var-log", "Xorg.0.log", age=-100)
    expect("a server started as root", vrr.server_log(":0", home), root)
    expect("no display, no log", vrr.server_log("", home), None)
    del os.environ["XDG_STATE_HOME"]
    os.environ.update({k: v for k, v in saved.items() if v is not None})
    vrr.LOG_DIR = saved_log_dir


print("check_launcher:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
