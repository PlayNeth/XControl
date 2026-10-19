"""The Appearance page: GTK theme, icons, cursor, fonts, dark preference, Qt, and a
checker for apps that ignore the theme."""
import shutil
import threading
import traceback

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import appcheck, theming as T  # noqa: E402
from .i18n import N_, _  # noqa: E402

PREVIEW_ICONS = ["folder", "user-home", "text-x-generic", "image-x-generic", "audio-x-generic",
                 "utilities-terminal", "web-browser", "preferences-system", "edit-copy", "document-save",
                 "user-trash", "dialog-information"]
HINT_LABELS = {"hintnone": N_("None"), "hintslight": N_("Slight (recommended)"), "hintmedium": N_("Medium"),
               "hintfull": N_("Full (sharpest, changes letter shapes)")}
SUBPIXEL_LABELS = {"none": N_("Off (grayscale; for CRTs, projectors, rotated screens)"),
                   "rgb": N_("RGB (most LCD monitors)"), "bgr": N_("BGR"),
                   "vrgb": N_("Vertical RGB"), "vbgr": N_("Vertical BGR")}
KIT_NAMES = {"gtk2": "GTK 2", "gtk3": "GTK 3", "gtk4": "GTK 4"}

FINDINGS = {
    "gone": N_("The app has closed."),
    "other-user": N_("It runs as another user (user id {detail}), for example through sudo, so it reads that "
                     "user's theme settings, not yours. Run graphical apps as yourself."),
    "gtk-theme-env": N_("Its environment sets GTK_THEME={detail}, which overrides every theme setting. Remove "
                        "GTK_THEME from wherever it's set (~/.profile, ~/.xprofile, /etc/environment or the app's "
                        "launcher)."),
    "flatpak": N_("It's a Flatpak app. Flatpak apps can't see the themes installed on your system, only themes in "
                  "your home folder, and only when they're allowed to read them."),
    "snap": N_("It's a Snap app. Snaps only use themes packaged as snaps (e.g. gtk-common-themes); system themes "
               "don't reach them."),
    "appimage": N_("It's an AppImage. AppImages bring their own GTK, which often doesn't look in /usr/share/themes, "
                   "but always looks in your home folder."),
    "libadwaita": N_("It uses libadwaita (most new GNOME apps). libadwaita ignores GTK themes on purpose and only "
                     "follows the dark preference."),
    "theme-no-gtk4": N_("It's a GTK 4 app, and the theme {detail} has no GTK 4 version."),
    "theme-no-gtk2": N_("It's a GTK 2 app, and the theme {detail} has no GTK 2 version."),
    "theme-no-gtk3": N_("It's a GTK 3 app, and the theme {detail} has no GTK 3 version."),
    "qt-no-platformtheme": N_("It's a Qt app. Qt apps only follow these settings through qt5ct/qt6ct, which needs "
                              "QT_QPA_PLATFORMTHEME=qt5ct (or qt6ct) in your session environment, e.g. in "
                              "~/.xprofile, and a new login."),
    "own-toolkit": N_("It doesn't use GTK or Qt (games, Java, Tk, Electron and similar draw their own interface), "
                      "so desktop themes don't apply to it."),
    "user-css": N_("{detail} exists. GTK loads it on top of every theme, so whatever it styles wins. Theme "
                   "installers (their \"libadwaita\" or \"GTK 4\" option) and style editors leave it there."),
    "no-live-updates": N_("Nothing tells running apps about theme changes (no XSETTINGS manager). Apply once here "
                          "so XControl starts one; until then, restart the app after a change."),
    "restart": N_("Nothing blocks the theme. If it still looks wrong, restart the app once: it may have been "
                  "started before live updates were set up."),
}
FIXES = {
    "link-home": N_("Link the themes into my home folder"),
    "flatpak": N_("Copy the theme to my home folder and let Flatpak apps read it"),
    "user-css": N_("Turn the override off (renames it, nothing is deleted)"),
}


def _hint(text):
    lbl = Gtk.Label(label=text, xalign=0, wrap=True)
    lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.set_max_width_chars(70)
    lbl.get_style_context().add_class("dim-label")
    return lbl


def _section(title):
    frame = Gtk.Frame()
    head = Gtk.Label(xalign=0)
    head.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
    frame.set_label_widget(head)
    frame.set_shadow_type(Gtk.ShadowType.NONE)
    grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_start=12, margin_top=8, margin_bottom=4)
    frame.add(grid)
    return frame, grid


class AppearancePage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.settings = Gtk.Settings.get_default()
        self.loading = False
        self.labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        self.applied = T.current(self.settings)     # what Revert goes back to
        self.look = T.Look(**vars(self.applied))

        # ---- style
        frame, g = _section(_("Style"))
        self.theme = Gtk.ComboBoxText(hexpand=True)
        self.theme.connect("changed", self._changed)
        self.dark = Gtk.CheckButton(label=_("Prefer dark (apps that offer a dark variant, libadwaita apps too)"))
        self.dark.connect("toggled", self._changed)
        self.theme_note = _hint("")
        self.theme_note.set_no_show_all(True)
        self._rows(g, [(_("Theme"), self.theme), ("", self.dark), ("", self.theme_note)])
        self.pack_start(frame, False, False, 0)

        # ---- icons
        frame, g = _section(_("Icons"))
        self.icons = Gtk.ComboBoxText(hexpand=True)
        self.icons.connect("changed", self._changed)
        preview = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12,
                              column_spacing=6, row_spacing=6)
        for name in PREVIEW_ICONS:
            img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.DND)
            img.set_pixel_size(32)
            preview.add(img)
        self._rows(g, [(_("Icon theme"), self.icons), ("", preview)])
        self.pack_start(frame, False, False, 0)

        # ---- cursor
        frame, g = _section(_("Cursor"))
        self.cursor = Gtk.ComboBoxText(hexpand=True)
        self.cursor.connect("changed", self._changed)
        self.cursor_size = Gtk.ComboBoxText()
        for s in T.CURSOR_SIZES:
            self.cursor_size.append(str(s), _("{px} px").format(px=s))
        self.cursor_size.connect("changed", self._changed)
        box = Gtk.Box(spacing=8)
        box.pack_start(self.cursor, True, True, 0)
        box.pack_start(Gtk.Label(label=_("Size")), False, False, 0)
        box.pack_start(self.cursor_size, False, False, 0)
        self._rows(g, [(_("Cursor theme"), box),
                       ("", _hint(_("i3 and other window managers load the cursor when they start; restart them "
                                    "(i3: Mod+Shift+R) to see it on the desktop and window borders.")))])
        self.pack_start(frame, False, False, 0)

        # ---- fonts
        frame, g = _section(_("Fonts"))
        self.font = Gtk.FontButton(hexpand=True)
        self.font.set_use_font(True)
        self.font.connect("font-set", self._changed)
        self.antialias = Gtk.CheckButton(label=_("Smooth edges (antialiasing)"))
        self.antialias.connect("toggled", self._changed)
        self.hint = Gtk.ComboBoxText(hexpand=True)
        for k in T.HINT_STYLES:
            self.hint.append(k, _(HINT_LABELS[k]))
        self.hint.connect("changed", self._changed)
        self.rgba = Gtk.ComboBoxText(hexpand=True)
        for k in T.SUBPIXEL:
            self.rgba.append(k, _(SUBPIXEL_LABELS[k]))
        self.rgba.connect("changed", self._changed)
        self._rows(g, [(_("Interface font"), self.font), ("", self.antialias),
                       (_("Hinting"), self.hint), (_("Subpixel order"), self.rgba)])
        self.pack_start(frame, False, False, 0)

        # ---- Qt
        self.qt_tools, qt_env = T.qt_tools()
        self.qt_check = Gtk.CheckButton(label=_("Also set the icon theme and font for Qt apps (qt5ct/qt6ct)"))
        follows_gtk = qt_env.startswith(("gtk", "xdgdesktopportal"))
        self.qt_check.set_active(bool(self.qt_tools) and not follows_gtk)
        if follows_gtk:
            frame, g = _section(_("Qt applications"))
            self._rows(g, [("", _hint(_("Qt apps take their colors, icons and font from the GTK settings above, "
                                        "because QT_QPA_PLATFORMTHEME={value}. Nothing else is needed.")
                                      .format(value=qt_env)))])
            self.pack_start(frame, False, False, 0)
        elif self.qt_tools:
            frame, g = _section(_("Qt applications"))
            note = (_("Qt apps follow this because QT_QPA_PLATFORMTHEME={value}.").format(value=qt_env)
                    if qt_env.startswith(("qt5ct", "qt6ct")) else
                    _("Qt apps only use these settings when QT_QPA_PLATFORMTHEME=qt5ct (or qt6ct) is set in your "
                      "session, e.g. in ~/.xprofile. It isn't set now."))
            self._rows(g, [("", self.qt_check), ("", _hint(note))])
            self.pack_start(frame, False, False, 0)

        # ---- live updates and buttons
        self.live = _hint("")
        self.pack_start(self.live, False, False, 0)
        bar = Gtk.Box(spacing=6)
        self.revert_btn = Gtk.Button(label=_("Revert"))
        self.revert_btn.connect("clicked", self._revert)
        bar.pack_start(self.revert_btn, False, False, 0)
        self.apply_btn = Gtk.Button(label=_("Apply"))
        self.apply_btn.get_style_context().add_class("suggested-action")
        self.apply_btn.connect("clicked", self._apply)
        bar.pack_end(self.apply_btn, False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.pack_start(_hint(_("Changes are previewed in this window. Apply sets them for GTK 2, 3 and 4, X "
                                "cursors, libadwaita's dark preference and Qt, and updates open apps.")),
                        False, False, 0)

        # ---- troubleshooting
        frame, g = _section(_("An app ignores the theme?"))
        self.check_btn = Gtk.Button(label=_("Check an app…"), halign=Gtk.Align.START)
        self.check_btn.connect("clicked", self._check_app)
        self._rows(g, [("", self.check_btn),
                       ("", _hint(_("Click the button, then click the app's window. XControl looks at how the app "
                                    "runs and tells you why it doesn't follow the theme.")))])
        self.pack_start(frame, False, False, 0)

        self._fill()

    def _rows(self, g, rows):
        for i, (label, w) in enumerate(rows):
            lbl = Gtk.Label(label=label, xalign=0)
            self.labels.add_widget(lbl)
            g.attach(lbl, 0, i, 1, 1)
            g.attach(w, 1, i, 1, 1)

    # ---- model -> view
    def _fill(self):
        self.loading = True
        try:
            look = self.look
            self.themes = T.gtk_themes()
            self.theme.remove_all()
            for t in self.themes:
                kits = ", ".join(KIT_NAMES[k] for k in ("gtk2", "gtk3", "gtk4") if k in t.toolkits)
                self.theme.append(t.name, f"{t.title}  ({kits})")
            if not self.theme.set_active_id(look.gtk_theme):
                self.theme.append(look.gtk_theme, look.gtk_theme)
                self.theme.set_active_id(look.gtk_theme)
            self.dark.set_active(look.prefer_dark)
            self.icons.remove_all()
            for t in T.icon_themes():
                self.icons.append(t.name, t.title)
            if not self.icons.set_active_id(look.icon_theme):
                self.icons.append(look.icon_theme, look.icon_theme)
                self.icons.set_active_id(look.icon_theme)
            self.cursor.remove_all()
            for t in T.cursor_themes():
                self.cursor.append(t.name, t.title)
            if look.cursor_theme and not self.cursor.set_active_id(look.cursor_theme):
                self.cursor.append(look.cursor_theme, look.cursor_theme)
                self.cursor.set_active_id(look.cursor_theme)
            if not self.cursor_size.set_active_id(str(look.cursor_size)):
                self.cursor_size.append(str(look.cursor_size), _("{px} px").format(px=look.cursor_size))
                self.cursor_size.set_active_id(str(look.cursor_size))
            self.font.set_font(look.font)
            self.antialias.set_active(look.antialias)
            self.hint.set_active_id(look.hint_style if look.hinting else "hintnone")
            self.rgba.set_active_id(look.subpixel)
            self.rgba.set_sensitive(look.antialias)
            self._theme_note()
            self._live_note()
        finally:
            self.loading = False

    def _theme_note(self):
        t = next((t for t in self.themes if t.name == self.look.gtk_theme), None)
        if t is None:
            text = _("This theme isn't in any theme folder (it may be built into a program), so other apps "
                     "probably can't find it. Pick one from the list.")
        else:
            missing = [KIT_NAMES[k] for k in ("gtk2", "gtk3", "gtk4") if k not in t.toolkits]
            text = (_("This theme has no version for {kits}; apps using those keep their default look.")
                    .format(kits=", ".join(missing)) if missing else "")
        self.theme_note.set_text(text)
        self.theme_note.set_visible(bool(text))

    def _live_note(self):
        kind, _pid = T.xsettings_manager()
        if kind == "xsettingsd":
            text = _("Open apps update right away (xsettingsd is running).")
        elif kind in ("gnome", "mate", "xfce"):
            text = _("Open apps update right away through your desktop's settings service.")
        elif kind == "other":
            text = _("Another program manages live settings; open apps may only update after a restart.")
        elif shutil.which("xsettingsd"):
            text = _("Apply starts xsettingsd (and adds it to your login), so open apps update right away.")
        else:
            text = _("Install xsettingsd so open apps update right away; until then they pick up changes when "
                     "they restart.")
        self.live.set_text(text)

    # ---- view -> look (previewed in this window)
    def _changed(self, *_args):
        if self.loading:
            return
        look = self.look
        look.gtk_theme = self.theme.get_active_id() or look.gtk_theme
        look.prefer_dark = self.dark.get_active()
        look.icon_theme = self.icons.get_active_id() or look.icon_theme
        look.cursor_theme = self.cursor.get_active_id() or look.cursor_theme
        look.cursor_size = int(self.cursor_size.get_active_id() or look.cursor_size)
        look.font = self.font.get_font() or look.font
        look.antialias = self.antialias.get_active()
        hint = self.hint.get_active_id() or "hintslight"
        look.hinting = hint != "hintnone"
        look.hint_style = hint
        look.subpixel = self.rgba.get_active_id() or "none"
        self.rgba.set_sensitive(look.antialias)
        self._preview(look)
        self._theme_note()
        self.window.set_status(_("Previewing here; press Apply to use it everywhere"))

    def _preview(self, look):
        p = self.settings.props
        p.gtk_theme_name = look.gtk_theme
        p.gtk_application_prefer_dark_theme = look.prefer_dark
        p.gtk_icon_theme_name = look.icon_theme
        if look.cursor_theme:
            p.gtk_cursor_theme_name = look.cursor_theme
            p.gtk_cursor_theme_size = look.cursor_size
        p.gtk_font_name = look.font
        p.gtk_xft_antialias = 1 if look.antialias else 0
        p.gtk_xft_hinting = 1 if look.hinting else 0
        p.gtk_xft_hintstyle = look.hint_style
        p.gtk_xft_rgba = look.subpixel

    def _revert(self, *_args):
        self.look = T.Look(**vars(self.applied))
        self._preview(self.look)
        self._fill()
        self.window.set_status(_("Back to the current settings"))

    def _apply(self, *_args):
        try:
            notes = T.apply(self.look, qt=self.qt_check.get_active())
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.window.message(_("Could not apply the appearance settings"), str(e))
            return
        self.applied = T.Look(**vars(self.look))
        self._live_note()
        if "live" in notes or "started" in notes:
            self.window.set_status(_("Applied; open apps are updating"))
        else:
            self.window.set_status(_("Applied; open apps update when they restart"))

    # ---- troubleshooting
    def _check_app(self, *_args):
        self.check_btn.set_sensitive(False)
        self.check_btn.set_label(_("Click the app's window…"))

        def work():
            pid, info = appcheck.pick_window()
            report = None
            if pid:
                kind, _p = T.xsettings_manager()
                report = appcheck.analyze(pid, info, self.applied, kind)
            GLib.idle_add(self._show_report, pid, info, report)
        threading.Thread(target=work, daemon=True).start()

    def _show_report(self, pid, info, report):
        self.check_btn.set_sensitive(True)
        self.check_btn.set_label(_("Check an app…"))
        if not pid:
            reason = {"no-xprop": _("xprop is needed for this (package xorg-xprop)."),
                      "no-pid": _("That window doesn't say which program it belongs to."),
                      "timeout": _("No window was clicked.")}.get(info, info)
            self.window.message(_("Couldn't check the app"), reason)
            return False
        dlg = Gtk.Dialog(title=_("Why {app} looks different").format(app=report.name or pid),
                         transient_for=self.window, modal=True)
        dlg.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        box = dlg.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)
        kits = ", ".join(report.toolkits) or _("none found")
        head = Gtk.Label(xalign=0)
        head.set_markup("<b>{}</b>\n{}".format(
            GLib.markup_escape_text(report.name or str(pid)),
            GLib.markup_escape_text(_("Toolkit: {kits}").format(kits=kits) +
                                    (f" · {report.packaging}" if report.packaging else ""))))
        box.pack_start(head, False, False, 0)
        for code, detail in report.findings:
            lbl = Gtk.Label(label="• " + _(FINDINGS[code]).format(detail=detail), xalign=0, wrap=True)
            lbl.set_max_width_chars(70)
            box.pack_start(lbl, False, False, 0)
        for fix in report.fixes:
            b = Gtk.Button(label=_(FIXES[fix]), halign=Gtk.Align.START)
            b.connect("clicked", self._run_fix, fix, dlg)
            box.pack_start(b, False, False, 0)
        dlg.show_all()
        dlg.run()
        dlg.destroy()
        return False

    def _run_fix(self, button, fix, dlg):
        try:
            if fix == "user-css":
                done = appcheck.disable_user_css()
                msg = _("Renamed: {items}. Restart the app.").format(items=", ".join(done)) if done else \
                    _("There was nothing to turn off.")
            elif fix == "link-home":
                done = appcheck.link_into_home(self.applied)
                msg = (_("Linked into your home folder: {items}. Restart the app.").format(
                       items=", ".join(done)) if done else _("The themes are already in your home folder."))
            else:
                appcheck.flatpak_fix(self.applied)
                msg = _("Done. Restart the app.")
            button.set_sensitive(False)
            self.window.set_status(msg)
            dlg.get_content_area().pack_start(_hint(msg), False, False, 0)
            dlg.show_all()
        except Exception as e:  # noqa: BLE001
            self.window.message(_("That didn't work"), str(e))
