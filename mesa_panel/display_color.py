"""Scaling and colour controls for one display (part of the Displays page).

Only properties the output really has are shown. Changes go into the Monitor
object and are applied with the page's Apply button (with the usual revert)."""
import traceback

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from . import output_props as P  # noqa: E402
from .i18n import N_, _, num  # noqa: E402

SCALING_LABELS = {
    "None": N_("Off: the display does its own scaling"),
    "Full": N_("Stretch to fill the screen"),
    "Center": N_("Centered, no scaling (black borders)"),
    "Full aspect": N_("Scale, keeping the aspect ratio"),
}
UNDERSCAN_LABELS = {"off": N_("Off"), "on": N_("On"), "auto": N_("Automatic (HDMI TVs)")}
RANGE_LABELS = {
    "Automatic": N_("Automatic"),
    "Full": N_("Full (0–255, for PC monitors)"),
    "Limited 16:235": N_("Limited (16–235, for TVs)"),
}
BPC_CHOICES = [6, 8, 10, 12, 16]


def _hint(text):
    lbl = Gtk.Label(label=text, xalign=0, wrap=True)
    lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.set_max_width_chars(70)
    lbl.get_style_context().add_class("dim-label")
    return lbl


def _wheel_steps(scale, event):
    """One wheel notch = one step increment (GTK jumps much further by default)."""
    adj = scale.get_adjustment()
    step = 0
    if event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.RIGHT):
        step = 1
    elif event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.LEFT):
        step = -1
    elif event.direction == Gdk.ScrollDirection.SMOOTH:
        ok, dx, dy = event.get_scroll_deltas()
        if ok and abs(dx - dy) >= 0.5:
            step = 1 if dx - dy > 0 else -1
    if step:
        adj.set_value(adj.get_value() + step * adj.get_step_increment())
    return True


def _scale(lo, hi, step, digits, fmt):
    s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    s.set_digits(digits)
    s.set_hexpand(True)
    s.set_value_pos(Gtk.PositionType.RIGHT)
    s.get_adjustment().set_page_increment(step)
    s.connect("format-value", lambda _s, v: fmt(v))
    s.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
    s.connect("scroll-event", _wheel_steps)
    return s


class ColorPanel(Gtk.Expander):
    def __init__(self, on_change):
        super().__init__()
        head = Gtk.Label(xalign=0)
        head.set_markup("<b>" + _("Scaling and color") + "</b>")
        self.set_label_widget(head)
        self.on_change = on_change
        self.mon = None
        self.loading = False

        g = Gtk.Grid(column_spacing=12, row_spacing=8, margin_top=8)
        self.grid = g
        self.rows = {}

        def row(key, label, widget, hint=None):
            n = len(self.rows) * 2
            name = Gtk.Label(label=label, xalign=0)
            g.attach(name, 0, n, 1, 1)
            g.attach(widget, 1, n, 1, 1)
            widgets = [name, widget]
            if hint:
                h = _hint(hint)
                g.attach(h, 1, n + 1, 1, 1)
                widgets.append(h)
            self.rows[key] = widgets

        self.scaling = Gtk.ComboBoxText(hexpand=True)
        self.scaling.connect("changed", self._enum_changed, "scaling mode")
        row("scaling mode", _("GPU scaling"), self.scaling,
            _("Used when the resolution is lower than the display's native one."))

        self.underscan = Gtk.ComboBoxText()
        self.underscan.connect("changed", self._enum_changed, "underscan")
        self.hborder = Gtk.SpinButton.new_with_range(0, 128, 1)
        self.vborder = Gtk.SpinButton.new_with_range(0, 128, 1)
        self.hborder.connect("value-changed", self._border_changed, "underscan hborder")
        self.vborder.connect("value-changed", self._border_changed, "underscan vborder")
        ub = Gtk.Box(spacing=6)
        ub.pack_start(self.underscan, True, True, 0)
        # TRANSLATORS: horizontal and vertical border sizes, in pixels
        ub.pack_start(Gtk.Label(label=_("Borders")), False, False, 8)
        ub.pack_start(self.hborder, False, False, 0)
        ub.pack_start(Gtk.Label(label="×"), False, False, 0)
        ub.pack_start(self.vborder, False, False, 0)
        row("underscan", _("Underscan"), ub,
            _("Shrinks the picture so a TV that crops the edges (overscan) shows all of it."))

        self.range = Gtk.ComboBoxText()
        self.range.connect("changed", self._enum_changed, "Broadcast RGB")
        row("Broadcast RGB", _("Output range"), self.range,
            _("If blacks look gray or dark details are crushed, the display and the GPU disagree on the range."))

        self.bpc = Gtk.ComboBoxText()
        self.bpc.connect("changed", self._bpc_changed)
        row("max bpc", _("Color depth"), self.bpc,
            _("The highest depth the link may use; the driver lowers it when bandwidth runs out."))

        self.saturation = _scale(0, 200, 5, 0, lambda v: _("{n} %").format(n=int(round(v))))
        self.saturation.add_mark(100, Gtk.PositionType.BOTTOM, None)
        self.saturation.connect("value-changed", self._saturation_changed)
        self.sat_note = _hint("")
        self.sat_note.set_no_show_all(True)
        sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sbox.pack_start(self.saturation, False, False, 0)
        sbox.pack_start(self.sat_note, False, False, 0)
        row("CTM", _("Saturation"), sbox,
            _("Done by the display engine, so it applies to everything on screen, games included. "
              "At 100 colors are unchanged."))

        self.gamma = _scale(0.5, 2.0, 0.05, 2, lambda v: num(v, 2))
        self.gamma.add_mark(1.0, Gtk.PositionType.BOTTOM, None)
        self.gamma.connect("value-changed", self._gamma_changed)
        row("gamma", _("Gamma"), self.gamma,
            _("Higher values brighten dark and middle tones. Night-light tools also change gamma "
              "and may override this."))

        reset = Gtk.Button(label=_("Reset to defaults"), halign=Gtk.Align.START)
        reset.connect("clicked", self._reset)
        self.reset_btn = reset
        g.attach(reset, 1, len(self.rows) * 2, 1, 1)

        self.empty = _hint(_("The driver offers no scaling or color settings for this display."))
        self.empty.set_no_show_all(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(g, False, False, 0)
        box.pack_start(self.empty, False, False, 0)
        self.add(box)

    def label_widgets(self):
        """Left-column labels, for lining up with the page's other labels."""
        return [w[0] for w in self.rows.values()]

    # ---- model -> view
    def show_monitor(self, m):
        """Fill the controls from `m`. Never leaves the panel stuck ignoring changes:
        a value the driver reports in an unexpected form only disables that control."""
        try:
            self._show_monitor(m)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            self.loading = False

    def _show_monitor(self, m):
        self.mon = m
        self.loading = True
        props = m.props if m else {}
        avail = {k: (k in props) for k in ("scaling mode", "underscan", "Broadcast RGB", "max bpc", "CTM")}
        avail["gamma"] = bool(m and m.has_gamma)
        for key, widgets in self.rows.items():
            for w in widgets:
                w.set_visible(avail[key])
                w.set_no_show_all(not avail[key])
        anything = any(avail.values())
        self.reset_btn.set_visible(anything)
        self.empty.set_visible(bool(m) and not anything)
        if not m:
            self.loading = False
            return

        self._fill_enum(self.scaling, m, "scaling mode", SCALING_LABELS)
        self._fill_enum(self.underscan, m, "underscan", UNDERSCAN_LABELS)
        for spin, name in ((self.hborder, "underscan hborder"), (self.vborder, "underscan vborder")):
            lo, hi = m.ranges.get(name, (0, 128))
            spin.set_range(lo, hi)
            try:
                spin.set_value(int(m.props.get(name, "0")))
            except ValueError:
                spin.set_value(0)
            spin.set_sensitive(name in m.props and m.props.get("underscan", "off") != "off")
        self._fill_enum(self.range, m, "Broadcast RGB", RANGE_LABELS)

        self.bpc.remove_all()
        if "max bpc" in props:
            lo, hi = m.ranges.get("max bpc", (8, 16))
            for b in [b for b in BPC_CHOICES if lo <= b <= hi]:
                self.bpc.append(str(b), _("{bits} bits per color").format(bits=b))
            if not self.bpc.set_active_id(props["max bpc"]):
                self.bpc.append(props["max bpc"], _("{bits} bits per color").format(bits=props["max bpc"]))
                self.bpc.set_active_id(props["max bpc"])

        if "CTM" in props:
            s = P.saturation_of(P.ctm_decode(props["CTM"].split()))
            self.saturation.set_value(100 if s is None else s * 100)
            self.sat_note.set_text(_("Another program set a custom color matrix; moving the slider replaces it."))
            self.sat_note.set_visible(s is None)
        if m.has_gamma:
            g = m.gamma
            self.gamma.set_value(g[0] if len(set(round(x, 2) for x in g)) == 1 else 1.0)
        self.loading = False

    def _fill_enum(self, combo, m, name, labels):
        combo.remove_all()
        if name not in m.props:
            return
        for value in m.choices.get(name) or [m.props[name]]:
            combo.append(value, _(labels[value]) if value in labels else value)
        combo.set_active_id(m.props[name])

    # ---- view -> model
    def _set(self, name, value):
        if self.loading or not self.mon or name not in self.mon.props:
            return
        if self.mon.props[name] != value:
            self.mon.props[name] = value
            self.on_change()

    def _enum_changed(self, combo, name):
        if combo.get_active_id():
            self._set(name, combo.get_active_id())
        if name == "underscan" and not self.loading and self.mon:
            on = self.mon.props.get("underscan", "off") != "off"
            self.hborder.set_sensitive(on)
            self.vborder.set_sensitive(on)

    def _border_changed(self, spin, name):
        self._set(name, str(int(spin.get_value())))

    def _bpc_changed(self, combo):
        if combo.get_active_id():
            self._set("max bpc", combo.get_active_id())

    def _saturation_changed(self, scale):
        if self.loading or not self.mon or "CTM" not in self.mon.props:
            return
        P.set_saturation(self.mon, scale.get_value() / 100)
        self.sat_note.hide()
        self.on_change()

    def _gamma_changed(self, scale):
        if self.loading or not self.mon or not self.mon.has_gamma:
            return
        g = round(scale.get_value(), 2)
        self.mon.gamma = (g, g, g)
        self.on_change()

    def _reset(self, *_args):
        m = self.mon
        if not m:
            return
        for name in P.ORDER:
            if name not in m.props:
                continue
            if name == "CTM":
                P.set_saturation(m, 1.0)
            else:
                d = P.default_of(m, name)
                if d is not None:
                    m.props[name] = d
        if m.has_gamma:
            m.gamma = (1.0, 1.0, 1.0)
        self.show_monitor(m)
        self.on_change()
