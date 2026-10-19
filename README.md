# XControl

A Catalyst-style control panel for X11 on Linux: per-game graphics overrides for
Mesa drivers, display settings through xrandr, and mice, touchpads, keyboards and
gaming mice. (Formerly *mesa-panel*; see [Upgrading from mesa-panel](#upgrading-from-mesa-panel).)

| Setting | OpenGL | Vulkan | Wine / Proton (DXVK / VKD3D-Proton) |
|---|---|---|---|
| Anisotropic filtering Off, 2–16× | yes (shim) | yes (layer) | yes (layer + DXVK config) |
| Forced MSAA 2–8× | games that draw to the window directly | no | Direct3D 8/9 with the WineD3D renderer |
| MSAA Off | window MSAA | no | Direct3D 11 through DXVK |
| Transparency AA | alpha test (fixed-function or shader `discard`), while MSAA is active | no | WineD3D: yes; DXVK: supersample only, when the game uses MSAA |
| VSync off / on | `vblank_mode` | `MESA_VK_WSI_PRESENT_MODE` | DXVK sync interval |
| Fast sync / adaptive | no | yes | yes |
| Frame limiter | yes (shim) | yes (layer) | yes (layer) |
| FreeSync off / on | `adaptive_sync` | `adaptive_sync` | `adaptive_sync` (Vulkan) |
| Post-process AA (FXAA/SMAA), sharpening | no | vkBasalt | vkBasalt |

Profiles match a game by Steam AppID (`steam:220`) or by the file name of the
program or one of its arguments (`ioquake3.x86_64`, `game.exe`). Anything
without a profile gets the global settings.

## Install (Arch)

```sh
makepkg -si
```

Dependencies: `python`, `python-gobject`, `python-cairo`, `gtk3`, `xorg-xrandr`
(build: `vulkan-headers`). The package is 64-bit only. That covers Proton games
too, since Wine's WoW64 mode makes the Vulkan calls from 64-bit code. Native
32-bit Linux games won't load the GL shim and print a harmless `ld.so` warning.

## Using it

1. Open **XControl**, set the global settings, and use **Add game** for
   per-game profiles. Changes save automatically.
2. Start games through the launcher:
   - Steam: set the game's launch options to `xcontrol-run %command%`
   - Anything else: `xcontrol-run /path/to/game`, or fill in **Command**
     in the profile and press **Launch**.
3. To check what would be applied: `xcontrol-run --print-env /path/to/game`.
   Set `XCONTROL_DEBUG=1` to have the shim and layer log what they hook.

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

## FreeSync

**FreeSync** sets Mesa's `adaptive_sync` option for the game (Mesa reads its driconf options
from the environment, like `vblank_mode`; the game's output then shows "default value of option
adaptive_sync overridden by environment"). Mesa already asks for variable refresh in fullscreen
games by default, so **Always off** is the useful setting for games that stutter or flicker with it.

X also has to allow it, which it doesn't by default. Add this to the `Device` section of your
xorg.conf (xf86-video-amdgpu and modesetting both support it) and restart X:

    Option "VariableRefresh" "true"

The display details (Displays → **Details**) show whether the display supports it and whether X has it enabled (read
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

## Displays

The Displays page drives xrandr. You can drag monitors around (edges snap),
change resolution, refresh rate and rotation, set the primary display, and turn
outputs on or off. **Apply** asks you to confirm and reverts after 15 seconds
if you don't. **Restore this layout when I log in** adds an autostart entry
that runs `xcontrol --apply-display`. In a Wayland session xrandr can't
change outputs, so the page explains that and disables Apply.

### Scaling and color

The **Scaling and color** section under the display settings shows only what the X driver offers
for that output. xf86-video-amdgpu and modesetting both pass the kernel's connector properties
through, so on AMD you normally get all of them:

- **GPU scaling** (`scaling mode`): what happens when the resolution is below the display's
  native one: let the display scale, stretch, center without scaling, or scale keeping the aspect
  ratio.
- **Underscan** (`underscan`, plus border sizes): for TVs that crop the edges.
- **Output range** (`Broadcast RGB`): full 0–255 or limited 16–235, for gray blacks or crushed
  shadows on HDMI.
- **Color depth** (`max bpc`): the highest bits per color the link may use.
- **Saturation** (`CTM`): the display engine's color matrix, 0 % (grayscale) to 200 %, applied
  to everything on screen including games. It's the same idea as Catalyst's saturation slider or
  NVIDIA's "digital vibrance".
- **Gamma** (`xrandr --gamma`): night-light tools such as redshift also change gamma and win.

**Saturation** and **Gamma** change the screen live while you drag; leaving without Apply (or
closing the panel) puts the old colors back. Changes go through **Apply** with the usual
15-second revert. A saved layout only stores values
that differ from the driver's defaults, so they come back after X restarts.

## Custom resolutions and ignoring the EDID

**Resolutions…** on the Displays page opens a per-display editor:

- **Add a resolution:** width, height and refresh rate, plus a timing standard:
  - **CVT**: VESA's standard formula, CRT-style blanking.
  - **CVT reduced blanking (v1):** lower pixel clock, for LCDs and bandwidth-limited links.
  - **CVT reduced blanking v2:** hits the exact refresh rate; good for high refresh rates.
  - **GTF**: the classic CRT formula.
  - **DMT**: the fixed VESA table (640×480 at 60 Hz = 25.175 MHz, and so on). This
    matters for low resolutions, because CVT's 640×480 at 60 Hz is below the 25 MHz
    many HDMI links accept.
  - **Manual:** paste any modeline.

  The preview shows the modeline, pixel clock, horizontal frequency and actual
  refresh rate. It warns when a mode is outside the range the display reports or
  too slow for HDMI. **Classic modes** fills in 640×480, 800×600, 1024×768 and so on.
- **Offer only my resolutions for this display** hides the EDID's mode list, for
  displays whose EDID lists modes they can't really show.

New modes go to xrandr right away; pick one on the Displays page and press Apply
(with the usual 15-second revert). X forgets custom modes when it restarts, so the
panel re-creates them at login. The full layout is re-applied only when **Restore
this layout when I log in** is on.

All generators match `edid-decode` exactly (1,056 CVT/RB/RBv2/GTF timings and the
87-entry DMT table). Run `make check` to verify.

## System-wide mode list (EDID override)

The options above only change what the panel offers. Games and other programs read
the mode list from the kernel, which builds it from the display's EDID. **Resolutions…
→ System-wide mode list…** builds a corrected EDID that lists only the modes you tick:

- It keeps the display's name, serial number, size and colour data from its real EDID.
- A mode that matches an established timing sets that bit. A VESA (DMT) mode uses a
  standard-timing slot. Everything else is stored as an exact detailed timing, so
  your custom CVT, GTF or manual modes keep their exact timings.
- It clears the "continuous frequency / GTF" flag, so the kernel doesn't add extra
  modes on its own, and widens the range limits to cover your modes.
- If the display has a CTA-861 block (HDMI, audio, HDR), that data is kept; only its
  video modes are replaced.

Every generated EDID is checked against `edid-decode --check` in `make check`.

Buttons:

- **Save EDID file…** writes the EDID to a file.
- **Test now** loads it through the kernel's debugfs `edid_override` until the next
  reboot (asks for your password via polkit). **Undo test** restores the original.
- **Make permanent…** installs it to `/usr/lib/firmware/edid/` and shows what to add
  to your boot setup: the `drm.edid_firmware=` kernel parameter, and on Arch a
  mkinitcpio `FILES=` entry, because the kms hook loads the GPU driver from the
  initramfs. The panel never edits your bootloader or initramfs configuration itself.

The top of the dialog says whether the kernel is actually using the override, and if not,
what's missing: the kernel parameter (or one naming the wrong connector), the initramfs
`FILES=` entry, an initramfs built before the file last changed, or simply a pending
reboot. **Test now** always lasts only until the next reboot.

The only code that runs as root is `xcontrol-edid-helper`. It validates every
argument, accepts only real EDID files, and writes only to the connector's debugfs
override or `/usr/lib/firmware/edid/xcontrol-*.bin`.

## Switching X drivers

The same connector has a different X name depending on the driver: `DisplayPort-0` and
`HDMI-A-0` with xf86-video-amdgpu or xf86-video-ati, `DP-1` and `HDMI-1` with modesetting.
Custom resolutions, the "only my resolutions" choice and the saved layout are stored under
the X name, so when an output disappears and another appears on the same kernel connector,
the panel moves the saved settings over (on the Displays page and at login).

## Input

The **Input** page has three tabs.

**Mouse & Touchpad** (libinput, through `xinput`), per device:
- acceleration: **Flat** (no acceleration, what most players want) or **Adaptive**;
- pointer speed and scroll speed;
- natural scrolling, left-handed, middle click by pressing both buttons, horizontal scrolling;
- touchpads: tap to click, tap and drag, drag lock, disable while typing, how to scroll
  (two fingers or edge) and how to right-click (bottom corner or two fingers).

**Keyboard**: layout and variant, a second layout and the key to switch, Caps Lock behavior,
the Compose key (`setxkbmap`), and key repeat delay and speed (`xset`). Only the settings you
change here are managed; anything you don't touch is left to your own setup.

Mouse and touchpad changes are used when you press **Apply** (they're kept per device until
then, so you can change several devices first). **Reset to defaults** puts the driver's
defaults in the controls; Apply uses them and forgets that device's saved settings. Keyboard
changes apply immediately. X forgets input settings when a device is unplugged or the
session ends, so XControl saves them per device name and a small background helper
(`xcontrol --watch-input`, started at login from `~/.config/autostart/xcontrol-input.desktop`)
puts them back at login and whenever a device is plugged in. **Stop managing the keyboard**
removes the saved keyboard settings.

**Gaming Mouse** uses [libratbag](https://github.com/libratbag/libratbag)'s `ratbagd` (the
service Piper uses) for supported Logitech, SteelSeries, Razer, Roccat, G.Skill and other mice:
- DPI stages, which one is in use, which one the mouse starts with, and enabling or disabling stages;
- polling rate, button debounce time and angle snapping, when the mouse supports them;
- button remapping: any mouse button, DPI and profile switching, wheel directions, double click,
  or disabled. Keyboard keys and macros set elsewhere (Piper) are shown and kept;
- LEDs: off, on, color cycle or breathing, color, brightness and effect speed (Logitech mice keep a
  brightness only for the cycle and breathing effects; dim a steady light with a darker color);
- profiles, if the mouse has several.

These settings live in the mouse's own memory and are written by **Save to mouse**. On mice
with onboard profiles (most Logitech G mice), saving makes the mouse reload its settings and
switch to the DPI stage chosen under **After saving, use** next to the button. libratbag can't
see presses of the mouse's own DPI button, so pick the stage you want there before saving.

## Appearance

One place to pick the GTK theme, icon theme, cursor (theme and size), interface font
(antialiasing, hinting, subpixel order) and the dark preference. Choices preview inside
XControl; **Apply** writes them everywhere an X11 program looks:

- `~/.config/gtk-3.0/settings.ini`, `~/.config/gtk-4.0/settings.ini` and `~/.gtkrc-2.0`
  (other settings in those files are kept)
- `~/.icons/default/index.theme` and `Xcursor.*`/`Xft.*` in `~/.Xresources` (merged with
  `xrdb`) for the cursor and fonts of plain X programs; the root window cursor is set too
- GNOME's `org.gnome.desktop.interface` (including `color-scheme`, which libadwaita apps
  follow), Xfce's xfconf when present, and qt5ct/qt6ct when installed
- the XSETTINGS manager, which is what makes **open apps change without a restart**. On X,
  GTK apps read `settings.ini` only when they start, and ignore it altogether while an
  XSETTINGS manager runs. That is the usual reason a theme tool "doesn't apply": a leftover
  `xsettingsd` keeps announcing the old theme. XControl updates `xsettingsd`'s config and
  reloads it, or starts it (and adds it to your login) if none is running. With GNOME, MATE
  or Xfce's own settings daemon, it goes through those instead.

On i3 and similar window managers, restart the window manager (i3: Mod+Shift+R) to get the new
cursor on the desktop and window borders.

### An app ignores the theme?

**Check an app…** lets you click the app's window and inspects that process: the toolkit it
really loads, how it's packaged, its environment and the user it runs as. Usual causes:

- `GTK_THEME` set in its environment (overrides everything)
- an **AppImage** whose bundled GTK doesn't search `/usr/share/themes`: one click links the
  theme into `~/.local/share/themes`, where every GTK looks
- **Flatpak**: copies the theme to your home folder and grants Flatpak apps read access
- **libadwaita** apps: they only follow the dark preference, by design
- the theme has no version for the app's GTK (e.g. a GTK 3 theme and a GTK 4 app)
- Qt apps without `QT_QPA_PLATFORMTHEME=qt5ct` (or `qt6ct`) in the session environment
- a leftover `~/.config/gtk-4.0/gtk.css` (or `gtk-3.0/gtk.css`): GTK loads it on top of every
  theme. Theme installers with a "libadwaita"/"GTK 4" option and style editors leave one behind;
  one click renames it (and the `assets` link next to it) so nothing is lost
- the app runs as another user (sudo), or draws its own interface

## Mouse wheel

Turning the wheel over a dropdown, number field or slider scrolls the page instead of changing
the setting, so scrolling past settings can't change them by accident. Number fields and
sliders take the wheel once you've clicked into them; dropdowns never do.

## Upgrading from mesa-panel

XControl was called mesa-panel. The package replaces it, and on first start your profiles,
display settings and login entry are carried over from `~/.config/mesa-panel`. The old
commands `mesa-panel` and `mesa-panel-run` still work (they point to `xcontrol` and
`xcontrol-run`), so Steam launch options don't need changing, and the `MESAPANEL_*`
environment variables are still read. An EDID override installed as
`/usr/lib/firmware/edid/mesa-panel-*.bin` keeps working; installing a new one uses the
`xcontrol-*.bin` name, and the dialog tells you to update the kernel parameter.

## System

The **System** page shows the distribution, kernel, uptime, package count, window manager,
X server and X driver (from the server's log), OpenGL, Mesa and Vulkan versions, the
processor (cores, cache, clock, frequency driver and policy, microcode), memory and swap,
each graphics card (model and card maker, kernel driver, video memory, and on amdgpu its
load, clocks, temperature and power), motherboard and BIOS, UEFI and Secure Boot, drives,
disk space, network adapters, sound cards and sound server, and every temperature and fan
sensor. Usage, clocks, temperatures and memory refresh every 2 seconds while the page is
open. Everything is read from `/proc` and `/sys` without root; OpenGL and Vulkan details
need `glxinfo` (mesa-utils) and `vulkaninfo` (vulkan-tools), and device names come from
hwdata.

**Copy** puts it on the clipboard as text, leaving out your computer and user names (the arrow
has **Copy in English** for bug reports). `xcontrol --sysinfo` prints the same text in a
terminal (`--sysinfo --english` for English).

## Display details

**Details** on the Displays page opens what the selected display reports in its EDID,
plus what the driver exposes through xrandr:

- **Identity:** model, manufacturer, product code, serial number, manufacture date.
- **Panel:** native resolution, size, pixel density, color depth (with the driver's
  `max bpc` limit), gamma.
- **Refresh & sync:** highest refresh rate and resolution, supported refresh range,
  variable refresh rate (`vrr_capable` plus the FreeSync range).
- **Color & HDR:** HDR10/HLG/HDR10+/Dolby Vision, peak and full-frame brightness,
  gamut coverage of sRGB/DCI-P3/Rec. 2020 computed from the reported primaries,
  white point, wide-color signaling.
- **Connection:** X11 and kernel output names, current mode, input type, HDMI 2.0/2.1
  capability (TMDS clock, FRL bandwidth), audio, YCbCr formats, power saving.

**Copy details** copies a plain-text summary, and **Save EDID…** writes the raw EDID
for `edid-decode` or bug reports. The data comes from the kernel
(`/sys/class/drm`).

Keep in mind that this is what the monitor *claims*. Gamut and brightness figures in
EDIDs are often rounded or copied between models, so treat them as approximate.

## Translations

The interface uses gettext; translations live in `po/`. A Brazilian Portuguese
translation is included, and the app follows your desktop language.

- Add a language: `make new-po LANG_CODE=es`, then translate `po/es.po`
  (Poedit works well).
- After changing strings in the code: `make update-po` merges them into every
  translation.
- `make` checks each translation with `msgfmt --check`, which also catches
  broken `{placeholders}`, and translates the app-menu entry.

**Copy** on the System page and **Copy details** in the display details copy in your language. The arrow next to
it has **Copy in English**, which is more useful in bug reports.

## Title bar

On GNOME-style desktops (GNOME, Pantheon, Budgie) the panel draws a GTK header bar like their
own apps. Everywhere else, including i3 and other tiling window managers, Xfce and KDE, the
window manager draws the title bar, the same as for Thunar, and status messages appear in a
small bar at the bottom of the window. `XCONTROL_CSD=1` or `0` forces either style;
`XCONTROL_DECORATION` picks the header bar's buttons (for example `":close"`).

## Limitations

- Forced MSAA can't work for games that render through framebuffer objects
  (most games since ~2008), or for Vulkan games. That was also true of the
  Catalyst-era drivers. Use the game's own AA, or a post-process AA such as
  vkBasalt.
- Transparency AA finds alpha-tested shaders by looking for `discard`, the usual way
  to write an alpha test. Shaders that discard for other reasons get supersampled
  too: correct, but slower. Games that load precompiled SPIR-V shaders aren't detected.
- Recent DXVK versions can describe samplers through `VK_EXT_descriptor_heap`
  without calling `vkCreateSampler`. The `samplerAnisotropy` entries in
  `DXVK_CONFIG` cover that case for D3D9/11.
