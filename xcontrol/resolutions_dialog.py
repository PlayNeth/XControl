"""Per-display custom resolutions, and the option to ignore the EDID's mode list."""
import re

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import widgets  # noqa: E402
from . import config, edid, modelines, xrandr  # noqa: E402
from .i18n import N_, _, num  # noqa: E402
from .i18n import hz as hz_text  # noqa: E402

STANDARD_LABELS = [
    ("cvt", N_("CVT – standard blanking (CRT style)")),
    ("cvt-rb", N_("CVT – reduced blanking (LCD)")),
    ("cvt-rb2", N_("CVT – reduced blanking v2 (exact refresh rate)")),
    ("gtf", N_("GTF – classic CRT formula")),
    ("dmt", N_("DMT – VESA standard timings")),
    ("manual", N_("Manual modeline")),
]
SHORT_NAMES = {"cvt": "CVT", "cvt-rb": "CVT-RB", "cvt-rb2": "CVT-RBv2", "gtf": "GTF", "dmt": "DMT",
               "manual": N_("manual")}
TAGS = {"": "cvt", "R": "cvt-rb", "R2": "cvt-rb2", "G": "gtf", "D": "dmt", "M": "manual"}
CLASSIC = [(640, 480), (720, 400), (800, 600), (1024, 768), (1152, 864), (1280, 960), (1280, 1024),
           (1600, 1200), (1280, 720), (1920, 1080)]
_NAME_RE = re.compile(r"^(\d+)x(\d+)_([\d.]+)(R2|R|G|D|M)?$")


def standard_of(mode_name):
    """The timing standard of a mode this panel created, else None (EDID mode)."""
    m = _NAME_RE.match(mode_name)
    return TAGS[m.group(4) or ""] if m else None


def mode_label(mode_name, preferred=False, rates=()):
    std = standard_of(mode_name)
    if std:
        w, h = _NAME_RE.match(mode_name).group(1, 2)
        if rates:
            # TRANSLATORS: a resolution the user created, e.g. "640x480 @ 59.94 Hz (custom, DMT)"
            return _("{w}x{h} @ {hz} (custom, {standard})").format(
                w=w, h=h, hz=hz_text(float(rates[0])), standard=_(SHORT_NAMES[std]))
        # TRANSLATORS: a resolution the user created, e.g. "1024x768 (custom, DMT)"
        return _("{w}x{h} (custom, {standard})").format(w=w, h=h, standard=_(SHORT_NAMES[std]))
    if preferred:
        return _("{mode}  (recommended)").format(mode=mode_name)
    return mode_name


def _work_area_height(window):
    """Usable height of the monitor showing the panel (minus panels/taskbars)."""
    try:
        display = window.get_display()
        mon = display.get_monitor_at_window(window.get_window()) or display.get_primary_monitor()
        return mon.get_workarea().height
    except Exception:  # noqa: BLE001
        return 768


class ResolutionsDialog(Gtk.Dialog):
    def __init__(self, page, monitor):
        super().__init__(title=_("Resolutions for {output}").format(output=monitor.name),
                         transient_for=page.window, modal=True)
        self.page = page
        self.mon = monitor
        self.changed = False
        self.set_default_size(620, -1)
        self.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        self.limits = self._edid_limits()

        area = self.get_content_area()
        outer = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        outer.set_propagate_natural_height(True)
        outer.set_max_content_height(max(320, _work_area_height(page.window) - 140))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, border_width=16)
        outer.add(box)
        area.pack_start(outer, True, True, 0)

        # ---- ignore EDID
        row = Gtk.Box(spacing=12)
        lbl = Gtk.Label(label=_("Offer only my resolutions for this display"), xalign=0, hexpand=True)
        self.ignore_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        row.pack_start(lbl, True, True, 0)
        row.pack_start(self.ignore_switch, False, False, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(self._hint(_(
            "Hides every other mode: the ones the display reports in its EDID and the scaled modes some "
            "drivers add (modesetting does this on connectors that support scaling). Custom resolutions are "
            "re-created automatically when you log in or open this panel.")),
            False, False, 0)

        # ---- my resolutions
        box.pack_start(self._heading(_("My resolutions")), False, False, 0)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        list_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        list_scroll.set_shadow_type(Gtk.ShadowType.IN)
        list_scroll.set_propagate_natural_height(True)   # grows with the list...
        list_scroll.set_max_content_height(230)          # ...then scrolls (about four entries)
        list_scroll.add(self.listbox)
        box.pack_start(list_scroll, False, False, 0)

        # ---- add
        box.pack_start(self._heading(_("Add a resolution")), False, False, 0)
        g = Gtk.Grid(column_spacing=10, row_spacing=8)
        self.w_spin = Gtk.SpinButton.new_with_range(320, 16384, 8)
        self.h_spin = Gtk.SpinButton.new_with_range(200, 16384, 1)
        self.hz_spin = Gtk.SpinButton.new_with_range(10, 500, 1)
        self.hz_spin.set_digits(2)
        self.w_spin.set_increments(8, 64)
        self.w_spin.set_value(1024)
        self.h_spin.set_value(768)
        self.hz_spin.set_value(60)
        size = Gtk.Box(spacing=6)
        size.pack_start(self.w_spin, False, False, 0)
        size.pack_start(Gtk.Label(label="×"), False, False, 0)
        size.pack_start(self.h_spin, False, False, 0)
        size.pack_start(Gtk.Label(label="@"), False, False, 0)
        size.pack_start(self.hz_spin, False, False, 0)
        size.pack_start(Gtk.Label(label="Hz"), False, False, 0)
        presets = Gtk.MenuButton(label=_("Classic modes"))
        menu = Gtk.Menu()
        for w, h in CLASSIC:
            item = Gtk.MenuItem(label=f"{w} × {h}")
            item.connect("activate", self._preset, w, h)
            menu.append(item)
        menu.show_all()
        presets.set_popup(menu)
        size.pack_start(presets, False, False, 6)
        g.attach(Gtk.Label(label=_("Resolution"), xalign=0), 0, 0, 1, 1)
        g.attach(size, 1, 0, 1, 1)

        self.std_combo = Gtk.ComboBoxText()
        for key, label in STANDARD_LABELS:
            self.std_combo.append(key, _(label))
        self.std_combo.set_active_id("cvt")
        g.attach(Gtk.Label(label=_("Timing"), xalign=0), 0, 1, 1, 1)
        g.attach(self.std_combo, 1, 1, 1, 1)

        self.manual_entry = Gtk.Entry(hexpand=True,
                                      placeholder_text="25.175 640 656 752 800 480 490 492 525 -hsync -vsync")
        self.manual_entry.set_tooltip_text(_("Paste a modeline, e.g. from the cvt or gtf tools or an old xorg.conf"))
        self.manual_label = Gtk.Label(label=_("Modeline"), xalign=0)
        g.attach(self.manual_label, 0, 2, 1, 1)
        g.attach(self.manual_entry, 1, 2, 1, 1)

        self.preview = Gtk.Label(xalign=0, selectable=True, wrap=True)
        self.preview.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.info = Gtk.Label(xalign=0, wrap=True)
        self.info.get_style_context().add_class("dim-label")
        self.warning = Gtk.Label(xalign=0, wrap=True)
        g.attach(self.preview, 1, 3, 1, 1)
        g.attach(self.info, 1, 4, 1, 1)
        g.attach(self.warning, 1, 5, 1, 1)
        self.add_btn = Gtk.Button(label=_("Add"), halign=Gtk.Align.END)
        self.add_btn.get_style_context().add_class("suggested-action")
        self.add_btn.connect("clicked", self._add)
        g.attach(self.add_btn, 1, 6, 1, 1)
        box.pack_start(g, False, False, 0)

        # ---- system-wide
        box.pack_start(self._heading(_("For all programs")), False, False, 0)
        sys_row = Gtk.Box(spacing=8)
        sys_row.pack_start(self._hint(_(
            "The options above only change what this panel offers. To hide unwanted modes from games and every "
            "other program, give the kernel a corrected EDID.")), True, True, 0)
        sys_btn = Gtk.Button(label=_("System-wide mode list…"), valign=Gtk.Align.CENTER)
        sys_btn.connect("clicked", self._system_wide)
        sys_row.pack_start(sys_btn, False, False, 0)
        box.pack_start(sys_row, False, False, 0)

        for w in (self.w_spin, self.h_spin, self.hz_spin):
            w.connect("value-changed", self._update_preview)
        self.std_combo.connect("changed", self._update_preview)
        self.manual_entry.connect("changed", self._update_preview)

        self.data = config.load()
        self.ignore_switch.set_active(monitor.name in self.data["display"]["edid_ignored"])
        self.ignore_switch.connect("notify::active", self._ignore_toggled)
        self._fill_list()
        self.show_all()
        widgets.protect(self)
        self._update_preview()

    # ---- helpers
    @staticmethod
    def _hint(text):
        lbl = Gtk.Label(label=text, xalign=0, wrap=True)
        lbl.set_max_width_chars(70)
        lbl.get_style_context().add_class("dim-label")
        return lbl

    @staticmethod
    def _heading(text):
        lbl = Gtk.Label(xalign=0, margin_top=6)
        lbl.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        return lbl

    def _edid_limits(self):
        try:
            raw = xrandr.query_verbose().get(self.mon.name, {}).get("edid")
        except Exception:  # noqa: BLE001
            raw = None
        return edid.parse(raw) if raw else None

    def _modes(self):
        return [modelines.Modeline.from_dict(d)
                for d in self.data["display"]["custom_modes"].get(self.mon.name, [])]

    def _save(self, modes=None):
        disp = self.data["display"]
        if modes is not None:
            if modes:
                disp["custom_modes"][self.mon.name] = [m.to_dict() for m in modes]
            else:
                disp["custom_modes"].pop(self.mon.name, None)
        fresh = config.load()      # (keep what other pages saved while this was open)
        for key in ("custom_modes", "edid_ignored"):
            fresh["display"][key] = disp[key]
        config.save(fresh)
        self.data = fresh
        from .display_page import sync_autostart
        sync_autostart(self.data)
        self.changed = True

    def _fill_list(self):
        for child in self.listbox.get_children():
            child.destroy()
        modes = self._modes()
        if not modes:
            empty = Gtk.Label(label=_("No custom resolutions yet."), margin=10, xalign=0)
            empty.get_style_context().add_class("dim-label")
            self.listbox.add(empty)
        for m in modes:
            row = Gtk.Box(spacing=8, margin=8)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            title = Gtk.Label(xalign=0)
            title.set_markup("<b>{}</b>  {}".format(
                GLib.markup_escape_text(f"{m.width} × {m.height} @ {num(m.refresh, 2)} Hz"),
                GLib.markup_escape_text(_(SHORT_NAMES[m.standard]))))
            line = Gtk.Label(label=m.modeline(), xalign=0, selectable=True)
            line.get_style_context().add_class("dim-label")
            line.set_ellipsize(Pango.EllipsizeMode.END)
            text.pack_start(title, False, False, 0)
            text.pack_start(line, False, False, 0)
            row.pack_start(text, True, True, 0)
            rm = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
            rm.set_tooltip_text(_("Remove"))
            rm.set_valign(Gtk.Align.CENTER)
            rm.connect("clicked", self._remove, m)
            row.pack_end(rm, False, False, 0)
            self.listbox.add(row)
        self.listbox.show_all()

    def _current(self):
        """The modeline the form describes, or (None, error message)."""
        std = self.std_combo.get_active_id()
        if std == "manual":
            try:
                return modelines.parse_modeline(self.manual_entry.get_text()), None
            except ValueError as e:
                return None, str(e) if self.manual_entry.get_text().strip() else ""
        w, h, hz = int(self.w_spin.get_value()), int(self.h_spin.get_value()), self.hz_spin.get_value()
        try:
            m = modelines.generate(std, w, h, hz)
        except ValueError as e:  # e.g. GTF at 320x240: a negative front porch
            return None, str(e)
        if m is None:
            return None, _("VESA DMT has no timing for {w} × {h}. Pick another timing standard.").format(w=w, h=h)
        return m, None

    def _update_preview(self, *_args):
        manual = self.std_combo.get_active_id() == "manual"
        self.manual_entry.set_visible(manual)
        self.manual_label.set_visible(manual)
        for w in (self.w_spin, self.h_spin, self.hz_spin):
            w.set_sensitive(not manual)
        m, err = self._current()
        self.add_btn.set_sensitive(m is not None)
        if not m:
            self.preview.set_text(err or "")
            self.info.set_text("")
            self.warning.set_text("")
            return
        self.preview.set_markup(f"<tt>{GLib.markup_escape_text(m.modeline())}</tt>")
        self.info.set_text(_("Pixel clock {clock} MHz · horizontal {hfreq} kHz · refresh {hz} Hz").format(
            clock=num(m.clock_khz / 1000, 3), hfreq=num(m.hfreq_khz, 2), hz=num(m.refresh, 3)))
        warnings = []
        if m.clock_khz < 25000 and "HDMI" in self.mon.name.upper():
            warnings.append(_("Below 25 MHz: HDMI links usually refuse this. Use DMT or a higher refresh rate."))
        lim = self.limits
        if lim and lim.vrange and not (lim.vrange[0] - 0.5 <= m.refresh <= lim.vrange[1] + 0.5):
            warnings.append(_("Outside the {low}–{high} Hz range the display reports; it may show no picture.")
                            .format(low=lim.vrange[0], high=lim.vrange[1]))
        if lim and lim.max_pixel_clock_mhz and m.clock_khz > lim.max_pixel_clock_mhz * 1000:
            warnings.append(_("Above the display's reported maximum pixel clock ({clock} MHz).")
                            .format(clock=lim.max_pixel_clock_mhz))
        self.warning.set_markup("\n".join(
            f"<span foreground='#c01c28'>⚠ {GLib.markup_escape_text(w)}</span>" for w in warnings))

    # ---- actions
    def _preset(self, _item, w, h):
        self.w_spin.set_value(w)
        self.h_spin.set_value(h)

    def _add(self, *_args):
        m, err = self._current()
        if not m:
            return
        modes = self._modes()
        if any(x.name == m.name for x in modes):
            self.page.window.set_status(_("That resolution is already in the list"))
            return
        try:
            xrandr.add_custom_mode(self.mon.name, m)
            present = any(x.name == self.mon.name and m.name in x.modes for x in xrandr.query())
        except Exception as e:  # noqa: BLE001
            self.page.window.message(_("xrandr could not add this resolution"), str(e))
            return
        if not present:
            self.page.window.message(
                _("The X server did not keep this resolution"),
                _("xrandr accepted {mode}, but it is not in the mode list of {output}. "
                  "The display driver may have rejected it.").format(mode=m.name, output=self.mon.name))
            return
        modes.append(m)
        self._save(modes)
        self._fill_list()
        self.page.window.set_status(_("Resolution added. Pick it on the Displays page and press Apply."))

    def _remove(self, _btn, m):
        if self.mon.enabled and self.mon.mode == m.name:
            self.page.window.message(_("This resolution is in use"),
                                     _("Switch the display to another resolution before removing it."))
            return
        try:
            xrandr.remove_custom_mode(self.mon.name, m.name)
        except Exception:  # noqa: BLE001 - already gone from the server; still drop it from the list
            pass
        self._save([x for x in self._modes() if x.name != m.name])
        self._fill_list()

    def _system_wide(self, *_args):
        from .edid_override_dialog import EdidOverrideDialog
        dlg = EdidOverrideDialog(self.page.window, self.mon.name)
        dlg.run()
        dlg.destroy()

    def _ignore_toggled(self, sw, _pspec):
        ignored = self.data["display"]["edid_ignored"]
        if sw.get_active() and self.mon.name not in ignored:
            ignored.append(self.mon.name)
        elif not sw.get_active() and self.mon.name in ignored:
            ignored.remove(self.mon.name)
        self._save()
