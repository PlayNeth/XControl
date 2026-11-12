# Wallpaper & Lock

## Wallpaper

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

## Screen lock

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

## At login

`xcontrol --desktop-daemon` sets the wallpaper, applies blanking, runs xss-lock (restarting it
if it dies) and redraws the wallpaper when displays change. It's added to
`~/.config/autostart`, but i3 doesn't run that folder by itself, so add one line to your i3
config instead (or use `dex`):

    exec --no-startup-id xcontrol --session

`--session` starts everything XControl uses at login, each part only when its settings are in
use: it restores the display layout, starts xsettingsd for live theme updates, starts the
input watcher (mouse, touchpad and keyboard settings, re-applied on hotplug) and runs the desktop
service. Single flags still work and can be combined, e.g.
`xcontrol --desktop-daemon --watch-input`. The Wallpaper & Lock page warns when nothing would start them.
