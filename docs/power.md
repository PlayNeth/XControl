# Power

The **Power** page has three tabs: Sleep & Buttons, Screen and Alerts.

## Sleep & Buttons

- **Sleep when idle** after 10 minutes to 3 hours, counted from the last mouse, keyboard or
  gamepad input. It never sleeps while something keeps the screen on ([Screen tab](#keep-the-screen-on)) or, if you
  want, while sound is playing. The screen lock locks first when it's on. **Sleep now** too.
- **Buttons**: what the power button, the sleep and hibernate keys and (on laptops) closing the
  lid do: shut down, sleep, hibernate, hybrid sleep, sleep then hibernate, lock, restart or
  nothing. Saved in `/etc/systemd/logind.conf.d/50-xcontrol.conf` through a small root helper
  (pkexec), and logind re-reads it right away (it's never restarted).
- **Power profile**: power saver, balanced or performance, when power-profiles-daemon (or
  tuned-ppd) runs.

## Screen

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

## Alerts

XControl can run [poweralertd](https://git.sr.ht/~kennylevinsen/poweralertd)
for the session: a notification when the battery starts
or stops charging, gets low or critical, or the charger is plugged in or out,
and the same for wireless devices with their own battery (mice, keyboards,
controllers, headsets, phones...), which you can pick by kind. Any notification
program shows them, and `poweralertd` works as the app name in the
[Notifications](notifications.md) page's per-app rules. The alerts themselves are poweralertd's, in English.

Start it from one place only: if poweralertd's own systemd user service is
enabled, or your i3 config runs it, every alert shows twice. The page (and the
session check) says so and can turn the service off.
