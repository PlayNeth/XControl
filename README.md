# XControl

A Catalyst-style control panel for X11 on Linux. It covers per-game graphics overrides for Mesa
drivers, displays, input devices and PlayStation controllers, and the parts of a desktop that a
window manager like i3 leaves to you: theme, wallpaper, screen lock, bar, compositor,
notifications, sound, power and users.

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

## What's in it

- **Gaming & Hardware:** [Gaming](docs/gaming.md), [Displays](docs/displays.md),
  [Input](docs/input.md), [Controllers](docs/controllers.md), [Sound](docs/sound.md)
- **Desktop:** [Appearance](docs/appearance.md), [Desktop](docs/desktop.md),
  [Bar & Compositor](docs/bar-and-compositor.md), [Notifications](docs/notifications.md),
  [Window Manager (i3)](docs/window-manager.md), [Default Apps](docs/default-apps.md)
- **System:** [Date & Language](docs/date-and-language.md), [Power](docs/power.md),
  [Users](docs/users.md), [System](docs/system.md), [X server](docs/x-server.md)

The full documentation is in [docs/](docs/README.md).

## Install (Arch)

Clone the repository, then from its folder:

```sh
makepkg -si
```

Dependencies: `python`, `python-gobject`, `python-cairo`, `gtk3`, `xorg-xrandr`
(build: `vulkan-headers`). The package is 64-bit only. That covers Proton games
too, since Wine's WoW64 mode makes the Vulkan calls from 64-bit code. Native
32-bit Linux games won't load the GL shim and print a harmless `ld.so` warning.

## Using it

1. Open **XControl**, set the global settings, and use **Add game** for per-game profiles.
   Changes save automatically.
2. Start games through the launcher:
   - Steam: set the game's launch options to `xcontrol-run %command%`
   - Anything else: `xcontrol-run /path/to/game`, or fill in **Command** in the profile and
     press **Launch**.
3. On i3, add one line to your i3 config so the display layout, input settings, wallpaper, bar,
   compositor, screen lock and the rest start at login:

       exec --no-startup-id xcontrol --session

   System → **Check & Backup** tells you if something XControl relies on isn't running.

Turning the mouse wheel over a dropdown, number field or slider scrolls the page instead of
changing the setting. Number fields and sliders take the wheel once you've clicked into them.

On GNOME-style desktops (GNOME, Pantheon, Budgie) XControl draws a GTK header bar. Everywhere
else the window manager draws the title bar and status messages appear at the bottom of the
window. `XCONTROL_CSD=1` or `0` forces either style; `XCONTROL_DECORATION` picks the header
bar's buttons (for example `":close"`).

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
- DualSense support hasn't been tested on real hardware yet; the DualShock 4 has.

## Development

`make check` runs the tests and the translation checks. See
[Translations](docs/translations.md) for adding a language. Changes are listed in
[CHANGELOG.md](CHANGELOG.md).

## License

MIT, see [LICENSE](LICENSE).
