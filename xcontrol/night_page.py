"""Night light settings, shown on the Displays page (the desktop service does the work)."""
import datetime

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import desktop as D, night as NL, xrandr  # noqa: E402
from .desktop_page import _command, _hint  # noqa: E402
from .i18n import N_, _  # noqa: E402

MODE_LABELS = {"sun": N_("From sunset to sunrise"), "times": N_("At set hours"), "always": N_("All the time")}


def _time_entry(value):
    e = Gtk.Entry(text=value, width_chars=6, max_length=5)
    e.set_placeholder_text("20:00")
    return e


class NightPanel(Gtk.Frame):
    def __init__(self, window):
        super().__init__(shadow_type=Gtk.ShadowType.NONE)
        self.window = window
        self.loading = True
        self._timer = None
        head = Gtk.Box(spacing=10)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>{}</b>".format(GLib.markup_escape_text(_("Night light"))))
        head.pack_start(lbl, False, False, 0)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", self._changed)
        head.pack_start(self.switch, False, False, 0)
        self.set_label_widget(head)
        g = Gtk.Grid(column_spacing=12, row_spacing=8, margin_start=12, margin_top=8, margin_bottom=4)
        self.add(g)
        self.grid = g
        self.labels = []

        def row(r, label, widget):
            lab = Gtk.Label(label=label, xalign=0)
            self.labels.append(lab)
            g.attach(lab, 0, r, 1, 1)
            g.attach(widget, 1, r, 1, 1)
            return lab

        g.attach(_hint(_("Warmer colors in the evening, easier on the eyes. It changes right away (no Apply "
                         "needed) and builds on each display's gamma above.")), 0, 0, 2, 1)
        self.mode = Gtk.ComboBoxText()
        for k in NL.MODES:
            self.mode.append(k, _(MODE_LABELS[k]))
        self.mode.connect("changed", self._changed)
        row(1, _("When"), self.mode)

        loc = Gtk.Box(spacing=8)
        self.auto_loc = Gtk.CheckButton(label=_("From the time zone"))
        self.auto_loc.connect("toggled", self._changed)
        self.lat = Gtk.SpinButton.new_with_range(-90, 90, 0.1)
        self.lon = Gtk.SpinButton.new_with_range(-180, 180, 0.1)
        for s in (self.lat, self.lon):
            s.set_digits(2)
            s.connect("value-changed", self._changed)
        loc.pack_start(self.auto_loc, False, False, 0)
        loc.pack_start(Gtk.Label(label=_("Latitude")), False, False, 0)
        loc.pack_start(self.lat, False, False, 0)
        loc.pack_start(Gtk.Label(label=_("Longitude")), False, False, 0)
        loc.pack_start(self.lon, False, False, 0)
        self.loc_label = row(2, _("Location"), loc)
        self.loc_box = loc

        hours = Gtk.Box(spacing=8)
        self.start = _time_entry("20:00")
        self.end = _time_entry("07:00")
        self.fade = Gtk.SpinButton.new_with_range(0, 180, 5)
        for w in (self.start, self.end):
            w.connect("changed", self._changed)
        self.fade.connect("value-changed", self._changed)
        hours.pack_start(Gtk.Label(label=_("from")), False, False, 0)
        hours.pack_start(self.start, False, False, 0)
        hours.pack_start(Gtk.Label(label=_("to")), False, False, 0)
        hours.pack_start(self.end, False, False, 0)
        hours.pack_start(Gtk.Label(label=_("changing over")), False, False, 0)
        hours.pack_start(self.fade, False, False, 0)
        hours.pack_start(Gtk.Label(label=_("minutes")), False, False, 0)
        self.hours_label = row(3, _("Hours"), hours)
        self.hours_box = hours

        self.temp = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, NL.TEMP_RANGE[0], 6000, 100)
        self.temp.set_hexpand(True)
        self.temp.set_inverted(True)        # warmer to the right
        self.temp.set_digits(0)
        self.temp.set_value_pos(Gtk.PositionType.RIGHT)
        self.temp.connect("format-value", lambda _s, v: f"{int(v)} K")
        for v, mark in ((4500, _("a little")), (3400, _("warm")), (2300, _("very warm"))):
            self.temp.add_mark(v, Gtk.PositionType.BOTTOM, mark)
        self.temp.connect("value-changed", self._changed)
        row(4, _("Night color"), self.temp)
        self.preview = Gtk.ToggleButton(label=_("Show it now"))
        self.preview.set_tooltip_text(_("Turn the night color on until the schedule next changes (or click "
                                        "again)"))
        self.preview.connect("toggled", self._preview)
        g.attach(self.preview, 1, 5, 1, 1)
        self.preview.set_halign(Gtk.Align.START)

        self.skip_box = Gtk.Box(spacing=12)
        row(6, _("Leave alone"), self.skip_box)
        self.status = Gtk.Label(xalign=0, wrap=True)
        g.attach(self.status, 1, 7, 1, 1)
        self.conflict = _hint("")
        g.attach(self.conflict, 1, 8, 1, 1)
        g.attach(_command(_("Switch it from a key (until the schedule next changes):"),
                          "bindsym $mod+Shift+n exec --no-startup-id xcontrol --night toggle", window), 1, 9, 1, 1)

        self.n = D.load()["night"]
        self._fill()
        self.loading = False
        poll = GLib.timeout_add_seconds(3, lambda: self._poll() if self.get_mapped() else True)
        self.connect("destroy", lambda *_a: GLib.source_remove(poll))
        self.connect("map", lambda *_a: self._poll())   # (not polled while another page is shown)

    def label_widgets(self):
        return self.labels

    def _fill(self):
        n = self.n
        self.loading = True
        self.switch.set_active(n["enabled"])
        self.mode.set_active_id(n["mode"])
        auto = n["latitude"] is None or n["longitude"] is None
        self.auto_loc.set_active(auto)
        loc = (n["latitude"], n["longitude"]) if not auto else (NL.location_from_timezone() or (0.0, 0.0))
        self.lat.set_value(loc[0])
        self.lon.set_value(loc[1])
        self.start.set_text(n["start"])
        self.end.set_text(n["end"])
        self.fade.set_value(n["fade_minutes"])
        self.temp.set_value(n["night_temp"])
        for c in self.skip_box.get_children():
            c.destroy()
        try:
            outs = [m.name for m in xrandr.query() if m.connected]
        except Exception:  # noqa: BLE001
            outs = []
        self.skips = {}
        for o in sorted(set(outs) | set(n["outputs"])):
            c = Gtk.CheckButton(label=o, active=o in n["outputs"])
            c.connect("toggled", self._changed)
            self.skip_box.pack_start(c, False, False, 0)
            self.skips[o] = c
        self.skip_box.show_all()
        self._sensitivity()
        self.loading = False
        self._poll()

    def _sensitivity(self):
        on = self.switch.get_active()
        mode = self.mode.get_active_id()
        for w in (self.mode, self.loc_box, self.hours_box, self.temp, self.skip_box):
            w.set_sensitive(on or w is self.temp)
        for w in (self.loc_label, self.loc_box):
            w.set_visible(mode == "sun")
        for w in (self.hours_label, self.hours_box):
            w.set_visible(mode == "times")
        self.lat.set_sensitive(not self.auto_loc.get_active())
        self.lon.set_sensitive(not self.auto_loc.get_active())

    def _changed(self, *_a):
        if self.loading:
            return
        n = self.n
        n["enabled"] = self.switch.get_active()
        n["mode"] = self.mode.get_active_id() or "sun"
        if self.auto_loc.get_active():
            n["latitude"] = n["longitude"] = None
            loc = NL.location_from_timezone()
            if loc:
                self.loading = True
                self.lat.set_value(loc[0])
                self.lon.set_value(loc[1])
                self.loading = False
        else:
            n["latitude"], n["longitude"] = round(self.lat.get_value(), 2), round(self.lon.get_value(), 2)
        for k, w in (("start", self.start), ("end", self.end)):
            t = w.get_text().strip()
            if len(t) in (4, 5) and NL.normalize({k: t})[k] == t:
                n[k] = t
        n["fade_minutes"] = int(self.fade.get_value())
        n["night_temp"] = int(self.temp.get_value())
        n["outputs"] = [o for o, c in self.skips.items() if c.get_active()]
        self._sensitivity()
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(400, self._commit)

    def _commit(self):
        self._timer = None
        try:
            fresh = D.load()
            fresh["night"] = NL.normalize(self.n)
            D.save(fresh)
            D.notify_daemon(fresh)
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not save the settings"), str(e))
            return False
        GLib.timeout_add(1200, lambda: self._poll() and False)
        return False

    def _preview(self, btn):
        if self.loading:
            return
        D.set_night("on" if btn.get_active() else "auto")
        GLib.timeout_add(800, lambda: self._poll() and False)

    def _poll(self):
        n = NL.normalize(self.n)
        st = D.state()
        shown = (st.get("night") or {}).get("shown")
        forced = NL.forced(D._runtime, n)
        self.loading, was = True, self.loading
        self.preview.set_active(forced == "on")
        self.loading = was
        parts = []
        if shown and shown != 6500:
            parts.append(_("Now {k} K.").format(k=shown))
        if forced == "on":
            parts.append(_("On by hand until the schedule next changes."))
        elif forced == "off":
            parts.append(_("Off by hand until the schedule next changes."))
        elif n["enabled"]:
            nxt = NL.next_change(n)
            night = NL.night_amount(n) >= 0.5
            if nxt:
                at = nxt.strftime("%H:%M") if nxt.date() == datetime.date.today() else nxt.strftime("%a %H:%M")
                parts.append((_("Night light until {time}.") if night else _("Next on at {time}.")).format(time=at))
            if n["mode"] == "sun" and n["latitude"] is None and not NL.location_from_timezone():
                parts.append(_("The time zone doesn't give a location; set it by hand."))
        self.status.set_text(" ".join(parts))
        self.status.set_visible(bool(parts))
        other = NL.conflicting()
        self.conflict.set_text(_("{programs} is also changing the colors; stop it (and remove it from your i3 "
                                 "config), or the two will fight.").format(programs=", ".join(other)) if other else "")
        self.conflict.set_visible(bool(other))
        return True
