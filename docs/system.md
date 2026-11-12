# About & Tools

![The About & Tools page, Overview tab](images/system.png)

The **About & Tools** page shows the distribution, kernel, uptime, package count, window manager,
X server and X driver (from the server's log), OpenGL, Mesa and Vulkan versions, the
processor (cores, cache, clock, frequency driver and policy, microcode), memory and swap,
each graphics card (model and card maker, kernel driver, video memory, and on amdgpu its
load, clocks, temperature and power), motherboard and BIOS, UEFI and Secure Boot, drives,
disk space, network adapters, sound cards and sound server, and every temperature and fan
sensor. Usage, clocks, temperatures and memory refresh every 2 seconds while the page is
open. Everything is read from `/proc` and `/sys` without root; OpenGL and Vulkan details
need `glxinfo` (mesa-utils) and `vulkaninfo` (vulkan-tools), and device names come from
hwdata.

**Copy** puts it on the clipboard as text, leaving out your computer and user names (the arrow
has **Copy in English** for bug reports). `xcontrol --sysinfo` prints the same text in a
terminal (`--sysinfo --english` for English).

## Boot splash

About & Tools → **Boot splash** sets Plymouth's theme, the picture or animation shown while the
computer starts. Every installed theme is shown with a picture: XControl ships pictures of
Plymouth's ten built-in themes (made from Plymouth's own renderer, without a distribution
logo; see `data/plymouth/README`), and themes you add show their own `preview.png` if they
have one. **Preview** plays the selected theme for a few seconds in a window. That needs
Plymouth's X11 renderer (`/usr/lib/plymouth/renderers/x11.so`) and your password, because
Plymouth only runs as root; XControl refuses to start it unless your X display answers
first, so Plymouth never tries to take over the graphics card while X runs.

**Apply** writes `Theme=`, and the optional `ShowDelay=` (wait before showing it, so a fast
boot doesn't flash the splash) and `DeviceScale=` (for high-DPI screens), in the `[Daemon]`
section of `/etc/plymouth/plymouthd.conf`, keeping the rest of the file, then rebuilds the
initramfs, which the theme is copied into. This goes through `xcontrol-plymouth-helper`
(pkexec), which only accepts installed theme names and those two numbers.

The splash also needs two things in your own files, which XControl checks and shows the
exact line for, but doesn't edit:

- the `plymouth` hook in `HOOKS` in `/etc/mkinitcpio.conf`, after `systemd` (or `udev`) and
  `kms`, and before `sd-encrypt` / `encrypt` if the disk is encrypted. With Arch's default
  list that's `HOOKS=(base systemd autodetect microcode modconf kms plymouth keyboard
  sd-vconsole block filesystems fsck)`;
- `splash` (and `quiet`, which hides the kernel's messages) on the kernel command line: with
  systemd-boot, on the `options` line of your entry in `/boot/loader/entries/`; with a unified
  kernel image, in `/etc/kernel/cmdline`; with GRUB, in `GRUB_CMDLINE_LINUX_DEFAULT`.

## Kernel modules

The **Kernel modules** tab shows the kernel command line and every module that's loaded.
Search by module, device or parameter name; select one to see what it is (from `modinfo`), the
devices it drives, the modules that need it, each parameter with its current value and
description, and the `options`/`blacklist` lines about it in `/etc/modprobe.d` and
`/usr/lib/modprobe.d`. **Include parts built into the kernel** adds the built-in parts that
have parameters. A few parameters can only be read by root.

**Change…** next to a module's parameters sets values for every time the module loads. They're
saved in `/etc/modprobe.d/xcontrol-MODULE.conf` (XControl never edits other files there) by
`xcontrol-module-helper`, the second small root helper, run through pkexec like the EDID one.
It accepts only module and parameter names that exist and plain values (letters, digits and
`. , : + / - _`), and XControl checks each value against the parameter's type first. Leave a
field empty for the module's default; **Remove XControl's settings** deletes the file.

- **Also change it now** writes the value to `/sys/module/MODULE/parameters/` for the
  parameters the kernel allows changing while the module runs; the rest apply at the next load.
- **Rebuild the boot image** runs `mkinitcpio -P` (or dracut / update-initramfs). It's needed
  for modules that load from the initramfs, which carries its own copy of modprobe.d; XControl
  ticks it for modules listed in mkinitcpio's `MODULES` and for GPU drivers with the `kms` hook.
- Values set on the kernel command line (`amdgpu.ppfeaturemask=…`) win over modprobe.d; the
  dialog warns about those, and about other modprobe.d files setting the same parameter.
- Parts built into the kernel can't be set through modprobe.d; the page shows the command-line
  form instead.

## Session check and backups

About & Tools → **Check & Backup** looks at everything that quietly breaks other pages and offers a fix
where it can: whether `xcontrol --session` runs at login, whether the desktop service is up and
what keeps stopping, whether a **polkit agent** runs (on i3 nothing starts one, and then every
password prompt fails silently; it can start an installed agent and gives the line for your i3
config), extra bars, compositors, notification programs or locks running besides XControl's,
lines in your i3 config that start them twice, another night-light program, XSETTINGS for live
theme changes, notifications and sound.

**Save a backup…** writes one JSON file with all of XControl's settings plus the files it
writes that aren't regenerated from them (theme files, `mimeapps.list`, the terminal choice,
`locale.conf`, `~/.face`). **Restore a backup…** puts them back (keeping the current files as
`*.before-restore`; only those known files are ever written), applies them and restarts XControl.
