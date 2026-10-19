"""xcontrol-run: start a program with its profile applied.

Steam:   set the game's launch options to   xcontrol-run %command%
Other:   xcontrol-run [--profile NAME] [--print-env] [--] program args...
         --print-env shows the settings that would be applied without starting anything.
"""
import hashlib
import os
import re
import sys

from . import config
from .paths import GL_SHIM

USAGE = "usage: xcontrol-run [--profile NAME] [--print-env] [--] command [args...]"

VK_PRESENT = {"off": "immediate", "on": "fifo", "fast": "mailbox", "adaptive": "relaxed"}


def vkbasalt_config(settings):
    """vkBasalt configuration text for these settings, or None when it isn't needed."""
    s = config.normalize_settings(settings)
    effects, lines = [], []
    if s["post_aa"] == "smaa":
        effects.append("smaa")
        lines += ["smaaEdgeDetection = luma", "smaaThreshold = 0.05", "smaaMaxSearchSteps = 32"]
    elif s["post_aa"] == "fxaa":
        effects.append("fxaa")
        lines += ["fxaaQualitySubpix = 0.75", "fxaaQualityEdgeThreshold = 0.125"]
    if s["sharpen"]:
        effects.append("cas")  # after AA, so the AA edges aren't sharpened back
        lines.append(f"casSharpness = {s['sharpen'] / 100:.2f}")
    if not effects:
        return None
    return "\n".join(["# written by xcontrol", "effects = " + ":".join(effects), *lines,
                      "toggleKey = Home", "enableOnLaunch = True", ""])


def vkbasalt_config_path(text, base=None):
    """Where the config goes: one file per distinct configuration, so games
    running at the same time with different settings don't overwrite each other."""
    base = os.environ if base is None else base
    cache = base.get("XDG_CACHE_HOME") or os.path.join(base.get("HOME", "/tmp"), ".cache")
    digest = hashlib.sha1(text.encode()).hexdigest()[:12]
    return os.path.join(cache, "xcontrol", f"vkbasalt-{digest}.conf")


def write_support_files(settings, base=None):
    """Create files the environment from compose_env() points to. Call before starting the game."""
    text = vkbasalt_config(settings)
    if text:
        path = vkbasalt_config_path(text, base)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path) as f:
                if f.read() == text:
                    return
        except OSError:
            pass
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, path)


def compose_env(settings, base=None):
    """Return the environment variables (to add/override) for these settings."""
    base = os.environ if base is None else base
    s = config.normalize_settings(settings)
    env = {}
    dxvk = []
    use_gl_shim = False
    use_vk_layer = False

    # Anisotropic filtering: our GL shim + Vulkan layer, plus the driver and
    # DXVK knobs where they exist (they cover paths the hooks can't see).
    if s["af"]:
        off = s["af"] == 1
        env["XCONTROL_AF"] = str(s["af"])
        # driver and DXVK overrides: 0 means "no anisotropy" there
        driver = "0" if off else str(s["af"])
        env["RADV_TEX_ANISO"] = driver
        env["AMD_TEX_ANISO"] = driver
        dxvk += [f"d3d9.samplerAnisotropy = {driver}", f"d3d11.samplerAnisotropy = {driver}"]
        use_gl_shim = use_vk_layer = True

    # MSAA: OpenGL default framebuffer (shim), WineD3D swapchains (SampleCount);
    # "off" can also be enforced for Direct3D 11 through DXVK.
    wined3d_config = []
    if s["msaa"] == 1:
        env["XCONTROL_MSAA"] = "1"
        dxvk += ["d3d11.disableMsaa = True"]
        use_gl_shim = True
    elif s["msaa"]:
        env["XCONTROL_MSAA"] = str(s["msaa"])
        wined3d_config.append(f"SampleCount={s['msaa']}")
        use_gl_shim = True

    # Direct3D 8/9 renderer. DXVK can't force MSAA; Wine's own WineD3D can.
    if s["d3d_renderer"] == "wined3d":
        existing = base.get("WINEDLLOVERRIDES", "").strip().strip(";")
        env["WINEDLLOVERRIDES"] = ";".join(([existing] if existing else []) + ["d3d8,d3d9=b"])
        env["PROTON_USE_WINED3D"] = "1"

    # Transparency AA
    if s["traa"] != "off":
        env["XCONTROL_TRAA"] = "1" if s["traa"] == "multisample" else "2"
        use_gl_shim = True
        if s["traa"] == "supersample":
            dxvk += ["d3d9.forceSampleRateShading = True", "d3d11.forceSampleRateShading = True"]

    # VSync
    v = s["vsync"]
    if v != "app":
        env["MESA_VK_WSI_PRESENT_MODE"] = VK_PRESENT[v]
        if v == "off":
            env["vblank_mode"] = "0"
            dxvk += ["dxgi.syncInterval = 0", "d3d9.presentInterval = 0"]
        elif v == "on":
            env["vblank_mode"] = "3"
            dxvk += ["dxgi.syncInterval = 1", "d3d9.presentInterval = 1"]
        elif v == "fast":
            dxvk += ["dxgi.syncInterval = 0", "d3d9.presentInterval = 0", "dxvk.tearFree = True"]
        elif v == "adaptive":
            dxvk += ["dxgi.syncInterval = 1", "d3d9.presentInterval = 1", "dxvk.tearFree = False"]

    # FreeSync / variable refresh: Mesa's driconf option, which environment variables
    # override (like vblank_mode). Mesa asks for VRR on fullscreen windows by default;
    # X still has to allow it (Option "VariableRefresh").
    if s["freesync"] != "app":
        env["adaptive_sync"] = "1" if s["freesync"] == "on" else "0"

    # Post-process AA and sharpening through vkBasalt (Vulkan only: native Vulkan, DXVK, VKD3D-Proton)
    text = vkbasalt_config(s)
    if text:
        env["ENABLE_VKBASALT"] = "1"
        env["VKBASALT_CONFIG_FILE"] = vkbasalt_config_path(text, base)

    # Frame limiter: done in our own hooks for both APIs.
    if s["fps_limit"]:
        env["XCONTROL_FPS"] = str(s["fps_limit"])
        use_gl_shim = use_vk_layer = True

    if use_vk_layer:
        env["XCONTROL_VK"] = "1"
    if use_gl_shim:
        preload = base.get("LD_PRELOAD", "")
        parts = [p for p in re.split(r"[ :]", preload) if p and p != GL_SHIM]
        env["LD_PRELOAD"] = ":".join([GL_SHIM] + parts)
    if dxvk:
        existing = base.get("DXVK_CONFIG", "").strip().rstrip(";")
        env["DXVK_CONFIG"] = "; ".join(([existing] if existing else []) + dxvk)
    if wined3d_config:
        existing = base.get("WINE_D3D_CONFIG", "").strip().rstrip(";,")
        env["WINE_D3D_CONFIG"] = ";".join(([existing] if existing else []) + wined3d_config)
    return env


def steam_appid(argv, base=None):
    base = os.environ if base is None else base
    for key in ("SteamAppId", "SteamGameId", "STEAM_COMPAT_APP_ID"):
        val = base.get(key, "")
        if val.isdigit() and val != "0":
            return val
    for a in argv:  # Steam's reaper: ... AppId=12345 -- ...
        m = re.fullmatch(r"AppId=(\d+)", a)
        if m:
            return m.group(1)
    return None


def resolve(argv, base=None, profile_name=None):
    game, settings = find_settings(argv, base, profile_name)
    return game, compose_env(settings, base)


def find_settings(argv, base=None, profile_name=None):
    data = config.load()
    appid = steam_appid(argv, base)
    game = config.find_game(data, appid=appid, argv=argv, name=profile_name)
    return game, (game["settings"] if game else data["global"])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    profile = None
    print_env = False
    while argv:
        if argv[0] == "--profile" and len(argv) > 1:
            profile = argv[1]
            argv = argv[2:]
        elif argv[0] == "--print-env":
            print_env = True
            argv = argv[1:]
        elif argv[0] in ("-h", "--help"):
            print(USAGE)
            return 0
        elif argv[0] == "--":
            argv = argv[1:]
            break
        else:
            break
    if not argv and not print_env:
        print(USAGE, file=sys.stderr)
        return 2

    game, settings = find_settings(argv, profile_name=profile)
    env = compose_env(settings)
    if profile and not game:
        print(f"xcontrol-run: no profile named {profile!r}, using global settings", file=sys.stderr)
    if print_env or os.environ.get("XCONTROL_DEBUG"):
        print(f"xcontrol-run: profile = {game['name'] if game else 'global'}", file=sys.stderr)
        for k, v in sorted(env.items()):
            print(f"  {k}={v}", file=sys.stderr)
    if print_env:  # dry run: show what would be applied, start nothing
        return 0

    try:
        write_support_files(settings)
    except OSError as e:
        print(f"xcontrol-run: cannot write the vkBasalt configuration: {e}", file=sys.stderr)
    new_env = dict(os.environ)
    new_env.update(env)
    try:
        os.execvpe(argv[0], argv, new_env)
    except OSError as e:
        print(f"xcontrol-run: cannot run {argv[0]}: {e}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    sys.exit(main())
