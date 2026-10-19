"""The Desktop page: wallpaper, screen lock and screen power."""
import shutil

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import desktop as D, wallpaper as W  # noqa: E402
from .i18n import N_, _  # noqa: E402

MODE_LABELS = {"fill": N_("Fill (crop to cover the display)"), "fit": N_("Fit (whole picture, borders in the color)"),
               "center": N_("Center (original size)"), "tile": N_("Tile"), "stretch": N_("Stretch (distort)")}
LAYOUT_LABELS = {"same": N_("Same picture on every display"), "span": N_("One picture across all displays"),
                 "separate": N_("A different picture per display")}
LOCKER_LABELS = {"i3lock": "i3lock", "xsecurelock": N_("xsecurelock (most robust)"), "slock": "slock"}
IDLE_CHOICES = [0, 1, 2, 3, 5, 10, 15, 20, 30, 45, 60]
OFF_CHOICES = [0, 1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 90, 120]
PREVIEW_W = 420


def _hint(text, markup=False):
    lbl = Gtk.Label(xalign=0, wrap=True)
    lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.set_max_width_chars(80)
    if markup:
        lbl.set_markup(text)
    else:
        lbl.set_text(text)
    lbl.get_style_context().add_class("dim-label")
    return lbl


def _rgba(text):
    c = Gdk.RGBA()
    c.parse(text or "#000000")
    return c


def _hex(rgba):
    return "#{:02x}{:02x}{:02x}".format(*(round(v * 255) for v in (rgba.red, rgba.green, rgba.blue)))


def _minutes(n):
    return _("Never") if n == 0 else (_("{n} minute") if n == 1 else _("{n} minutes")).format(n=n)


class DesktopPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.desk = D.load()
        self.loading = True
        self._timer = None
        self.preview_surface = None
        self.labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        self.autostart_bar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        self.autostart_bar.get_content_area().add(_hint(
            _("i3 doesn't run <tt>~/.config/autostart</tt> by itself, so after the next login nothing would set "
              "the wallpaper or start the screen lock. Add this line to your i3 config:\n"
              "<tt>exec --no-startup-id xcontrol --desktop-daemon</tt>"), markup=True))
        self.autostart_bar.set_no_show_all(True)
        self.pack_start(self.autostart_bar, False, False, 0)

        self._build_wallpaper()
        self._build_lock()
        self._build_power()
        self.connect("map", lambda *_a: (self._sensitivity(), self._refresh_status()))  # after show_all
        self._fill()
        self.loading = False

    # ---------------------------------------------------------------- layout helpers
    def _section(self, title, switch=None):
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        head = Gtk.Box(spacing=10)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        head.pack_start(lbl, False, False, 0)
        if switch:
            head.pack_start(switch, False, False, 0)
        frame.set_label_widget(head)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_start=12, margin_top=8, margin_bottom=4)
        frame.add(grid)
        self.pack_start(frame, False, False, 0)
        return grid

    def _row(self, grid, r, label, widget):
        lbl = Gtk.Label(label=label, xalign=0)
        self.labels.add_widget(lbl)
        grid.attach(lbl, 0, r, 1, 1)
        grid.attach(widget, 1, r, 1, 1)
        return lbl

    # ---------------------------------------------------------------- wallpaper
    def _build_wallpaper(self):
        self.wp_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.wp_switch.set_tooltip_text(_("Let XControl set the desktop background (instead of feh or nitrogen)"))
        self.wp_switch.connect("notify::active", self._changed)
        g = self._section(_("Wallpaper"), self.wp_switch)
        self.wp_grid = g

        self.preview = Gtk.DrawingArea(halign=Gtk.Align.START)
        self.preview.connect("draw", self._draw_preview)
        g.attach(self.preview, 1, 0, 1, 1)

        self.layout = Gtk.ComboBoxText(hexpand=True)
        for k in W.LAYOUTS:
            self.layout.append(k, _(LAYOUT_LABELS[k]))
        self.layout.connect("changed", self._layout_changed)
        self._row(g, 1, _("Layout"), self.layout)

        self.which = Gtk.ComboBoxText(hexpand=True)
        self.which.connect("changed", self._which_changed)
        self.which_label = self._row(g, 2, _("Display"), self.which)

        pick = Gtk.Box(spacing=6)
        self.file = Gtk.FileChooserButton(title=_("Choose a picture"), action=Gtk.FileChooserAction.OPEN,
                                          hexpand=True)
        flt = Gtk.FileFilter()
        flt.set_name(_("Pictures"))
        flt.add_pixbuf_formats()
        self.file.add_filter(flt)
        self.file.connect("file-set", self._changed)
        pick.pack_start(self.file, True, True, 0)
        clear = Gtk.Button.new_from_icon_name("edit-clear-symbolic", Gtk.IconSize.BUTTON)
        clear.set_tooltip_text(_("No picture, only the color"))
        clear.connect("clicked", self._clear_picture)
        pick.pack_start(clear, False, False, 0)
        self._row(g, 3, _("Picture"), pick)

        self.mode = Gtk.ComboBoxText(hexpand=True)
        for k in W.MODES:
            self.mode.append(k, _(MODE_LABELS[k]))
        self.mode.connect("changed", self._changed)
        self._row(g, 4, _("Placement"), self.mode)

        self.color = Gtk.ColorButton(halign=Gtk.Align.START)
        self.color.set_use_alpha(False)
        self.color.connect("color-set", self._changed)
        self._row(g, 5, _("Background color"), self.color)

        self.wp_conflict = _hint("")
        self.wp_conflict.set_no_show_all(True)
        g.attach(self.wp_conflict, 1, 6, 1, 1)

    # ---------------------------------------------------------------- lock
    def _build_lock(self):
        self.lock_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.lock_switch.connect("notify::active", self._changed)
        g = self._section(_("Screen lock"), self.lock_switch)

        self.locker = Gtk.ComboBoxText(hexpand=True)
        self.locker.connect("changed", self._changed)
        self._row(g, 0, _("Locker"), self.locker)
        self.locker_note = _hint("")
        self.locker_note.set_no_show_all(True)
        g.attach(self.locker_note, 1, 1, 1, 1)

        self.idle = Gtk.ComboBoxText(hexpand=True)
        for n in IDLE_CHOICES:
            self.idle.append(str(n), _minutes(n))
        self.idle.connect("changed", self._changed)
        self._row(g, 2, _("Lock after being idle for"), self.idle)

        self.on_sleep = Gtk.CheckButton(label=_("Lock before suspend and hibernate"))
        self.on_sleep.connect("toggled", self._changed)
        g.attach(self.on_sleep, 1, 3, 1, 1)

        img = Gtk.Box(spacing=8)
        self.lock_image = Gtk.ComboBoxText()
        self.lock_image.append("wallpaper", _("The wallpaper"))
        self.lock_image.append("color", _("A plain color"))
        self.lock_image.connect("changed", self._changed)
        img.pack_start(self.lock_image, False, False, 0)
        self.lock_color = Gtk.ColorButton()
        self.lock_color.set_use_alpha(False)
        self.lock_color.connect("color-set", self._changed)
        img.pack_start(self.lock_color, False, False, 0)
        self.image_label = self._row(g, 4, _("Lock screen shows"), img)
        self.lock_image_box = img
        self.show_failed = Gtk.CheckButton(label=_("Show the number of failed attempts"))
        self.show_failed.connect("toggled", self._changed)
        g.attach(self.show_failed, 1, 5, 1, 1)

        bar = Gtk.Box(spacing=8)
        self.lock_now = Gtk.Button(label=_("Lock now"))
        self.lock_now.connect("clicked", self._lock_now)
        bar.pack_start(self.lock_now, False, False, 0)
        self.lock_status = _hint("")
        bar.pack_start(self.lock_status, True, True, 0)
        g.attach(bar, 1, 6, 1, 1)
        g.attach(_hint(_("To lock with a key, add to your i3 config:") +
                       "\n<tt>bindsym $mod+Shift+x exec --no-startup-id xcontrol --lock</tt>", markup=True), 1, 7, 1, 1)
        self.lock_conflict = _hint("")
        self.lock_conflict.set_no_show_all(True)
        g.attach(self.lock_conflict, 1, 8, 1, 1)

    # ---------------------------------------------------------------- power
    def _build_power(self):
        g = self._section(_("Screen power"))
        self.screen_off = Gtk.ComboBoxText(hexpand=True)
        self.screen_off.append("default", _("Leave as it is"))
        for n in OFF_CHOICES:
            self.screen_off.append(str(n), _minutes(n))
        self.screen_off.connect("changed", self._changed)
        self._row(g, 0, _("Turn the screen off after"), self.screen_off)
        g.attach(_hint(_("Counted from the last time you used the mouse or keyboard. On a CRT this also saves the "
                         "tube.")), 1, 1, 1, 1)

    # ---------------------------------------------------------------- model -> view
    def _monitors(self):
        try:
            self.screen = W.screen_size()
        except Exception:  # noqa: BLE001
            self.screen = (1920, 1080)
        self.mons = W.monitors()

    def _fill(self):
        self._monitors()
        wp, lock, blank = self.desk["wallpaper"], self.desk["lock"], self.desk["blanking"]
        self.wp_switch.set_active(wp["enabled"])
        self.layout.set_active_id(wp["layout"])
        self.which.remove_all()
        for name, *_rest in self.mons:
            self.which.append(name, name)
        self.which.set_active(0)
        self._show_picture()
        self.color.set_rgba(_rgba(wp["color"]))

        installed = D.installed_lockers()
        self.locker.remove_all()
        for k in D.LOCKERS:
            if k in installed or k == lock["locker"]:
                self.locker.append(k, _(LOCKER_LABELS[k]) + ("" if k in installed else " " + _("(not installed)")))
        self.locker.set_active_id(lock["locker"])
        self.lock_switch.set_active(lock["enabled"])
        if not self.idle.set_active_id(str(lock["idle_minutes"])):
            self.idle.append(str(lock["idle_minutes"]), _minutes(lock["idle_minutes"]))
            self.idle.set_active_id(str(lock["idle_minutes"]))
        self.on_sleep.set_active(lock["lock_on_sleep"])
        self.lock_image.set_active_id(lock["image"])
        self.lock_color.set_rgba(_rgba(lock["color"]))
        self.show_failed.set_active(lock["show_failed"])

        off = str(blank["screen_off_minutes"]) if blank["managed"] else "default"
        if not self.screen_off.set_active_id(off):
            self.screen_off.append(off, _minutes(blank["screen_off_minutes"]))
            self.screen_off.set_active_id(off)
        self._sensitivity()
        self._refresh_status()
        self._update_preview()

    def _current_target(self):
        """The dict the picture/placement widgets edit: the shared one, or one display's."""
        wp = self.desk["wallpaper"]
        if wp["layout"] == "separate":
            name = self.which.get_active_id()
            if name:
                return wp["monitors"].setdefault(name, {"file": wp["file"], "mode": wp["mode"]})
        return wp

    def _show_picture(self):
        t = self._current_target()
        self.loading, was = True, self.loading
        if t.get("file"):
            self.file.set_filename(t["file"])
        else:
            self.file.unselect_all()
        self.mode.set_active_id(t.get("mode", "fill"))
        self.loading = was

    def _sensitivity(self):
        wp_on = self.wp_switch.get_active()
        for child in self.wp_grid.get_children():
            if child is not self.preview:
                child.set_sensitive(wp_on)
        separate = self.layout.get_active_id() == "separate"
        self.which.set_visible(separate)
        self.which_label.set_visible(separate)
        locker = self.locker.get_active_id()
        is_i3lock = locker == "i3lock"
        for w in (self.image_label, self.lock_image_box, self.show_failed):
            w.set_visible(is_i3lock)
        self.lock_color.set_visible(self.lock_image.get_active_id() == "color")
        notes = []
        if not shutil.which("xss-lock"):
            notes.append(_("Install xss-lock: it starts the locker when you're idle and before the computer "
                           "sleeps."))
        if not D.installed_lockers():
            notes.append(_("Install a locker: i3lock, xsecurelock or slock."))
        elif locker == "slock":
            notes.append(_("slock is set up when it's compiled (config.h); XControl can only start it."))
        elif locker == "xsecurelock":
            notes.append(_("xsecurelock is set up with XSECURELOCK_* environment variables; it doesn't show the "
                           "wallpaper."))
        self.locker_note.set_text("\n".join(notes))
        self.locker_note.set_visible(bool(notes))
        can_lock = bool(D.installed_lockers())
        self.lock_now.set_sensitive(can_lock)

    def _refresh_status(self):
        st = D.state()
        lock = self.desk["lock"]
        if lock["enabled"] and st.get("xss_lock"):
            self.lock_status.set_text(_("Active: xss-lock is running."))
        elif lock["enabled"]:
            self.lock_status.set_text(_("Not running yet."))
        else:
            self.lock_status.set_text("")
        conflicts = D.session_conflicts()
        wp_lines = [line for kind, line in conflicts if kind == "wallpaper"]
        lock_lines = [line for kind, line in conflicts if kind == "lock"]
        foreign = list(D.foreign_xss_lock().values())
        self._conflict(self.wp_conflict, self.desk["wallpaper"]["enabled"] and wp_lines,
                       _("Your i3 config also sets the wallpaper; remove these lines or they'll replace XControl's "
                         "at login:"), wp_lines)
        self._conflict(self.lock_conflict, lock["enabled"] and (lock_lines or foreign),
                       _("Another screen lock is set up; remove it from your i3 config, or two lockers will "
                         "start:"), lock_lines or foreign)
        self.autostart_bar.set_visible(D.wanted(self.desk) and D.autostart_runs() is False)

    def _conflict(self, label, show, text, lines):
        if show:
            label.set_markup("⚠ " + GLib.markup_escape_text(text) + "\n" +
                             "\n".join(f"<tt>{GLib.markup_escape_text(line)}</tt>" for line in lines[:4]))
        label.set_visible(bool(show))

    # ---------------------------------------------------------------- preview
    def _update_preview(self):
        sw, sh = self.screen
        scale = PREVIEW_W / max(sw, 1)
        height = max(40, round(sh * scale))
        self.preview.set_size_request(PREVIEW_W, height)
        try:
            self.preview_surface, _errors = W.compose(self.desk["wallpaper"], self.mons, sw, sh, scale=scale)
        except Exception:  # noqa: BLE001
            self.preview_surface = None
        self.preview.queue_draw()

    def _draw_preview(self, _w, cr):
        if self.preview_surface:
            cr.set_source_surface(self.preview_surface, 0, 0)
            cr.paint()
        sw, _sh = self.screen
        scale = PREVIEW_W / max(sw, 1)
        cr.set_line_width(1)
        for name, x, y, w, h in self.mons:
            cr.set_source_rgba(1, 1, 1, 0.8)
            cr.rectangle(x * scale + 0.5, y * scale + 0.5, w * scale - 1, h * scale - 1)
            cr.stroke()
            cr.move_to(x * scale + 6, y * scale + 16)
            cr.select_font_face("Sans")
            cr.set_font_size(11)
            cr.set_source_rgba(0, 0, 0, 0.6)
            cr.text_path(name)
            cr.stroke_preserve()
            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.fill()
        return False

    # ---------------------------------------------------------------- view -> model
    def _layout_changed(self, *_a):
        if self.loading:
            return
        self.desk["wallpaper"]["layout"] = self.layout.get_active_id()
        self._show_picture()
        self._changed()

    def _which_changed(self, *_a):
        if not self.loading:
            self._show_picture()

    def _clear_picture(self, *_a):
        self.file.unselect_all()
        self._current_target()["file"] = ""
        self._changed()

    def _changed(self, *_a):
        if self.loading:
            return
        wp, lock, blank = self.desk["wallpaper"], self.desk["lock"], self.desk["blanking"]
        wp["enabled"] = self.wp_switch.get_active()
        t = self._current_target()
        path = self.file.get_filename()
        if path:
            t["file"] = path
        t["mode"] = self.mode.get_active_id() or "fill"
        wp["color"] = _hex(self.color.get_rgba())
        lock["enabled"] = self.lock_switch.get_active()
        lock["locker"] = self.locker.get_active_id() or lock["locker"]
        lock["idle_minutes"] = int(self.idle.get_active_id() or 0)
        lock["lock_on_sleep"] = self.on_sleep.get_active()
        lock["image"] = self.lock_image.get_active_id() or "wallpaper"
        lock["color"] = _hex(self.lock_color.get_rgba())
        lock["show_failed"] = self.show_failed.get_active()
        off = self.screen_off.get_active_id() or "default"
        blank["managed"] = off != "default"
        blank["screen_off_minutes"] = int(off) if off != "default" else blank["screen_off_minutes"]
        self._sensitivity()
        self._update_preview()
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(400, self._commit)

    def _commit(self):
        self._timer = None
        try:
            D.save(self.desk)
            result = D.notify_daemon(self.desk)
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not save the desktop settings"), str(e))
            return False
        self.window.set_status({"started": _("Desktop settings applied"), "reloaded": _("Desktop settings applied"),
                                "stopped": _("XControl no longer manages the desktop")}.get(result, ""))
        GLib.timeout_add(1500, lambda: self._refresh_status() and False)
        return False

    def _lock_now(self, *_a):
        if not D.lock_now(self.desk):
            self.window.message(_("Could not lock the screen"), _("Install i3lock, xsecurelock or slock."))
