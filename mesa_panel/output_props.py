"""Scaling and colour settings that X drivers expose as RandR output properties.

Both xf86-video-amdgpu and modesetting pass the kernel's connector properties
through ("scaling mode", "underscan", "max bpc", "Broadcast RGB"), and both add
"CTM", the colour transformation matrix the display engine applies to every
pixel. Gamma uses xrandr's own --gamma. Only properties an output actually has
are shown or set.
"""
import copy

# name -> value the driver starts with (None: the top of the property's range)
MANAGED = {
    "scaling mode": "None",
    "underscan": "off",
    "underscan hborder": "0",
    "underscan vborder": "0",
    "Broadcast RGB": "Automatic",
    "max bpc": None,
    "CTM": None,  # identity
}
ORDER = list(MANAGED)

# Rec. 709 luma weights: desaturating keeps perceived brightness
LUMA = (0.2126, 0.7152, 0.0722)
IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


# ---- CTM: 3x3 matrix of S31.32 sign-magnitude fixed point, as 18 32-bit words (low word first)
def ctm_encode(matrix):
    words = []
    for row in matrix:
        for v in row:
            mag = min(round(abs(v) * (1 << 32)), (1 << 63) - 1)
            u = mag | (1 << 63 if v < 0 and mag else 0)
            words += [u & 0xFFFFFFFF, u >> 32]
    return words


def ctm_decode(words):
    """Matrix from the property as xrandr prints it: 18 32-bit words (xrandr < 1.5.3)
    or 9 decimals (xrandr >= 1.5.3). None if it isn't a full matrix.
    A single 0 is how xf86-video-amdgpu reports "no CTM set" (identity)."""
    words = list(words)
    if len(words) == 9 or any("." in str(w) for w in words):
        try:
            vals = [float(w) for w in words]
        except ValueError:
            return None
        return [vals[0:3], vals[3:6], vals[6:9]] if len(vals) == 9 else None
    try:
        words = [int(w, 0) & 0xFFFFFFFF if isinstance(w, str) else int(w) & 0xFFFFFFFF for w in words]
    except ValueError:
        return None
    if words in ([], [0]):
        return copy.deepcopy(IDENTITY)
    if len(words) != 18:
        return None
    vals = []
    for i in range(9):
        u = words[2 * i] | (words[2 * i + 1] << 32)
        v = (u & ((1 << 63) - 1)) / (1 << 32)
        vals.append(-v if u >> 63 else v)
    return [vals[0:3], vals[3:6], vals[6:9]]


def saturation_matrix(s):
    """s = 1 leaves colours alone, 0 is grayscale, 2 doubles saturation."""
    return [[(1 - s) * LUMA[j] + (s if i == j else 0.0) for j in range(3)] for i in range(3)]


def saturation_of(matrix):
    """The saturation a matrix applies, or None if it isn't a plain saturation matrix
    (set by another tool, e.g. a colour correction)."""
    if matrix is None:
        return None
    s = matrix[0][0] - matrix[1][0]
    expected = saturation_matrix(s)
    if all(abs(matrix[i][j] - expected[i][j]) < 1e-5 for i in range(3) for j in range(3)):  # xrandr prints 6 decimals
        return s
    return None


# ---- reading
def attach(monitors, verbose):
    """Fill monitor.props / .choices / .ranges / .gamma from parse_verbose() output."""
    for m in monitors:
        entry = verbose.get(m.name)
        if not entry:
            continue
        props = entry["props"]
        for name in ORDER:
            if name not in props:
                continue
            m.props[name] = " ".join(props[name].split())
            if name == "CTM":
                mat = ctm_decode(m.props[name].split())
                if mat is None:  # a format we don't understand: leave the colour matrix alone
                    del m.props[name]
                    continue
                m.props[name] = " ".join(str(w) for w in ctm_encode(mat))  # one internal format
            extra = props.get(name + " (range)", "")
            if extra.startswith("("):
                try:
                    lo, hi = (int(x) for x in extra.strip("()").split(","))
                    m.ranges[name] = (lo, hi)
                except ValueError:
                    pass
            elif extra:
                m.choices[name] = [c.strip() for c in extra.split(",") if c.strip()]
        g = props.get("Gamma")
        if g:
            # xrandr prints the exponent of the ramp, the reciprocal of what --gamma takes
            # (--gamma 1.2 reads back as 0.83), with two significant digits.
            try:
                m.gamma = tuple(round(1.0 / float(x), 2) for x in g.split(":"))
                m.has_gamma = len(m.gamma) == 3
            except (ValueError, ZeroDivisionError):
                pass


def default_of(m, name):
    if name == "max bpc":
        return str(m.ranges[name][1]) if name in m.ranges else None
    if name == "CTM":
        return None
    return MANAGED[name]


def is_default(m, name):
    if name == "CTM":
        mat = ctm_decode(m.props[name].split())
        return mat is not None and all(abs(mat[i][j] - IDENTITY[i][j]) < 1e-9 for i in range(3) for j in range(3))
    d = default_of(m, name)
    return d is None or m.props[name] == d  # unknown default: only set when changed


def _same(a, b, name):
    if name == "CTM":
        return ctm_decode(a.split()) == ctm_decode(b.split())
    return a == b


def _uniform(g):
    return len(set(round(x, 3) for x in g)) == 1


# ---- writing
def ctm_value(m, xrandr_version=None):
    """The CTM as this xrandr's --set reads it: xrandr 1.5.3 and later take nine
    comma-separated decimals (and would misread raw words as decimals), older ones
    take the 18 raw 32-bit words."""
    from . import xrandr
    mat = ctm_decode(m.props["CTM"].split()) or IDENTITY
    if (xrandr_version or xrandr.version()) >= (1, 5, 3):
        return ",".join(f"{v:.10f}" for row in mat for v in row)
    return ",".join(f"0x{w:x}" for w in ctm_encode(mat))


def set_saturation(m, s):
    m.props["CTM"] = " ".join(str(w) for w in ctm_encode(saturation_matrix(s)))


def args_for(m, reference=None):
    """xrandr arguments for this output's managed properties: every value that
    isn't the driver's default (so a saved layout restores it after X restarts),
    plus every value that differs from `reference` (so going back to a default,
    or reverting, is applied too)."""
    args = []
    ref_props = reference.props if reference is not None else {}
    for name in ORDER:
        if name not in m.props:
            continue
        changed = name in ref_props and not _same(m.props[name], ref_props[name], name)
        if changed or not is_default(m, name):
            value = ctm_value(m) if name == "CTM" else m.props[name]
            args += ["--set", name, value]
    if m.has_gamma:
        ref_g = reference.gamma if reference is not None and reference.has_gamma else None
        changed = ref_g is not None and any(abs(a - b) > 1e-3 for a, b in zip(m.gamma, ref_g))
        # Night-light tools (redshift and the like) leave unequal channels; never save those.
        custom = _uniform(m.gamma) and abs(m.gamma[0] - 1.0) > 1e-3
        if changed or custom:
            args += ["--gamma", ":".join(f"{g:.3g}" for g in m.gamma)]
    return args


def preview_args(m):
    """xrandr arguments that set only this output's colour matrix and gamma: no mode
    set, so they can run while a slider moves (live preview)."""
    args = ["--output", m.name]
    if "CTM" in m.props:
        args += ["--set", "CTM", ctm_value(m)]
    if m.has_gamma:
        args += ["--gamma", ":".join(f"{g:.3g}" for g in m.gamma)]
    return args if len(args) > 2 else []
