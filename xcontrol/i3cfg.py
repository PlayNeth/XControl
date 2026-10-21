"""XControl's i3 config: settings -> ~/.config/i3/config, generated from scratch.

The config i3 used before is kept as config.before-xcontrol (and can be restored). Every
write is checked with `i3 -C` first, so a mistake never replaces a working config, and i3 is
reloaded right after. Anything the page doesn't cover goes into the 'extra' lines.
"""
import os
import re
import shutil
import subprocess
import time

from . import config

MODS = {"Mod4": "Super (Windows key)", "Mod1": "Alt"}
BORDERS = ["normal", "pixel", "none"]
COLOR_CLASSES = ["focused", "focused_inactive", "unfocused", "urgent", "placeholder"]
COLOR_PARTS = ["border", "background", "text", "indicator", "child_border"]
DEFAULT_COLORS = {   # i3's own
    "focused": ["#4c7899", "#285577", "#ffffff", "#2e9ef4", "#285577"],
    "focused_inactive": ["#333333", "#5f676a", "#ffffff", "#484e50", "#5f676a"],
    "unfocused": ["#333333", "#222222", "#888888", "#292d2e", "#222222"],
    "urgent": ["#2f343a", "#900000", "#ffffff", "#900000", "#900000"],
    "placeholder": ["#000000", "#0c0c0c", "#ffffff", "#000000", "#0c0c0c"],
}
# things XControl starts itself: not imported as startup lines
ALWAYS_SKIPPED = re.compile(r"\b(xcontrol|i3-config-wizard)\b")
# what XControl starts itself when that part is switched on: such startup lines aren't imported
MANAGED = {
    "wallpaper": re.compile(r"\b(feh|nitrogen|xwallpaper|hsetroot)\b|\.fehbg"),
    "lock": re.compile(r"\b(xss-lock|xautolock|xidlehook)\b"),
    "bar": re.compile(r"\bpolybar\b|launch\.sh"),
    "picom": re.compile(r"\b(picom|compton|xcompmgr)\b"),
    "notify": re.compile(r"\b(dunst|xfce4-notifyd|notify-osd|notification-daemon)\b"),
}


def managed_now():
    """The parts XControl runs now (from the desktop settings)."""
    try:
        from . import desktop
        d = desktop.load()
    except Exception:  # noqa: BLE001
        return set()
    on = {"wallpaper": d["wallpaper"]["enabled"], "lock": d["lock"]["enabled"], "bar": d["bar"]["enabled"],
          "picom": d["picom"]["enabled"], "notify": d["notify"]["enabled"]}
    return {k for k, v in on.items() if v}


def skipped_by(cmd, managed):
    return bool(ALWAYS_SKIPPED.search(cmd)) or any(MANAGED[k].search(cmd) for k in managed)


SESSION_LINE = "exec --no-startup-id xcontrol --session"


def default_bindings(launcher="dmenu_run"):
    """i3's stock keybindings, written with $mod so the modifier can be switched."""
    b = []

    def add(keys, cmd, mode="default"):
        b.append({"keys": keys, "command": cmd, "mode": mode, "code": False, "release": False})
    add("$mod+Return", "exec i3-sensible-terminal")
    add("$mod+Shift+q", "kill")
    add("$mod+d", f"exec --no-startup-id {launcher}")
    for key, arrow, d in (("j", "Left", "left"), ("k", "Down", "down"), ("l", "Up", "up"),
                          ("semicolon", "Right", "right")):
        add(f"$mod+{key}", f"focus {d}")
        add(f"$mod+{arrow}", f"focus {d}")
        add(f"$mod+Shift+{key}", f"move {d}")
        add(f"$mod+Shift+{arrow}", f"move {d}")
    for keys, cmd in (("$mod+h", "split h"), ("$mod+v", "split v"), ("$mod+f", "fullscreen toggle"),
                      ("$mod+s", "layout stacking"), ("$mod+w", "layout tabbed"), ("$mod+e", "layout toggle split"),
                      ("$mod+Shift+space", "floating toggle"), ("$mod+space", "focus mode_toggle"),
                      ("$mod+a", "focus parent"), ("$mod+Shift+minus", "move scratchpad"),
                      ("$mod+minus", "scratchpad show")):
        add(keys, cmd)
    for i in range(1, 11):
        key = str(i % 10)
        add(f"$mod+{key}", f"workspace number $ws{i}")
        add(f"$mod+Shift+{key}", f"move container to workspace number $ws{i}")
    add("$mod+Shift+c", "reload")
    add("$mod+Shift+r", "restart")
    add("$mod+Shift+e", "exec \"i3-nagbar -t warning -m 'Exit i3? This ends your X session.' -B 'Yes, exit i3' "
                        "'i3-msg exit'\"")
    add("$mod+Shift+x", "exec --no-startup-id xcontrol --lock")
    for key, cmd in (("XF86AudioRaiseVolume", "exec --no-startup-id pactl set-sink-volume @DEFAULT_SINK@ +5%"),
                     ("XF86AudioLowerVolume", "exec --no-startup-id pactl set-sink-volume @DEFAULT_SINK@ -5%"),
                     ("XF86AudioMute", "exec --no-startup-id pactl set-sink-mute @DEFAULT_SINK@ toggle"),
                     ("XF86AudioMicMute", "exec --no-startup-id pactl set-source-mute @DEFAULT_SOURCE@ toggle")):
        add(key, cmd)
    add("$mod+r", 'mode "resize"')
    for key, arrow, cmd in (("j", "Left", "shrink width"), ("k", "Down", "grow height"),
                            ("l", "Up", "shrink height"), ("semicolon", "Right", "grow width")):
        add(key, f"resize {cmd} 10 px or 10 ppt", "resize")
        add(arrow, f"resize {cmd} 10 px or 10 ppt", "resize")
    for key in ("Return", "Escape", "$mod+r"):
        add(key, 'mode "default"', "resize")
    return b


DEFAULT = {
    "enabled": False, "mod": "Mod4",
    # look
    "font": "Monospace 10", "border": "pixel", "border_width": 2, "float_border": "normal", "float_border_width": 2,
    "title_align": "left", "hide_edge_borders": "none", "gaps_inner": 0, "gaps_outer": 0,
    "smart_gaps": "off", "smart_borders": "off", "colors": None, "background": "#ffffff",
    # behavior
    "focus_follows_mouse": True, "mouse_warping": "output", "focus_on_activation": "smart",
    "focus_wrapping": "yes", "default_orientation": "auto", "workspace_layout": "default",
    "back_and_forth": False, "popup_fullscreen": "smart", "floating_drag": True, "tiling_drag": True,
    # workspaces: name and display per number 1..10
    "workspaces": None,
    "bindings": None, "startup": [], "rules": [],
    "i3bar": True,      # i3's own bar when XControl's bar is off
    "extra": "",
}
CHOICES = {
    "border": BORDERS, "float_border": BORDERS, "title_align": ["left", "center", "right"],
    "hide_edge_borders": ["none", "vertical", "horizontal", "both", "smart", "smart_no_gaps"],
    "smart_gaps": ["off", "on", "inverse_outer"], "smart_borders": ["off", "on", "no_gaps"],
    "mouse_warping": ["output", "none"], "focus_on_activation": ["smart", "urgent", "focus", "none"],
    "focus_wrapping": ["yes", "no", "force", "workspace"], "default_orientation": ["auto", "horizontal", "vertical"],
    "workspace_layout": ["default", "stacking", "tabbed"], "popup_fullscreen": ["smart", "ignore", "leave_fullscreen", "all"],
    "mod": list(MODS),
}


def normalize(c):
    out = {k: v for k, v in DEFAULT.items()}
    if isinstance(c, dict):
        out.update({k: v for k, v in c.items() if k in DEFAULT})
    for k, choices in CHOICES.items():
        if out[k] not in choices:
            out[k] = DEFAULT[k]
    for k in ("border_width", "float_border_width", "gaps_inner", "gaps_outer"):
        try:
            out[k] = max(0, min(200, int(out[k])))
        except (TypeError, ValueError):
            out[k] = DEFAULT[k]
    colors = {k: list(v) for k, v in DEFAULT_COLORS.items()}
    for k, v in (out["colors"] or {}).items():
        if k in colors and isinstance(v, (list, tuple)) and len(v) == 5:
            colors[k] = [str(x) for x in v]
    out["colors"] = colors
    ws = out["workspaces"] if isinstance(out["workspaces"], list) else []
    out["workspaces"] = [{"name": str((ws[i] or {}).get("name") or i + 1) if i < len(ws) and isinstance(ws[i], dict)
                          else str(i + 1),
                          "output": str((ws[i] or {}).get("output", "")) if i < len(ws) and isinstance(ws[i], dict)
                          else ""} for i in range(10)]
    if not isinstance(out["bindings"], list):
        launcher = "rofi -show drun" if shutil.which("rofi") else "dmenu_run"
        out["bindings"] = default_bindings(launcher)
    out["bindings"] = [{"keys": str(b.get("keys", "")).strip(), "command": str(b.get("command", "")).strip(),
                        "mode": str(b.get("mode") or "default"), "code": bool(b.get("code")),
                        "release": bool(b.get("release"))}
                       for b in out["bindings"] if isinstance(b, dict) and b.get("keys") and b.get("command")]
    out["startup"] = [{"command": str(s.get("command", "")).strip(), "always": bool(s.get("always")),
                       "no_startup_id": bool(s.get("no_startup_id", True))}
                      for s in out["startup"] if isinstance(s, dict) and str(s.get("command", "")).strip()]
    out["rules"] = [{"kind": r.get("kind") if r.get("kind") in ("for_window", "assign") else "for_window",
                     "criteria": str(r.get("criteria", "")).strip(), "action": str(r.get("action", "")).strip()}
                    for r in out["rules"] if isinstance(r, dict) and str(r.get("criteria", "")).strip()]
    out["extra"] = str(out["extra"] or "")
    return out


def load():
    return normalize(config.load().get("i3"))


def save(c):
    data = config.load()
    data["i3"] = c
    config.save(data)


# ---------------------------------------------------------------- keys
_MOD_ALIASES = {"mod4": "mod4", "super": "mod4", "mod1": "mod1", "alt": "mod1", "control": "ctrl", "ctrl": "ctrl",
                "shift": "shift", "mod2": "mod2", "mod3": "mod3", "mod5": "mod5", "lock": "lock"}


def key_id(keys, mod="Mod4", code=False):
    """A comparable form of a key combination: $mod expanded, modifiers sorted, case folded."""
    parts = [p for p in keys.replace("$mod", mod).split("+") if p]
    if not parts:
        return ""
    *mods, key = parts
    mods = sorted({_MOD_ALIASES.get(m.lower(), m.lower()) for m in mods})
    return "+".join(mods + [("code:" if code else "") + key.lower()])


def clashes(bindings, mod):
    """{index: [other indexes]} for bindings that share keys in the same mode."""
    seen, out = {}, {}
    for i, b in enumerate(bindings):
        k = (b["mode"], key_id(b["keys"], mod, b["code"]), b["release"])
        if k in seen:
            out.setdefault(i, []).append(seen[k])
            out.setdefault(seen[k], []).append(i)
        else:
            seen[k] = i
    return out


# ---------------------------------------------------------------- the file
def _q(name):
    # i3 unescapes backslash-backslash and backslash-quote inside quotes (see _unquote)
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _terminal():
    try:
        from . import defaults
        return defaults.terminal_command()
    except Exception:  # noqa: BLE001
        return None


def generate(c, bar_enabled=False, ver=None):
    ver = ver or version() or (4, 24)
    hide_edges, smart_borders = c["hide_edge_borders"], c["smart_borders"]
    if ver >= (4, 24) and smart_borders != "off":
        # 4.24 deprecated smart_borders: the same thing is now a hide_edge_borders value
        if hide_edges == "none":
            hide_edges = "smart" if smart_borders == "on" else "smart_no_gaps"
        smart_borders = "off"
    popup = c["popup_fullscreen"] if ver >= (4, 24) or c["popup_fullscreen"] != "all" else "smart"
    L = ["# Generated by XControl (i3 page). It's rewritten on every change; edits here are lost.",
         "# i3 config file (v4)",
         "# Your previous config is kept next to this file as config.before-xcontrol.",
         "", f"set $mod {c['mod']}", ""]
    for i, ws in enumerate(c["workspaces"], 1):
        L.append(f"set $ws{i} {_q(ws['name'])}")
    L += ["", "# ---- look", f"font pango:{c['font']}"]
    L.append(f"default_border {c['border']}" + (f" {c['border_width']}" if c["border"] != "none" else ""))
    L.append(f"default_floating_border {c['float_border']}" +
             (f" {c['float_border_width']}" if c["float_border"] != "none" else ""))
    L += [f"title_align {c['title_align']}", f"hide_edge_borders {hide_edges}",
          f"gaps inner {c['gaps_inner']}", f"gaps outer {c['gaps_outer']}"]
    if c["smart_gaps"] != "off":
        L.append(f"smart_gaps {c['smart_gaps']}")
    if smart_borders != "off":   # i3 doesn't take 'off' here
        L.append(f"smart_borders {smart_borders}")
    for cls in COLOR_CLASSES:
        L.append(f"client.{cls:<17} " + " ".join(c["colors"][cls]))
    L.append(f"client.background {c['background']}")
    L += ["", "# ---- behavior",
          f"focus_follows_mouse {'yes' if c['focus_follows_mouse'] else 'no'}",
          f"mouse_warping {c['mouse_warping']}",
          f"focus_on_window_activation {c['focus_on_activation']}",
          f"focus_wrapping {c['focus_wrapping']}",
          f"default_orientation {c['default_orientation']}",
          f"workspace_layout {c['workspace_layout']}",
          f"workspace_auto_back_and_forth {'yes' if c['back_and_forth'] else 'no'}",
          f"popup_during_fullscreen {popup}"]
    if c["floating_drag"]:
        L.append("floating_modifier $mod")
    L.append("tiling_drag modifier titlebar" if c["tiling_drag"] else "tiling_drag off")
    outs = [(i, ws["output"]) for i, ws in enumerate(c["workspaces"], 1) if ws["output"]]
    if outs:
        L += ["", "# ---- workspaces on displays"] + [f"workspace $ws{i} output {o}" for i, o in outs]

    L += ["", "# ---- keys"]
    modes = []
    for b in c["bindings"]:
        if b["mode"] not in modes:
            modes.append(b["mode"])

    term = _terminal()

    def bind(b):
        opts = " --release" if b["release"] else ""
        cmd = b["command"]
        if term:   # the terminal chosen on the Default Apps page
            cmd = re.sub(r"\bi3-sensible-terminal\b", term, cmd)
        return f"{'bindcode' if b['code'] else 'bindsym'}{opts} {b['keys']} {cmd}"
    L += [bind(b) for b in c["bindings"] if b["mode"] == "default"]
    for m in modes:
        if m == "default":
            continue
        L += ["", f"mode {_q(m)} {{"] + ["    " + bind(b) for b in c["bindings"] if b["mode"] == m] + ["}"]

    L += ["", "# ---- startup", SESSION_LINE + "   # wallpaper, bar, compositor, lock, input (XControl)"]
    for s in c["startup"]:
        L.append(f"{'exec_always' if s['always'] else 'exec'}{' --no-startup-id' if s['no_startup_id'] else ''} "
                 f"{s['command']}")
    if c["rules"]:
        L += ["", "# ---- window rules"]
        for r in c["rules"]:
            crit = r["criteria"] if r["criteria"].startswith("[") else f"[{r['criteria']}]"
            L.append(f"{r['kind']} {crit} {r['action']}".rstrip())
    if c["i3bar"] and not bar_enabled:
        L += ["", "bar {", "    status_command i3status", "    position bottom", "}"]
    if c["extra"].strip():
        L += ["", "# ---- added on the page", c["extra"].strip()]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- on disk
def home():
    return os.path.expanduser("~")


def target():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home(), ".config")
    return os.path.join(base, "i3", "config")


def loaded_path():
    """The file i3 reads: ~/.i3/config wins over ~/.config/i3/config."""
    old = os.path.join(home(), ".i3", "config")
    return old if os.path.exists(old) else target()


def backup_path():
    return target() + ".before-xcontrol"


def is_ours(path=None):
    try:
        with open(path or target(), errors="replace") as f:
            return f.readline().startswith("# Generated by XControl")
    except OSError:
        return False


def validate(text):
    """(ok, errors) from `i3 -C` on the text (ok when i3 isn't installed: nothing to check with)."""
    if not shutil.which("i3"):
        return True, []
    tmp = target() + ".xcontrol-check"
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        r = subprocess.run(["i3", "-C", "-c", tmp], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return False, [str(e)]
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return r.returncode == 0, parse_errors(r.stdout + r.stderr)


def parse_errors(output):
    """i3 -C's report boiled down to one line per problem: the offending config line."""
    lines = [re.sub(r"^.*?ERROR:\s*(CONFIG:\s?)?", "", ln) for ln in output.splitlines() if "ERROR" in ln]
    out, last = [], None
    for ln in lines:
        m = re.match(r"^Line\s+(\d+):\s?(.*)$", ln)
        if m:
            last = (int(m.group(1)), m.group(2).strip())
        elif ln.strip().startswith("^") and last:
            out.append(f"Line {last[0]}: {last[1]}")
        elif ln.startswith("Expected") or ln.startswith("(in file") or not ln.strip():
            continue
        elif not ln.strip().startswith("*") and "v3" not in ln:
            out.append(ln.strip())
    return list(dict.fromkeys(out))


def _old_path():
    return os.path.join(home(), ".i3", "config")


def _keep(path):
    """Move a config that isn't XControl's aside as <path>.before-xcontrol (a symlink stays one)."""
    if os.path.lexists(path) and not is_ours(path):
        dest = path + ".before-xcontrol"
        if os.path.lexists(dest):
            dest += time.strftime("-%Y%m%d-%H%M%S")
        os.rename(path, dest)


def take_over():
    """Keep the configs i3 could read as backups, so XControl's can take their place
    (~/.i3/config would win over ~/.config/i3/config, so it moves aside too)."""
    _keep(target())
    _keep(_old_path())


def previous():
    """The config i3 used before XControl's: the current one when XControl hasn't taken over yet."""
    for path in (_old_path() + ".before-xcontrol", backup_path(), _old_path(), target()):
        if os.path.exists(path) and not is_ours(path):
            return path
    return None


def write(c, bar_enabled=False):
    """Check and write the config, then reload i3. Returns (ok, errors)."""
    text = generate(c, bar_enabled)
    try:
        with open(target(), encoding="utf-8", errors="replace") as f:
            if f.read() == text and not os.path.lexists(_old_path()):
                return True, []   # nothing changed: no reload
    except OSError:
        pass
    ok, errors = validate(text)
    if not ok:
        return False, errors
    path = target()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:   # written before the user's config moves aside, so a full disk leaves it where it was
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(text)
        take_over()
        os.replace(path + ".tmp", path)
    except OSError:
        try:
            os.remove(path + ".tmp")
        except OSError:
            pass
        raise
    reload()
    return True, []


def bar_enabled():
    """XControl's bar is on (then no i3bar block is written)."""
    try:
        from . import desktop
        return bool(desktop.load()["bar"]["enabled"]) and bool(shutil.which("polybar"))
    except Exception:  # noqa: BLE001
        return False


def refresh():
    """Rewrite XControl's i3 config after something it depends on changed (the bar was switched)."""
    c = load()
    if c["enabled"] and is_ours():
        return write(c, bar_enabled())
    return True, []


def restore():
    """Put the previous config(s) back (XControl's is kept as config.xcontrol)."""
    found = False
    for path in (target(), _old_path()):
        if os.path.lexists(path + ".before-xcontrol"):
            if is_ours(path):
                os.replace(path, path + ".xcontrol")
            if not os.path.lexists(path):
                os.rename(path + ".before-xcontrol", path)
                found = True
    if found:
        reload()
    return found


def can_restore():
    return any(os.path.lexists(p + ".before-xcontrol") for p in (target(), _old_path()))


def reload():
    if shutil.which("i3-msg") and os.environ.get("DISPLAY"):
        try:   # i3 not running: i3-msg just fails; a hung i3 mustn't raise after the file was written
            subprocess.run(["i3-msg", "-q", "reload"], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


_version = {}   # (path, mtime) -> version: the page and every write ask


def version():
    """i3's (major, minor), or None when it isn't installed."""
    exe = shutil.which("i3")
    try:
        key = (exe, os.stat(exe).st_mtime)
    except (OSError, TypeError):   # not installed
        return None
    if key in _version:
        return _version[key]
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"version (\d+)\.(\d+)", out)
    _version.clear()
    _version[key] = (int(m.group(1)), int(m.group(2))) if m else None
    return _version[key]


# ---------------------------------------------------------------- import
def _logical_lines(text):
    lines, buf = [], ""
    for raw in text.splitlines():
        if raw.rstrip().endswith("\\"):
            buf += raw.rstrip()[:-1] + " "
            continue
        lines.append(buf + raw)
        buf = ""
    if buf:
        lines.append(buf)
    return lines


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return re.sub(r'\\([\\"])', r"\1", s[1:-1])
    return s


def import_config(text, base=None, managed=None):
    """Settings from an existing i3 config: everything recognized, plus the remaining lines as
    'extra'. Startup lines for what XControl runs now (`managed`, see MANAGED; by default from
    the desktop settings) are left out, and so is a bar { } block when XControl's bar is on (else
    it's kept as is). Returns (settings, skipped)."""
    managed = managed_now() if managed is None else set(managed)
    c = normalize(base or {})
    c["bindings"], c["startup"], c["rules"] = [], [], []
    variables, extra, skipped = {}, [], []
    mod_value = None
    mode, depth_skip, keep_bar = "default", 0, False
    ws_vars = {}

    def subst(s):
        for name in sorted(variables, key=len, reverse=True):
            s = s.replace(name, variables[name])
        return s

    for raw in _logical_lines(text):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if depth_skip:   # inside bar { }
            depth_skip += line.count("{") - line.count("}")
            if keep_bar:
                extra.append(("    " if depth_skip else "") + subst(line))
            continue
        m = re.match(r"^set\s+(\$\w+)\s+(.*)$", line)
        if m:
            name, value = m.group(1), _unquote(m.group(2))
            wm = re.match(r"^\$ws(\d+)$", name)
            if not (wm and 1 <= int(wm.group(1)) <= 10):   # $ws1..$ws10 stay: XControl sets them too
                variables[name] = m.group(2).strip()          # as i3 does: the text, quotes and all
            if name == "$mod":
                mod_value = value
                if value in MODS:
                    c["mod"] = value
            if wm and 1 <= int(wm.group(1)) <= 10:
                c["workspaces"][int(wm.group(1)) - 1]["name"] = value
                ws_vars[value] = int(wm.group(1))
            continue
        if re.match(r"^bar\s*\{", line):
            depth_skip = 1 + line.count("{") - 1 - line.count("}")
            keep_bar = "bar" not in managed   # your own i3bar setup stays (instead of the plain one)
            if keep_bar:
                extra.append(subst(line))
                c["i3bar"] = False
            else:
                skipped.append("bar { … }")
            continue
        # substituted, as the bindings that enter it are: mode "$mode_system" {
        mm = re.match(r'^mode\s+(?:--pango_markup\s+)?"?([^"{]+?)"?\s*\{$', subst(line))
        if mm:
            mode = mm.group(1).strip()
            continue
        if line == "}":
            mode = "default"
            continue
        full = subst(line)
        bm = re.match(r"^(bindsym|bindcode)((?:\s+--[\w-]+)*)\s+(\S+)\s+(.+)$", full)
        if bm:
            keys = bm.group(3)
            if mod_value and keys.startswith(mod_value + "+"):
                keys = "$mod+" + keys[len(mod_value) + 1:]
            keys = keys.replace(f"+{mod_value}+", "+$mod+") if mod_value else keys
            c["bindings"].append({"keys": keys, "command": bm.group(4).strip(), "mode": mode,
                                  "code": bm.group(1) == "bindcode", "release": "--release" in bm.group(2)})
            continue
        em = re.match(r"^(exec|exec_always)\s+(--no-startup-id\s+)?(.+)$", full)
        if em:
            cmd = em.group(3).strip()
            if skipped_by(cmd, managed):
                skipped.append(full)
            else:
                c["startup"].append({"command": cmd, "always": em.group(1) == "exec_always",
                                     "no_startup_id": bool(em.group(2))})
            continue
        rm = re.match(r"^(for_window|assign)\s+(\[.*?\])\s*(.*)$", full)
        if rm:
            c["rules"].append({"kind": rm.group(1), "criteria": rm.group(2), "action": rm.group(3).strip()})
            continue
        wo = re.match(r'^workspace\s+(".*?"|\S+)\s+output\s+(.+)$', full)
        if wo:
            vm = re.match(r"^\$ws(\d+)$", wo.group(1))
            num = int(vm.group(1)) if vm else ws_vars.get(_unquote(wo.group(1)))
            if num is None and _unquote(wo.group(1)).split(":")[0].isdigit():
                num = int(_unquote(wo.group(1)).split(":")[0])
            if num and 1 <= num <= 10:
                c["workspaces"][num - 1]["output"] = wo.group(2).strip()
                continue
        if _setting(c, full):
            continue
        extra.append(full)
    c["extra"] = "\n".join(extra)
    return normalize(c), skipped


def _setting(c, line):
    """Simple 'key value' settings into c; True when recognized."""
    m = re.match(r"^(\S+)\s+(.*)$", line)
    if not m:
        return False
    key, value = m.group(1), m.group(2).strip()
    words = value.split()
    if key == "font":
        if not re.match(r"^(pango|xft):", value):
            return False   # an X core font (-misc-fixed-…): kept as is in 'extra', it isn't a Pango one
        c["font"] = re.sub(r"^(pango|xft):\s*", "", value)
        return True
    if key in ("default_border", "new_window") and words and words[0] in BORDERS:
        c["border"] = words[0]
        if len(words) > 1 and words[1].isdigit():
            c["border_width"] = int(words[1])
        return True
    if key in ("default_floating_border", "new_float") and words and words[0] in BORDERS:
        c["float_border"] = words[0]
        if len(words) > 1 and words[1].isdigit():
            c["float_border_width"] = int(words[1])
        return True
    if key == "gaps" and len(words) == 2 and words[0] in ("inner", "outer") and words[1].removesuffix("px").isdigit():
        c["gaps_" + words[0]] = int(words[1].removesuffix("px"))
        return True
    if key.startswith("client.") and key[7:] in COLOR_CLASSES:
        parts = words + c["colors"][key[7:]][len(words):]
        c["colors"][key[7:]] = parts[:5]
        return True
    if key == "client.background" and words:
        c["background"] = words[0]
        return True
    simple = {"title_align": "title_align", "hide_edge_borders": "hide_edge_borders", "smart_gaps": "smart_gaps",
              "smart_borders": "smart_borders", "mouse_warping": "mouse_warping",
              "focus_on_window_activation": "focus_on_activation", "focus_wrapping": "focus_wrapping",
              "default_orientation": "default_orientation", "workspace_layout": "workspace_layout",
              "popup_during_fullscreen": "popup_fullscreen"}
    if key in simple and value in CHOICES[simple[key]]:
        c[simple[key]] = value
        return True
    if key == "focus_follows_mouse":
        c["focus_follows_mouse"] = value in ("yes", "true", "on", "enable")
        return True
    if key == "workspace_auto_back_and_forth":
        c["back_and_forth"] = value in ("yes", "true", "on", "enable")
        return True
    if key == "floating_modifier":
        c["floating_drag"] = True
        return True
    if key == "tiling_drag":
        c["tiling_drag"] = value != "off"
        return True
    return False
