# Users

The **Users** page lists the regular accounts (UID 1000 and up; never root or system
accounts) and changes them:

- **Full name**, **login name** (renaming moves `/home/OLD` to `/home/NEW`; not for the account
  you're logged in with, nor one with programs running), **password** (with a strength hint),
  **administrator** (the `wheel` group), **login shell** (from `/etc/shells`) and **picture**.
- **Groups**: the optional ones only, explained in plain words (`input` for sc-controller and
  gamepad tools, `uucp` for serial ports, `video`, `audio`, `storage`, `rfkill` and so on).
  They apply from the next login.
- **Add user…** (full name, login name suggested from it, password, administrator) and
  **Remove…** (keeping the home folder or deleting it).

Changes go through `xcontrol-user-helper`, the third small root helper, run with pkexec. It
only touches regular accounts, accepts only valid names (the full name can't contain `: , =`),
reads passwords from its standard input (never the command line), only manages the groups listed
above, and refuses to delete, rename or demote the account that's using XControl, so you can't
lock yourself out. Your own picture is also written to `~/.face`; login screens that use
AccountsService (LightDM, GDM, SDDM) get a copy in `/var/lib/AccountsService`.

XControl's root helpers come with a polkit policy (`io.github.xcontrol.policy`): after you type your
password once, further changes don't ask again for a few minutes. On i3 a polkit agent has to
be running for the password prompt, e.g. `exec --no-startup-id /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1`.
