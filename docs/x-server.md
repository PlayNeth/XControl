# X server

The **X server** tab on the System page is the X counterpart of Kernel modules. It reads the
running server's log (`~/.local/share/xorg/Xorg.N.log` or `/var/log/Xorg.N.log`) for:

- which server runs (X.Org or XLibre) and its version;
- every module it loaded: video drivers (the one in use, and the ones it tried and let go),
  input drivers, extensions and others, with their files, versions and ABI classes, and the
  GPU (`/dev/dri/cardN`) each video driver drives;
- every option and where its value came from: a config file, or the default.

Options come from the manuals: the video driver's (`man 4 modesetting`, `man 4 amdgpu`, ...)
and xorg.conf's ServerFlags section (`man 5 xorg.conf`), read from the installed roff sources,
so you see exactly what your driver version documents (XLibre's modesetting has `TearFree`, on
by default, and `Atomic`, off). Options X used that the manual doesn't list (from a patched
or newer driver) are shown too, marked as such. Undocumented options can still be set by name. Changes go to
one file, `/etc/X11/xorg.conf.d/30-xcontrol.conf`, through a root helper
(`xcontrol-xorg-helper`, password asked) that accepts only plain option names and values:
driver options in an `OutputClass` section per kernel driver (`MatchDriver "amdgpu"`), which X
applies to whichever X driver runs that GPU without touching your own Device sections, and
server-wide ones in a `ServerFlags` section. `AutoAddDevices` and `AutoEnableDevices` aren't
offered (they can leave X without a keyboard and mouse).

**Choosing the video driver**: for each GPU, Automatic (what X picks by itself: a vendor
driver's package adds a rule for its GPUs, otherwise modesetting) or any installed X driver
that suits it (modesetting always; amdgpu, ati, intel, nouveau or nvidia for their own GPUs).
The tab lists the drivers the running server would find, in its own search order (XLibre:
`/usr/lib/xorg/modules/xlibre-25`, then `xlibre-25.0`, then the plain
`/usr/lib/xorg/modules`; X.Org: the plain folder), with the driver interface (video ABI)
version each was built for, read from the module's own version info. Only drivers built for
the server's ABI are offered (XLibre 25 takes 28; X.Org 21.1 takes 25), since the server won't
load the others; the tab says so for each one it skips. The choice is a Device section (with the
GPU's `BusID` only when there's more than one GPU: XLibre 25.1 has been seen crashing in its bus
probe with one on a single-GPU machine), in its own file, `/etc/X11/xorg.conf.d/00-xcontrol-driver.conf`: X uses the first
Device section it reads for its screen instead of guessing a driver. (A `Driver` line in an
OutputClass section can't do it: X reads `/usr/share/X11/xorg.conf.d` first, where the driver
packages' own classes, like `10-amdgpu.conf`, already name theirs, and the first named driver
that works wins.) After the next start the tab says whether X used XControl's Device section,
and warns about a Device section read before it or a Screen section that names its own Device.
The helper refuses a driver whose module isn't installed. When your config already has a Device section of its own,
XControl doesn't add one (X makes every Device section after the first an extra GPU device of
the screen): the tab names that section's file and its Driver line, which is what decides, and
shows the drivers to put there.

XLibre 25.1 (25.1.9 at least) crashes at start on an OutputClass section that has neither
`Driver`, `Modules` nor `ModulePath` (its bus probe reads the missing ModulePath; fixed in its
development code). XControl's options are exactly such a section, so on XLibre it adds an
empty `ModulePath ""`, which only keeps the standard module path. Each X driver keeps its own options: switching away remembers them and switching
back brings them back. The outputs get other names with the other driver (`DP-1` with
modesetting is `DisplayPort-0` with amdgpu); saved display settings move over (see [Switching X
drivers](displays.md#switching-x-drivers)).

They take effect the next time X starts. If X ever won't start, undo everything from a text
console: `sudo rm /etc/X11/xorg.conf.d/30-xcontrol.conf`. After each start, the tab (and the
session check) says which of XControl's options X ignored, and warns when they were chosen for
another X driver than the one now running. Options set in other files are listed too.
