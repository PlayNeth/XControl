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

The pages are grouped in the sidebar: Gaming & Hardware, Desktop and System.

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

### Night light

Warmer colors in the evening, set at the bottom of the Displays page and applied right away by
the desktop service (no Apply). **When**: from sunset to sunrise (the sun's position at your
location, which comes from the time zone unless you enter latitude and longitude), at set hours
with a gradual change, or all the time. **Night color** goes from 6000 K down to 1500 K, and
**Leave alone** skips displays you do color work on. It writes each display's gamma ramps
(RandR) on top of the gamma set above, so the two don't fight, re-applies them if another
program resets them, and puts normal colors back when it's turned off. From a key:
`xcontrol --night toggle` (on or off until the schedule next changes; also `on`, `off`, `auto`).
The page warns when redshift, gammastep or sct is running too.

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

## Controllers

A replacement for sc-controller / DS4Windows-style tools, starting with the
**DualShock 4** (PS4 controller, both models and the USB adapter), over USB or
Bluetooth. Turn on "Use XControl for controllers"; a small service
(`xcontrol --pads`) then runs with the desktop service and picks up controllers
as they connect.

- **Light bar**: color and brightness (0 turns it off), set through the kernel
  driver's LEDs (`/sys/class/leds/inputN:red|green|blue|global`), so rumble
  doesn't reset it. Changes apply right away.
- **Report rate over Bluetooth**: Linux's driver asks the controller for a
  report every 4 ms (250 Hz). XControl sends it the interval you pick (1, 2, 4
  or 8 ms) through its hidraw node, right away and whenever it reconnects; the
  page shows the rate actually measured. Bluetooth itself is the ceiling: a
  full DualShock 4 report needs at least two radio slots, so 1 ms usually lands
  around 500–800 Hz depending on the adapter (Wi-Fi + Bluetooth combo cards
  share their radio and sit at the low end). That's still faster than the
  cable: over USB the controller itself usually won't go past 250 Hz.
- **Report rate over USB**: Linux picks the USB polling interval, so this is
  usbhid's `jspoll` setting, which covers every USB gamepad. It asks for your
  password (`xcontrol-controller-helper`), is kept for the next boots
  (`/etc/tmpfiles.d/xcontrol-usbhid.conf`, plus `/etc/modprobe.d` when usbhid is
  a module), and reconnects a plugged-in DualShock 4 so it applies now. Faster
  polling only helps if the controller has new data that often: most DualShock
  4s produce 250 reports per second over USB no matter how often they're asked
  (the measured rate on the page tells). Other USB gamepads can benefit.
- **Xbox 360 controller for games**: games see a virtual Xbox 360 pad (uinput,
  045e:028e, the same as xpad) instead of the DualShock 4. Rumble from the game
  is passed on to the DualShock 4.
- **Hiding the DualShock 4**: SDL, Wine/Proton and Steam find controllers
  through their device files (the raw HID one too), so grabbing the input isn't
  enough. Once the service has the controller's files open, a small root helper
  (`xcontrol-controller-hide`, allowed without a password for the active
  session) takes your user's access to them away; it gives it back when you
  untick it or the service stops, and a reconnected controller gets it from udev
  as usual. Games already running keep what they had open. Being in the `input`
  group defeats this (every program can read every input device then). Steam
  has its own controller support: turn off "PlayStation Configuration Support"
  in Steam, or it uses the DualShock 4 as well.
- **Button remapping**: every DualShock 4 button (and the touchpad click) can be
  any Xbox button, a trigger, a d-pad direction or nothing. L2/R2 stay analog
  while they're mapped to LT/RT.
- The touchpad can keep moving the mouse pointer, or be hidden too.
- **Gyro aiming**: turn the controller to aim, either as a separate virtual
  mouse ("XControl gyro mouse", the most precise) or added to the virtual Xbox
  pad's right stick (works in every game; set the game's stick deadzone on the
  page so small turns get past it). It can be always on, on while a button is
  held (L2 by default), toggled by a button, or off while a button is held;
  touching the touchpad counts as a button too. "Around the way you face"
  (player space) uses the accelerometer to turn around the real vertical
  however you hold the controller; plain yaw and roll are there too. Slow
  movement is smoothed and tiny movement (hand tremor) is tightened away, while
  quick turns stay raw. The gyro's drift is learned whenever the controller lies
  still for a moment, or on request with "Calibrate now". Speed is in mouse
  dots per degree turned, so it pairs with the game's mouse sensitivity.

Permissions come from `/usr/lib/udev/rules.d/70-xcontrol-controllers.rules`:
`/dev/uinput`, the DualShock 4's hidraw node and its light bar LEDs for the
logged-in user. They apply to controllers connected after installing, so
reconnect the controller once (or reboot). Stop sc-controller (`scc-daemon`)
first, or both will drive the controller and games see an extra pad.

## Appearance

One place to pick the GTK theme, icon theme, cursor (theme and size), interface font
(antialiasing, hinting, subpixel order), the dark preference, and **sounds and effects**:
event sounds (the alert/error "bell" sounds apps play), click and key feedback sounds, and
animations (the fades and slides in menus, popovers, switches and tabs). Choices preview inside
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

GTK 4.20 and later choose a theme's dark variant only from `gtk-interface-color-scheme`, which
on X11 comes from nothing but `~/.config/gtk-4.0/settings.ini` (there's no XSETTINGS key for
it, and the old `gtk-application-prefer-dark-theme` there no longer counts). XControl writes it
when that GTK 4 is installed; GTK 4 apps pick up a light/dark change when they restart.

Sounds and animations go through the same places (`gtk-enable-event-sounds`,
`gtk-enable-input-feedback-sounds`, `gtk-enable-animations`; `Net/EnableEventSounds`,
`Net/EnableInputFeedbackSounds`, `Gtk/EnableAnimations` over XSETTINGS; GNOME's
`enable-animations`, `event-sounds` and `input-feedback-sounds`), so open apps follow right away.
Windows fading as they open and close is picom's, on the Bar & Compositor page.

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

## Sound

Volumes, the default output and input, ports and card profiles are pavucontrol's job (**Open
the mixer** starts it). The Sound page covers what it can't do:

- **Devices**: each output, input and sound card's gear can **rename** it (the name every program
  shows), **hide** it from every program (e.g. the graphics card's HDMI audio you never use),
  **never let it sleep** (no pop and no lost first second, common with HDMI and USB DACs), and
  **prefer it whenever it's connected**. Hidden devices stay listed so they can come back.
  Bluetooth headsets and speakers work too; their settings follow the headset's address, so
  they hold in music and headset-with-mic mode alike.
- **Sound system (PipeWire)**: the sample rate, **follow what's playing** (music at 44.1 kHz
  plays unconverted; allowed rates), the **buffer size** (larger against crackling, smaller for
  less delay in games and music), and keeping every output awake.

Sample rate and buffer size change right away (PipeWire's settings metadata) and are saved in
`~/.config/pipewire/pipewire.conf.d/50-xcontrol.conf` (and the PulseAudio-side
`pipewire-pulse.conf.d`); device settings go to
`~/.config/wireplumber/wireplumber.conf.d/50-xcontrol.conf` (WirePlumber 0.5, or
`main.lua.d` and `bluetooth.lua.d` scripts for 0.4) and restart WirePlumber.

## Desktop

### Wallpaper

XControl sets the wallpaper itself, so feh or nitrogen aren't needed. It draws the
picture with cairo and makes it the root window's background the same way feh and Esetroot
do (`_XROOTPMAP_ID`, `ESETROOT_PMAP_ID`), so picom and terminals with fake transparency see it.
The previous background is freed, not leaked.

- **Layout:** the same picture on every display, one picture across all of them, or a different
  picture per display.
- **Placement:** fill (crops to cover), fit (whole picture, bars in the background color),
  center, tile or stretch. You can also use just a color.
- It's redrawn automatically when the resolution or the display layout changes, including
  changes made outside XControl.

Remove `exec ~/.fehbg`, `feh --bg-…` or `nitrogen --restore` from your i3 config; the page points
out those lines if it finds them.

### Screen lock

XControl doesn't include a locker of its own. Lockers are security code: a missed keyboard grab
or a crash leaves the session open. XControl sets up the proven ones instead:
[xss-lock](https://bitbucket.org/raymonad/xss-lock) plus **i3lock**, **xsecurelock** or
**slock**.

- **Lock after being idle for:** sets X's screen saver timeout (`xset s`); xss-lock starts the
  locker when it kicks in.
- **Lock before suspend and hibernate:** xss-lock holds the suspend until the locker is up
  (`--transfer-sleep-lock`).
- **Lock screen shows** (i3lock): your wallpaper, drawn at your exact screen size, or a color.
- **Lock now**, or `xcontrol --lock` from a key binding, e.g.
  `bindsym $mod+Shift+x exec --no-startup-id xcontrol --lock`.

Remove any `exec xss-lock …` line from your i3 config, or two lockers will start.

### Screen power

**Turn the screen off after** sets DPMS (`xset dpms 0 0 N`). **Leave as it is** doesn't touch it.

### Keep the screen on

- **Stay awake now** holds off the screen lock and screen-off until you turn it off, or for 30
  minutes to 4 hours. From a key or a script: `xcontrol --awake on|off|toggle|MINUTES|status`.
- **Gamepads and joysticks count as activity** (like joystickwake): a button press, a d-pad or a
  real stick/trigger movement (not stick drift) restarts X's idle timer the way a key press does,
  and wakes a screen that's off. Every device udev marks as a joystick is watched, including ones
  plugged in later; motion sensors and touchpads of controllers are ignored. It reads
  `/dev/input/event*`, which the logged-in user can normally read already.
  Virtual pads that programs create (Steam Input, sc-controller, xboxdrv, input-remapper) are
  marked as such on the page, with the program that probably made them.
- **Apps can keep it on**: XControl answers `org.freedesktop.ScreenSaver` on the session bus, so
  Steam, browsers, video players and SDL games that ask for the screen to stay on get their
  way while they play (and the request ends when the app quits). A desktop's own power manager
  answering already takes precedence.
- **While the focused window is full screen**.

While something keeps the screen on, the service suspends X's screen saver and DPMS timers
(`XScreenSaverSuspend`); when it ends, the idle time starts over, so the screen doesn't go dark
the moment a video finishes. The page shows what is keeping it on.

### At login

`xcontrol --desktop-daemon` sets the wallpaper, applies blanking, runs xss-lock (restarting it
if it dies) and redraws the wallpaper when displays change. It's added to
`~/.config/autostart`, but i3 doesn't run that folder by itself, so add one line to your i3
config instead (or use `dex`):

    exec --no-startup-id xcontrol --session

`--session` starts everything XControl uses at login, each part only when its settings are in
use: it restores the display layout, starts xsettingsd for live theme updates, starts the
input watcher (mouse, touchpad and keyboard settings, re-applied on hotplug) and runs the desktop
service. Single flags still work and can be combined, e.g.
`xcontrol --desktop-daemon --watch-input`. The Desktop page warns when nothing would start them.

## Bar & Compositor

XControl can run polybar and picom for you, so their config files don't have to be written by
hand. It generates its own (`~/.config/xcontrol/polybar.ini` and `picom.conf`) from what you pick;
your own polybar and picom configs are neither used nor changed. Changes apply right away.

**Bar (polybar):** top or bottom, height, on every display or only the primary one, font, colors
(with a see-through background when a compositor runs), and the modules: i3 workspaces (polybar's
`internal/i3`), workspaces for other window managers (`internal/xworkspaces`, off by default), window
title, clock, CPU, memory, CPU temperature, volume, network, disk, keyboard layout, battery
(laptops) and the system tray, each on the left, center or right, in any order. Labels are words
(CPU, RAM, VOL) or icons when a Nerd Font is installed (e.g. `ttf-nerd-fonts-symbols`).
Every module has a gear button with its settings, e.g. for the i3 workspaces: name or number,
only this display's workspaces, urgent ones from other displays, hiding numbers ("1:web" →
"web"), sorting, click and scroll (wrapping, reversed), a separator, label spacing, and colors
for the current, other, shown-elsewhere and urgent workspaces and for i3 modes; the title's
length, clock formats and color, memory as percent or amount, network address, speed or name,
temperature in °C or °F, the volume step and what right-click runs (e.g. `alacritty -e wiremix`),
keyboard layout and Caps Lock, tray spacing and icon size. The bar has height in pixels or
points, rounded corners, the text between modules, scrolling anywhere to switch workspaces and
the language for dates.

Anything else polybar offers goes into **Extra polybar settings** (per module, and for the bar):
`key = value` lines that are added to that section and replace XControl's own line with the same
key. The generated file uses polybar's usual section names (`[module/i3]`, `[module/date]`,
`[module/pulseaudio]`, `[module/systray]`...). One bar runs per display, and the bars are
restarted when displays change; polybar picks up setting changes by itself.

**Compositor (picom):** backend (glx, xrender, egl), VSync, letting full-screen games skip the
compositor (lower input lag, and needed for FreeSync), shadows, fading, rounded corners, blur
behind see-through windows, and the opacity of focused and other windows. The generated file
only uses options that work from picom 9 to 12, and keeps the bar, the desktop, i3's frames,
menus and the lock screen free of effects.

Both are started by `xcontrol --session` and restarted if they crash; if one keeps failing, the
page shows why (e.g. a backend your driver doesn't support). The page also points out
`exec polybar`/`launch.sh`, `exec picom` lines and an i3 `bar { }` block in your i3 config, which
would start a second bar or compositor, and can stop ones that are already running.

## Notifications

With **Use XControl's notifications (dunst)** on, XControl writes its own
`~/.config/xcontrol/dunstrc` and runs dunst for the session (restarting it when the settings
change); `~/.config/dunst/dunstrc` isn't used or changed. It writes the syntax of the installed
dunst (the `(x, y)` forms of 1.12 and later, `10x50` before).

- **Where they show**: corner, distance from the edges, which display (with the focus, with the
  mouse, the first), width, tallest size, how many at once and the space between them.
- **Look**: font (or the interface font), rounded corners, border, padding, icon position and
  size (from your icon theme), text alignment, what's shown (title and text, with the app name,
  with progress, or your own format), see-through (with the compositor) and separators.
- **Colors and timing** for low, normal and critical notifications, and whether critical ones get
  through **Do not disturb** (dunst's pause levels, 1.10 and later).
- **Behavior**: age shown after a while, keeping notifications while you're away, the history,
  repeated ones stacked, waiting/actions/links indicators, progress bars, what left, middle and
  right clicks do, and a sound.
- **Per app**: hide an app's notifications, only keep them in the history, keep them until
  clicked, change their urgency, or silence them.
- **Extra dunst settings** for anything else, and test buttons for each urgency.

Shortcuts for i3: `dunstctl close`, `dunstctl close-all`, `dunstctl history-pop`,
`dunstctl context`, and `xcontrol --dnd on|off|toggle` for Do not disturb. The page warns when
another notification program holds the session bus (and can stop it) or is started by your i3
config.

### Power alerts

XControl can run [poweralertd](https://git.sr.ht/~kennylevinsen/poweralertd)
for the session (Notifications page): a notification when the battery starts
or stops charging, gets low or critical, or the charger is plugged in or out,
and the same for wireless devices with their own battery (mice, keyboards,
controllers, headsets, phones...), which you can pick by kind. Any notification
program shows them, and `poweralertd` works as the app name in dunst's per-app
rules. The alerts themselves are poweralertd's, in English.

Start it from one place only: if poweralertd's own systemd user service is
enabled, or your i3 config runs it, every alert shows twice. The page (and the
session check) says so and can turn the service off.

## Window Manager (i3)

When **Use XControl's i3 config** is on, XControl writes `~/.config/i3/config` itself and reloads
i3 after every change. The config you had is moved aside as `config.before-xcontrol` (and
`~/.i3/config`, which i3 would otherwise read first, as `~/.i3/config.before-xcontrol`); switching
the page off offers to put it back. Every change is checked with `i3 -C` before it's written, so
a mistake shows up on the page as an error and never replaces a working config. **Show the file…**
shows (and copies) what's written.

The first time it's switched on you can start from i3's defaults or **import** your current config:
keys (with `$mod` and other variables resolved), modes, startup programs, window rules, workspace
names and displays, font, borders, gaps and colors come over; lines XControl now takes care of
(polybar/`launch.sh`, picom, feh, xss-lock, dunst, an i3 `bar { }`, each only when XControl runs
that part) are left out, and anything else lands in **Extra i3 config**.

- **Look:** title font, borders for tiled and floating windows, title position, hiding borders
  at the screen edge, gaps between windows and around the edge (and none for a lone window), and
  all of i3's window colors. On i3 4.24 and later, "no border for a lone window" is one of the
  hide-edge-borders choices (4.24 deprecated the separate `smart_borders`); older i3 gets the old
  form.
- **Keys:** the main key (Super or Alt, `$mod`), dragging windows, and every key binding in every
  mode, with search. Add or change a binding by typing it or pressing it (**Press keys…** grabs
  the keyboard, so even combinations i3 uses reach it). Keys used twice are shown in red.
- **Behavior & Workspaces:** focus follows the mouse, mouse warping, what happens when a window
  asks for attention, focus wrapping, where new windows go, new workspace layout, dialogs over
  full-screen windows, going back to the previous workspace, and a name and display for
  workspaces 1–10.
- **Startup & Rules:** programs started with i3 (or on every reload), window rules (`for_window`,
  `assign`; **Pick a window…** fills in a program's class with `xprop`), i3's own bar when
  XControl's bar is off, and **Extra i3 config** for anything else from i3's user guide.

`exec --no-startup-id xcontrol --session` is always in the generated file, so the wallpaper,
bar, compositor, screen lock and input settings start with i3.

## Default Apps

Which program opens links, email links, folders, text files, pictures, videos, music, PDFs,
archives and office documents, saved in `~/.config/mimeapps.list` (what xdg-open, browsers and
file managers read). Picking a program for a group sets it for every type in the group it can
open. **Every file type** lists all types with a program, searchable, to change any one. The
page also cleans up entries pointing to programs that are no longer installed, warns when
`$BROWSER` overrides the browser, and makes your own launchers in `~/.local/share/applications`
(AppImages, Wine, Steam games) count by refreshing their `mimeinfo.cache`, which nothing else does.

**Terminal**: there's no standard for it, so the choice goes to `~/.config/xdg-terminals.list`
(xdg-terminal-exec, which GLib uses for programs that run in a terminal), and XControl's i3
config uses it for the terminal key instead of i3-sensible-terminal.

## Date & Language

- **Time zone** (searchable), **automatic time** from the internet (needs systemd-timesyncd,
  chrony or ntpd), **setting the time by hand**, and **keeping the hardware clock in local
  time** for dual boot with Windows. These go through systemd's timedated, so polkit asks for
  your password.
- **Language** (menus and messages) and **Formats** (dates, times, numbers, currency, units,
  paper), with a preview, **just for you** or **for everyone** (through systemd's localed).
  They take effect at the next login. Just for you is saved in `~/.config/locale.conf`, but
  Arch only reads that file when no language is set yet, and a login screen (LightDM, SDDM,
  ly…) has already set the system one by then. So XControl also adds a marked block to
  `~/.xprofile` (which login screens run for X sessions) that loads it, and writes
  `~/.config/environment.d/90-xcontrol-locale.conf` for programs systemd starts. Going back
  to the system language removes both; the rest of your `~/.xprofile` is left alone.
- **More languages…** turns languages on for the whole computer: it enables them in
  `/etc/locale.gen` and runs `locale-gen`, through a small root helper (pkexec) that only accepts
  names listed in `/usr/share/i18n/SUPPORTED`.

## Power

- **Sleep when idle** after 10 minutes to 3 hours, counted from the last mouse, keyboard or
  gamepad input. It never sleeps while something keeps the screen on (Desktop page) or, if you
  want, while sound is playing. The screen lock locks first when it's on. **Sleep now** too.
- **Buttons**: what the power button, the sleep and hibernate keys and (on laptops) closing the
  lid do: shut down, sleep, hibernate, hybrid sleep, sleep then hibernate, lock, restart or
  nothing. Saved in `/etc/systemd/logind.conf.d/50-xcontrol.conf` through a small root helper
  (pkexec), and logind re-reads it right away (it's never restarted).
- **Power profile**: power saver, balanced or performance, when power-profiles-daemon (or
  tuned-ppd) runs.

## Session check and backups

System → **Check & Backup** looks at everything that quietly breaks other pages and offers a fix
where it can: whether `xcontrol --session` runs at login, whether the desktop service is up and
what keeps stopping, whether a **polkit agent** runs (on i3 nothing starts one, and then every
password prompt fails silently; it can start an installed agent and gives the line for your i3
config), extra bars, compositors, notification programs or locks running besides XControl's,
lines in your i3 config that start them twice, another night-light program, XSETTINGS for live
theme changes, notifications and sound.

**Save a backup…** writes one JSON file with all of XControl's settings plus the files it
writes that aren't regenerated from them (theme files, `mimeapps.list`, the terminal choice,
`locale.conf`, `~/.face`). **Restore a backup…** puts them back (keeping the current files as
`*.before-restore`; only those known files are ever written), applies them and restarts XControl.

## Users

The **Users** page lists the regular accounts (UID 1000 and up; never root or system
accounts) and changes them:

- **Full name**, **login name** (renaming moves `/home/OLD` to `/home/NEW`; not for the account
  you're logged in with, nor one with programs running), **password** (with a strength hint),
  **administrator** (the `wheel` group), **login shell** (from `/etc/shells`) and **picture**.
- **Groups**: the optional ones only, explained in plain words (`input` for sc-controller and
  gamepad tools, `uucp` for serial ports, `video`, `audio`, `storage`, `rfkill` and so on).
  They apply from the next login.
- **Add user…** (full name, login name suggested from it, password, administrator) and
  **Remove…** (keeping the home folder or deleting it).

Changes go through `xcontrol-user-helper`, the third small root helper, run with pkexec. It
only touches regular accounts, accepts only valid names (the full name can't contain `: , =`),
reads passwords from its standard input (never the command line), only manages the groups listed
above, and refuses to delete, rename or demote the account that's using XControl, so you can't
lock yourself out. Your own picture is also written to `~/.face`; login screens that use
AccountsService (LightDM, GDM, SDDM) get a copy in `/var/lib/AccountsService`.

All three helpers come with a polkit policy (`io.github.xcontrol.policy`): after you type your
password once, further changes don't ask again for a few minutes. On i3 a polkit agent has to
be running for the password prompt, e.g. `exec --no-startup-id /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1`.

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

### Kernel modules

The **Kernel modules** tab shows the kernel command line and every module that's loaded.
Search by module, device or parameter name; select one to see what it is (from `modinfo`), the
devices it drives, the modules that need it, each parameter with its current value and
description, and the `options`/`blacklist` lines about it in `/etc/modprobe.d` and
`/usr/lib/modprobe.d`. **Include parts built into the kernel** adds the built-in parts that
have parameters. A few parameters can only be read by root.

**Change…** next to a module's parameters sets values for every time the module loads. They're
saved in `/etc/modprobe.d/xcontrol-MODULE.conf` (XControl never edits other files there) by
`xcontrol-module-helper`, the second small root helper, run through pkexec like the EDID one.
It accepts only module and parameter names that exist and plain values (letters, digits and
`. , : + / - _`), and XControl checks each value against the parameter's type first. Leave a
field empty for the module's default; **Remove XControl's settings** deletes the file.

- **Also change it now** writes the value to `/sys/module/MODULE/parameters/` for the
  parameters the kernel allows changing while the module runs; the rest apply at the next load.
- **Rebuild the boot image** runs `mkinitcpio -P` (or dracut / update-initramfs). It's needed
  for modules that load from the initramfs, which carries its own copy of modprobe.d; XControl
  ticks it for modules listed in mkinitcpio's `MODULES` and for GPU drivers with the `kms` hook.
- Values set on the kernel command line (`amdgpu.ppfeaturemask=…`) win over modprobe.d; the
  dialog warns about those, and about other modprobe.d files setting the same parameter.
- Parts built into the kernel can't be set through modprobe.d; the page shows the command-line
  form instead.

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
