"""The Input page: mouse and touchpad (libinput), keyboard (XKB), and gaming mouse
hardware (libratbag)."""
import os
import traceback

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import input_devices as D, keyboard as K, ratbag as R  # noqa: E402
from .i18n import N_, _  # noqa: E402
from .paths import input_autostart_file  # noqa: E402

PROFILE_LABELS = {
    "adaptive": N_("Adaptive: faster movement goes further"),
    "flat": N_("Flat: no acceleration (best for games)"),
    "custom": N_("Custom (set elsewhere)"),
}
SCROLL_LABELS = {
    "twofinger": N_("Two fingers"),
    "edge": N_("Right edge of the touchpad"),
    "button": N_("Hold a button and move"),
    "none": N_("Off"),
}
CLICK_LABELS = {
    "buttonareas": N_("Press the bottom corners (right corner = right click)"),
    "clickfinger": N_("Press with 1, 2 or 3 fingers (2 = right click)"),
    "none": N_("Off"),
}
# literal strings so xgettext finds them (same meaning as ratbag.SPECIALS / BUTTON_NAMES)
SPECIAL_LABELS = {
    1: N_("Double click"), 2: N_("Wheel left"), 3: N_("Wheel right"), 4: N_("Wheel up"), 5: N_("Wheel down"),
    6: N_("Ratchet mode switch"), 7: N_("DPI cycle up"), 8: N_("DPI cycle down"), 9: N_("DPI up"),
    10: N_("DPI down"), 11: N_("DPI shift (sniper)"), 12: N_("Default DPI"), 13: N_("Profile cycle up"),
    14: N_("Profile cycle down"), 15: N_("Profile up"), 16: N_("Profile down"), 17: N_("Second mode"),
    18: N_("Battery level"),
}
BUTTON_LABELS = {1: N_("Left click"), 2: N_("Right click"), 3: N_("Middle click"), 4: N_("Back"), 5: N_("Forward")}
LED_MODE_LABELS = {R.LED_OFF: N_("Off"), R.LED_ON: N_("On"), R.LED_CYCLE: N_("Color cycle"),
                   R.LED_BREATHING: N_("Breathing")}


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


def _wheel_steps(scale, event):
    """One wheel notch = one step (GTK jumps a whole page by default)."""
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


def _scale(lo, hi, step, digits, fmt, marks=()):
    s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    s.set_digits(digits)
    s.set_hexpand(True)
    s.set_value_pos(Gtk.PositionType.RIGHT)
    s.get_adjustment().set_page_increment(step)
    s.connect("format-value", lambda _s, v: fmt(v))
    for value, text in marks:
        s.add_mark(value, Gtk.PositionType.BOTTOM, text)
    s.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
    s.connect("scroll-event", _wheel_steps)
    return s


def sync_autostart():
    """The background helper is needed while any input setting is saved."""
    from . import config
    data = config.load()["input"]
    path = input_autostart_file()
    if not (data["devices"] or data["keyboard"]):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=XControl input settings\n"
                "Exec=xcontrol --watch-input\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n")
    D.start_watcher()


class _Debounce:
    """Run fn(value) once input settles (slider drags)."""

    def __init__(self, ms, fn):
        self.ms, self.fn, self.timer, self.value = ms, fn, None, None

    def __call__(self, value):
        self.value = value
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(self.ms, self._fire)

    def _fire(self):
        self.timer = None
        self.fn(self.value)
        return False

    def flush(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self._fire()


# ---------------------------------------------------------------------------
class PointerTab(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.devices = []
        self.dev = None
        self.loading = False
        self.pending = {}       # device name -> {setting: value} waiting for Apply
        self.resetting = set()  # device names whose saved settings Apply should forget

        bar = Gtk.Box(spacing=6)
        bar.pack_start(Gtk.Label(label=_("Device:")), False, False, 0)
        self.combo = Gtk.ComboBoxText(hexpand=True)
        self.combo.connect("changed", self._device_chosen)
        bar.pack_start(self.combo, True, True, 0)
        refresh = Gtk.Button(label=_("Refresh"))
        refresh.connect("clicked", lambda *_a: self.reload())
        bar.pack_start(refresh, False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.empty = _hint("")
        self.empty.set_no_show_all(True)
        self.pack_start(self.empty, False, False, 0)

        # ---- pointer
        self.pointer_frame, g = _section(_("Pointer"))
        self.rows = {}
        self.profile = Gtk.ComboBoxText()
        self.profile.connect("changed", self._combo_changed, "accel_profile")
        self.speed = _scale(-1, 1, 0.05, 2, lambda v: f"{v:+.2f}",
                            [(-1, _("Slow")), (0, _("Default")), (1, _("Fast"))])
        self.speed.connect("value-changed", lambda s: self._set("accel_speed", round(s.get_value(), 2)))
        self.scroll = _scale(0.25, 4, 0.25, 2, lambda v: f"{v:.2f}×", [(1, _("Default"))])
        self.scroll.connect("value-changed", lambda s: self._set("scroll_factor", round(s.get_value(), 2)))
        self.checks = {}
        rows = [("accel_profile", _("Acceleration"), self.profile),
                ("accel_speed", _("Pointer speed"), self.speed),
                ("scroll_factor", _("Scroll speed"), self.scroll)]
        for i, (key, label, widget) in enumerate(rows):
            self._row(g, i, key, label, widget)
        checks = [("natural_scroll", _("Natural scrolling (content follows your fingers)")),
                  ("left_handed", _("Left-handed (swap the left and right buttons)")),
                  ("middle_emulation", _("Middle click by pressing left and right together")),
                  ("horizontal_scroll", _("Horizontal scrolling"))]
        for i, (key, label) in enumerate(checks, start=len(rows)):
            self._check(g, i, key, label)
        self.pack_start(self.pointer_frame, False, False, 0)

        # ---- touchpad
        self.pad_frame, g = _section(_("Touchpad"))
        pad_checks = [("tapping", _("Tap to click")),
                      ("tap_drag", _("Tap and drag")),
                      ("tap_drag_lock", _("Drag lock (lifting the finger doesn't end the drag)")),
                      ("disable_while_typing", _("Disable while typing"))]
        for i, (key, label) in enumerate(pad_checks):
            self._check(g, i, key, label)
        self.scroll_method = Gtk.ComboBoxText()
        self.scroll_method.connect("changed", self._combo_changed, "scroll_method")
        self.click_method = Gtk.ComboBoxText()
        self.click_method.connect("changed", self._combo_changed, "click_method")
        self._row(g, len(pad_checks), "scroll_method", _("Scrolling"), self.scroll_method)
        self._row(g, len(pad_checks) + 1, "click_method", _("Right click"), self.click_method)
        self.pad_frame.show_all()           # shown/hidden as a whole per device from here on
        self.pad_frame.set_no_show_all(True)
        self.pad_frame.hide()
        self.pack_start(self.pad_frame, False, False, 0)

        foot = Gtk.Box(spacing=6)
        reset = Gtk.Button(label=_("Reset to defaults"))
        reset.set_tooltip_text(_("Set this device back to its driver defaults (press Apply to use them)"))
        reset.connect("clicked", self._reset)
        self.reset_btn = reset
        foot.pack_start(reset, False, False, 0)
        self.apply_btn = Gtk.Button(label=_("Apply"))
        self.apply_btn.get_style_context().add_class("suggested-action")
        self.apply_btn.connect("clicked", self._apply)
        self.apply_btn.set_sensitive(False)
        foot.pack_end(self.apply_btn, False, False, 0)
        self.pack_start(foot, False, False, 0)
        self.pack_start(_hint(_("Changes are used when you press Apply, and kept for each device by name: "
                                "XControl puts them back at login and whenever the device is plugged in. "
                                "Refresh discards changes you haven't applied.")), False, False, 0)

        # line up label columns
        group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        for frame in (self.pointer_frame, self.pad_frame):
            grid = frame.get_child()
            for child in grid.get_children():
                if grid.child_get_property(child, "left-attach") == 0:
                    group.add_widget(child)
        self.reload()

    def _row(self, g, i, key, label, widget):
        name = Gtk.Label(label=label, xalign=0)
        g.attach(name, 0, i, 1, 1)
        g.attach(widget, 1, i, 1, 1)
        self.rows[key] = (name, widget)

    def _check(self, g, i, key, label):
        c = Gtk.CheckButton(label=label)
        c.connect("toggled", lambda b: None if self.loading else self._set(key, b.get_active()))
        g.attach(c, 1, i, 1, 1)
        self.rows[key] = (c,)
        self.checks[key] = c

    # ---- model -> view
    def reload(self):
        keep = self.dev.name if self.dev else None
        self.pending, self.resetting = {}, set()
        self.apply_btn.set_sensitive(False)
        try:
            self.devices = D.pointers() if D.available() else []
            msg = "" if D.available() else _("xinput was not found, or this isn't an X11 session.")
        except Exception as e:  # noqa: BLE001
            self.devices, msg = [], str(e)
        self.loading = True
        self.combo.remove_all()
        for d in self.devices:
            kind = _("touchpad") if d.is_touchpad else _("mouse")
            self.combo.append(d.name, f"{d.name}  ({kind})")
        self.loading = False
        if not self.devices:
            self.empty.set_text(msg or _("No mouse or touchpad using the libinput driver was found."))
        self.empty.set_visible(not self.devices)
        for w in (self.pointer_frame, self.reset_btn):
            w.set_sensitive(bool(self.devices))
        names = [d.name for d in self.devices]
        self.combo.set_active(names.index(keep) if keep in names else (0 if names else -1))
        if not self.devices:
            self.dev = None
            self.pad_frame.hide()

    def _device_chosen(self, combo):
        if self.loading:
            return
        name = combo.get_active_id()
        self.dev = next((d for d in self.devices if d.name == name), None)
        self._fill()

    def value(self, key):
        """What the controls show: an unapplied change, or the device's current value."""
        d = self.dev
        pending = self.pending.get(d.name, {})
        return pending[key] if key in pending else d.get(key)

    def _fill(self):
        d = self.dev
        if not d:
            return
        val = self.value
        self.loading = True
        try:
            for key, widgets in self.rows.items():
                for w in widgets:
                    w.set_visible(d.has(key))
                    w.set_no_show_all(not d.has(key))
            self.profile.remove_all()
            for p in d.choices("accel_profile"):
                if p != "custom" or val("accel_profile") == "custom":
                    self.profile.append(p, _(PROFILE_LABELS[p]))
            self.profile.set_active_id(val("accel_profile") or "")
            if d.has("accel_speed"):
                self.speed.set_value(val("accel_speed"))
                self.speed.set_sensitive(val("accel_profile") != "custom")
            if d.has("scroll_factor"):
                self.scroll.set_value(val("scroll_factor"))
            for key, c in self.checks.items():
                if d.has(key):
                    c.set_active(bool(val(key)))
            for combo, key, labels in ((self.scroll_method, "scroll_method", SCROLL_LABELS),
                                       (self.click_method, "click_method", CLICK_LABELS)):
                combo.remove_all()
                for c in d.choices(key):
                    combo.append(c, _(labels[c]))
                combo.set_active_id(val(key) or "none")
            self.pad_frame.set_visible(d.is_touchpad)
        finally:
            self.loading = False

    # ---- view -> device
    def _combo_changed(self, combo, key):
        if not self.loading and combo.get_active_id():
            self._set(key, combo.get_active_id())
            if key == "accel_profile":
                self.speed.set_sensitive(combo.get_active_id() != "custom")

    def _set(self, key, value):
        """Remember a change for Apply."""
        d = self.dev
        if not d or self.loading:
            return
        changes = self.pending.setdefault(d.name, {})
        if value == d.get(key) and d.name not in self.resetting:
            changes.pop(key, None)  # back to what the device already has
        else:
            changes[key] = value
        if not changes and d.name not in self.resetting:
            self.pending.pop(d.name, None)
        dirty = bool(self.pending) or bool(self.resetting)
        self.apply_btn.set_sensitive(dirty)
        if dirty:
            self.window.set_status(_("Press Apply to use the new settings"))

    def _reset(self, *_args):
        """Put the driver's defaults in the controls; Apply uses them and forgets the saved settings."""
        d = self.dev
        if not d:
            return
        defaults = {}
        for key in D.SETTINGS:
            if d.has(key):
                default = d.get(key, default=True)
                if default is not None:
                    defaults[key] = default
        self.pending[d.name] = defaults
        self.resetting.add(d.name)
        self.apply_btn.set_sensitive(True)
        self._fill()
        self.window.set_status(_("Defaults shown; press Apply to use them"))

    def _apply(self, *_args):
        by_name = {d.name: d for d in self.devices}
        errors = []
        for name in sorted(set(self.pending) | self.resetting):
            d = by_name.get(name)
            if not d:
                continue
            changes = self.pending.get(name, {})
            for key, value in changes.items():
                if value == d.get(key):
                    continue
                try:
                    D.apply(d, key, value)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{name}: {key}: {e}")
            if name in self.resetting:
                # keep only what differs from the defaults (changes made after Reset)
                D.forget_device(name)
                for key, value in changes.items():
                    if value != d.get(key, default=True):
                        D.save_setting(name, key, value)
            else:
                for key, value in changes.items():
                    D.save_setting(name, key, value)
        sync_autostart()
        self.reload()
        if errors:
            self.window.message(_("Could not change this setting"), "\n".join(errors))
        else:
            self.window.set_status(_("Settings applied"))


# ---------------------------------------------------------------------------
class KeyboardTab(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.loading = False
        self.lists = K.load_lists()
        self.state = {"layout": "", "variant": "", "options": [], "repeat_delay": 660, "repeat_rate": 25}

        self.warning = _hint("")
        self.warning.set_no_show_all(True)
        self.pack_start(self.warning, False, False, 0)

        frame, g = _section(_("Layout"))
        self.layout1 = self._layout_combo(False)
        self.variant1 = Gtk.ComboBoxText(hexpand=True)
        self.layout2 = self._layout_combo(True)
        self.variant2 = Gtk.ComboBoxText(hexpand=True)
        self.switch = self._option_combo("grp", _("Not set"))
        self.caps = self._option_combo("caps", _("Default (Caps Lock)"))
        self.compose = self._option_combo("compose", _("None"))
        for c in (self.layout1, self.layout2):
            c.connect("changed", self._layout_changed)
        for c in (self.variant1, self.variant2, self.switch, self.caps, self.compose):
            c.connect("changed", self._xkb_changed)
        rows = [(_("Keyboard layout"), self.layout1), (_("Variant"), self.variant1),
                (_("Second layout"), self.layout2), (_("Variant"), self.variant2),
                (_("Switch layouts with"), self.switch), (_("Caps Lock key"), self.caps),
                (_("Compose key"), self.compose)]
        self.rows = []
        labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        for i, (label, w) in enumerate(rows):
            lbl = Gtk.Label(label=label, xalign=0)
            labels.add_widget(lbl)
            g.attach(lbl, 0, i, 1, 1)
            g.attach(w, 1, i, 1, 1)
            self.rows.append((lbl, w))
        for lbl, w in self.rows[3:5]:  # second layout's variant and switch key: only with a second layout
            for x in (lbl, w):
                x.show()
                x.set_no_show_all(True)
        self.pack_start(frame, False, False, 0)

        frame, g = _section(_("Key repeat"))
        self.delay = _scale(150, 1000, 10, 0, lambda v: _("{ms} ms").format(ms=int(v)))
        self.rate = _scale(5, 60, 1, 0, lambda v: _("{n} per second").format(n=int(v)))
        self._repeat_later = _Debounce(300, lambda _v: self._apply({"repeat_delay": int(self.delay.get_value()),
                                                                     "repeat_rate": int(self.rate.get_value())}))
        for s in (self.delay, self.rate):
            s.connect("value-changed", lambda *_a: None if self.loading else self._repeat_later(None))
        for i, text in enumerate((_("Delay before repeating"), _("Repeat speed"))):
            lbl = Gtk.Label(label=text, xalign=0)
            labels.add_widget(lbl)
            g.attach(lbl, 0, i, 1, 1)
        g.attach(self.delay, 1, 0, 1, 1)
        g.attach(self.rate, 1, 1, 1, 1)
        g.attach(Gtk.Entry(placeholder_text=_("Type here to test"), hexpand=True), 1, 2, 1, 1)
        self.pack_start(frame, False, False, 0)

        foot = Gtk.Box(spacing=6)
        reset = Gtk.Button(label=_("Stop managing the keyboard"))
        reset.set_tooltip_text(_("Forget XControl's keyboard settings; your own setup (xorg.conf.d, i3 config) "
                                 "takes over again from the next login"))
        reset.connect("clicked", self._forget)
        foot.pack_start(reset, False, False, 0)
        self.pack_start(foot, False, False, 0)
        self.pack_start(_hint(_("Changes apply right away. XControl only re-applies the keyboard settings you "
                                "change here, at login and when a keyboard is plugged in.")), False, False, 0)
        self.reload()

    def _layout_combo(self, optional):
        c = Gtk.ComboBoxText(hexpand=True)
        if optional:
            c.append("", _("None"))
        for code, desc in sorted(self.lists.layouts.items(), key=lambda kv: kv[1].lower()):
            c.append(code, desc)
        return c

    def _option_combo(self, group, default_label):
        c = Gtk.ComboBoxText(hexpand=True)
        c.append("", default_label)
        for opt, desc in self.lists.options.get(group, {}).items():
            c.append(opt, desc)
        return c

    def _fill_variants(self, combo, layout, selected):
        combo.remove_all()
        combo.append("", _("Default"))
        for v, desc in sorted(self.lists.variants.get(layout, {}).items(), key=lambda kv: kv[1].lower()):
            combo.append(v, desc)
        if not combo.set_active_id(selected):
            if selected:
                combo.append(selected, selected)
                combo.set_active_id(selected)
            else:
                combo.set_active(0)

    @staticmethod
    def _select_option(combo, options, group):
        current = next((o for o in options if o.startswith(group + ":")), "")
        if not combo.set_active_id(current):
            combo.append(current, current)
            combo.set_active_id(current)

    def reload(self):
        if not K.available():
            self.warning.set_text(_("setxkbmap was not found, or this isn't an X11 session."))
            self.warning.show()
            self.set_sensitive(False)
            return
        try:
            self.state = K.current()
        except Exception as e:  # noqa: BLE001
            self.warning.set_text(str(e))
            self.warning.show()
            return
        self.loading = True
        try:
            pairs = K.split_layouts(self.state["layout"], self.state["variant"]) or [("us", "")]
            (l1, v1), (l2, v2) = pairs[0], (pairs[1] if len(pairs) > 1 else ("", ""))
            for combo, code in ((self.layout1, l1), (self.layout2, l2)):
                if not combo.set_active_id(code):
                    combo.append(code, code)
                    combo.set_active_id(code)
            self._fill_variants(self.variant1, l1, v1)
            self._fill_variants(self.variant2, l2, v2)
            self._select_option(self.switch, self.state["options"], "grp")
            self._select_option(self.caps, self.state["options"], "caps")
            self._select_option(self.compose, self.state["options"], "compose")
            self.delay.set_value(self.state["repeat_delay"])
            self.rate.set_value(self.state["repeat_rate"])
            self._second_visible(bool(l2))
        finally:
            self.loading = False

    def _second_visible(self, on):
        for lbl, w in self.rows[3:5]:
            lbl.set_visible(on)
            w.set_visible(on)
        self.variant2.set_sensitive(on)

    def _layout_changed(self, combo):
        if self.loading:
            return
        self.loading = True
        try:
            if combo is self.layout1:
                self._fill_variants(self.variant1, combo.get_active_id() or "", "")
            else:
                self._fill_variants(self.variant2, combo.get_active_id() or "", "")
                self._second_visible(bool(combo.get_active_id()))
        finally:
            self.loading = False
        self._xkb_changed()

    def _xkb_changed(self, *_args):
        if self.loading:
            return
        pairs = [(self.layout1.get_active_id() or "us", self.variant1.get_active_id() or "")]
        if self.layout2.get_active_id():
            pairs.append((self.layout2.get_active_id(), self.variant2.get_active_id() or ""))
        layout, variant = K.join_layouts(pairs)
        options = list(self.state["options"])
        for combo, group in ((self.switch, "grp"), (self.caps, "caps"), (self.compose, "compose")):
            options = K.with_option(options, group, combo.get_active_id() or "")
        self._apply({"layout": layout, "variant": variant, "options": options})

    def _apply(self, changes):
        try:
            K.apply_settings(changes, base=self.state)
            self.state.update(changes)
            K.save(changes)
            sync_autostart()
            self.window.set_status(_("Keyboard settings saved"))
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not change the keyboard settings"), str(e))

    def _forget(self, *_args):
        K.forget()
        sync_autostart()
        self.window.set_status(_("XControl no longer changes the keyboard"))


# ---------------------------------------------------------------------------
class GamingMouseTab(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.devices = []
        self.dev = None
        self.profile = None
        self.loading = False

        bar = Gtk.Box(spacing=6)
        bar.pack_start(Gtk.Label(label=_("Mouse:")), False, False, 0)
        self.combo = Gtk.ComboBoxText(hexpand=True)
        self.combo.connect("changed", self._device_chosen)
        bar.pack_start(self.combo, True, True, 0)
        bar.pack_start(Gtk.Label(label=_("Profile:")), False, False, 0)
        self.profile_combo = Gtk.ComboBoxText()
        self.profile_combo.connect("changed", self._profile_chosen)
        bar.pack_start(self.profile_combo, False, False, 0)
        refresh = Gtk.Button(label=_("Refresh"))
        refresh.connect("clicked", lambda *_a: self.reload())
        bar.pack_start(refresh, False, False, 0)
        self.pack_start(bar, False, False, 0)

        self.message = _hint("")
        self.message.set_no_show_all(True)
        self.pack_start(self.message, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.pack_start(self.body, False, False, 0)

        actions = Gtk.Box(spacing=6)
        self.active_btn = Gtk.Button(label=_("Use this profile"))
        self.active_btn.connect("clicked", self._make_profile_active)
        actions.pack_start(self.active_btn, False, False, 0)
        self.save_btn = Gtk.Button(label=_("Save to mouse"))
        self.save_btn.get_style_context().add_class("suggested-action")
        self.save_btn.connect("clicked", self._commit)
        actions.pack_end(self.save_btn, False, False, 0)
        self.pack_start(actions, False, False, 0)
        self.pack_start(_hint(_("Settings are stored in the mouse itself, so they also work on other computers. "
                                "Changes take effect when you press “Save to mouse”.")), False, False, 0)
        self.reload()

    # ---- loading
    def reload(self):
        keep = self.dev.name if self.dev else None
        why = R.available()
        self.devices = []
        if why is None:
            try:
                self.devices = R.devices()
            except Exception as e:  # noqa: BLE001
                why = str(e)
        self.loading = True
        self.combo.remove_all()
        for i, d in enumerate(self.devices):
            self.combo.append(str(i), d.name)
        self.loading = False
        if why == "not-installed":
            msg = _("Install libratbag (the ratbagd service) to set DPI, polling rate, buttons and lighting on "
                    "supported gaming mice from Logitech, SteelSeries, Razer, Roccat, G.Skill and others.")
        elif why:
            msg = _("Could not reach ratbagd: {error}").format(error=why)
        elif not self.devices:
            msg = _("No supported gaming mouse found. libratbag lists supported models on its website.")
        else:
            msg = ""
        self.message.set_text(msg)
        self.message.set_visible(bool(msg))
        for w in (self.body, self.save_btn, self.active_btn, self.profile_combo):
            w.set_sensitive(bool(self.devices))
        names = [d.name for d in self.devices]
        self.combo.set_active(names.index(keep) if keep in names else (0 if names else -1))
        if not self.devices:
            for c in self.body.get_children():
                self.body.remove(c)

    def _device_chosen(self, combo):
        if self.loading or combo.get_active() < 0:
            return
        self.dev = self.devices[combo.get_active()]
        self.loading = True
        self.profile_combo.remove_all()
        for p in self.dev.profiles:
            label = p.get("Name") or _("Profile {n}").format(n=p["Index"] + 1)
            if p.get("IsActive"):
                label += " " + _("(in use)")
            self.profile_combo.append(str(p["Index"]), label)
        self.loading = False
        active = self.dev.active_profile()
        self.profile_combo.set_active_id(str(active["Index"]) if active else "0")
        self.profile_combo.set_visible(len(self.dev.profiles) > 1)
        self.active_btn.set_visible(len(self.dev.profiles) > 1)

    def _profile_chosen(self, combo):
        if self.loading or not self.dev or combo.get_active() < 0:
            return
        self.profile = self.dev.profiles[combo.get_active()]
        self.active_btn.set_sensitive(not self.profile.get("IsActive"))
        self._build()

    # ---- the settings of one profile
    def _build(self):
        for c in self.body.get_children():
            self.body.remove(c)
        self.w = {"use": [], "default": [], "dpi": [], "enabled": [], "buttons": [], "leds": []}
        p = self.profile
        self.loading = True
        try:
            self._build_dpi(p)
            self._build_sensor(p)
            self._build_buttons(p)
            self._build_leds(p)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            self.loading = False
        self.body.show_all()

    def _guard(self, fn):
        def run(*args):
            if self.loading:
                return
            try:
                fn(*args)
                self.window.set_status(_("Changed; press “Save to mouse” to keep it"))
            except Exception as e:  # noqa: BLE001
                self.window.message(_("The mouse didn't accept this setting"), str(e))
                self._build()
        return run

    def _build_dpi(self, p):
        if not p.resolutions:
            return
        frame, g = _section(_("Sensitivity (DPI)"))
        g.attach(_hint(_("In use")), 1, 0, 1, 1)
        g.attach(_hint(_("At power-on")), 2, 0, 1, 1)
        g.attach(_hint(_("DPI")), 3, 0, 1, 1)
        active_group = default_group = None
        for i, r in enumerate(p.resolutions, start=1):
            g.attach(Gtk.Label(label=_("Stage {n}").format(n=i), xalign=0), 0, i, 1, 1)
            use = Gtk.RadioButton.new_from_widget(active_group)
            active_group = active_group or use
            use.set_active(bool(r.get("IsActive")))
            use.connect("toggled", self._guard(lambda b, r=r: b.get_active() and r.make_active()))
            g.attach(use, 1, i, 1, 1)
            self.w["use"].append(use)
            default = Gtk.RadioButton.new_from_widget(default_group)
            default_group = default_group or default
            default.set_active(bool(r.get("IsDefault")))
            default.connect("toggled", self._guard(lambda b, r=r: b.get_active() and r.make_default()))
            g.attach(default, 2, i, 1, 1)
            self.w["default"].append(default)
            choices = r.choices
            if choices:
                step = min((b - a for a, b in zip(choices, choices[1:])), default=50) or 50
                spin = Gtk.SpinButton.new_with_range(choices[0], choices[-1], step)
                spin.set_value(r.dpi)

                def snap(s, r=r, choices=choices):
                    want = int(s.get_value())
                    dpi = min(choices, key=lambda c: abs(c - want))
                    if dpi != want:
                        s.set_value(dpi)
                        return
                    if dpi != r.dpi:
                        r.set_dpi(dpi)
                spin.connect("value-changed", self._guard(snap))
                g.attach(spin, 3, i, 1, 1)
                self.w["dpi"].append(spin)
            else:
                g.attach(Gtk.Label(label=str(r.dpi), xalign=0), 3, i, 1, 1)
            if r.can_disable:
                off = Gtk.CheckButton(label=_("Enabled"))
                off.set_active(not r.get("IsDisabled"))
                off.connect("toggled", self._guard(lambda b, r=r: r.set_disabled(not b.get_active())))
                g.attach(off, 4, i, 1, 1)
                self.w["enabled"].append(off)
        self.body.pack_start(frame, False, False, 0)

    def _build_sensor(self, p):
        rows = []
        if p.report_rates:
            c = Gtk.ComboBoxText()
            for hz in p.report_rates:
                c.append(str(hz), _("{hz} Hz ({ms} ms)").format(hz=hz, ms=f"{1000 / hz:g}"))
            c.set_active_id(str(p.get("ReportRate")))
            c.connect("changed", self._guard(lambda c: p.set_report_rate(int(c.get_active_id()))))
            rows.append((_("Polling rate"), c))
            self.w["rate"] = c
        if p.debounces and p.get("Debounce", -1) != -1:
            c = Gtk.ComboBoxText()
            for ms in p.debounces:
                c.append(str(ms), _("{ms} ms").format(ms=ms))
            c.set_active_id(str(p.get("Debounce")))
            c.connect("changed", self._guard(lambda c: p.set_debounce(int(c.get_active_id()))))
            rows.append((_("Button debounce"), c))
            self.w["debounce"] = c
        if p.angle_snapping is not None:
            c = Gtk.CheckButton(label=_("Straighten nearly straight lines"))
            c.set_active(p.angle_snapping)
            c.connect("toggled", self._guard(lambda c: p.set_angle_snapping(c.get_active())))
            rows.append((_("Angle snapping"), c))
            self.w["angle"] = c
        if not rows:
            return
        frame, g = _section(_("Sensor"))
        for i, (label, w) in enumerate(rows):
            g.attach(Gtk.Label(label=label, xalign=0), 0, i, 1, 1)
            g.attach(w, 1, i, 1, 1)
        if p.angle_snapping is not None:
            g.attach(_hint(_("Angle snapping helps drawing straight lines but hurts aiming in games.")),
                     1, len(rows), 1, 1)
        self.body.pack_start(frame, False, False, 0)

    def _build_buttons(self, p):
        if not p.buttons:
            return
        frame, g = _section(_("Buttons"))
        for i, b in enumerate(p.buttons):
            g.attach(Gtk.Label(label=_("Button {n}").format(n=b["Index"] + 1), xalign=0), 0, i, 1, 1)
            c = Gtk.ComboBoxText(hexpand=True)
            types = b.action_types
            if R.ACTION_BUTTON in types:
                for n in range(1, 11):
                    name = _(BUTTON_LABELS[n]) if n in BUTTON_LABELS else _("Button {n}").format(n=n)
                    c.append(f"b{n}", _("{action} (button {n})").format(action=name, n=n) if n in BUTTON_LABELS
                             else name)
            if R.ACTION_SPECIAL in types:
                for n, label in SPECIAL_LABELS.items():
                    c.append(f"s{n}", _(label))
            if R.ACTION_NONE in types:
                c.append("none", _("Disabled"))
            kind, value = R.describe_mapping(b.mapping)
            current = {"button": f"b{value}", "special": f"s{value}", "none": "none"}.get(kind)
            if current is None or not c.set_active_id(current):
                text = {"key": _("Keyboard key (set in Piper)"), "macro": _("Macro (set in Piper)")}.get(
                    kind, _("Other ({kind})").format(kind=kind))
                c.append("keep", text)
                c.set_active_id("keep")

            def changed(c, b=b):
                choice = c.get_active_id()
                if choice == "keep" or not choice:
                    return
                if choice == "none":
                    b.set_none()
                elif choice[0] == "b":
                    b.set_button(int(choice[1:]))
                else:
                    b.set_special(R.SPECIAL_BASE + int(choice[1:]))
            c.connect("changed", self._guard(changed))
            g.attach(c, 1, i, 1, 1)
            self.w["buttons"].append(c)
        self.body.pack_start(frame, False, False, 0)

    def _build_leds(self, p):
        if not p.leds:
            return
        frame, g = _section(_("Lighting"))
        row = 0
        for led in p.leds:
            name = _("LED {n}").format(n=led["Index"] + 1)
            g.attach(Gtk.Label(label=name, xalign=0), 0, row, 1, 1)
            mode = Gtk.ComboBoxText()
            for m in led.get("Modes", []):
                if m in LED_MODE_LABELS:
                    mode.append(str(m), _(LED_MODE_LABELS[m]))
            mode.set_active_id(str(led.get("Mode")))
            mode.connect("changed", self._guard(lambda c, led=led: (led.set_mode(int(c.get_active_id())),
                                                                    self._build())))
            box = Gtk.Box(spacing=8)
            box.pack_start(mode, False, False, 0)
            if led.color_bits:
                rgba = Gdk.RGBA()
                r, gg, b = led.rgb
                rgba.red, rgba.green, rgba.blue, rgba.alpha = r / 255, gg / 255, b / 255, 1
                color = Gtk.ColorButton.new_with_rgba(rgba)
                color.set_sensitive(led.get("Mode") in (R.LED_ON, R.LED_BREATHING))

                def set_color(btn, led=led):
                    c = btn.get_rgba()
                    led.set_color((round(c.red * 255), round(c.green * 255), round(c.blue * 255)))
                color.connect("color-set", self._guard(set_color))
                box.pack_start(color, False, False, 0)
            g.attach(box, 1, row, 1, 1)
            row += 1
            if led.get("Mode") != R.LED_OFF:
                bright = _scale(0, 255, 5, 0, lambda v: f"{round(v * 100 / 255)} %")
                bright.set_value(led.get("Brightness", 255))
                later = _Debounce(250, self._guard(lambda v, led=led: led.set_brightness(v)))
                bright.connect("value-changed", lambda s, later=later: None if self.loading else later(s.get_value()))
                g.attach(Gtk.Label(label=_("Brightness"), xalign=0), 0, row, 1, 1)
                g.attach(bright, 1, row, 1, 1)
                row += 1
            if led.get("Mode") in (R.LED_CYCLE, R.LED_BREATHING):
                speed = _scale(100, 10000, 100, 0, lambda v: _("{s} s").format(s=f"{v / 1000:g}"))
                speed.set_value(led.get("EffectDuration", 1000))
                later = _Debounce(250, self._guard(lambda v, led=led: led.set_duration(v)))
                speed.connect("value-changed", lambda s, later=later: None if self.loading else later(s.get_value()))
                g.attach(Gtk.Label(label=_("Effect length"), xalign=0), 0, row, 1, 1)
                g.attach(speed, 1, row, 1, 1)
                row += 1
        self.body.pack_start(frame, False, False, 0)

    # ---- actions
    def _make_profile_active(self, *_args):
        if self.profile:
            try:
                self.profile.make_active()
                for p in self.dev.profiles:
                    p.props["IsActive"] = p is self.profile
                self._device_chosen(self.combo)
                self.window.set_status(_("Profile switched"))
            except Exception as e:  # noqa: BLE001
                self.window.message(_("Could not switch profiles"), str(e))

    def _commit(self, *_args):
        if not self.dev:
            return
        try:
            self.dev.commit()
            self.window.set_status(_("Saved to the mouse"))
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not save to the mouse"), str(e))


# ---------------------------------------------------------------------------
class InputPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=stack, halign=Gtk.Align.CENTER, margin_top=12)
        self.pack_start(switcher, False, False, 0)
        self.pack_start(stack, True, True, 0)
        for tab, name, title in ((PointerTab, "pointer", _("Mouse & Touchpad")),
                                 (KeyboardTab, "keyboard", _("Keyboard")),
                                 (GamingMouseTab, "gaming", _("Gaming Mouse"))):
            try:
                widget = tab(window)
            except Exception as e:  # noqa: BLE001 - one broken tab must not take the page down
                traceback.print_exc()
                widget = _hint(_("This section could not be loaded: {error}").format(error=e))
            stack.add_titled(widget, name, title)
