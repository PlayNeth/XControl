# Input

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
