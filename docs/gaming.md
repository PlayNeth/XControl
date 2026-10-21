# Gaming

The Gaming page sets graphics overrides globally and per game. Profiles match a game by Steam
AppID (`steam:220`) or by the file name of the program or one of its arguments
(`ioquake3.x86_64`, `game.exe`). Anything without a profile gets the global settings. The table
in the [README](../README.md) shows which setting works with which API.

## Launching games

Settings only reach games started through the launcher:

- Steam: set the game's launch options to `xcontrol-run %command%`.
- Anything else: `xcontrol-run /path/to/game`, or fill in **Command** in the profile and press
  **Launch**.

`xcontrol-run --print-env /path/to/game` shows what would be applied. Set `XCONTROL_DEBUG=1` to
have the shim and layer log what they hook.

## How it works

- **`xcontrol-run`** looks up the profile and sets environment variables, then
  `exec`s the game.
- **`libxcontrol_gl.so`** (`LD_PRELOAD`) intercepts GL calls through direct
  linking, `glXGetProcAddress`/`eglGetProcAddress`, and `dlsym` on a libGL/libEGL
  handle (the SDL path).
  - AF: forces `GL_TEXTURE_MAX_ANISOTROPY` whenever a texture or sampler gets a
    linear or mipmapped minification filter. Point-sampled textures are left
    alone.
  - MSAA: adds sample buffers to `glXChooseFBConfig`, `glXChooseVisual` and
    `eglChooseConfig`. If no matching config exists, it falls back to what the
    game asked for.
  - TrAA: enables alpha-to-coverage or per-sample shading while
    `GL_ALPHA_TEST` is on.
  - FPS: sleeps before `SwapBuffers`.
  - Other `dlsym` lookups pass through as a tail call, so other interposers
    (Steam overlay, MangoHud) keep working in either load order.
- **`VK_LAYER_XCONTROL_overrides`** is an implicit Vulkan layer that only loads
  when `XCONTROL_VK=1`.
  - AF: patches `vkCreateSampler` for linear samplers and turns on the
    `samplerAnisotropy` feature if the game didn't.
  - FPS: limits in `vkQueuePresentKHR`.
- Driver and DXVK knobs (`RADV_TEX_ANISO`, `DXVK_CONFIG`, …) are set alongside
  the hooks to cover paths they can't see.

## 3D preview

The Gaming page opens with a live 3D scene, like the ones in the old Catalyst and NVIDIA control
panels: glxgears' three gears turning above a checkerboard floor, with a chain-link fence
behind them, drawn with the settings you're editing:

- **Multisampling**: the gears' edges (drawn into a multisampled framebuffer).
- **Anisotropic filtering**: the floor as it stretches to the horizon.
- **Transparency**: the fence, alpha-tested, with alpha-to-coverage or with per-sample shading.
- **Frame limiter**: the animation's frame rate.

The corner shows the frame rate and the OpenGL renderer. Drag to turn the scene; double-click
resets it. It only draws while it's on screen, and the **3D preview** heading collapses it
(remembered). "Application decides" settings are shown as the plain picture. It renders with OpenGL 3.3
off-screen (EGL) and shows each frame as an image, so the rest of the window is drawn normally;
GTK's own GL widget makes GTK 3 draw the whole window through OpenGL, which leaves garbage on
screen without a compositor. Nothing else to install.

## FreeSync

**FreeSync** sets Mesa's `adaptive_sync` option for the game (Mesa reads its driconf options
from the environment, like `vblank_mode`; the game's output then shows "default value of option
adaptive_sync overridden by environment"). Mesa already asks for variable refresh in fullscreen
games by default, so **Always off** is the useful setting for games that stutter or flicker with it.

X also has to allow it, which it doesn't by default. Add this to the `Device` section of your
xorg.conf (xf86-video-amdgpu and modesetting both support it) and restart X:

    Option "VariableRefresh" "true"

The [display details](displays.md#display-details) (Displays → **Details**) show whether the display supports it and whether X has it enabled (read
from the X server log). It also needs a fullscreen game with the compositor off or unredirecting
it, a frame rate inside the display's FreeSync range, and usually a single active display.

## Post-processing (vkBasalt)

**Edge smoothing** (FXAA or SMAA) and **Sharpening** (AMD's CAS) run through
[vkBasalt](https://github.com/DadSchoorse/vkBasalt) after the game draws each frame, so they work
where forced MSAA can't: native Vulkan games and Windows games through DXVK or VKD3D-Proton. They
don't apply to OpenGL games. The launcher writes a small vkBasalt configuration to
`~/.cache/xcontrol/` and sets `ENABLE_VKBASALT=1`. Press **Home** in a game to toggle the
effects and compare.

## Direct3D 8/9 games and MSAA

DXVK has no way to force MSAA. For old Direct3D 8/9 games (Need for Speed: Hot Pursuit 2,
GTA: Vice City and similar), set **Direct3D 8/9 games** to **WineD3D** in the game's
profile. The launcher then makes Wine use its built-in `d3d8`/`d3d9` for that game only
(`WINEDLLOVERRIDES=d3d8,d3d9=b`, plus `PROTON_USE_WINED3D=1` under Proton) and passes
the MSAA level as `WINE_D3D_CONFIG=SampleCount=N`. The rest of the prefix keeps using DXVK.

For a game in your own Wine prefix, add a profile whose **Applies to** is the executable
name (for example `nfshp2.exe`), then start it with:

```sh
WINEPREFIX=~/your-prefix xcontrol-run wine /path/to/nfshp2.exe
```
