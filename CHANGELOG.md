# Changelog

XControl was called mesa-panel up to 0.8.0. Versions before 0.5.0 weren't kept.

## 0.20.1 (2026-10-19)

**Show which watched gamepads are virtual and what made them**

- Mark virtual gamepads (made by Steam Input, sc-controller, xboxdrv,
  input-remapper and the like) in the Desktop page's list of watched devices
- Name the program that probably created a virtual pad, or say it came from a
  system service when it can't be seen

## 0.20.0 (2026-10-19)

**Add a Notifications page and options to keep the screen on**

- Add a Notifications page that runs dunst with XControl's own config (your
  ~/.config/dunst/dunstrc is left alone), restarting it when settings change
- Set where notifications show, their look, colors and timeouts per urgency,
  click actions, history, progress bars and an optional sound
- Add per-app rules: hide, keep only in history, keep until clicked, change
  urgency or silence; plus extra dunst settings and test buttons
- Add Do not disturb (critical notifications can still get through) and
  `xcontrol --dnd on|off|toggle`
- Warn when another notification program holds the session bus or is started
  by the i3 config, and offer to stop it
- Add "Keep the screen on" to the Desktop page: "Stay awake now" holds off the
  screen lock and screen-off until turned off or for 30 minutes to 4 hours
- Add `xcontrol --awake on|off|toggle|MINUTES|status` for keys and scripts
- Let gamepads and joysticks count as activity, like a key press: buttons and
  real stick movement (not stick drift) restart the idle timer and wake the screen
- Let apps (Steam, browsers, video players, SDL games) keep the screen on by
  answering org.freedesktop.ScreenSaver requests
- Keep the screen on while the focused window is full screen, and show on the
  page what is keeping it on
- Keep your own i3bar block and the startup lines for parts XControl doesn't
  run when importing an i3 config (only skip what XControl actually manages)
- Add libxss as a dependency and dunst as an optional one

## 0.19.3 (2026-10-19)

**Reword the hint for the generic workspaces bar module**

- Reword the "Workspaces (other window managers)" hint to recommend
  "i3 workspaces" on i3

## 0.19.2 (2026-10-19)

**Add bar workspaces module for window managers other than i3**

- Add a "Workspaces (other window managers)" bar module (polybar's
  xworkspaces) for bspwm, Openbox, Xfwm and others, off by default
- Add its settings: name or number, only this display's workspaces, showing
  empty workspaces, click and scroll, spacing and colors
- Rename the existing module to "i3 workspaces" and switch off the other one
  when either is ticked, so workspaces aren't shown twice
- Place modules added by an update next to the module they follow by default
  instead of at the end of the list

## 0.19.1 (2026-10-19)

**Add sounds and animations settings to the Appearance page**

- Add a "Sounds and effects" section to the Appearance page: event sounds
  (alerts and errors), click and key feedback sounds, and animations in menus,
  popups, switches and tabs
- Apply them through GTK 2/3/4 settings files, XSETTINGS and GNOME's settings,
  so open apps follow right away
- Point to the compositor's "Fade windows in and out" for window open and
  close fades

## 0.19.0 (2026-10-19)

**Add Window Manager (i3) page that writes the i3 config**

- Add a Window Manager (i3) page; with "Use XControl's i3 config" on, XControl
  writes ~/.config/i3/config itself and reloads i3 after every change
- Move the previous config aside as config.before-xcontrol and offer to put it
  back when the page is switched off
- Check every change with "i3 -C" first, so a mistake shows as an error on the
  page and never replaces a working config; "Show the file…" shows and copies it
- Start from i3's defaults or import the current config: keys, modes, startup
  programs, window rules, workspaces, font, borders, gaps and colors, leaving
  out what XControl now handles and keeping the rest as "Extra i3 config"
- Add Look settings: title font, borders, title position, hiding edge borders,
  gaps (and none for a lone window) and all of i3's window colors
- Add a Keys editor: the main key (Super or Alt), dragging windows and every
  binding in every mode, with search, "Press keys…" to capture a combination,
  and keys used twice shown in red
- Add Behavior & Workspaces settings: focus follows mouse, mouse warping,
  attention requests, focus wrapping, new window placement and layout, popups
  over full-screen windows, back-and-forth, and names and displays for
  workspaces 1–10
- Add Startup & Rules: programs started with i3 or on every reload, window
  rules with "Pick a window…", and i3's own bar when XControl's bar is off
- Always include "xcontrol --session" in the generated config
- Update the i3 config when the Bar & Compositor page turns XControl's bar on
  or off, so i3's own bar comes and goes with it

## 0.18.0 (2026-10-19)

**Add per-module settings and extra polybar options to the bar**

- Add a gear button to every bar module that opens its own settings, replacing
  the shared "Module options" section
- Add i3 workspace settings: name or number, only this display's workspaces,
  urgent ones from other displays, hiding numbers, sorting, click and scroll,
  a separator, spacing and colors for each workspace state and for i3 modes
- Add settings for the other modules: title length, clock formats and color,
  memory as percent or amount, network address, speed or name, temperature in
  °C or °F, volume step and right-click command, keyboard layout and Caps Lock
  display, tray spacing and icon size
- Add bar height in pixels or points, rounded corners, the text between
  modules, and scrolling anywhere on the bar to switch workspaces
- Add second accent and highlight colors (Caps Lock indicator, current workspace)
- Add "Extra polybar settings" for the bar and each module: key = value lines
  that are added to the generated config and override XControl's own
- Use polybar's usual section names ([module/i3], [module/date]...) in the
  generated file
- Keep clock, temperature warning and disk settings made in earlier versions

## 0.17.1 (2026-10-19)

**Fix bar clock showing dates in English and add a clock language**

- Fix the bar's clock always showing weekday and month names in English; it now
  follows the session's language (LC_ALL, LC_TIME or LANG)
- Add a "Clock language" choice to the bar settings to pick any installed
  UTF-8 locale instead

## 0.17.0 (2026-10-19)

**Add Bar & Compositor page to run polybar and picom**

- Add a Bar & Compositor page that runs polybar and picom from generated
  configs; your own polybar and picom configs are neither used nor changed
- Configure the bar: top or bottom, height, every display or only the primary
  one, font, colors and a see-through background when a compositor runs
- Choose bar modules (workspaces, window title, clock, CPU, memory, temperature,
  volume, network, disk, keyboard layout, battery, tray), placed left, center
  or right in any order, with word labels or Nerd Font icons
- Configure picom: backend, VSync, letting full-screen games skip the
  compositor (needed for FreeSync), shadows, fading, rounded corners, blur and
  window opacity, keeping the bar, desktop, menus and lock screen free of effects
- Run one bar per display and restart the bars when displays change
- Start both from "xcontrol --session", restart them if they crash, and show
  why one keeps failing (e.g. a backend the driver doesn't support)
- Point out polybar, picom and i3 "bar { }" lines in the i3 config that would
  start a second bar or compositor, and offer to stop ones already running
- Fix the Desktop page's login warning still appearing without its text

## 0.16.1 (2026-10-19)

**Fix 3D preview leaving garbage on screen without a compositor**

- Fix the Gaming page's 3D preview leaving stale screen contents in parts of the
  window on i3 without a compositor
- Render the preview off-screen in its own OpenGL context (EGL) and show each
  frame as an image, so the rest of the window is drawn normally

## 0.16.0 (2026-10-19)

**Add live 3D preview of graphics settings to the Gaming page**

- Add a live 3D scene to the Gaming page, like the old Catalyst and NVIDIA
  panels: glxgears' gears above a checkerboard floor with a chain-link fence
- Show the settings being edited in the scene: multisampling on the gears'
  edges, anisotropic filtering on the floor, transparency anti-aliasing on the
  fence, and the frame limiter on the animation
- Show the frame rate and OpenGL renderer in the corner; drag to turn the scene
  and double-click to reset it
- Let the "3D preview" heading collapse the scene, remembered between runs; it
  only draws while visible and needs nothing extra installed (OpenGL 3.3)
- Fix saving game profiles overwriting settings that other pages had saved in
  the meantime
- Add tests for the preview's geometry, textures and settings mapping

## 0.15.0 (2026-10-19)

**Add Users page for managing user accounts**

- Add a Users page that lists the regular accounts (never root or system accounts)
- Change an account's full name, login name, password (with a strength hint),
  administrator rights (wheel group), login shell and picture
- Rename accounts, moving /home/OLD to /home/NEW; not allowed for the account
  you're logged in with or one with programs running
- Choose optional groups (input, uucp, video, audio, storage, rfkill...), each
  explained in plain words; they apply from the next login
- Add new users and remove users, keeping or deleting their home folder
- Write your own picture to ~/.face and copy pictures for login screens that use
  AccountsService (LightDM, GDM, SDDM)
- Refuse to delete, rename or remove admin rights from the account running
  XControl, so you can't lock yourself out
- Add a polkit policy for all root helpers so the password is asked only once
  for a few minutes of changes
- Add Copy buttons to the i3 config lines shown on the Desktop page and make
  its hints selectable
- Add xcontrol-user-helper, a third root helper run through pkexec, with tests

## 0.14.1 (2026-10-19)

**Add xcontrol --session to start all login helpers with one line**

- Add "xcontrol --session", one i3 config line that restores the display layout,
  starts xsettingsd for live theme updates, starts the input watcher and runs
  the desktop service, each only when its settings are in use
- Allow combining login flags, e.g. "xcontrol --desktop-daemon --watch-input"
- Suggest "xcontrol --session" in the Desktop page's login warning
- Fix the Desktop page's login warning showing up as an empty bar without text

## 0.14.0 (2026-10-19)

**Add Desktop page with wallpaper, screen lock and screen power**

- Add a Desktop page between Appearance and System
- Set the wallpaper without feh or nitrogen: same picture on every display, one
  picture across all displays, or a different picture per display
- Offer fill, fit, center, tile and stretch placement, or just a background color,
  with a live preview of the displays
- Make the wallpaper visible to picom and terminals with fake transparency, and
  redraw it automatically when the resolution or display layout changes
- Set up a screen lock through xss-lock with i3lock, xsecurelock or slock: lock
  after an idle time and before suspend and hibernate
- Let i3lock show the wallpaper, drawn at the exact screen size, or a plain color,
  and optionally the number of failed attempts
- Add a "Lock now" button and an "xcontrol --lock" command for key bindings
- Add "Turn the screen off after" to control DPMS screen blanking
- Add "xcontrol --desktop-daemon", started at login through ~/.config/autostart,
  that applies these settings and keeps xss-lock running
- Point out wallpaper and screen lock lines in the i3 config that would conflict,
  and warn when i3 would not start the desktop service at login
- Add tests for wallpaper placement and drawing, lock commands and conflicts

## 0.13.2 (2026-10-19)

**Let the window be narrower by scrolling pages sideways**

- Fix pages and dialogs forcing a wide window: the Gaming, Displays, Input, Appearance and
  System pages, display details and the resolution, EDID and module parameter dialogs
  now scroll sideways when the window is too narrow
- Make the Kernel modules list narrower by default and scroll the whole tab sideways when
  the details pane would get too small

## 0.13.1 (2026-10-19)

**Warn on the Appearance page about leftover gtk.css overrides**

- Show a warning at the top of the Appearance page when ~/.config/gtk-4.0/gtk.css or
  gtk-3.0/gtk.css overrides the chosen theme (as left by nwg-look's GTK 4 export and
  some theme installers), with a "Turn it off" button that renames it
- Check for such files again whenever the page is shown and after Apply

## 0.13.0 (2026-10-19)

**Let kernel module parameters be changed from the System page**

- Add Change… next to a module's parameters to set values used every time it loads,
  saved in /etc/modprobe.d/xcontrol-MODULE.conf; other modprobe.d files are never edited
- Check each value against the parameter's type before saving, and leave empty fields
  at the module's default
- Add "Also change it now" to write values to the running module where the kernel allows
- Add "Rebuild the boot image" (mkinitcpio, dracut or update-initramfs), ticked for modules
  that load from the initramfs, such as GPU drivers with the kms hook
- Warn when the kernel command line or another modprobe.d file sets the same parameter
- Add "Remove XControl's settings" to delete the module's XControl file
- Show the kernel command-line form for parts built into the kernel, which modprobe.d
  can't reach
- Add xcontrol-module-helper, a second root helper run through pkexec, which accepts only
  existing module and parameter names and plain values
- Add tests for the module helper

## 0.12.0 (2026-10-19)

**Add a Kernel modules tab to the System page**

- Split the System page into Overview and Kernel modules tabs
- Show the kernel command line and every loaded module with its size and the modules
  that use it, sortable by column
- Search modules by name, the devices they drive or their parameter names
- Select a module to see its description, file, version, license, dependencies,
  firmware count and the devices it drives (from modinfo)
- List each module parameter with its current value, type and description, marking
  those only root can read
- Show the options and blacklist lines for the module in /etc/modprobe.d and
  /usr/lib/modprobe.d
- Add "Include parts built into the kernel" to list built-in parts that have parameters
- Add a Copy button for a module's details
- Add tests for the kernel module code

## 0.11.2 (2026-10-19)

**Fix the dark preference being ignored by GTK 4.20 and later**

- Fix GTK 4.20+ apps ignoring Prefer dark: write gtk-interface-color-scheme to the GTK 4
  settings file when that GTK version is installed (older GTK 4 is left alone)
- Note that open GTK 4 apps switch between light and dark only when they restart
- Add tests for the new GTK 4 setting

## 0.11.1 (2026-10-19)

**Fix theme changes not reaching open apps with a custom xsettingsd config**

- Fix Apply not updating open apps when the running xsettingsd reads another config file
  (such as ~/.xsettingsd or one given with -c): XControl now writes the file it really uses

## 0.11.0 (2026-10-19)

**Add a System information page and move monitor info into Displays**

- Add a System page: distribution, kernel, uptime, packages, window manager, X server and
  driver, OpenGL, Mesa and Vulkan versions, processor, memory and swap
- Show each graphics card's model, maker, driver and video memory, plus load, clocks,
  temperature and power on amdgpu
- Show motherboard and BIOS, UEFI and Secure Boot, drives, disk space, network adapters,
  sound cards and server, and all temperature and fan sensors
- Refresh usage, clocks, temperatures and memory every 2 seconds while the page is open
- Add Copy (and Copy in English) for the system report, leaving out computer and user
  names, and xcontrol --sysinfo [--english] to print it in a terminal
- Remove the Monitor Info page: Details on the Displays page now opens the selected
  display's EDID information in its own window
- Detect a leftover ~/.config/gtk-3.0 or gtk-4.0 gtk.css in "Check an app…" and offer to
  turn it off by renaming it (and its assets link), deleting nothing
- Add tests for the system information code

## 0.10.1 (2026-10-19)

**Recognise Qt apps that already follow the GTK theme**

- Show that Qt apps already take colors, icons and font from the GTK settings when
  QT_QPA_PLATFORMTHEME is gtk or xdgdesktopportal, and stop offering to set qt5ct/qt6ct then

## 0.10.0 (2026-10-19)

**Add an Appearance page for themes, icons, cursor and fonts**

- Add an Appearance page to pick the GTK theme, icon theme, cursor theme and size,
  interface font, antialiasing, hinting, subpixel order and the dark preference
- Preview choices inside XControl, with Apply and Revert, and warn when a theme has
  no version for GTK 2, 3 or 4
- Write the choices to GTK 2/3/4 settings files, the default cursor theme, ~/.Xresources
  (merged with xrdb), GNOME settings, Xfce's xfconf, and qt5ct/qt6ct when installed
- Make open apps change without a restart by updating and reloading xsettingsd, or
  starting it and adding it to the login, or going through the desktop's settings daemon
- Add "Check an app…": click a window to see why it ignores the theme (GTK_THEME set,
  AppImage, Flatpak, Snap, libadwaita, missing theme version, Qt setup, another user)
- Offer one-click fixes: link themes into the home folder for AppImages, and copy the
  theme and grant read access for Flatpak apps
- Add --page appearance to open the panel on the Appearance page
- Add tests for the theme settings code

## 0.9.3 (2026-10-19)

**Stop the mouse wheel changing settings and keep the window responsive**

- Make the mouse wheel scroll the page instead of changing a dropdown, number field or
  slider under the pointer; number fields and sliders take the wheel only once clicked
- Fix the window freezing for seconds while a gaming mouse saves or changes settings:
  ratbagd calls now run in the background, with a "Talking to the mouse…" spinner
- Fix gaming mouse saves failing with a timeout on slow mice (wait up to 30 seconds)
- Show "Looking for gaming mice…" while the Gaming Mouse tab searches for devices
- Explain on Logitech mice that a steady LED has no brightness setting, and hide the
  brightness slider there; pick a darker color to dim it
- Fix a possible crash when changing an LED's mode rebuilt the controls too early

## 0.9.2 (2026-10-19)

**Let gaming mice switch to a chosen DPI stage after saving**

- Add an "After saving, use" choice next to Save to mouse: on mice with onboard profiles
  (most Logitech G mice) saving reloads the mouse, which then switches to this DPI stage
- Keep the "In use" DPI stage and the after-saving choice in step when either is changed
- Update the after-saving list when a DPI stage is enabled or disabled
- Explain in the hint that XControl can't see presses of the mouse's own DPI button

## 0.9.1 (2026-10-19)

**Add an Apply button for mouse and touchpad settings**

- Add an Apply button to the Mouse & Touchpad tab: changes are kept per device until
  you press it, so several devices can be changed before applying
- Make Reset to defaults only show the driver defaults in the controls; Apply uses them
  and forgets that device's saved settings, keeping any changes made after the reset
- Discard unapplied changes when pressing Refresh
- Report all settings that failed to apply in one message

## 0.9.0 (2026-10-19)

**Rename mesa-panel to XControl and add an Input page**

- Rename the program to XControl: commands xcontrol and xcontrol-run, config in
  ~/.config/xcontrol, XCONTROL_* environment variables, libxcontrol_gl.so shim
- Carry profiles, display settings and the login entry over from ~/.config/mesa-panel
  on first start
- Keep the old mesa-panel and mesa-panel-run commands and MESAPANEL_* variables working,
  so Steam launch options need no change; the package replaces mesa-panel
- Keep recognising EDID overrides installed under the old mesa-panel-*.bin name
- Add an Input page with Mouse & Touchpad, Keyboard and Gaming Mouse tabs
- Add per-device mouse and touchpad settings through xinput/libinput: flat or adaptive
  acceleration, pointer and scroll speed, natural scrolling, left-handed, middle click emulation
- Add touchpad settings: tap to click, tap and drag, drag lock, disable while typing,
  two-finger or edge scrolling, and bottom-corner or two-finger right click
- Add keyboard settings: layout and variant, a second layout and switch key, Caps Lock
  behaviour, Compose key, and key repeat delay and speed, with a test field
- Re-apply saved input settings at login and when a device is plugged in, through a
  background helper (xcontrol --watch-input) started from autostart
- Add gaming mouse settings through libratbag's ratbagd: DPI stages, polling rate, debounce,
  angle snapping, button remapping, LED effects and profiles, written with "Save to mouse"
- Add --page input to open the panel on the Input page
- Add tests for the input settings and ratbag code, with fake xinput and ratbagd services

## 0.8.0 (2026-10-19)

**Preview saturation and gamma live while dragging**

- Change the screen live while dragging the Saturation and Gamma sliders or pressing
  "Reset to defaults", before pressing Apply
- Put the previous colors back when leaving without Apply, reloading the page or closing
  the panel
- Show in the status bar that colors are being previewed, or why the preview failed

## 0.7.5 (2026-10-19)

**Let the window manager draw the title bar outside GNOME-style desktops**

- Use the window manager's own title bar on i3 and other tiling window managers, Xfce,
  KDE and similar desktops; keep the GTK header bar only on GNOME, Pantheon and Budgie
- Show status messages in a small bar at the bottom of the window when there is no
  header bar
- Add MESAPANEL_CSD=1 or 0 to force either title bar style

## 0.7.4 (2026-10-19)

**Show only the close button under tiling window managers**

- Show only the close button in the title bar under i3, bspwm, awesome, xmonad, dwm and
  other tiling window managers, where minimize and maximize do nothing
- Let users choose the title bar buttons with the MESAPANEL_DECORATION variable

## 0.7.3 (2026-10-19)

**Fix clearing the primary display**

- Fix unticking "Make this the primary display" having no effect: Apply now clears the
  primary display when none is chosen
- Grey out the primary display option when only one display is on, with a tooltip
  explaining what it does

## 0.7.2 (2026-10-19)

**Fix saturation and color settings with xrandr 1.5.3**

- Fix the saturation setting with xrandr 1.5.3 and later, which read and print the color
  matrix as nine decimals instead of raw words
- Fix the Scaling and color section getting stuck and ignoring changes when the driver
  reports a value in an unexpected form
- Leave the color matrix alone, instead of misreading it, when its format isn't understood
- Show an error message instead of failing silently when Apply can't build the xrandr
  command
- Add tests for the xrandr 1.5.3 color matrix format

## 0.7.1 (2026-10-19)

**Log xrandr commands when debugging is on**

- Print every xrandr command the panel runs, and its errors, to the terminal when
  MESAPANEL_DEBUG is set, to help diagnose display settings that fail to apply

## 0.7.0 (2026-10-18)

**Add scaling and color settings to the Displays page**

- Add a "Scaling and color" section for the selected display, showing only the settings
  the X driver offers for that output
- Add GPU scaling (display scales, stretch, center, keep aspect ratio) and underscan with
  adjustable borders for TVs that crop the edges
- Add output range (automatic, full 0-255, limited 16-235) and maximum color depth
- Add a saturation slider (0 to 200 %) through the display engine's color matrix, which
  also affects games, and warn when another program set a custom matrix
- Add a gamma slider, and never save uneven gamma left by night-light tools
- Add "Reset to defaults" for these settings
- Apply them with the usual 15-second revert, and restore non-default values with the
  saved layout after X restarts
- Add tests for the color matrix encoding and the generated xrandr arguments

## 0.6.0 (2026-10-18)

**Add FreeSync control and vkBasalt post-processing**

- Add a per-game FreeSync setting (application decides, always off, on for fullscreen
  games) through Mesa's adaptive_sync option
- Warn on the Gaming page when X has variable refresh disabled, with the xorg.conf line
  to add
- Show on the Monitor Info page whether variable refresh is enabled in X, read from the
  X server log
- Add a Post-Processing section with FXAA or SMAA edge smoothing and CAS sharpening
  through vkBasalt, for Vulkan games and Windows games through DXVK or VKD3D-Proton
- Grey out the post-processing options and explain why when vkBasalt isn't installed
- Add vkbasalt as an optional dependency and tests for the new launcher settings

## 0.5.1 (2026-10-18)

**Show EDID override status and keep settings across X driver switches**

- Show at the top of the System-wide mode list dialog whether the kernel is using the
  override, and if not, what is missing (kernel parameter, initramfs entry, rebuild, reboot)
- Point out when the kernel parameter names the wrong file or connector
- Move saved custom resolutions, "only my resolutions" choices and the saved layout to the
  new output names when switching between amdgpu/ati and modesetting X drivers
- Tell users who already set up an override to rebuild the initramfs after reinstalling it
- Add tests for the override status check and output name mapping

## 0.5.0 (2026-10-18)

**Initial version of Mesa Panel**

- Initial version: a Catalyst-style GTK control panel for Mesa drivers on X11
- Set global and per-game graphics overrides: anisotropic filtering, forced MSAA,
  transparency AA, VSync mode (incl. fast sync and adaptive) and a frame limiter
- Match profiles by Steam AppID or by program name; add installed Steam games or any
  program, and launch games through mesa-panel-run (e.g. as Steam launch options)
- Apply settings through a GL preload shim, an implicit Vulkan layer, Mesa driver
  variables and DXVK config; use WineD3D for Direct3D 8/9 games to force MSAA
- Arrange displays with xrandr: drag monitors, change resolution, refresh rate,
  rotation, primary display and on/off, with a 15-second confirm-or-revert
- Restore the display layout at login through an autostart entry
- Add custom resolutions (CVT, CVT-RB, CVT-RBv2, GTF, DMT or manual modeline) and
  optionally hide the modes from the display's EDID
- Build a corrected EDID listing only chosen modes, test it until reboot or install
  it permanently through a small root helper
- Show what each monitor reports on a Monitor Info page (panel, refresh range, VRR,
  HDR, gamut, connection) with copy and save-EDID options
- Include a Brazilian Portuguese translation
