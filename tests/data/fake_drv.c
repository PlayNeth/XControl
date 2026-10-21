typedef unsigned int CARD32; typedef unsigned char CARD8; typedef unsigned short CARD16;
typedef struct { const char *modname; const char *vendor; CARD32 _modinfo1_; CARD32 _modinfo2_; CARD32 xf86version;
  CARD8 majorversion; CARD8 minorversion; CARD16 patchlevel; const char *abiclass; CARD32 abiversion;
  const char *moduleclass; CARD32 checksum[4]; } XF86ModuleVersionInfo;
typedef struct { XF86ModuleVersionInfo *vers; void *setup; void *teardown; } XF86ModuleData;
static XF86ModuleVersionInfo vers = { "amdgpu", "X.Org Foundation", 0xef23fdc5, 0x10dc023a, 0x01150109, 23, 0, 0,
  "X.Org Video Driver", (ABIMAJ << 16) | ABIMIN, "X.Org Video Driver", {0,0,0,0} };
XF86ModuleData amdgpuModuleData = { &vers, 0, 0 };
