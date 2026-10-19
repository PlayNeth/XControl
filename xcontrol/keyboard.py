"""Keyboard: repeat delay/rate (xset) and layout, variant and options (setxkbmap).

Only settings the user changed in XControl are saved and re-applied, so a layout
set elsewhere (an i3 config line, xorg.conf.d) is left alone otherwise.
"""
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from . import config

RULES_DIRS = ("/usr/share/X11/xkb/rules", "/usr/local/share/X11/xkb/rules")
# option groups offered in the panel: group -> what it does
OPTION_GROUPS = ("grp", "caps", "compose", "ctrl", "altwin", "lv3", "numpad", "terminate")


@dataclass
class XkbLists:
    layouts: dict = field(default_factory=dict)    # "br" -> "Portuguese (Brazil)"
    variants: dict = field(default_factory=dict)   # "br" -> {"abnt2": "Portuguese (Brazil, ABNT2)"}
    options: dict = field(default_factory=dict)    # "caps" -> {"caps:escape": "Make Caps Lock ..."}
    groups: dict = field(default_factory=dict)     # "caps" -> "Caps Lock behavior"


def parse_lst(text):
    lists = XkbLists()
    section = None
    for line in text.splitlines():
        if line.startswith("! "):
            section = line[2:].strip()
            continue
        m = re.match(r"^\s+(\S+)\s+(.*)$", line)
        if not m:
            continue
        key, desc = m.group(1), m.group(2).strip()
        if section == "layout":
            lists.layouts[key] = desc
        elif section == "variant":
            layout, _, desc2 = desc.partition(": ")
            lists.variants.setdefault(layout, {})[key] = desc2 or desc
        elif section == "option":
            if ":" in key:
                lists.options.setdefault(key.split(":", 1)[0], {})[key] = desc
            else:
                lists.groups[key] = desc
    return lists


def load_lists():
    for d in RULES_DIRS:
        for name in ("evdev.lst", "base.lst"):
            path = os.path.join(d, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    return parse_lst(f.read())
            except OSError:
                continue
    return XkbLists()


def available():
    return bool(os.environ.get("DISPLAY")) and shutil.which("setxkbmap") is not None


def _run(args):
    out = subprocess.run(args, capture_output=True, text=True, timeout=10, env=dict(os.environ, LC_ALL="C"))
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"{args[0]} exited with {out.returncode}")
    return out.stdout


# ---- reading the current state
def parse_query(text):
    """`setxkbmap -query` -> {"layout": "us,br", "variant": ",abnt2", "options": [...]}"""
    out = {"layout": "", "variant": "", "options": []}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key in ("layout", "variant", "model"):
            out[key] = value
        elif key == "options":
            out["options"] = [o for o in value.split(",") if o]
    return out


def parse_xset(text):
    """`xset q` -> (delay ms, rate per second)"""
    m = re.search(r"auto repeat delay:\s*(\d+)\s+repeat rate:\s*(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else (660, 25)


def current():
    state = parse_query(_run(["setxkbmap", "-query"]))
    try:
        state["repeat_delay"], state["repeat_rate"] = parse_xset(_run(["xset", "q"]))
    except (RuntimeError, OSError):
        state["repeat_delay"], state["repeat_rate"] = 660, 25
    return state


# ---- writing
def repeat_args(delay, rate):
    return ["xset", "r", "rate", str(int(delay)), str(int(rate))]


def xkb_args(layout, variant, options):
    """setxkbmap call; "-option ''" first clears the old options (setxkbmap adds otherwise)."""
    args = ["setxkbmap", "-layout", layout, "-variant", variant or "", "-option", ""]
    for o in options:
        args += ["-option", o]
    return args


def apply_settings(kb, base=None):
    """Apply saved keyboard settings `kb` on top of the current state `base`."""
    if not kb:
        return
    if "repeat_delay" in kb or "repeat_rate" in kb:
        cur = base or {}
        delay = kb.get("repeat_delay", cur.get("repeat_delay", 660))
        rate = kb.get("repeat_rate", cur.get("repeat_rate", 25))
        _run(repeat_args(delay, rate))
    if any(k in kb for k in ("layout", "variant", "options")):
        cur = base if base is not None else parse_query(_run(["setxkbmap", "-query"]))
        _run(xkb_args(kb.get("layout", cur["layout"]), kb.get("variant", cur["variant"]),
                      kb.get("options", cur["options"])))


def apply_saved():
    kb = config.load()["input"]["keyboard"]
    if kb and available():
        apply_settings(kb)


def save(changes):
    data = config.load()
    data["input"]["keyboard"].update(changes)
    config.save(data)


def forget():
    data = config.load()
    data["input"]["keyboard"] = {}
    config.save(data)


# ---- helpers for the layout fields
def split_layouts(layout, variant):
    """("us,br", ",abnt2") -> [("us", ""), ("br", "abnt2")]"""
    ls = layout.split(",") if layout else []
    vs = variant.split(",") if variant else []
    return [(lay, vs[i] if i < len(vs) else "") for i, lay in enumerate(ls)]


def join_layouts(pairs):
    pairs = [(lay, var) for lay, var in pairs if lay]
    layout = ",".join(lay for lay, _ in pairs)
    variant = ",".join(var for _, var in pairs)
    return layout, ("" if not variant.strip(",") else variant)


def with_option(options, group, choice):
    """Replace the option of `group` (e.g. all "caps:*") with `choice` ("" removes it)."""
    out = [o for o in options if not o.startswith(group + ":")]
    if choice:
        out.append(choice)
    return out
