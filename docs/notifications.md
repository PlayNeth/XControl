# Notifications

With **Use XControl's notifications (dunst)** on, XControl writes its own
`~/.config/xcontrol/dunstrc` and runs dunst for the session (restarting it when the settings
change); `~/.config/dunst/dunstrc` isn't used or changed. It writes the syntax of the installed
dunst (the `(x, y)` forms of 1.12 and later, `10x50` before). The settings are on three tabs:
**Look**, **Behavior** and **Per app**. Battery and power alerts are on the
[Power](power.md#alerts) page.

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
