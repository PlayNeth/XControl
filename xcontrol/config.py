"""Profile storage: ~/.config/xcontrol/profiles.json

{
  "global":  {settings},
  "games":   [{"name", "match": ["steam:220", "hl2_linux"], "command", "settings"}],
  "display": {"command": [...xrandr args...], "autostart": false}
}
"""
import copy
import json
import os
import threading

from .paths import config_dir

# 0 = application decides (stored, not in these lists), 1 = forced off
AF_VALUES = [1, 2, 4, 8, 16]
MSAA_VALUES = [1, 2, 4, 8]
TRAA_VALUES = ["off", "multisample", "supersample"]
VSYNC_VALUES = ["app", "off", "on", "fast", "adaptive"]
D3D_RENDERERS = ["dxvk", "wined3d"]  # for Direct3D 8/9 games under Wine/Proton
FREESYNC_VALUES = ["app", "off", "on"]
POST_AA_VALUES = ["off", "fxaa", "smaa"]  # vkBasalt

DEFAULT_SETTINGS = {
    "af": 0,            # 0 = application decides, 1 = off, 2..16 = forced
    "msaa": 0,          # 0 = application decides, 1 = off, 2..8 = forced
    "traa": "off",
    "vsync": "app",
    "fps_limit": 0,     # 0 = no limit
    "d3d_renderer": "dxvk",
    "freesync": "app",  # app = Mesa's default (on for fullscreen games)
    "post_aa": "off",   # vkBasalt post-process AA (Vulkan, DXVK, VKD3D-Proton)
    "sharpen": 0,       # vkBasalt CAS sharpening, 0 (off) to 100
}


def normalize_settings(s):
    out = dict(DEFAULT_SETTINGS)
    if isinstance(s, dict):
        out.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS})
    if out["af"] not in [0] + AF_VALUES:
        out["af"] = 0
    if out["msaa"] not in [0] + MSAA_VALUES:
        out["msaa"] = 0
    if out["traa"] not in TRAA_VALUES:
        out["traa"] = "off"
    if out["vsync"] not in VSYNC_VALUES:
        out["vsync"] = "app"
    if out["d3d_renderer"] not in D3D_RENDERERS:
        out["d3d_renderer"] = "dxvk"
    if out["freesync"] not in FREESYNC_VALUES:
        out["freesync"] = "app"
    if out["post_aa"] not in POST_AA_VALUES:
        out["post_aa"] = "off"
    try:
        out["fps_limit"] = max(0, int(out["fps_limit"]))
    except (TypeError, ValueError, OverflowError):  # OverflowError: 1e999 in the file
        out["fps_limit"] = 0
    try:
        out["sharpen"] = min(100, max(0, int(out["sharpen"])))
    except (TypeError, ValueError, OverflowError):
        out["sharpen"] = 0
    return out


def _path():
    return os.path.join(config_dir(), "profiles.json")


def _as(value, kind):
    """value if it has the expected JSON type (a hand-edited or damaged file may not), else empty."""
    return value if isinstance(value, kind) else kind()


def load():
    data = {"global": dict(DEFAULT_SETTINGS), "games": [],
            "display": {"command": [], "autostart": False, "custom_modes": {}, "edid_ignored": []},
            "input": {"devices": {}, "keyboard": {}}}
    try:
        with open(_path()) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return data
    raw = _as(raw, dict)
    data["global"] = normalize_settings(raw.get("global"))
    for g in _as(raw.get("games"), list):
        if not isinstance(g, dict) or not g.get("name"):
            continue
        data["games"].append({
            "name": str(g["name"]),
            "match": [str(m) for m in _as(g.get("match"), list) if str(m).strip()],
            "command": str(g.get("command", "")),
            "settings": normalize_settings(g.get("settings")),
        })
    disp = _as(raw.get("display"), dict)
    data["display"]["command"] = [str(a) for a in _as(disp.get("command"), list)]
    data["display"]["autostart"] = bool(disp.get("autostart", False))
    # custom resolutions per output: {"HDMI-A-0": [Modeline dict, ...]}
    modes = _as(disp.get("custom_modes"), dict)
    data["display"]["custom_modes"] = {str(k): [m for m in v if isinstance(m, dict)]
                                       for k, v in modes.items() if isinstance(v, list)}
    # outputs where only the custom resolutions are offered
    data["display"]["edid_ignored"] = [str(o) for o in _as(disp.get("edid_ignored"), list)]
    # input: {"devices": {device name: {setting: value}}, "keyboard": {setting: value}}
    inp = _as(raw.get("input"), dict)
    devs = _as(inp.get("devices"), dict)
    data["input"]["devices"] = {str(k): dict(v) for k, v in devs.items() if isinstance(v, dict)}
    data["input"]["keyboard"] = dict(_as(inp.get("keyboard"), dict))
    # desktop: {"wallpaper": {...}, "lock": {...}, "blanking": {...}} (checked by desktop.normalize)
    desk = raw.get("desktop")
    if isinstance(desk, dict):
        data["desktop"] = desk
    # i3: XControl's i3 config (checked by i3cfg.normalize)
    i3 = raw.get("i3")
    if isinstance(i3, dict):
        data["i3"] = i3
    # audio: XControl's PipeWire/WirePlumber settings (checked by audio.normalize)
    au = raw.get("audio")
    if isinstance(au, dict):
        data["audio"] = au
    # controllers: XControl's controller service (checked by pad_service.normalize)
    co = raw.get("controllers")
    if isinstance(co, dict):
        data["controllers"] = co
    # xserver: X options remembered per X driver, for switching drivers (xserver.py)
    xs = raw.get("xserver")
    if isinstance(xs, dict):
        data["xserver"] = xs
    # small interface preferences, e.g. {"preview": false}
    ui = raw.get("ui")
    if isinstance(ui, dict):
        data["ui"] = ui
    return data


def save(data):
    """Write atomically: a crash, or another XControl process saving at the same
    time (each uses its own temporary file), never leaves a partial profiles.json."""
    os.makedirs(config_dir(), exist_ok=True)
    tmp = f"{_path()}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _path())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def new_game(data, name, match, command=""):
    game = {"name": name, "match": match, "command": command,
            "settings": copy.deepcopy(data["global"])}
    data["games"].append(game)
    return game


def find_game(data, appid=None, argv=(), name=None):
    """Pick the profile for a launch: explicit name, Steam AppID, or any
    argument whose basename matches a rule (so `game.exe` under Proton works)."""
    if name:
        for g in data["games"]:
            if g["name"] == name:
                return g
        return None
    basenames = {os.path.basename(a).lower() for a in argv if a}
    full = {a for a in argv if a}
    for g in data["games"]:
        for rule in g["match"]:
            rule = rule.strip()
            if rule.lower().startswith("steam:"):
                if appid and rule[6:].strip() == str(appid):
                    return g
            elif "/" in rule:
                if rule in full:
                    return g
            elif rule.lower() in basenames:
                return g
    return None
