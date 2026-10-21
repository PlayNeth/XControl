# Window Manager (i3)

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
