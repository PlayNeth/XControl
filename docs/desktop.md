# Desktop

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

## Screen power

**Turn the screen off after** sets DPMS (`xset dpms 0 0 N`). **Leave as it is** doesn't touch it.

## Keep the screen on

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
`xcontrol --desktop-daemon --watch-input`. The Desktop page warns when nothing would start them.
