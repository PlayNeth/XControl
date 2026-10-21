# Date & Language

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
