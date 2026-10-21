# Appearance

One place to pick the GTK theme, icon theme, cursor (theme and size), interface font
(antialiasing, hinting, subpixel order), the dark preference, and **sounds and effects**:
event sounds (the alert/error "bell" sounds apps play), click and key feedback sounds, and
animations (the fades and slides in menus, popovers, switches and tabs). Choices preview inside
XControl; **Apply** writes them everywhere an X11 program looks:

- `~/.config/gtk-3.0/settings.ini`, `~/.config/gtk-4.0/settings.ini` and `~/.gtkrc-2.0`
  (other settings in those files are kept)
- `~/.icons/default/index.theme` and `Xcursor.*`/`Xft.*` in `~/.Xresources` (merged with
  `xrdb`) for the cursor and fonts of plain X programs; the root window cursor is set too
- GNOME's `org.gnome.desktop.interface` (including `color-scheme`, which libadwaita apps
  follow), Xfce's xfconf when present, and qt5ct/qt6ct when installed
- the XSETTINGS manager, which is what makes **open apps change without a restart**. On X,
  GTK apps read `settings.ini` only when they start, and ignore it altogether while an
  XSETTINGS manager runs. That is the usual reason a theme tool "doesn't apply": a leftover
  `xsettingsd` keeps announcing the old theme. XControl updates `xsettingsd`'s config and
  reloads it, or starts it (and adds it to your login) if none is running. With GNOME, MATE
  or Xfce's own settings daemon, it goes through those instead.

GTK 4.20 and later choose a theme's dark variant only from `gtk-interface-color-scheme`, which
on X11 comes from nothing but `~/.config/gtk-4.0/settings.ini` (there's no XSETTINGS key for
it, and the old `gtk-application-prefer-dark-theme` there no longer counts). XControl writes it
when that GTK 4 is installed; GTK 4 apps pick up a light/dark change when they restart.

Sounds and animations go through the same places (`gtk-enable-event-sounds`,
`gtk-enable-input-feedback-sounds`, `gtk-enable-animations`; `Net/EnableEventSounds`,
`Net/EnableInputFeedbackSounds`, `Gtk/EnableAnimations` over XSETTINGS; GNOME's
`enable-animations`, `event-sounds` and `input-feedback-sounds`), so open apps follow right away.
Windows fading as they open and close is picom's, on the [Bar & Compositor](bar-and-compositor.md) page.

On i3 and similar window managers, restart the window manager (i3: Mod+Shift+R) to get the new
cursor on the desktop and window borders.

## An app ignores the theme?

**Check an app…** lets you click the app's window and inspects that process: the toolkit it
really loads, how it's packaged, its environment and the user it runs as. Usual causes:

- `GTK_THEME` set in its environment (overrides everything)
- an **AppImage** whose bundled GTK doesn't search `/usr/share/themes`: one click links the
  theme into `~/.local/share/themes`, where every GTK looks
- **Flatpak**: copies the theme to your home folder and grants Flatpak apps read access
- **libadwaita** apps: they only follow the dark preference, by design
- the theme has no version for the app's GTK (e.g. a GTK 3 theme and a GTK 4 app)
- Qt apps without `QT_QPA_PLATFORMTHEME=qt5ct` (or `qt6ct`) in the session environment
- a leftover `~/.config/gtk-4.0/gtk.css` (or `gtk-3.0/gtk.css`): GTK loads it on top of every
  theme. Theme installers with a "libadwaita"/"GTK 4" option and style editors leave one behind;
  one click renames it (and the `assets` link next to it) so nothing is lost
- the app runs as another user (sudo), or draws its own interface
