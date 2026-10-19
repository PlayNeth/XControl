/*
 * xcontrol Vulkan layer (VK_LAYER_XCONTROL_overrides)
 *
 * Implicit layer, only enabled when XCONTROL_VK=1 (set by xcontrol-run).
 * Covers native Vulkan games and Proton games (DXVK / VKD3D-Proton):
 *   XCONTROL_AF=2|4|8|16   force anisotropic filtering in vkCreateSampler
 *   XCONTROL_AF=1          force anisotropic filtering off
 *   XCONTROL_FPS=N         frame limiter in vkQueuePresentKHR
 *   XCONTROL_DEBUG=1       log to stderr
 */
#define _GNU_SOURCE
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>

#define EXPORT __attribute__((visibility("default")))
#define LOG(...) do { if (g_debug) { fprintf(stderr, "[xcontrol/vk] " __VA_ARGS__); fputc('\n', stderr); } } while (0)

static int g_af, g_fps, g_debug;

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
    g_fps = env_int("FPS");
    g_debug = env_int("DEBUG");
    if (g_af < 0) g_af = 0;
    if (g_af > 16) g_af = 16;
    if (g_fps < 0) g_fps = 0;
    LOG("loaded: af=%d fps=%d", g_af, g_fps);
}

/* ---- dispatch bookkeeping ---------------------------------------------- */
/* Every dispatchable handle starts with the loader's dispatch table pointer;
 * physical devices share it with their instance, queues with their device. */
static inline void *dkey(const void *handle) { return *(void **)handle; }

struct inst_data {
    void *key;
    VkInstance instance;
    PFN_vkGetInstanceProcAddr gipa;
    PFN_vkDestroyInstance destroy;
    PFN_vkGetPhysicalDeviceFeatures get_features;
    PFN_vkGetPhysicalDeviceProperties get_props;
    struct inst_data *next;
};

struct dev_data {
    void *key;
    VkDevice device;
    PFN_vkGetDeviceProcAddr gdpa;
    PFN_vkDestroyDevice destroy;
    PFN_vkCreateSampler create_sampler;
    PFN_vkQueuePresentKHR queue_present;
    int aniso_ok;
    float max_aniso;
    struct dev_data *next;
};

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static struct inst_data *g_insts;
static struct dev_data *g_devs;

static struct inst_data *find_inst(void *key)
{
    struct inst_data *i;
    pthread_mutex_lock(&g_lock);
    for (i = g_insts; i && i->key != key; i = i->next)
        ;
    pthread_mutex_unlock(&g_lock);
    return i;
}

static struct dev_data *find_dev(void *key)
{
    struct dev_data *d;
    pthread_mutex_lock(&g_lock);
    for (d = g_devs; d && d->key != key; d = d->next)
        ;
    pthread_mutex_unlock(&g_lock);
    return d;
}

/* ---- instance ----------------------------------------------------------- */
static VKAPI_ATTR VkResult VKAPI_CALL mp_CreateInstance(const VkInstanceCreateInfo *ci,
                                                        const VkAllocationCallbacks *alloc,
                                                        VkInstance *out)
{
    VkLayerInstanceCreateInfo *link = (VkLayerInstanceCreateInfo *)ci->pNext;
    while (link && !(link->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO &&
                     link->function == VK_LAYER_LINK_INFO))
        link = (VkLayerInstanceCreateInfo *)link->pNext;
    if (!link)
        return VK_ERROR_INITIALIZATION_FAILED;

    PFN_vkGetInstanceProcAddr gipa = link->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    link->u.pLayerInfo = link->u.pLayerInfo->pNext;

    PFN_vkCreateInstance create = (PFN_vkCreateInstance)gipa(VK_NULL_HANDLE, "vkCreateInstance");
    VkResult res = create(ci, alloc, out);
    if (res != VK_SUCCESS)
        return res;

    struct inst_data *d = calloc(1, sizeof(*d));
    if (!d)
        return res;
    d->key = dkey(*out);
    d->instance = *out;
    d->gipa = gipa;
    d->destroy = (PFN_vkDestroyInstance)gipa(*out, "vkDestroyInstance");
    d->get_features = (PFN_vkGetPhysicalDeviceFeatures)gipa(*out, "vkGetPhysicalDeviceFeatures");
    d->get_props = (PFN_vkGetPhysicalDeviceProperties)gipa(*out, "vkGetPhysicalDeviceProperties");
    pthread_mutex_lock(&g_lock);
    d->next = g_insts;
    g_insts = d;
    pthread_mutex_unlock(&g_lock);
    return res;
}

static VKAPI_ATTR void VKAPI_CALL mp_DestroyInstance(VkInstance instance, const VkAllocationCallbacks *alloc)
{
    if (!instance)
        return;
    void *key = dkey(instance);
    struct inst_data *d = NULL, **pp;
    pthread_mutex_lock(&g_lock);
    for (pp = &g_insts; *pp; pp = &(*pp)->next)
        if ((*pp)->key == key) { d = *pp; *pp = d->next; break; }
    pthread_mutex_unlock(&g_lock);
    if (d) {
        d->destroy(instance, alloc);
        free(d);
    }
}

/* ---- device ------------------------------------------------------------- */
static VKAPI_ATTR VkResult VKAPI_CALL mp_CreateDevice(VkPhysicalDevice phys,
                                                      const VkDeviceCreateInfo *ci,
                                                      const VkAllocationCallbacks *alloc,
                                                      VkDevice *out)
{
    VkLayerDeviceCreateInfo *link = (VkLayerDeviceCreateInfo *)ci->pNext;
    while (link && !(link->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO &&
                     link->function == VK_LAYER_LINK_INFO))
        link = (VkLayerDeviceCreateInfo *)link->pNext;
    if (!link)
        return VK_ERROR_INITIALIZATION_FAILED;

    PFN_vkGetInstanceProcAddr gipa = link->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr gdpa = link->u.pLayerInfo->pfnNextGetDeviceProcAddr;
    link->u.pLayerInfo = link->u.pLayerInfo->pNext;

    struct inst_data *inst = find_inst(dkey(phys));
    VkDeviceCreateInfo info = *ci;
    VkPhysicalDeviceFeatures feats_copy;
    VkPhysicalDeviceFeatures2 *feats2 = NULL;
    VkBool32 feats2_saved = VK_FALSE;
    int aniso_ok = 0;
    float max_aniso = 16.0f;

    /* Anisotropy needs the samplerAnisotropy feature; turn it on if the
     * hardware has it and the game didn't ask for it. */
    if (g_af > 1 && inst && inst->get_features) {
        VkPhysicalDeviceFeatures supported;
        VkPhysicalDeviceProperties props;
        inst->get_features(phys, &supported);
        inst->get_props(phys, &props);
        max_aniso = props.limits.maxSamplerAnisotropy;
        if (supported.samplerAnisotropy) {
            aniso_ok = 1;
            for (const VkBaseInStructure *s = ci->pNext; s; s = s->pNext)
                if (s->sType == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2)
                    feats2 = (VkPhysicalDeviceFeatures2 *)s;
            if (ci->pEnabledFeatures) {
                feats_copy = *ci->pEnabledFeatures;
                feats_copy.samplerAnisotropy = VK_TRUE;
                info.pEnabledFeatures = &feats_copy;
            } else if (feats2) {
                feats2_saved = feats2->features.samplerAnisotropy;
                feats2->features.samplerAnisotropy = VK_TRUE;
            } else {
                memset(&feats_copy, 0, sizeof(feats_copy));
                feats_copy.samplerAnisotropy = VK_TRUE;
                info.pEnabledFeatures = &feats_copy;
            }
        }
    }

    PFN_vkCreateDevice create = (PFN_vkCreateDevice)gipa(inst ? inst->instance : VK_NULL_HANDLE, "vkCreateDevice");
    VkResult res = create(phys, &info, alloc, out);
    if (feats2)
        feats2->features.samplerAnisotropy = feats2_saved; /* leave the app's struct as it was */
    if (res != VK_SUCCESS)
        return res;

    struct dev_data *d = calloc(1, sizeof(*d));
    if (!d)
        return res;
    d->key = dkey(*out);
    d->device = *out;
    d->gdpa = gdpa;
    d->destroy = (PFN_vkDestroyDevice)gdpa(*out, "vkDestroyDevice");
    d->create_sampler = (PFN_vkCreateSampler)gdpa(*out, "vkCreateSampler");
    d->queue_present = (PFN_vkQueuePresentKHR)gdpa(*out, "vkQueuePresentKHR");
    d->aniso_ok = aniso_ok;
    d->max_aniso = max_aniso;
    pthread_mutex_lock(&g_lock);
    d->next = g_devs;
    g_devs = d;
    pthread_mutex_unlock(&g_lock);
    LOG("device created: AF override %s", g_af == 1 ? "off" : (aniso_ok && g_af ? "on" : "none"));
    return res;
}

static VKAPI_ATTR void VKAPI_CALL mp_DestroyDevice(VkDevice device, const VkAllocationCallbacks *alloc)
{
    if (!device)
        return;
    void *key = dkey(device);
    struct dev_data *d = NULL, **pp;
    pthread_mutex_lock(&g_lock);
    for (pp = &g_devs; *pp; pp = &(*pp)->next)
        if ((*pp)->key == key) { d = *pp; *pp = d->next; break; }
    pthread_mutex_unlock(&g_lock);
    if (d) {
        d->destroy(device, alloc);
        free(d);
    }
}

/* ---- anisotropic filtering --------------------------------------------- */
static int sampler_eligible(const VkSamplerCreateInfo *ci)
{
    if (ci->unnormalizedCoordinates)
        return 0;
    if (ci->minFilter != VK_FILTER_LINEAR && ci->magFilter != VK_FILTER_LINEAR)
        return 0; /* point-sampled: UI, pixel art, lookup tables */
    if (ci->minFilter > VK_FILTER_LINEAR || ci->magFilter > VK_FILTER_LINEAR)
        return 0; /* cubic filtering can't be combined with anisotropy */
    for (const VkBaseInStructure *s = ci->pNext; s; s = s->pNext) {
        if (s->sType == VK_STRUCTURE_TYPE_SAMPLER_YCBCR_CONVERSION_INFO)
            return 0;
        if (s->sType == VK_STRUCTURE_TYPE_SAMPLER_REDUCTION_MODE_CREATE_INFO &&
            ((const VkSamplerReductionModeCreateInfo *)s)->reductionMode !=
                VK_SAMPLER_REDUCTION_MODE_WEIGHTED_AVERAGE)
            return 0;
    }
    return 1;
}

static VKAPI_ATTR VkResult VKAPI_CALL mp_CreateSampler(VkDevice device, const VkSamplerCreateInfo *ci,
                                                       const VkAllocationCallbacks *alloc, VkSampler *out)
{
    struct dev_data *d = find_dev(dkey(device));
    if (!d)
        return VK_ERROR_INITIALIZATION_FAILED;
    if (g_af == 1 && ci->anisotropyEnable) {
        VkSamplerCreateInfo info = *ci;
        info.anisotropyEnable = VK_FALSE;
        info.maxAnisotropy = 1.0f;
        static int logged_off;
        if (!logged_off) {
            logged_off = 1;
            LOG("vkCreateSampler: anisotropic filtering forced off");
        }
        return d->create_sampler(device, &info, alloc, out);
    }
    if (g_af > 1 && d->aniso_ok && sampler_eligible(ci)) {
        VkSamplerCreateInfo info = *ci;
        float af = (float)g_af;
        info.anisotropyEnable = g_af > 1 ? VK_TRUE : VK_FALSE;
        info.maxAnisotropy = af > d->max_aniso ? d->max_aniso : af;
        static int logged;
        if (!logged) {
            logged = 1;
            LOG("vkCreateSampler: forcing %.0fx anisotropic filtering", info.maxAnisotropy);
        }
        return d->create_sampler(device, &info, alloc, out);
    }
    return d->create_sampler(device, ci, alloc, out);
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

static void fps_wait(void)
{
    int64_t interval = 1000000000LL / g_fps, now, target;
    pthread_mutex_lock(&fps_lock);
    now = mono_ns();
    if (fps_next == 0 || now - fps_next > interval)
        fps_next = now;
    target = fps_next;
    fps_next += interval;
    pthread_mutex_unlock(&fps_lock);
    if (target > now) {
        struct timespec ts = { target / 1000000000LL, target % 1000000000LL };
        while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) != 0)
            ;
    }
}

static VKAPI_ATTR VkResult VKAPI_CALL mp_QueuePresentKHR(VkQueue queue, const VkPresentInfoKHR *info)
{
    struct dev_data *d = find_dev(dkey(queue));
    if (!d || !d->queue_present)
        return VK_ERROR_DEVICE_LOST;
    if (g_fps > 0)
        fps_wait();
    return d->queue_present(queue, info);
}

/* ---- proc address plumbing ---------------------------------------------- */
static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL mp_GetDeviceProcAddr(VkDevice device, const char *name);
static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL mp_GetInstanceProcAddr(VkInstance instance, const char *name);

static PFN_vkVoidFunction device_hook(const char *name)
{
    if (!strcmp(name, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)mp_GetDeviceProcAddr;
    if (!strcmp(name, "vkDestroyDevice"))     return (PFN_vkVoidFunction)mp_DestroyDevice;
    if (g_af && !strcmp(name, "vkCreateSampler"))
        return (PFN_vkVoidFunction)mp_CreateSampler;
    if (g_fps > 0 && !strcmp(name, "vkQueuePresentKHR"))
        return (PFN_vkVoidFunction)mp_QueuePresentKHR;
    return NULL;
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL mp_GetDeviceProcAddr(VkDevice device, const char *name)
{
    PFN_vkVoidFunction f = device_hook(name);
    if (f)
        return f;
    struct dev_data *d = device ? find_dev(dkey(device)) : NULL;
    return d ? d->gdpa(device, name) : NULL;
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL mp_GetInstanceProcAddr(VkInstance instance, const char *name)
{
    if (!strcmp(name, "vkGetInstanceProcAddr")) return (PFN_vkVoidFunction)mp_GetInstanceProcAddr;
    if (!strcmp(name, "vkCreateInstance"))      return (PFN_vkVoidFunction)mp_CreateInstance;
    if (!strcmp(name, "vkDestroyInstance"))     return (PFN_vkVoidFunction)mp_DestroyInstance;
    if (!strcmp(name, "vkCreateDevice"))        return (PFN_vkVoidFunction)mp_CreateDevice;
    PFN_vkVoidFunction f = device_hook(name);
    if (f)
        return f;
    struct inst_data *d = instance ? find_inst(dkey(instance)) : NULL;
    return d ? d->gipa(instance, name) : NULL;
}

EXPORT VKAPI_ATTR VkResult VKAPI_CALL vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface *v)
{
    if (!v || v->sType != LAYER_NEGOTIATE_INTERFACE_STRUCT)
        return VK_ERROR_INITIALIZATION_FAILED;
    if (v->loaderLayerInterfaceVersion > 2)
        v->loaderLayerInterfaceVersion = 2;
    v->pfnGetInstanceProcAddr = mp_GetInstanceProcAddr;
    v->pfnGetDeviceProcAddr = mp_GetDeviceProcAddr;
    v->pfnGetPhysicalDeviceProcAddr = NULL;
    return VK_SUCCESS;
}

/* Older loaders look these up by name. */
EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(VkInstance i, const char *n)
{
    return mp_GetInstanceProcAddr(i, n);
}

EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(VkDevice d, const char *n)
{
    return mp_GetDeviceProcAddr(d, n);
}
