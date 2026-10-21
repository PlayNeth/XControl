"""A live 3D preview for the Gaming page, in the spirit of the old Catalyst and NVIDIA
control panels: glxgears' three gears turning above a checkerboard floor, with a
chain-link fence behind them, drawn with the settings being edited:

  multisampling     the gears' edges (rendered into a multisampled framebuffer)
  anisotropic       the floor stretching to the horizon
  transparency AA   the fence (alpha test / alpha-to-coverage / per-sample shading)
  frame limiter     the animation's frame rate

It renders off-screen in its own OpenGL context (EGL, surfaceless) and shows each frame as
an ordinary image. GTK's GtkGLArea isn't used on purpose: in GTK 3 on X11 it switches the
whole window to OpenGL drawing, which without a compositor (i3) leaves stale screen contents
in parts of the window. OpenGL is called through libepoxy with ctypes; nothing else is needed.
The animation only runs while the preview is on screen.
"""
import ctypes
import ctypes.util
import math
import time

import cairo

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .i18n import _  # noqa: E402

# ---------------------------------------------------------------- GL through libepoxy
GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT = 0x4000, 0x0100
GL_DEPTH_TEST, GL_MULTISAMPLE, GL_SAMPLE_ALPHA_TO_COVERAGE, GL_SAMPLE_SHADING = 0x0B71, 0x809D, 0x809E, 0x8C36
GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_COMPILE_STATUS, GL_LINK_STATUS = 0x8B31, 0x8B30, 0x8B81, 0x8B82
GL_ARRAY_BUFFER, GL_STATIC_DRAW, GL_FLOAT, GL_TRIANGLES = 0x8892, 0x88E4, 0x1406, 0x0004
GL_TEXTURE_2D, GL_RGBA, GL_RGBA8, GL_UNSIGNED_BYTE, GL_TEXTURE0 = 0x0DE1, 0x1908, 0x8058, 0x1401, 0x84C0
GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T = 0x2801, 0x2800, 0x2802, 0x2803
GL_LINEAR, GL_NEAREST, GL_LINEAR_MIPMAP_LINEAR, GL_REPEAT = 0x2601, 0x2600, 0x2703, 0x2901
GL_TEXTURE_MAX_ANISOTROPY, GL_MAX_TEXTURE_MAX_ANISOTROPY = 0x84FE, 0x84FF
GL_FRAMEBUFFER, GL_READ_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER_BINDING = 0x8D40, 0x8CA8, 0x8CA9, 0x8CA6
GL_RENDERBUFFER, GL_COLOR_ATTACHMENT0, GL_DEPTH_ATTACHMENT, GL_DEPTH_COMPONENT24 = 0x8D41, 0x8CE0, 0x8D00, 0x81A6
GL_FRAMEBUFFER_COMPLETE, GL_MAX_SAMPLES, GL_RENDERER, GL_VERSION = 0x8CD5, 0x8D57, 0x1F01, 0x1F02
GL_MAJOR_VERSION, GL_MINOR_VERSION, GL_NUM_EXTENSIONS, GL_EXTENSIONS = 0x821B, 0x821C, 0x821D, 0x1F03

_u, _i, _f, _p = ctypes.c_uint, ctypes.c_int, ctypes.c_float, ctypes.c_void_p
_SIGS = {
    "glClearColor": (None, [_f, _f, _f, _f]), "glClear": (None, [_u]), "glEnable": (None, [_u]),
    "glDisable": (None, [_u]), "glViewport": (None, [_i, _i, _i, _i]),
    "glGetIntegerv": (None, [_u, ctypes.POINTER(_i)]), "glGetFloatv": (None, [_u, ctypes.POINTER(_f)]),
    "glGetString": (ctypes.c_char_p, [_u]), "glGetStringi": (ctypes.c_char_p, [_u, _u]),
    "glCreateShader": (_u, [_u]),
    "glShaderSource": (None, [_u, _i, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(_i)]),
    "glCompileShader": (None, [_u]), "glGetShaderiv": (None, [_u, _u, ctypes.POINTER(_i)]),
    "glGetShaderInfoLog": (None, [_u, _i, ctypes.POINTER(_i), ctypes.c_char_p]),
    "glCreateProgram": (_u, []), "glAttachShader": (None, [_u, _u]),
    "glBindAttribLocation": (None, [_u, _u, ctypes.c_char_p]), "glLinkProgram": (None, [_u]),
    "glGetProgramiv": (None, [_u, _u, ctypes.POINTER(_i)]),
    "glGetProgramInfoLog": (None, [_u, _i, ctypes.POINTER(_i), ctypes.c_char_p]),
    "glUseProgram": (None, [_u]), "glGetUniformLocation": (_i, [_u, ctypes.c_char_p]),
    "glUniformMatrix4fv": (None, [_i, _i, ctypes.c_ubyte, ctypes.POINTER(_f)]),
    "glUniform3f": (None, [_i, _f, _f, _f]), "glUniform1i": (None, [_i, _i]), "glUniform1f": (None, [_i, _f]),
    "glGenVertexArrays": (None, [_i, ctypes.POINTER(_u)]), "glBindVertexArray": (None, [_u]),
    "glGenBuffers": (None, [_i, ctypes.POINTER(_u)]), "glBindBuffer": (None, [_u, _u]),
    "glBufferData": (None, [_u, ctypes.c_ssize_t, _p, _u]),
    "glVertexAttribPointer": (None, [_u, _i, _u, ctypes.c_ubyte, _i, _p]),
    "glEnableVertexAttribArray": (None, [_u]), "glDrawArrays": (None, [_u, _i, _i]),
    "glGenTextures": (None, [_i, ctypes.POINTER(_u)]), "glBindTexture": (None, [_u, _u]),
    "glActiveTexture": (None, [_u]),
    "glTexImage2D": (None, [_u, _i, _i, _i, _i, _i, _u, _u, _p]),
    "glTexParameteri": (None, [_u, _u, _i]), "glTexParameterf": (None, [_u, _u, _f]),
    "glGenerateMipmap": (None, [_u]),
    "glGenFramebuffers": (None, [_i, ctypes.POINTER(_u)]), "glBindFramebuffer": (None, [_u, _u]),
    "glDeleteFramebuffers": (None, [_i, ctypes.POINTER(_u)]),
    "glGenRenderbuffers": (None, [_i, ctypes.POINTER(_u)]), "glBindRenderbuffer": (None, [_u, _u]),
    "glDeleteRenderbuffers": (None, [_i, ctypes.POINTER(_u)]),
    "glRenderbufferStorage": (None, [_u, _u, _i, _i]),
    "glRenderbufferStorageMultisample": (None, [_u, _i, _u, _i, _i]),
    "glFramebufferRenderbuffer": (None, [_u, _u, _u, _u]), "glCheckFramebufferStatus": (_u, [_u]),
    "glBlitFramebuffer": (None, [_i, _i, _i, _i, _i, _i, _i, _i, _u, _u]),
    "glMinSampleShading": (None, [_f]),
    "glReadPixels": (None, [_i, _i, _i, _i, _u, _u, _p]), "glPixelStorei": (None, [_u, _i]),
}
GL_BGRA, GL_PACK_ALIGNMENT = 0x80E1, 0x0D05


class GL:
    def __init__(self):
        lib = ctypes.CDLL(ctypes.util.find_library("epoxy") or "libepoxy.so.0")
        for name, (res, args) in _SIGS.items():
            ptr = _p.in_dll(lib, "epoxy_" + name).value  # epoxy's dispatch stub for this function
            setattr(self, name[2:], ctypes.CFUNCTYPE(res, *args)(ptr))
        self._keep = lib

    def get_int(self, enum):
        v = _i(0)
        self.GetIntegerv(enum, ctypes.byref(v))
        return v.value

    def gen(self, fn):
        v = _u(0)
        fn(1, ctypes.byref(v))
        return v.value


class EGLContext:
    """An OpenGL 3.3 core context with no window: rendering goes into framebuffer objects."""
    EGL_NONE, EGL_OPENGL_API, EGL_OPENGL_BIT, EGL_PBUFFER_BIT = 0x3038, 0x30A2, 0x0008, 0x0001
    EGL_SURFACE_TYPE, EGL_RENDERABLE_TYPE, EGL_RED, EGL_GREEN, EGL_BLUE = 0x3033, 0x3040, 0x3024, 0x3023, 0x3022
    EGL_WIDTH, EGL_HEIGHT = 0x3057, 0x3056
    EGL_MAJOR, EGL_MINOR, EGL_PROFILE, EGL_CORE = 0x3098, 0x30FB, 0x30FD, 0x1
    EGL_PLATFORM_SURFACELESS_MESA = 0x31DD

    def __init__(self):
        egl = ctypes.CDLL(ctypes.util.find_library("EGL") or "libEGL.so.1")
        vp, i = ctypes.c_void_p, ctypes.c_int
        for name, res, args in (("eglGetDisplay", vp, [vp]), ("eglInitialize", i, [vp, vp, vp]),
                                ("eglBindAPI", i, [ctypes.c_uint]), ("eglGetProcAddress", vp, [ctypes.c_char_p]),
                                ("eglChooseConfig", i, [vp, ctypes.POINTER(i), ctypes.POINTER(vp), i,
                                                        ctypes.POINTER(i)]),
                                ("eglCreateContext", vp, [vp, vp, vp, ctypes.POINTER(i)]),
                                ("eglCreatePbufferSurface", vp, [vp, vp, ctypes.POINTER(i)]),
                                ("eglMakeCurrent", i, [vp, vp, vp, vp]), ("eglDestroyContext", i, [vp, vp]),
                                ("eglDestroySurface", i, [vp, vp]), ("eglGetError", i, [])):
            f = getattr(egl, name)
            f.restype, f.argtypes = res, args
        self.egl = egl
        dpy = None
        get_platform = egl.eglGetProcAddress(b"eglGetPlatformDisplayEXT")
        if get_platform:  # no window system needed at all
            fn = ctypes.CFUNCTYPE(vp, ctypes.c_uint, vp, vp)(get_platform)
            dpy = fn(self.EGL_PLATFORM_SURFACELESS_MESA, None, None)
            if dpy and not egl.eglInitialize(dpy, None, None):
                dpy = None
        if not dpy:
            dpy = egl.eglGetDisplay(None)
            if not dpy or not egl.eglInitialize(dpy, None, None):
                raise RuntimeError("EGL is not available")
        self.dpy = dpy
        if not egl.eglBindAPI(self.EGL_OPENGL_API):
            raise RuntimeError("EGL has no desktop OpenGL")

        def attrs(*pairs):
            flat = [v for p in pairs for v in p] + [self.EGL_NONE]
            return (i * len(flat))(*flat)
        config, n = vp(), i(0)
        for surface_type in (self.EGL_PBUFFER_BIT, 0):
            want = [(self.EGL_RENDERABLE_TYPE, self.EGL_OPENGL_BIT), (self.EGL_RED, 8), (self.EGL_GREEN, 8),
                    (self.EGL_BLUE, 8)] + ([(self.EGL_SURFACE_TYPE, surface_type)] if surface_type else [])
            if egl.eglChooseConfig(dpy, attrs(*want), ctypes.byref(config), 1, ctypes.byref(n)) and n.value:
                break
        if not n.value:
            raise RuntimeError("no suitable EGL config")
        self.ctx = egl.eglCreateContext(dpy, config, None, attrs((self.EGL_MAJOR, 3), (self.EGL_MINOR, 3),
                                                                 (self.EGL_PROFILE, self.EGL_CORE)))
        if not self.ctx:
            raise RuntimeError(f"no OpenGL 3.3 context (EGL error 0x{egl.eglGetError():x})")
        # a 1×1 pbuffer to be current with; without one, surfaceless contexts are used
        self.surf = egl.eglCreatePbufferSurface(dpy, config, attrs((self.EGL_WIDTH, 1), (self.EGL_HEIGHT, 1)))
        self.make_current()

    def make_current(self):
        if not self.egl.eglMakeCurrent(self.dpy, self.surf, self.surf, self.ctx):
            raise RuntimeError(f"eglMakeCurrent failed (0x{self.egl.eglGetError():x})")

    def destroy(self):
        self.egl.eglMakeCurrent(self.dpy, None, None, None)
        if self.surf:
            self.egl.eglDestroySurface(self.dpy, self.surf)
        self.egl.eglDestroyContext(self.dpy, self.ctx)


# ---------------------------------------------------------------- math (column-major 4x4)
def mat_mul(a, b):
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def perspective(fovy, aspect, near, far):
    f = 1 / math.tan(math.radians(fovy) / 2)
    return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1,
            0, 0, 2 * far * near / (near - far), 0]


def translate(x, y, z):
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]


def rotate(deg, x, y, z):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    n = math.sqrt(x * x + y * y + z * z)
    x, y, z = x / n, y / n, z / n
    return [x * x * (1 - c) + c, y * x * (1 - c) + z * s, x * z * (1 - c) - y * s, 0,
            x * y * (1 - c) - z * s, y * y * (1 - c) + c, y * z * (1 - c) + x * s, 0,
            x * z * (1 - c) + y * s, y * z * (1 - c) - x * s, z * z * (1 - c) + c, 0, 0, 0, 0, 1]


def apply(m, v):
    return tuple(sum(m[c * 4 + r] * (v[c] if c < 3 else 1.0) for c in range(4)) for r in range(3))


# ---------------------------------------------------------------- geometry
def gear(inner, outer, width, teeth, depth):
    """glxgears' gear as triangles: [(x, y, z, nx, ny, nz, u, v)]."""
    r0, r1, r2 = inner, outer - depth / 2, outer + depth / 2
    da = 2 * math.pi / teeth / 4
    hw = width / 2
    out = []

    def tri(a, b, c, n):
        for p in (a, b, c):
            out.append((*p, *n, 0.0, 0.0))

    def quad(a, b, c, d, n):
        tri(a, b, c, n)
        tri(a, c, d, n)

    def pt(r, ang, z):
        return (r * math.cos(ang), r * math.sin(ang), z)

    for i in range(teeth):
        a = i * 2 * math.pi / teeth
        for z, nz in ((hw, 1.0), (-hw, -1.0)):
            n = (0.0, 0.0, nz)
            quad(pt(r0, a, z), pt(r1, a, z), pt(r1, a + 4 * da, z), pt(r0, a + 4 * da, z), n)   # ring
            quad(pt(r1, a, z), pt(r2, a + da, z), pt(r2, a + 2 * da, z), pt(r1, a + 3 * da, z), n)  # tooth
        outline = [(r1, a), (r2, a + da), (r2, a + 2 * da), (r1, a + 3 * da), (r1, a + 4 * da)]
        for (ra, aa), (rb, ab) in zip(outline, outline[1:]):
            u, v = pt(ra, aa, 0), pt(rb, ab, 0)
            nx, ny = v[1] - u[1], -(v[0] - u[0])
            ln = math.hypot(nx, ny) or 1
            quad(pt(ra, aa, hw), pt(ra, aa, -hw), pt(rb, ab, -hw), pt(rb, ab, hw), (nx / ln, ny / ln, 0.0))
        for k in range(4):  # inner bore, smooth
            a0, a1 = a + k * da, a + (k + 1) * da
            n0 = (-math.cos(a0), -math.sin(a0), 0.0)
            quad(pt(r0, a0, -hw), pt(r0, a0, hw), pt(r0, a1, hw), pt(r0, a1, -hw), n0)
    return out


def plane(corners, uv_scale, normal):
    """Two triangles for a quad [(x,y,z)×4] with tiled texture coordinates."""
    uv = [(0, 0), (uv_scale[0], 0), (uv_scale[0], uv_scale[1]), (0, uv_scale[1])]
    idx = (0, 1, 2, 0, 2, 3)
    return [(*corners[i], *normal, *uv[i]) for i in idx]


def checker_texture(size=256, cells=4):
    """Light and dark squares with thin dark lines: shimmer and blur at a distance show
    the texture filtering clearly."""
    data = bytearray(size * size * 4)
    step = size // cells
    for y in range(size):
        for x in range(size):
            if x % step < 2 or y % step < 2:
                c = (35, 35, 40)
            elif ((x // step) + (y // step)) % 2:
                c = (220, 220, 225)
            else:
                c = (80, 84, 96)
            i = (y * size + x) * 4
            data[i:i + 4] = bytes((*c, 255))
    return bytes(data)


def fence_texture(size=64, wire=3):
    """Chain link: two diagonal wires per tile, alpha 0 between them."""
    data = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            d1, d2 = (x + y) % size, (x - y) % size
            on = min(d1, size - d1) < wire or min(d2, size - d2) < wire
            i = (y * size + x) * 4
            data[i:i + 4] = bytes((190, 196, 205, 255 if on else 0))
    return bytes(data)


VERT = b"""#version 330 core
layout(location = 0) in vec3 pos;
layout(location = 1) in vec3 nrm;
layout(location = 2) in vec2 uv;
uniform mat4 mvp;
uniform mat4 model;
out vec3 vN;
out vec2 vUV;
out vec3 vW;
void main() {
    vN = mat3(model) * nrm;
    vUV = uv;
    vW = (model * vec4(pos, 1.0)).xyz;
    gl_Position = mvp * vec4(pos, 1.0);
}
"""
FRAG = b"""#version 330 core
in vec3 vN;
in vec2 vUV;
in vec3 vW;
uniform int mode;          // 0 lit color, 1 floor, 2 fence
uniform vec3 color;
uniform sampler2D tex;
uniform int alpha_test;    // fence: discard below 0.5 (no transparency AA)
uniform vec3 eye;
out vec4 frag;
const vec3 sky = vec3(0.10, 0.12, 0.16);
void main() {
    vec3 L = normalize(vec3(0.4, 0.8, 0.6));
    vec4 c;
    if (mode == 0) {
        vec3 N = normalize(vN);
        vec3 V = normalize(eye - vW);
        vec3 H = normalize(L + V);
        float d = max(dot(N, L), 0.0);
        float s = pow(max(dot(N, H), 0.0), 40.0) * 0.5;
        c = vec4(color * (0.22 + 0.85 * d) + vec3(s), 1.0);
    } else {
        c = texture(tex, vUV);
        if (mode == 2 && alpha_test == 1 && c.a < 0.5) discard;
        if (mode == 1) c.rgb *= 0.9;
    }
    float fog = 1.0 - exp(-max(length(vW - eye) - 18.0, 0.0) * 0.012);
    frag = vec4(mix(c.rgb, sky, fog), c.a);
}
"""


class Preview3D(Gtk.Overlay):
    """The GL area plus a caption with what's being shown and the frame rate."""

    def __init__(self):
        super().__init__()
        self.area = Gtk.DrawingArea(hexpand=True)
        self.area.set_size_request(-1, 240)
        self.area.connect("draw", self._draw)
        self.area.connect("unrealize", self._unrealize)
        self.area.connect("map", self._start)
        self.area.connect("unmap", self._stop)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK)
        self.area.connect("button-press-event", self._press)
        self.area.connect("button-release-event", lambda *_a: self._drag.clear())
        self.area.connect("motion-notify-event", self._motion)
        self.area.set_tooltip_text(_("Drag to turn the scene"))
        self.add(self.area)

        self.caption = Gtk.Label(halign=Gtk.Align.START, valign=Gtk.Align.END, margin=8)
        self.caption.get_style_context().add_class("xcontrol-preview-caption")
        self.add_overlay(self.caption)
        self.fps_label = Gtk.Label(halign=Gtk.Align.END, valign=Gtk.Align.START, margin=8)
        self.fps_label.get_style_context().add_class("xcontrol-preview-caption")
        self.add_overlay(self.fps_label)
        css = Gtk.CssProvider()
        css.load_from_data(b".xcontrol-preview-caption { color: #f0f0f0; background-color: rgba(0,0,0,0.55);"
                           b" padding: 3px 7px; border-radius: 4px; font-size: smaller; }")
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.settings = {"msaa": 0, "af": 0, "traa": "off", "fps_limit": 0}
        self.gl = None
        self.error = None
        self.tick_id = None
        self.angle = 0.0
        self.yaw, self.pitch = -18.0, 8.0
        self._drag = {}
        self.last_time = None
        self.last_frame = 0.0
        self.frames, self.fps_since = 0, time.monotonic()
        self.fbo = None
        self.fbo_key = None
        self.ctx = None
        self.image = None       # the last frame, as a cairo surface
        self._pixels = None
        self._caption()

    # ---- what to show
    def set_settings(self, s):
        self.settings = {k: s.get(k, v) for k, v in self.settings.items()}
        self._caption()
        self._frame()

    def _effective(self):
        s = self.settings
        samples = s["msaa"] if s["msaa"] > 1 else 1
        af = s["af"] if s["af"] > 1 else 1
        traa = s["traa"] if samples > 1 else "off"   # it only works on top of multisampling
        return samples, af, traa

    def _caption(self):
        samples, af, traa = self._effective()
        s = self.settings
        limit = getattr(self, "max_samples", 0)
        if samples > 1 and limit and samples > limit:
            parts = [_("{n}× MSAA (this GPU: {max}×)").format(n=samples, max=limit)]
        else:
            parts = []
        parts = parts or [(_("{n}× MSAA").format(n=samples) if samples > 1 else
                  (_("No forced AA") if s["msaa"] == 0 else _("AA off")))]
        parts.append(_("{n}× AF").format(n=af) if af > 1 else
                     (_("App's filtering") if s["af"] == 0 else _("AF off")))
        if traa != "off":
            parts.append(_("supersampled fence") if traa == "supersample" else _("alpha-to-coverage fence"))
        if s["fps_limit"]:
            parts.append(_("limit {n} FPS").format(n=s["fps_limit"]))
        if self.error:
            parts = [self.error]
        self.caption.set_text(" · ".join(parts))

    # ---- animation
    def _start(self, *_a):
        if self.tick_id is None:
            self.last_time = None
            self.tick_id = self.area.add_tick_callback(self._tick)

    def _stop(self, *_a):
        if self.tick_id is not None:
            self.area.remove_tick_callback(self.tick_id)
            self.tick_id = None

    def _tick(self, _w, clock):
        now = clock.get_frame_time() / 1e6
        limit = self.settings["fps_limit"]
        if limit and now - self.last_frame < 1.0 / limit - 0.002:
            return GLib.SOURCE_CONTINUE
        dt = 0 if self.last_time is None else min(now - self.last_time, 0.1)
        self.last_time = self.last_frame = now
        self.angle = (self.angle + dt * 70.0) % 360.0   # degrees per second, like glxgears
        self._frame()
        return GLib.SOURCE_CONTINUE

    def _press(self, _w, ev):
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            self.yaw, self.pitch = -18.0, 8.0
        self._drag.update(x=ev.x, y=ev.y, yaw=self.yaw, pitch=self.pitch)

    def _motion(self, _w, ev):
        if self._drag:
            self.yaw = self._drag["yaw"] + (ev.x - self._drag["x"]) * 0.4
            self.pitch = max(-5.0, min(40.0, self._drag["pitch"] + (ev.y - self._drag["y"]) * 0.3))
            if self.tick_id is None:
                self._frame()

    # ---- GL setup (on the first frame)
    def _ensure_gl(self):
        if self.gl or self.error:
            return bool(self.gl)
        try:
            self.ctx = EGLContext()
            self.gl = GL()
            self._setup()
        except Exception as e:  # noqa: BLE001
            self.gl = None
            self.error = _("3D preview unavailable: {error}").format(error=e)
            self._caption()
        return bool(self.gl)

    def _unrealize(self, _area):
        self._stop()
        if self.ctx:
            try:
                self.ctx.make_current()
                self._free_fbo()
            finally:
                self.ctx.destroy()
        self.ctx = self.gl = None
        self.fbo = self.fbo_key = None

    def _shader(self, kind, src):
        gl = self.gl
        sh = gl.CreateShader(kind)
        arr = (ctypes.c_char_p * 1)(src)
        gl.ShaderSource(sh, 1, arr, None)
        gl.CompileShader(sh)
        ok = _i(0)
        gl.GetShaderiv(sh, GL_COMPILE_STATUS, ctypes.byref(ok))
        if not ok.value:
            log = ctypes.create_string_buffer(4096)
            gl.GetShaderInfoLog(sh, 4096, None, log)
            raise RuntimeError(log.value.decode(errors="replace"))
        return sh

    def _mesh(self, verts):
        gl = self.gl
        flat = [c for v in verts for c in v]
        buf = (ctypes.c_float * len(flat))(*flat)
        vao = gl.gen(gl.GenVertexArrays)
        gl.BindVertexArray(vao)
        vbo = gl.gen(gl.GenBuffers)
        gl.BindBuffer(GL_ARRAY_BUFFER, vbo)
        gl.BufferData(GL_ARRAY_BUFFER, ctypes.sizeof(buf), buf, GL_STATIC_DRAW)
        stride = 8 * 4
        for loc, size, off in ((0, 3, 0), (1, 3, 12), (2, 2, 24)):
            gl.VertexAttribPointer(loc, size, GL_FLOAT, 0, stride, ctypes.c_void_p(off))
            gl.EnableVertexAttribArray(loc)
        return vao, len(verts)

    def _texture(self, data, size, repeat=True):
        gl = self.gl
        tex = gl.gen(gl.GenTextures)
        gl.BindTexture(GL_TEXTURE_2D, tex)
        buf = ctypes.create_string_buffer(data, len(data))
        gl.TexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, size, size, 0, GL_RGBA, GL_UNSIGNED_BYTE, buf)
        gl.GenerateMipmap(GL_TEXTURE_2D)
        gl.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
        gl.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        wrap = GL_REPEAT if repeat else 0x812F
        gl.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, wrap)
        gl.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, wrap)
        return tex

    def _setup(self):
        gl = self.gl
        self.version = (gl.get_int(GL_MAJOR_VERSION), gl.get_int(GL_MINOR_VERSION))
        exts = {gl.GetStringi(GL_EXTENSIONS, i) for i in range(gl.get_int(GL_NUM_EXTENSIONS))}
        self.has_aniso = self.version >= (4, 6) or b"GL_EXT_texture_filter_anisotropic" in exts or \
            b"GL_ARB_texture_filter_anisotropic" in exts
        self.has_sample_shading = self.version >= (4, 0) or b"GL_ARB_sample_shading" in exts
        self.max_samples = max(1, gl.get_int(GL_MAX_SAMPLES))
        mx = _f(1.0)
        if self.has_aniso:
            gl.GetFloatv(GL_MAX_TEXTURE_MAX_ANISOTROPY, ctypes.byref(mx))
        self.max_aniso = mx.value
        self.renderer = (gl.GetString(GL_RENDERER) or b"").decode(errors="replace")

        prog = gl.CreateProgram()
        gl.AttachShader(prog, self._shader(GL_VERTEX_SHADER, VERT))
        gl.AttachShader(prog, self._shader(GL_FRAGMENT_SHADER, FRAG))
        gl.LinkProgram(prog)
        ok = _i(0)
        gl.GetProgramiv(prog, GL_LINK_STATUS, ctypes.byref(ok))
        if not ok.value:
            raise RuntimeError("shader link failed")
        self.prog = prog
        self.u = {n: gl.GetUniformLocation(prog, n.encode())
                  for n in ("mvp", "model", "mode", "color", "tex", "alpha_test", "eye")}

        self.gears = [
            (self._mesh(gear(1.0, 4.0, 1.0, 20, 0.7)), (-3.0, -2.0), (0.8, 0.1, 0.0), 1.0, 0.0),
            (self._mesh(gear(0.5, 2.0, 2.0, 10, 0.7)), (3.1, -2.0), (0.0, 0.8, 0.2), -2.0, -9.0),
            (self._mesh(gear(1.3, 2.0, 0.5, 10, 0.7)), (-3.1, 4.2), (0.2, 0.2, 1.0), -2.0, -25.0),
        ]
        self.floor = self._mesh(plane([(-120, -7.5, 60), (120, -7.5, 60), (120, -7.5, -180), (-120, -7.5, -180)],
                                      (60, 60), (0, 1, 0)))
        self.fence = self._mesh(plane([(-16, -7.5, -9), (16, -7.5, -9), (16, 9, -9), (-16, 9, -9)],
                                      (10, 5.2), (0, 0, 1)))
        self.floor_tex = self._texture(checker_texture(), 256)
        self.fence_tex = self._texture(fence_texture(), 64)
        self.fps_label.set_text(self.renderer.split(" (")[0])
        self._caption()

    # ---- framebuffers
    def _free_fbo(self):
        if self.fbo and self.gl:
            for fbo, *rbs in self.fbo:
                self.gl.DeleteFramebuffers(1, ctypes.byref(_u(fbo)))
                for rb in rbs:
                    self.gl.DeleteRenderbuffers(1, ctypes.byref(_u(rb)))
        self.fbo, self.fbo_key = None, None

    def _make_fbo(self, w, h, samples, depth):
        gl = self.gl
        fbo = gl.gen(gl.GenFramebuffers)
        gl.BindFramebuffer(GL_FRAMEBUFFER, fbo)
        rbs = []
        formats = [(GL_RGBA8, GL_COLOR_ATTACHMENT0)] + ([(GL_DEPTH_COMPONENT24, GL_DEPTH_ATTACHMENT)] if depth else [])
        for fmt, attach in formats:
            rb = gl.gen(gl.GenRenderbuffers)
            gl.BindRenderbuffer(GL_RENDERBUFFER, rb)
            if samples > 1:
                gl.RenderbufferStorageMultisample(GL_RENDERBUFFER, samples, fmt, w, h)
            else:
                gl.RenderbufferStorage(GL_RENDERBUFFER, fmt, w, h)
            gl.FramebufferRenderbuffer(GL_FRAMEBUFFER, attach, GL_RENDERBUFFER, rb)
            rbs.append(rb)
        ok = gl.CheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
        return (fbo, *rbs), ok

    def _ensure_fbo(self, w, h, samples):
        """(scene framebuffer, plain framebuffer to read from); they're the same without MSAA."""
        if self.fbo_key == (w, h, samples):
            return True
        self._free_fbo()
        scene, ok = self._make_fbo(w, h, samples, True)
        if samples > 1:
            resolve, ok2 = self._make_fbo(w, h, 1, False)
            self.fbo = [scene, resolve]
            ok = ok and ok2
        else:
            self.fbo = [scene]
        self.fbo_key = (w, h, samples)
        return ok

    # ---- drawing
    def _draw(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        if self.image is None:
            self._frame()
        if self.image is not None:
            cr.save()
            cr.translate(0, h)
            cr.scale(w / self.image.get_width(), -h / self.image.get_height())  # GL rows go bottom-up
            cr.set_source_surface(self.image, 0, 0)
            cr.paint()
            cr.restore()
        else:
            cr.set_source_rgb(0.10, 0.12, 0.16)
            cr.paint()
        return False

    def _frame(self):
        """Render one frame into self.image and have it shown."""
        area = self.area
        if not area.get_realized() or not self._ensure_gl():
            area.queue_draw()
            return
        self.ctx.make_current()
        w, h = max(1, area.get_allocated_width()), max(1, area.get_allocated_height())
        self._render(w, h)
        area.queue_draw()

    def _render(self, w, h):
        gl = self.gl
        samples, af, traa = self._effective()
        samples = min(samples, self.max_samples)
        if not self._ensure_fbo(w, h, samples):
            samples = 1
            self._ensure_fbo(w, h, 1)
        gl.BindFramebuffer(GL_FRAMEBUFFER, self.fbo[0][0])
        gl.Viewport(0, 0, w, h)
        gl.ClearColor(0.10, 0.12, 0.16, 1.0)
        gl.Clear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        gl.Enable(GL_DEPTH_TEST)
        gl.Enable(GL_MULTISAMPLE)
        gl.UseProgram(self.prog)
        u = self.u

        proj = perspective(34.0, w / h, 1.0, 400.0)
        cam = mat_mul(translate(0, -1.0, -25.0), mat_mul(rotate(self.pitch, 1, 0, 0), rotate(self.yaw, 0, 1, 0)))
        # the eye in world space: the camera transform undone
        eye = apply(mat_mul(rotate(-self.yaw, 0, 1, 0), rotate(-self.pitch, 1, 0, 0)), (0.0, 1.0, 25.0))
        gl.Uniform3f(u["eye"], *eye)
        gl.Uniform1i(u["tex"], 0)
        gl.ActiveTexture(GL_TEXTURE0)

        def draw(mesh, model):
            gl.UniformMatrix4fv(u["model"], 1, 0, (_f * 16)(*model))
            gl.UniformMatrix4fv(u["mvp"], 1, 0, (_f * 16)(*mat_mul(proj, mat_mul(cam, model))))
            gl.BindVertexArray(mesh[0])
            gl.DrawArrays(GL_TRIANGLES, 0, mesh[1])

        # floor, with the anisotropic filtering being previewed
        gl.Uniform1i(u["mode"], 1)
        gl.BindTexture(GL_TEXTURE_2D, self.floor_tex)
        if self.has_aniso:
            gl.TexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAX_ANISOTROPY, float(min(af, self.max_aniso)))
        draw(self.floor, translate(0, 0, 0))

        # gears
        gl.Uniform1i(u["mode"], 0)
        group = mat_mul(translate(0, 0.5, 0), mat_mul(rotate(20, 1, 0, 0), rotate(25, 0, 1, 0)))
        for mesh, (x, y), color, speed, phase in self.gears:
            gl.Uniform3f(u["color"], *color)
            draw(mesh, mat_mul(group, mat_mul(translate(x, y, 0), rotate(speed * self.angle + phase, 0, 0, 1))))

        # fence, with the transparency antialiasing being previewed
        gl.Uniform1i(u["mode"], 2)
        gl.BindTexture(GL_TEXTURE_2D, self.fence_tex)
        if traa == "multisample":
            gl.Uniform1i(u["alpha_test"], 0)
            gl.Enable(GL_SAMPLE_ALPHA_TO_COVERAGE)
        elif traa == "supersample" and self.has_sample_shading:
            gl.Uniform1i(u["alpha_test"], 1)
            gl.Enable(GL_SAMPLE_SHADING)
            gl.MinSampleShading(1.0)
        else:
            gl.Uniform1i(u["alpha_test"], 1)
        draw(self.fence, translate(0, 0, 0))
        gl.Disable(GL_SAMPLE_ALPHA_TO_COVERAGE)
        if self.has_sample_shading:
            gl.Disable(GL_SAMPLE_SHADING)

        # resolve the samples, then read the picture back for GTK to draw
        if len(self.fbo) > 1:
            gl.BindFramebuffer(GL_READ_FRAMEBUFFER, self.fbo[0][0])
            gl.BindFramebuffer(GL_DRAW_FRAMEBUFFER, self.fbo[1][0])
            gl.BlitFramebuffer(0, 0, w, h, 0, 0, w, h, GL_COLOR_BUFFER_BIT, GL_NEAREST)
        gl.BindFramebuffer(GL_FRAMEBUFFER, self.fbo[-1][0])
        stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_RGB24, w)
        # compare the size, not the byte count: w×h and a different w×h can need the same bytes
        if self.image is None or (self.image.get_width(), self.image.get_height()) != (w, h):
            self._pixels = bytearray(stride * h)
            self.image = cairo.ImageSurface.create_for_data(self._pixels, cairo.FORMAT_RGB24, w, h, stride)
        buf = (ctypes.c_char * len(self._pixels)).from_buffer(self._pixels)
        gl.PixelStorei(GL_PACK_ALIGNMENT, 4)
        gl.ReadPixels(0, 0, w, h, GL_BGRA, GL_UNSIGNED_BYTE, buf)   # = cairo's RGB24 layout (little-endian)
        del buf
        self.image.mark_dirty()
        gl.BindFramebuffer(GL_FRAMEBUFFER, 0)
        gl.BindVertexArray(0)

        self.frames += 1
        now = time.monotonic()
        if now - self.fps_since >= 1.0:
            fps = self.frames / (now - self.fps_since)
            self.frames, self.fps_since = 0, now
            self.fps_label.set_text(f"{fps:.0f} FPS · {self.renderer.split(' (')[0]}")
        return True
