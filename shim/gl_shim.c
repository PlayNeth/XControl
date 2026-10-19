/*
 * xcontrol OpenGL override shim (LD_PRELOAD)
 *
 * Forces per-game settings that Mesa has no knob for:
 *   XCONTROL_AF=1|2|4|8|16   anisotropic filtering on linear/mipmapped textures
 *                             (1 = force it off)
 *   XCONTROL_MSAA=1|2|4|8    multisampled default framebuffer (GLX and EGL)
 *                             (1 = force a single-sampled window)
 *   XCONTROL_TRAA=1|2        transparency AA for alpha-tested surfaces:
 *                             fixed-function alpha test: 1 = alpha-to-coverage,
 *                             2 = per-sample shading; shader alpha test (discard,
 *                             as in WineD3D and modern GL): per-sample shading
 *   XCONTROL_FPS=N           frame limiter on SwapBuffers
 *   XCONTROL_DEBUG=1         log what gets hooked to stderr
 *
 * Interception paths:
 *   - exported GL/GLX/EGL symbols (apps that link libGL directly)
 *   - glXGetProcAddress(ARB) / eglGetProcAddress
 *   - dlsym() on a libGL/libEGL/libOpenGL handle (SDL and most engines)
 *
 * GL headers are deliberately not included; the few types we need are
 * declared below so our definitions never clash with header prototypes.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define EXPORT __attribute__((visibility("default")))

typedef unsigned int GLenum;
typedef unsigned int GLuint;
typedef int GLint;
typedef float GLfloat;
typedef void (*fnptr)(void);

/* ---- GL / GLX / EGL constants ------------------------------------------ */
#define GL_TEXTURE_MIN_FILTER           0x2801
#define GL_LINEAR                       0x2601
#define GL_LINEAR_MIPMAP_NEAREST        0x2701
#define GL_NEAREST_MIPMAP_LINEAR        0x2702
#define GL_LINEAR_MIPMAP_LINEAR         0x2703
#define GL_TEXTURE_MAX_ANISOTROPY       0x84FE
#define GL_TEXTURE_RECTANGLE            0x84F5
#define GL_TEXTURE_BUFFER               0x8C2A
#define GL_TEXTURE_2D_MULTISAMPLE       0x9100
#define GL_TEXTURE_2D_MULTISAMPLE_ARRAY 0x9102
#define GL_ALPHA_TEST                   0x0BC0
#define GL_SAMPLE_ALPHA_TO_COVERAGE     0x809E
#define GL_SAMPLE_SHADING               0x8C36
#define GL_SAMPLES                      0x80A9

#define GLX_USE_GL          1
#define GLX_RGBA            4
#define GLX_DOUBLEBUFFER    5
#define GLX_STEREO          6
#define GLX_DRAWABLE_TYPE   0x8010
#define GLX_WINDOW_BIT      0x0001
#define GLX_SAMPLE_BUFFERS  100000
#define GLX_SAMPLES         100001

#define EGL_NONE            0x3038
#define EGL_SAMPLES         0x3031
#define EGL_SAMPLE_BUFFERS  0x3032
#define EGL_SURFACE_TYPE    0x3033
#define EGL_WINDOW_BIT      0x0004

#define MAX_ATTRIBS 256

/* ---- configuration ----------------------------------------------------- */
static int g_af, g_msaa, g_traa, g_fps, g_debug, g_active;

#define LOG(...) do { if (g_debug) { fprintf(stderr, "[xcontrol/gl] " __VA_ARGS__); fputc('\n', stderr); } } while (0)

/* XCONTROL_<name>, or MESAPANEL_<name> from before the rename */
static int env_int(const char *name)
{
    char key[64];
    const char *v;

    snprintf(key, sizeof key, "XCONTROL_%s", name);
    v = getenv(key);
    if (!v) {
        snprintf(key, sizeof key, "MESAPANEL_%s", name);
        v = getenv(key);
    }
    return v ? atoi(v) : 0;
}

__attribute__((constructor)) static void mp_init(void)
{
    g_af = env_int("AF");
    g_msaa = env_int("MSAA");
    g_traa = env_int("TRAA");
    g_fps = env_int("FPS");
    g_debug = env_int("DEBUG");
    if (g_af < 0) g_af = 0;
    if (g_af > 16) g_af = 16;
    if (g_msaa < 0) g_msaa = 0;   /* 1 = forced off, 2+ = forced sample count */
    if (g_msaa > 16) g_msaa = 16;
    if (g_traa < 0 || g_traa > 2) g_traa = 0;
    if (g_fps < 0) g_fps = 0;
    g_active = g_af || g_msaa || g_traa || g_fps;
    if (g_active)
        LOG("active: af=%d msaa=%d traa=%d fps=%d", g_af, g_msaa, g_traa, g_fps);
}

/* ---- real symbol lookup ------------------------------------------------ */
typedef void *(*dlsym_fn)(void *, const char *);
typedef fnptr (*gpa_fn)(const char *);

static dlsym_fn real_dlsym(void)
{
    static dlsym_fn f;
    if (!f) {
        f = (dlsym_fn)dlvsym(RTLD_NEXT, "dlsym", "GLIBC_2.34");
        if (!f)
            f = (dlsym_fn)dlvsym(RTLD_NEXT, "dlsym", "GLIBC_2.2.5");
    }
    return f;
}

/* Window-system entry point: next definition after us, else from the
 * already-loaded library (covers apps that dlopen'ed it RTLD_LOCAL). */
static void *real_winsys(const char *name, const char *lib)
{
    void *p = real_dlsym()(RTLD_NEXT, name);
    if (!p) {
        void *h = dlopen(lib, RTLD_LAZY | RTLD_NOLOAD);
        if (h) {
            p = real_dlsym()(h, name);
            dlclose(h);
        }
    }
    return p;
}

/* GL entry point: go through the real GetProcAddress so we get libglvnd's
 * dispatch stub (never our own export), whichever of GLX/EGL is loaded. */
static fnptr real_gl_proc(const char *name)
{
    static gpa_fn glx_gpa, egl_gpa;
    fnptr p;
    if (!glx_gpa)
        glx_gpa = (gpa_fn)real_winsys("glXGetProcAddressARB", "libGL.so.1");
    if (glx_gpa && (p = glx_gpa(name)))
        return p;
    if (!egl_gpa)
        egl_gpa = (gpa_fn)real_winsys("eglGetProcAddress", "libEGL.so.1");
    if (egl_gpa && (p = egl_gpa(name)))
        return p;
    return (fnptr)real_dlsym()(RTLD_NEXT, name);
}

#define REAL_GL(type, name) \
    static type real_##name; \
    if (!real_##name) real_##name = (type)real_gl_proc(#name)

/* ---- anisotropic filtering --------------------------------------------- */
typedef void (*PFN_pi)(GLuint, GLenum, GLint);
typedef void (*PFN_pf)(GLuint, GLenum, GLfloat);
typedef void (*PFN_piv)(GLuint, GLenum, const GLint *);
typedef void (*PFN_pfv)(GLuint, GLenum, const GLfloat *);
typedef void (*PFN_getiv)(GLuint, GLenum, GLint *);

enum { K_TEX, K_SAMPLER, K_DSA };

static int af_filter_ok(GLint f)
{
    return f == GL_LINEAR || f == GL_LINEAR_MIPMAP_NEAREST ||
           f == GL_LINEAR_MIPMAP_LINEAR || f == GL_NEAREST_MIPMAP_LINEAR;
}

static int af_target_ok(int kind, GLuint obj)
{
    if (kind != K_TEX)
        return 1;
    return obj != GL_TEXTURE_RECTANGLE && obj != GL_TEXTURE_BUFFER &&
           obj != GL_TEXTURE_2D_MULTISAMPLE && obj != GL_TEXTURE_2D_MULTISAMPLE_ARRAY;
}

static void set_aniso(int kind, GLuint obj)
{
    static PFN_pf fns[3];
    static const char *names[3] = { "glTexParameterf", "glSamplerParameterf", "glTextureParameterf" };
    if (!fns[kind])
        fns[kind] = (PFN_pf)real_gl_proc(names[kind]);
    if (fns[kind])
        fns[kind](obj, GL_TEXTURE_MAX_ANISOTROPY, (GLfloat)g_af);
}

#define PARAM_HOOKS(NAME, KIND)                                                         \
EXPORT void NAME##i(GLuint o, GLenum p, GLint v)                                       \
{                                                                                       \
    REAL_GL(PFN_pi, NAME##i);                                                           \
    if (g_af && p == GL_TEXTURE_MAX_ANISOTROPY && af_target_ok(KIND, o)) {              \
        set_aniso(KIND, o); return;                                                     \
    }                                                                                   \
    real_##NAME##i(o, p, v);                                                            \
    if (g_af > 1 && p == GL_TEXTURE_MIN_FILTER && af_filter_ok(v) && af_target_ok(KIND, o)) \
        set_aniso(KIND, o);                                                             \
}                                                                                       \
EXPORT void NAME##f(GLuint o, GLenum p, GLfloat v)                                     \
{                                                                                       \
    REAL_GL(PFN_pf, NAME##f);                                                           \
    if (g_af && p == GL_TEXTURE_MAX_ANISOTROPY && af_target_ok(KIND, o)) {              \
        set_aniso(KIND, o); return;                                                     \
    }                                                                                   \
    real_##NAME##f(o, p, v);                                                            \
    if (g_af > 1 && p == GL_TEXTURE_MIN_FILTER && af_filter_ok((GLint)v) && af_target_ok(KIND, o)) \
        set_aniso(KIND, o);                                                             \
}                                                                                       \
EXPORT void NAME##iv(GLuint o, GLenum p, const GLint *v)                               \
{                                                                                       \
    REAL_GL(PFN_piv, NAME##iv);                                                         \
    if (g_af && p == GL_TEXTURE_MAX_ANISOTROPY && af_target_ok(KIND, o)) {              \
        set_aniso(KIND, o); return;                                                     \
    }                                                                                   \
    real_##NAME##iv(o, p, v);                                                           \
    if (g_af > 1 && v && p == GL_TEXTURE_MIN_FILTER && af_filter_ok(v[0]) && af_target_ok(KIND, o)) \
        set_aniso(KIND, o);                                                             \
}                                                                                       \
EXPORT void NAME##fv(GLuint o, GLenum p, const GLfloat *v)                             \
{                                                                                       \
    REAL_GL(PFN_pfv, NAME##fv);                                                         \
    if (g_af && p == GL_TEXTURE_MAX_ANISOTROPY && af_target_ok(KIND, o)) {              \
        set_aniso(KIND, o); return;                                                     \
    }                                                                                   \
    real_##NAME##fv(o, p, v);                                                           \
    if (g_af > 1 && v && p == GL_TEXTURE_MIN_FILTER && af_filter_ok((GLint)v[0]) && af_target_ok(KIND, o)) \
        set_aniso(KIND, o);                                                             \
}

PARAM_HOOKS(glTexParameter, K_TEX)
PARAM_HOOKS(glSamplerParameter, K_SAMPLER)
PARAM_HOOKS(glTextureParameter, K_DSA)

/* Textures that never set a min filter keep the default
 * GL_NEAREST_MIPMAP_LINEAR; catch them when mipmaps get generated. */
static void af_after_mipgen(int kind, GLuint obj)
{
    static PFN_getiv get_tex, get_dsa;
    GLint f = 0;
    if (g_af <= 1 || !af_target_ok(kind, obj))
        return;
    if (kind == K_TEX) {
        if (!get_tex) get_tex = (PFN_getiv)real_gl_proc("glGetTexParameteriv");
        if (get_tex) get_tex(obj, GL_TEXTURE_MIN_FILTER, &f);
    } else {
        if (!get_dsa) get_dsa = (PFN_getiv)real_gl_proc("glGetTextureParameteriv");
        if (get_dsa) get_dsa(obj, GL_TEXTURE_MIN_FILTER, &f);
    }
    if (af_filter_ok(f))
        set_aniso(kind, obj);
}

typedef void (*PFN_u)(GLuint);
EXPORT void glGenerateMipmap(GLenum target)
{
    REAL_GL(PFN_u, glGenerateMipmap);
    real_glGenerateMipmap(target);
    af_after_mipgen(K_TEX, target);
}
EXPORT void glGenerateMipmapEXT(GLenum target)
{
    REAL_GL(PFN_u, glGenerateMipmapEXT);
    real_glGenerateMipmapEXT(target);
    af_after_mipgen(K_TEX, target);
}
EXPORT void glGenerateTextureMipmap(GLuint tex)
{
    REAL_GL(PFN_u, glGenerateTextureMipmap);
    real_glGenerateTextureMipmap(tex);
    af_after_mipgen(K_DSA, tex);
}

/* ---- transparency AA ---------------------------------------------------- */
typedef void (*PFN_getintegerv)(GLenum, GLint *);
typedef void (*PFN_minss)(GLfloat);

static __thread int t_samples = -1; /* cached per frame */
static __thread int t_a2c, t_ss;

static void traa_on(void)
{
    REAL_GL(PFN_u, glEnable);
    REAL_GL(PFN_getintegerv, glGetIntegerv);
    static PFN_minss min_ss;
    if (t_samples < 0) {
        GLint s = 0;
        if (real_glGetIntegerv) real_glGetIntegerv(GL_SAMPLES, &s);
        t_samples = s;
    }
    if (t_samples < 2)
        return;
    if (g_traa == 1) {
        real_glEnable(GL_SAMPLE_ALPHA_TO_COVERAGE);
        t_a2c = 1;
    } else {
        if (!min_ss) min_ss = (PFN_minss)real_gl_proc("glMinSampleShading");
        if (!min_ss) min_ss = (PFN_minss)real_gl_proc("glMinSampleShadingARB");
        if (min_ss) min_ss(1.0f);
        real_glEnable(GL_SAMPLE_SHADING);
        t_ss = 1;
    }
}

static void traa_off(void)
{
    REAL_GL(PFN_u, glDisable);
    if (t_a2c) { real_glDisable(GL_SAMPLE_ALPHA_TO_COVERAGE); t_a2c = 0; }
    if (t_ss)  { real_glDisable(GL_SAMPLE_SHADING); t_ss = 0; }
}

EXPORT void glEnable(GLenum cap)
{
    REAL_GL(PFN_u, glEnable);
    real_glEnable(cap);
    if (g_traa && cap == GL_ALPHA_TEST)
        traa_on();
}

EXPORT void glDisable(GLenum cap)
{
    REAL_GL(PFN_u, glDisable);
    real_glDisable(cap);
    if (g_traa && cap == GL_ALPHA_TEST)
        traa_off();
}

/* Shader-based alpha test. Core-profile renderers (WineD3D, modern engines)
 * implement alpha testing with `discard` in fragment shaders. We note which
 * programs contain such a shader and turn on per-sample shading only while one
 * of them is bound, so just the alpha-tested surfaces get supersampled. */
#define GL_FRAGMENT_SHADER 0x8B30
#define MAX_GL_OBJECTS (1 << 18)

enum { SH_FRAGMENT = 1, SH_DISCARD = 2 };
static unsigned char shader_flags[MAX_GL_OBJECTS];
static unsigned char program_discards[MAX_GL_OBJECTS];
static __thread int t_prog_ss;

typedef GLuint (*PFN_create_shader)(GLenum);
typedef GLuint (*PFN_create_program)(void);
typedef void (*PFN_shader_source)(GLuint, GLint, const char *const *, const GLint *);
typedef void (*PFN_attach)(GLuint, GLuint);

static int is_ident(char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
}

/* Whole-word search for "discard" in a (not necessarily terminated) string. */
static int has_discard(const char *src, size_t len)
{
    static const char word[] = "discard";
    const size_t wl = sizeof(word) - 1;
    for (const char *p = src; len >= wl && (p = memmem(p, len - (size_t)(p - src), word, wl)); p += wl) {
        size_t off = (size_t)(p - src);
        int before_ok = off == 0 || !is_ident(p[-1]);
        int after_ok = off + wl >= len || !is_ident(p[wl]);
        if (before_ok && after_ok)
            return 1;
        if (off + wl >= len)
            break;
    }
    return 0;
}

EXPORT GLuint glCreateShader(GLenum type)
{
    REAL_GL(PFN_create_shader, glCreateShader);
    GLuint sh = real_glCreateShader(type);
    if (sh < MAX_GL_OBJECTS)
        shader_flags[sh] = type == GL_FRAGMENT_SHADER ? SH_FRAGMENT : 0;
    return sh;
}

EXPORT GLuint glCreateProgram(void)
{
    REAL_GL(PFN_create_program, glCreateProgram);
    GLuint prog = real_glCreateProgram();
    if (prog < MAX_GL_OBJECTS)
        program_discards[prog] = 0; /* ids get reused after deletion */
    return prog;
}

EXPORT void glShaderSource(GLuint sh, GLint count, const char *const *strings, const GLint *lengths)
{
    REAL_GL(PFN_shader_source, glShaderSource);
    real_glShaderSource(sh, count, strings, lengths);
    if (!g_traa || sh >= MAX_GL_OBJECTS || !(shader_flags[sh] & SH_FRAGMENT) || !strings)
        return;
    shader_flags[sh] &= ~SH_DISCARD;
    for (GLint i = 0; i < count; i++) {
        if (!strings[i])
            continue;
        size_t len = (lengths && lengths[i] >= 0) ? (size_t)lengths[i] : strlen(strings[i]);
        if (has_discard(strings[i], len)) {
            shader_flags[sh] |= SH_DISCARD;
            break;
        }
    }
}

EXPORT void glAttachShader(GLuint prog, GLuint sh)
{
    REAL_GL(PFN_attach, glAttachShader);
    real_glAttachShader(prog, sh);
    if (g_traa && prog < MAX_GL_OBJECTS && sh < MAX_GL_OBJECTS && (shader_flags[sh] & SH_DISCARD))
        program_discards[prog] = 1;
}

EXPORT void glUseProgram(GLuint prog)
{
    REAL_GL(PFN_u, glUseProgram);
    real_glUseProgram(prog);
    if (!g_traa)
        return;
    int want = prog && prog < MAX_GL_OBJECTS && program_discards[prog];
    if (want == t_prog_ss)
        return;
    REAL_GL(PFN_u, glEnable);
    REAL_GL(PFN_u, glDisable);
    static PFN_minss min_ss;
    static int logged;
    if (want) {
        if (!min_ss) min_ss = (PFN_minss)real_gl_proc("glMinSampleShading");
        if (!min_ss) min_ss = (PFN_minss)real_gl_proc("glMinSampleShadingARB");
        if (min_ss) min_ss(1.0f);
        real_glEnable(GL_SAMPLE_SHADING);
        if (!logged) {
            logged = 1;
            LOG("transparency AA: supersampling alpha-tested shaders");
        }
    } else {
        real_glDisable(GL_SAMPLE_SHADING);
    }
    t_prog_ss = want;
}

/* ---- forced MSAA -------------------------------------------------------- */
typedef void *(*PFN_chooseFB)(void *, int, const int *, int *);
typedef void *(*PFN_chooseVis)(void *, int, int *);
typedef unsigned (*PFN_eglChoose)(void *, const int32_t *, void **, int32_t, int32_t *);

EXPORT void *glXChooseFBConfig(void *dpy, int screen, const int *attribs, int *nelements)
{
    static PFN_chooseFB real;
    int buf[MAX_ATTRIBS], n = 0, drawable = GLX_WINDOW_BIT;
    void *res;
    if (!real) real = (PFN_chooseFB)real_winsys("glXChooseFBConfig", "libGL.so.1");
    if (!real) return NULL;
    if (!g_msaa) return real(dpy, screen, attribs, nelements);

    for (int i = 0; attribs && attribs[i] != 0; i += 2) {
        if (n > MAX_ATTRIBS - 6) return real(dpy, screen, attribs, nelements);
        if (attribs[i] == GLX_SAMPLE_BUFFERS || attribs[i] == GLX_SAMPLES) continue;
        if (attribs[i] == GLX_DRAWABLE_TYPE) drawable = attribs[i + 1];
        buf[n++] = attribs[i];
        buf[n++] = attribs[i + 1];
    }
    if (!(drawable & GLX_WINDOW_BIT))
        return real(dpy, screen, attribs, nelements);
    /* Try the chosen sample count, then lower ones (8 -> 4 -> 2). With no
     * sample request ("off"), configs sort single-sampled first. */
    for (int want = g_msaa > 1 ? g_msaa : 0;; want /= 2) {
        int m = n;
        if (want) {
            buf[m++] = GLX_SAMPLE_BUFFERS; buf[m++] = 1;
            buf[m++] = GLX_SAMPLES;        buf[m++] = want;
        }
        buf[m] = 0;
        res = real(dpy, screen, buf, nelements);
        if (res && nelements && *nelements > 0) {
            if (want) LOG("glXChooseFBConfig: forced %dx MSAA%s", want, want < g_msaa ? " (highest available)" : "");
            else LOG("glXChooseFBConfig: forced MSAA off");
            return res;
        }
        if (want < 4)
            break;
    }
    LOG("glXChooseFBConfig: no matching MSAA config, using the game's request");
    return real(dpy, screen, attribs, nelements);
}

EXPORT void *glXChooseVisual(void *dpy, int screen, int *attribs)
{
    static PFN_chooseVis real;
    int buf[MAX_ATTRIBS], n = 0;
    void *res;
    if (!real) real = (PFN_chooseVis)real_winsys("glXChooseVisual", "libGL.so.1");
    if (!real) return NULL;
    if (!g_msaa || !attribs) return real(dpy, screen, attribs);

    for (int i = 0; attribs[i] != 0;) {
        int a = attribs[i];
        int is_bool = (a == GLX_USE_GL || a == GLX_RGBA || a == GLX_DOUBLEBUFFER || a == GLX_STEREO);
        if (n > MAX_ATTRIBS - 6) return real(dpy, screen, attribs);
        if (is_bool) {
            buf[n++] = a;
            i += 1;
        } else {
            if (a != GLX_SAMPLE_BUFFERS && a != GLX_SAMPLES) {
                buf[n++] = a;
                buf[n++] = attribs[i + 1];
            }
            i += 2;
        }
    }
    for (int want = g_msaa > 1 ? g_msaa : 0;; want /= 2) {
        int m = n;
        if (want) {
            buf[m++] = GLX_SAMPLE_BUFFERS; buf[m++] = 1;
            buf[m++] = GLX_SAMPLES;        buf[m++] = want;
        }
        buf[m] = 0;
        res = real(dpy, screen, buf);
        if (res) {
            if (want) LOG("glXChooseVisual: forced %dx MSAA%s", want, want < g_msaa ? " (highest available)" : "");
            else LOG("glXChooseVisual: forced MSAA off");
            return res;
        }
        if (want < 4)
            break;
    }
    LOG("glXChooseVisual: no matching MSAA visual, using the game's request");
    return real(dpy, screen, attribs);
}

EXPORT unsigned eglChooseConfig(void *dpy, const int32_t *attribs, void **configs,
                                int32_t size, int32_t *num)
{
    static PFN_eglChoose real;
    int32_t buf[MAX_ATTRIBS];
    int n = 0;
    int32_t surface = EGL_WINDOW_BIT;
    unsigned ok;
    if (!real) real = (PFN_eglChoose)real_winsys("eglChooseConfig", "libEGL.so.1");
    if (!real) return 0;
    if (!g_msaa) return real(dpy, attribs, configs, size, num);

    for (int i = 0; attribs && attribs[i] != EGL_NONE; i += 2) {
        if (n > MAX_ATTRIBS - 6) return real(dpy, attribs, configs, size, num);
        if (attribs[i] == EGL_SAMPLE_BUFFERS || attribs[i] == EGL_SAMPLES) continue;
        if (attribs[i] == EGL_SURFACE_TYPE) surface = attribs[i + 1];
        buf[n++] = attribs[i];
        buf[n++] = attribs[i + 1];
    }
    if (!(surface & EGL_WINDOW_BIT))
        return real(dpy, attribs, configs, size, num);
    for (int want = g_msaa > 1 ? g_msaa : 0;; want /= 2) {
        int m = n;
        if (want) {
            buf[m++] = EGL_SAMPLE_BUFFERS; buf[m++] = 1;
            buf[m++] = EGL_SAMPLES;        buf[m++] = want;
        }
        buf[m] = EGL_NONE;
        ok = real(dpy, buf, configs, size, num);
        if (ok && num && *num > 0) {
            if (want) LOG("eglChooseConfig: forced %dx MSAA%s", want, want < g_msaa ? " (highest available)" : "");
            else LOG("eglChooseConfig: forced MSAA off");
            return ok;
        }
        if (want < 4)
            break;
    }
    LOG("eglChooseConfig: no matching MSAA config, using the game's request");
    return real(dpy, attribs, configs, size, num);
}

/* ---- frame limiter ------------------------------------------------------ */
static pthread_mutex_t fps_lock = PTHREAD_MUTEX_INITIALIZER;
static int64_t fps_next;

static int64_t mono_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static void before_present(void)
{
    t_samples = -1;
    if (g_fps <= 0)
        return;
    int64_t interval = 1000000000LL / g_fps, now, target;
    pthread_mutex_lock(&fps_lock);
    now = mono_ns();
    if (fps_next == 0 || now - fps_next > interval)
        fps_next = now; /* first frame, or we fell behind: resync */
    target = fps_next;
    fps_next += interval;
    pthread_mutex_unlock(&fps_lock);
    if (target > now) {
        struct timespec ts = { target / 1000000000LL, target % 1000000000LL };
        while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) != 0)
            ;
    }
}

typedef void (*PFN_glxswap)(void *, unsigned long);
typedef unsigned (*PFN_eglswap)(void *, void *);
typedef unsigned (*PFN_eglswapdmg)(void *, void *, const int32_t *, int32_t);

EXPORT void glXSwapBuffers(void *dpy, unsigned long drawable)
{
    static PFN_glxswap real;
    if (!real) real = (PFN_glxswap)real_winsys("glXSwapBuffers", "libGL.so.1");
    before_present();
    if (real) real(dpy, drawable);
}

EXPORT unsigned eglSwapBuffers(void *dpy, void *surface)
{
    static PFN_eglswap real;
    if (!real) real = (PFN_eglswap)real_winsys("eglSwapBuffers", "libEGL.so.1");
    before_present();
    return real ? real(dpy, surface) : 0;
}

static PFN_eglswapdmg real_dmg_khr, real_dmg_ext;

static unsigned swap_damage_khr(void *dpy, void *s, const int32_t *r, int32_t n)
{
    before_present();
    return real_dmg_khr ? real_dmg_khr(dpy, s, r, n) : 0;
}

static unsigned swap_damage_ext(void *dpy, void *s, const int32_t *r, int32_t n)
{
    before_present();
    return real_dmg_ext ? real_dmg_ext(dpy, s, r, n) : 0;
}

/* ---- GetProcAddress / dlsym interception -------------------------------- */
EXPORT fnptr glXGetProcAddressARB(const unsigned char *name);
EXPORT fnptr glXGetProcAddress(const unsigned char *name);
EXPORT fnptr eglGetProcAddress(const char *name);

struct hook { const char *name; void *fn; };

static const struct hook hooks[] = {
    { "glTexParameteri", (void *)glTexParameteri },
    { "glTexParameterf", (void *)glTexParameterf },
    { "glTexParameteriv", (void *)glTexParameteriv },
    { "glTexParameterfv", (void *)glTexParameterfv },
    { "glSamplerParameteri", (void *)glSamplerParameteri },
    { "glSamplerParameterf", (void *)glSamplerParameterf },
    { "glSamplerParameteriv", (void *)glSamplerParameteriv },
    { "glSamplerParameterfv", (void *)glSamplerParameterfv },
    { "glTextureParameteri", (void *)glTextureParameteri },
    { "glTextureParameterf", (void *)glTextureParameterf },
    { "glTextureParameteriv", (void *)glTextureParameteriv },
    { "glTextureParameterfv", (void *)glTextureParameterfv },
    { "glGenerateMipmap", (void *)glGenerateMipmap },
    { "glGenerateMipmapEXT", (void *)glGenerateMipmapEXT },
    { "glGenerateTextureMipmap", (void *)glGenerateTextureMipmap },
    { "glEnable", (void *)glEnable },
    { "glDisable", (void *)glDisable },
    { "glCreateShader", (void *)glCreateShader },
    { "glCreateProgram", (void *)glCreateProgram },
    { "glShaderSource", (void *)glShaderSource },
    { "glAttachShader", (void *)glAttachShader },
    { "glUseProgram", (void *)glUseProgram },
    { "glXChooseFBConfig", (void *)glXChooseFBConfig },
    { "glXChooseVisual", (void *)glXChooseVisual },
    { "glXSwapBuffers", (void *)glXSwapBuffers },
    { "glXGetProcAddress", (void *)glXGetProcAddress },
    { "glXGetProcAddressARB", (void *)glXGetProcAddressARB },
    { "eglChooseConfig", (void *)eglChooseConfig },
    { "eglSwapBuffers", (void *)eglSwapBuffers },
    { "eglGetProcAddress", (void *)eglGetProcAddress },
    { NULL, NULL }
};

static void *lookup_hook(const char *name)
{
    if (!g_active || !name)
        return NULL;
    for (const struct hook *h = hooks; h->name; h++)
        if (strcmp(h->name, name) == 0)
            return h->fn;
    /* Damage-swap variants are only reachable through eglGetProcAddress. */
    if (strcmp(name, "eglSwapBuffersWithDamageKHR") == 0) {
        if (!real_dmg_khr)
            real_dmg_khr = (PFN_eglswapdmg)((gpa_fn)real_winsys("eglGetProcAddress", "libEGL.so.1"))(name);
        return real_dmg_khr ? (void *)swap_damage_khr : NULL;
    }
    if (strcmp(name, "eglSwapBuffersWithDamageEXT") == 0) {
        if (!real_dmg_ext)
            real_dmg_ext = (PFN_eglswapdmg)((gpa_fn)real_winsys("eglGetProcAddress", "libEGL.so.1"))(name);
        return real_dmg_ext ? (void *)swap_damage_ext : NULL;
    }
    return NULL;
}

EXPORT fnptr glXGetProcAddressARB(const unsigned char *name)
{
    static gpa_fn real;
    void *h = lookup_hook((const char *)name);
    if (h) return (fnptr)h;
    if (!real) real = (gpa_fn)real_winsys("glXGetProcAddressARB", "libGL.so.1");
    return real ? real((const char *)name) : NULL;
}

EXPORT fnptr glXGetProcAddress(const unsigned char *name)
{
    return glXGetProcAddressARB(name);
}

EXPORT fnptr eglGetProcAddress(const char *name)
{
    static gpa_fn real;
    void *h;
    if (!real) real = (gpa_fn)real_winsys("eglGetProcAddress", "libEGL.so.1");
    /* the damage variants need the real eglGetProcAddress resolved first */
    h = lookup_hook(name);
    if (h) return (fnptr)h;
    return real ? real(name) : NULL;
}

/* Is this a handle to one of the GL front-end libraries? Only those get
 * redirected; RTLD_NEXT/RTLD_DEFAULT and vendor libraries pass straight
 * through so other interposers (Steam overlay, MangoHud) keep working. */
static int is_frontend_handle(void *handle)
{
    static const char *libs[] = {
        "libGL.so.1", "libEGL.so.1", "libOpenGL.so.0", "libGLX.so.0",
        "libGL.so", "libEGL.so", "libOpenGL.so", NULL
    };
    if (handle == RTLD_NEXT || handle == RTLD_DEFAULT)
        return 0;
    for (int i = 0; libs[i]; i++) {
        void *h = dlopen(libs[i], RTLD_LAZY | RTLD_NOLOAD);
        if (h) {
            int same = (h == handle);
            dlclose(h);
            if (same) return 1;
        }
    }
    return 0;
}

EXPORT void *dlsym(void *handle, const char *name)
{
    dlsym_fn real = real_dlsym();
    if (g_active) {
        void *h = lookup_hook(name);
        if (h && is_frontend_handle(handle)) {
            LOG("dlsym: redirected %s", name);
            return h;
        }
    }
    /* Must be a tail call: glibc resolves RTLD_NEXT relative to the
     * return address, which has to stay the original caller's. */
#if defined(__has_attribute)
#if __has_attribute(musttail)
    __attribute__((musttail))
#endif
#endif
    return real(handle, name);
}
