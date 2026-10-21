# Power

- **Sleep when idle** after 10 minutes to 3 hours, counted from the last mouse, keyboard or
  gamepad input. It never sleeps while something keeps the screen on ([Desktop page](desktop.md#keep-the-screen-on)) or, if you
  want, while sound is playing. The screen lock locks first when it's on. **Sleep now** too.
- **Buttons**: what the power button, the sleep and hibernate keys and (on laptops) closing the
  lid do: shut down, sleep, hibernate, hybrid sleep, sleep then hibernate, lock, restart or
  nothing. Saved in `/etc/systemd/logind.conf.d/50-xcontrol.conf` through a small root helper
  (pkexec), and logind re-reads it right away (it's never restarted).
- **Power profile**: power saver, balanced or performance, when power-profiles-daemon (or
  tuned-ppd) runs.
