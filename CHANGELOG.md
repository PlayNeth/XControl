# Changelog

XControl was called mesa-panel up to 0.8.0. Versions before 0.5.0 weren't kept.

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
