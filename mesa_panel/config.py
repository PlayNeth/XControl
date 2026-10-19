"""Profile storage: ~/.config/mesa-panel/profiles.json

{
  "global":  {settings},
  "games":   [{"name", "match": ["steam:220", "hl2_linux"], "command", "settings"}],
  "display": {"command": [...xrandr args...], "autostart": false}
}
"""
import copy
import json
import os

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
    except (TypeError, ValueError):
        out["fps_limit"] = 0
    try:
        out["sharpen"] = min(100, max(0, int(out["sharpen"])))
    except (TypeError, ValueError):
        out["sharpen"] = 0
    return out


def _path():
    return os.path.join(config_dir(), "profiles.json")


def load():
    data = {"global": dict(DEFAULT_SETTINGS), "games": [],
            "display": {"command": [], "autostart": False, "custom_modes": {}, "edid_ignored": []}}
    try:
        with open(_path()) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return data
    data["global"] = normalize_settings(raw.get("global"))
    for g in raw.get("games", []):
        if not isinstance(g, dict) or not g.get("name"):
            continue
        data["games"].append({
            "name": str(g["name"]),
            "match": [str(m) for m in g.get("match", []) if str(m).strip()],
            "command": str(g.get("command", "")),
            "settings": normalize_settings(g.get("settings")),
        })
    disp = raw.get("display") or {}
    data["display"]["command"] = [str(a) for a in disp.get("command", [])]
    data["display"]["autostart"] = bool(disp.get("autostart", False))
    # custom resolutions per output: {"HDMI-A-0": [Modeline dict, ...]}
    modes = disp.get("custom_modes") or {}
    data["display"]["custom_modes"] = {str(k): [m for m in v if isinstance(m, dict)]
                                       for k, v in modes.items() if isinstance(v, list)}
    # outputs where only the custom resolutions are offered
    data["display"]["edid_ignored"] = [str(o) for o in disp.get("edid_ignored", [])]
    return data


def save(data):
    os.makedirs(config_dir(), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _path())


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
