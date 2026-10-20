"""The Controllers page: DualShock 4 light bar, polling rate, Xbox 360 emulation and buttons."""
import grp
import os
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import desktop as D, gyro as GY, pad_service as S, padmap as M, pads as P, widgets  # noqa: E402
from .desktop_page import _hint  # noqa: E402
from .i18n import N_, _  # noqa: E402

SOURCE_LABELS = {"cross": N_("Cross ✕"), "circle": N_("Circle ○"), "square": N_("Square □"),
                 "triangle": N_("Triangle △"), "l1": "L1", "r1": "R1", "l2": "L2", "r2": "R2",
                 "l3": N_("L3 (left stick click)"), "r3": N_("R3 (right stick click)"), "share": N_("Share"),
                 "options": N_("Options"), "ps": N_("PS button"), "touchpad": N_("Touchpad click"),
                 "dpad_up": N_("D-pad up"), "dpad_down": N_("D-pad down"), "dpad_left": N_("D-pad left"),
                 "dpad_right": N_("D-pad right")}
TARGET_LABELS = {"a": "A", "b": "B", "x": "X", "y": "Y", "lb": N_("LB (left bumper)"), "rb": N_("RB (right bumper)"),
                 "lt": N_("LT (left trigger)"), "rt": N_("RT (right trigger)"), "ls": N_("Left stick click"),
                 "rs": N_("Right stick click"), "back": N_("Back"), "start": N_("Start"), "guide": N_("Guide (Xbox)"),
                 "dpad_up": N_("D-pad up"), "dpad_down": N_("D-pad down"), "dpad_left": N_("D-pad left"),
                 "dpad_right": N_("D-pad right"), "none": N_("Nothing")}
SOURCE_LABELS["touch"] = N_("Touching the touchpad")
GYRO_OUTPUTS = [("off", N_("Off")), ("mouse", N_("As a mouse (most precise)")),
                ("stick", N_("As the right stick (works in every game)"))]
GYRO_MODES = [("always", N_("Always")), ("hold", N_("While holding")), ("toggle", N_("Press to switch on and off")),
              ("hold_off", N_("Off while holding"))]
GYRO_SPACES = [("player", N_("Around the way you face, however you hold it")), ("yaw", N_("Turning it flat (yaw)")),
               ("roll", N_("Tilting it sideways (roll)"))]
BT_RATES = [(0, N_("Leave it to the driver (250 Hz)")), (1, N_("1 ms (1000 Hz)")), (2, N_("2 ms (500 Hz)")),
            (4, N_("4 ms (250 Hz)")), (8, N_("8 ms (125 Hz)"))]
USB_RATES = [(0, N_("The controller's own (usually 250 Hz)")), (1, N_("1 ms (1000 Hz)")), (2, N_("2 ms (500 Hz)")),
             (4, N_("4 ms (250 Hz)")), (8, N_("8 ms (125 Hz)"))]


def _in_input_group():
    try:
        return grp.getgrnam("input").gr_gid in os.getgroups()
    except KeyError:
        return False


def _rgba(text):
    c = Gdk.RGBA()
    c.parse(text)
    return c


def _hex(c):
    return "#{:02x}{:02x}{:02x}".format(round(c.red * 255), round(c.green * 255), round(c.blue * 255))


class ControllersPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.c = S.load()
        self.loading = True
        self._timer = None
        self.labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        head = Gtk.Box(spacing=10)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>{}</b>".format(GLib.markup_escape_text(_("Use XControl for controllers"))))
        head.pack_start(lbl, False, False, 0)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", self._changed)
        head.pack_start(self.switch, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.pack_start(_hint(_("For DualShock 4 controllers (PS4), over USB or Bluetooth: light bar, report rate, "
                                "and an Xbox 360 controller for games, with your own button layout. Runs in the "
                                "background with the desktop service; stop sc-controller or DS4Windows-like tools "
                                "first, or both will drive the controller.")), False, False, 0)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.pack_start(self.status, False, False, 0)
        self.pads_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.pack_start(self.pads_box, False, False, 0)

        self.sections = []
        self._build_lightbar()
        self._build_rate()
        self._build_emulation()
        self._build_gyro()
        self._build_buttons()
        self._fill()
        widgets.protect(self)
        self.loading = False
        self.connect("map", lambda *_a: (self._sensitivity(), self._poll()))
        GLib.timeout_add_seconds(2, lambda: (self._poll() if self.get_mapped() else None) or True)

    def _section(self, title):
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        head = Gtk.Label(xalign=0)
        head.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        frame.set_label_widget(head)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_start=12, margin_top=8, margin_bottom=4)
        frame.add(grid)
        self.pack_start(frame, False, False, 0)
        self.sections.append(frame)
        return grid

    def _row(self, g, r, label, widget):
        lbl = Gtk.Label(label=label, xalign=0)
        self.labels.add_widget(lbl)
        g.attach(lbl, 0, r, 1, 1)
        g.attach(widget, 1, r, 1, 1)

    # ---------------------------------------------------------------- sections
    def _build_lightbar(self):
        g = self._section(_("Light bar"))
        self.color = Gtk.ColorButton(halign=Gtk.Align.START)
        self.color.props.use_alpha = False
        self.color.connect("color-set", self._lightbar_changed)
        self._row(g, 0, _("Color"), self.color)
        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.brightness.set_hexpand(True)
        self.brightness.set_value_pos(Gtk.PositionType.RIGHT)
        self.brightness.connect("format-value", lambda _s, v: _("Off") if v == 0 else f"{int(v)} %")
        self.brightness.connect("value-changed", self._lightbar_changed)
        self._row(g, 1, _("Brightness"), self.brightness)
        g.attach(_hint(_("A dimmer light bar makes a Bluetooth controller's battery last longer.")), 1, 2, 1, 1)

    def _build_rate(self):
        g = self._section(_("Report rate"))
        self.bt_rate = Gtk.ComboBoxText(hexpand=True)
        for ms, label in BT_RATES:
            self.bt_rate.append(str(ms), _(label))
        self.bt_rate.connect("changed", self._bt_rate_changed)
        self._row(g, 0, _("Over Bluetooth"), self.bt_rate)
        g.attach(_hint(_("How often the controller sends its state; it applies right away, and the rate it "
                         "really reaches shows above. Bluetooth itself usually tops out around 500–800 Hz, "
                         "depending on the adapter (Wi-Fi + Bluetooth cards share the radio). It's still "
                         "faster than the cable: over USB most DualShock 4s stay at 250 Hz whatever the "
                         "rate.")), 1, 1, 1, 1)
        usb = Gtk.Box(spacing=6)
        self.usb_rate = Gtk.ComboBoxText(hexpand=True)
        for ms, label in USB_RATES:
            self.usb_rate.append(str(ms), _(label))
        usb.pack_start(self.usb_rate, True, True, 0)
        self.usb_apply = Gtk.Button(label=_("Apply"))
        self.usb_apply.connect("clicked", self._usb_apply)
        usb.pack_start(self.usb_apply, False, False, 0)
        self._row(g, 2, _("Over USB"), usb)
        g.attach(_hint(_("Over USB the rate is set by Linux for every USB gamepad (usbhid's jspoll). Asks for "
                         "your password, kept for the next boots; a connected DualShock 4 reconnects to use it.")),
                 1, 3, 1, 1)

    def _build_emulation(self):
        g = self._section(_("For games"))
        self.emulate = Gtk.ComboBoxText(hexpand=True)
        self.emulate.append("xbox360", _("Show it as an Xbox 360 controller (works in almost every game)"))
        self.emulate.append("off", _("Leave it as a DualShock 4"))
        self.emulate.connect("changed", self._changed)
        self._row(g, 0, _("Games see"), self.emulate)
        self.hide_real = Gtk.CheckButton(label=_("Hide the DualShock 4 itself, so games don't see two controllers"))
        self.hide_real.connect("toggled", self._changed)
        g.attach(self.hide_real, 1, 1, 1, 1)
        self.touch_mouse = Gtk.CheckButton(label=_("The touchpad moves the mouse pointer"))
        self.touch_mouse.connect("toggled", self._changed)
        g.attach(self.touch_mouse, 1, 2, 1, 1)
        g.attach(_hint(_("Rumble from games reaches the DualShock 4. Steam reads controllers its own way: in Steam, "
                         "turn off PlayStation Configuration Support, or Steam sees the DualShock 4 as well.")),
                 1, 3, 1, 1)

    def _build_gyro(self):
        g = self._section(_("Gyro aiming"))
        self.gyro_out = Gtk.ComboBoxText(hexpand=True)
        for k, label in GYRO_OUTPUTS:
            self.gyro_out.append(k, _(label))
        self.gyro_out.connect("changed", self._changed)
        self._row(g, 0, _("Aim with it"), self.gyro_out)
        self.gyro_hint = _hint(_("Turn the controller to aim. As a mouse is the most precise, and most games take "
                                 "the mouse and the controller together; as the right stick works in every "
                                 "game, but the game's own stick deadzone and acceleration make it less exact."))
        g.attach(self.gyro_hint, 1, 1, 1, 1)
        self.gyro_rows = []

        def row(r, label, widget):
            lbl = Gtk.Label(label=label, xalign=0)
            self.labels.add_widget(lbl)
            g.attach(lbl, 0, r, 1, 1)
            g.attach(widget, 1, r, 1, 1)
            self.gyro_rows.append((lbl, widget))
            return lbl, widget

        when = Gtk.Box(spacing=6)
        self.gyro_mode = Gtk.ComboBoxText(hexpand=True)
        for k, label in GYRO_MODES:
            self.gyro_mode.append(k, _(label))
        self.gyro_mode.connect("changed", self._changed)
        when.pack_start(self.gyro_mode, True, True, 0)
        self.gyro_button = Gtk.ComboBoxText(hexpand=True)
        for src in S.ACTIVATORS:
            self.gyro_button.append(src, _(SOURCE_LABELS[src]))
        self.gyro_button.connect("changed", self._changed)
        when.pack_start(self.gyro_button, True, True, 0)
        row(2, _("When"), when)
        self.gyro_space = Gtk.ComboBoxText(hexpand=True)
        for k, label in GYRO_SPACES:
            self.gyro_space.append(k, _(label))
        self.gyro_space.connect("changed", self._changed)
        row(3, _("Turning"), self.gyro_space)
        self.gyro_sens = self._scale(0.5, 60, 0.5, 1, lambda v: _("{n} dots per degree").format(n=f"{v:g}"))
        self.sens_row = row(4, _("Speed"), self.gyro_sens)
        self.gyro_sens.set_tooltip_text(_("Mouse movement per degree you turn the controller; set it together "
                                          "with the game's mouse sensitivity."))
        self.gyro_stick_speed = self._scale(30, 720, 10, 0, lambda v: _("full stick at {n} °/s").format(n=int(v)))
        self.stick_speed_row = row(5, _("Stick speed"), self.gyro_stick_speed)
        self.gyro_dz = self._scale(0, 50, 1, 0, lambda v: f"{int(v)} %")
        self.dz_row = row(6, _("Game's deadzone"), self.gyro_dz)
        self.gyro_dz.set_tooltip_text(_("Set it to the game's own right-stick deadzone, so small turns aren't "
                                        "lost in it."))
        inv = Gtk.Box(spacing=12)
        self.gyro_inv_x = Gtk.CheckButton(label=_("Invert left/right"))
        self.gyro_inv_y = Gtk.CheckButton(label=_("Invert up/down"))
        for w in (self.gyro_inv_x, self.gyro_inv_y):
            w.connect("toggled", self._changed)
            inv.pack_start(w, False, False, 0)
        g.attach(inv, 1, 7, 1, 1)
        self.gyro_rows.append((inv,))
        cal = Gtk.Box(spacing=12)
        self.gyro_auto = Gtk.CheckButton(label=_("Correct its drift whenever it lies still"))
        self.gyro_auto.connect("toggled", self._changed)
        cal.pack_start(self.gyro_auto, False, False, 0)
        btn = Gtk.Button(label=_("Calibrate now"))
        btn.connect("clicked", self._calibrate)
        cal.pack_end(btn, False, False, 0)
        g.attach(cal, 1, 8, 1, 1)
        self.gyro_rows.append((cal,))
        cal_hint = _hint(_("Every gyro reads a little turning when there's none, which makes the aim creep. "
                           "Put the controller down on a flat surface and press Calibrate now (2 seconds), or "
                           "let it learn that whenever it lies still."))
        g.attach(cal_hint, 1, 9, 1, 1)
        self.gyro_rows.append((cal_hint,))
        self.stick_note = _hint(_("The right stick needs games to see the Xbox 360 controller (above)."))
        g.attach(self.stick_note, 1, 10, 1, 1)

    def _scale(self, lo, hi, step, digits, fmt):
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        sc.set_hexpand(True)
        sc.set_digits(digits)
        sc.set_value_pos(Gtk.PositionType.RIGHT)
        sc.connect("format-value", lambda _w, v: fmt(v))
        sc.connect("value-changed", self._changed)
        return sc

    def _calibrate(self, *_a):
        if S.calibrate_running():
            self.window.set_status(_("Calibrating the gyro: leave the controller still for 2 seconds"))
            GLib.timeout_add(2500, lambda: self._poll() and False)
        else:
            self.window.set_status(_("The controller service isn't running"))

    def _build_buttons(self):
        g = self._section(_("Buttons"))
        self.button_grid = g
        self.maps = {}
        half = (len(M.SOURCE_ORDER) + 1) // 2
        for i, src in enumerate(M.SOURCE_ORDER):
            col, row = (0, i) if i < half else (2, i - half)
            lbl = Gtk.Label(label=_(SOURCE_LABELS[src]), xalign=0)
            g.attach(lbl, col, row, 1, 1)
            combo = Gtk.ComboBoxText(hexpand=True)
            for t in M.TARGET_ORDER:
                combo.append(t, _(TARGET_LABELS[t]))
            combo.connect("changed", self._changed)
            g.attach(combo, col + 1, row, 1, 1)
            self.maps[src] = combo
        reset = Gtk.Button(label=_("Default layout"), halign=Gtk.Align.START)
        reset.connect("clicked", self._reset_map)
        g.attach(reset, 1, half, 1, 1)
        g.attach(_hint(_("Each DualShock 4 button can be any Xbox button, or nothing. L2 and R2 stay analog while "
                         "they're the triggers.")), 1, half + 1, 3, 1)

    # ---------------------------------------------------------------- values
    def _fill(self):
        c = self.c
        self.loading = True
        self.switch.set_active(c["enabled"])
        self.color.set_rgba(_rgba(c["lightbar"]))
        self.brightness.set_value(c["brightness"])
        self.bt_rate.set_active_id(str(c["bt_poll_ms"]) if str(c["bt_poll_ms"]) in
                                   [str(m) for m, _l in BT_RATES] else "1")
        jspoll = P.usb_jspoll()
        self.usb_rate.set_active_id(str(jspoll) if jspoll is not None and str(jspoll) in
                                    [str(m) for m, _l in USB_RATES] else "0")
        self.usb_apply.set_sensitive(P.can_set_usb_poll() and jspoll is not None)
        self.emulate.set_active_id(c["emulate"])
        self.hide_real.set_active(c["hide_real"])
        self.touch_mouse.set_active(c["touchpad_mouse"])
        for src, combo in self.maps.items():
            combo.set_active_id(c["map"][src])
        gy = c["gyro"]
        self.gyro_out.set_active_id(gy["output"])
        self.gyro_mode.set_active_id(gy["mode"])
        self.gyro_button.set_active_id(gy["button"])
        self.gyro_space.set_active_id(gy["space"])
        self.gyro_sens.set_value(gy["sens"])
        self.gyro_stick_speed.set_value(gy["stick_speed"])
        self.gyro_dz.set_value(gy["stick_dz"])
        self.gyro_inv_x.set_active(gy["invert_x"])
        self.gyro_inv_y.set_active(gy["invert_y"])
        self.gyro_auto.set_active(gy["auto_cal"])
        self._sensitivity()
        self.loading = False

    def _sensitivity(self):
        on = self.switch.get_active()
        for s in self.sections:
            s.set_sensitive(on)
        emu = self.emulate.get_active_id() == "xbox360"
        self.hide_real.set_sensitive(emu)
        self.touch_mouse.set_sensitive(emu)
        self.button_grid.set_sensitive(emu)
        out = self.gyro_out.get_active_id() or "off"
        for widgets_ in self.gyro_rows:
            for w in widgets_:
                w.set_visible(out != "off")
        self.gyro_button.set_sensitive(self.gyro_mode.get_active_id() != "always")
        for w in self.sens_row:
            w.set_visible(out == "mouse")
        for w in self.stick_speed_row + self.dz_row:
            w.set_visible(out == "stick")
        self.stick_note.set_visible(out == "stick" and not emu)

    def _changed(self, *_a):
        if self.loading:
            return
        c = self.c
        c["enabled"] = self.switch.get_active()
        c["emulate"] = self.emulate.get_active_id() or "xbox360"
        c["hide_real"] = self.hide_real.get_active()
        c["touchpad_mouse"] = self.touch_mouse.get_active()
        c["map"] = {src: combo.get_active_id() or "none" for src, combo in self.maps.items()}
        c["gyro"] = GY.normalize({
            "output": self.gyro_out.get_active_id(), "mode": self.gyro_mode.get_active_id(),
            "button": self.gyro_button.get_active_id(), "space": self.gyro_space.get_active_id(),
            "sens": self.gyro_sens.get_value(), "stick_speed": self.gyro_stick_speed.get_value(),
            "stick_dz": self.gyro_dz.get_value(), "invert_x": self.gyro_inv_x.get_active(),
            "invert_y": self.gyro_inv_y.get_active(), "auto_cal": self.gyro_auto.get_active()}, S.ACTIVATORS)
        self._sensitivity()
        self._commit_later()

    def _commit_later(self, delay=500):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(delay, self._commit)

    def _commit(self):
        self._timer = None
        try:
            S.save(S.normalize(self.c))
            D.notify_daemon(D.load())    # starts, restarts or stops the controller service
            S.reload_running()           # the light bar and report rate apply in place
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not save the settings"), str(e))
            return False
        self.window.set_status(_("Applied"))
        GLib.timeout_add(1500, lambda: self._poll() and False)
        return False

    def _lightbar_changed(self, *_a):
        if self.loading:
            return
        self.c["lightbar"] = _hex(self.color.get_rgba())
        self.c["brightness"] = int(self.brightness.get_value())
        for pad in P.discover():     # right away, without restarting anything
            P.set_lightbar(pad, self.c["lightbar"], self.c["brightness"])
        self._commit_later()

    def _bt_rate_changed(self, *_a):
        if self.loading:
            return
        self.c["bt_poll_ms"] = int(self.bt_rate.get_active_id() or 0)
        for pad in P.discover():     # (when it's hidden, the service does it with the file it holds)
            P.set_bt_poll(pad, self.c["bt_poll_ms"])
        self._commit_later()

    def _usb_apply(self, *_a):
        ms = int(self.usb_rate.get_active_id() or 0)
        ok, msg = P.set_usb_poll(ms)
        if ok:
            self.window.set_status(_("USB polling changed"))
        elif msg:
            self.window.message(_("Could not change the USB polling"), msg)

    def _reset_map(self, *_a):
        self.loading = True
        for src, combo in self.maps.items():
            combo.set_active_id(M.DEFAULT_MAP[src])
        self.loading = False
        self._changed()

    # ---------------------------------------------------------------- status
    def _poll(self):
        st = S.state()
        found = P.discover()
        for child in self.pads_box.get_children():
            child.destroy()
        live = {p["key"]: p for p in st.get("pads", [])}
        if not found:
            self.pads_box.pack_start(_hint(_("No DualShock 4 connected. Plug it in, or pair it over Bluetooth "
                                             "(hold Share and PS until the light bar flashes).")), False, False, 0)
        notes = set()
        for pad in found:
            info = live.get(pad.key, {})
            pct, charging = P.battery(pad)
            parts = [_("USB") if pad.bus == "usb" else _("Bluetooth")]
            if pct is not None:
                parts.append(_("battery {pct} %").format(pct=pct) + (" ⚡" if charging == "Charging" else ""))
            if info.get("rate"):
                parts.append(_("reporting at {hz} Hz").format(hz=info["rate"]))
            if info.get("virtual"):
                parts.append(_("games see an Xbox 360 controller"))
            if info.get("hidden"):
                parts.append(_("hidden from games"))
            if info.get("gyro"):
                parts.append({"calibrating": _("calibrating the gyro…"), "calibrated": _("gyro calibrated"),
                              "uncalibrated": _("gyro not calibrated yet")}.get(info["gyro"], ""))
            if info.get("gyro_error"):
                notes.add(_("The gyro mouse couldn't be made: {error}").format(error=info["gyro_error"]))
            row = Gtk.Label(xalign=0, wrap=True)
            row.set_markup("<b>{}</b>  <span alpha='70%'>{}</span>".format(
                GLib.markup_escape_text(pad.name), GLib.markup_escape_text(" · ".join(parts))))
            self.pads_box.pack_start(row, False, False, 0)
            if info.get("error"):
                notes.add(_("The controller service: {error}").format(error=info["error"]))
            if info.get("hide_error"):
                notes.add(_("Couldn't hide the DualShock 4 from games: {error}").format(error=info["hide_error"]))
            if info.get("hidden") and _in_input_group():
                notes.add(_("You're in the \"input\" group, which lets every program read every input device, "
                            "so games can still find the DualShock 4. Leave the group (gpasswd -d $USER input, "
                            "then log in again) to hide it."))
            if not P.lightbar_writable(pad):
                notes.add(_("The light bar can't be changed yet: XControl's device permissions apply after the "
                            "controller is reconnected (or after a reboot, right after installing)."))
            if info.get("hidden"):
                continue     # its files are deliberately off-limits now; the service has them open
            if any(n and not os.access(n, os.R_OK) for n in (pad.gamepad, pad.sensors, pad.touchpad)):
                notes.add(_("The touchpad and motion sensors can't be read yet: reconnect the controller so "
                            "XControl's device permissions apply."))
            if pad.bus == "bluetooth" and not P.hidraw_writable(pad):
                notes.add(_("The Bluetooth report rate can't be set yet: reconnect the controller so XControl's "
                            "device permissions apply."))
        for n in sorted(notes):
            self.pads_box.pack_start(_hint(n), False, False, 0)
        self.pads_box.show_all()
        if not self.c["enabled"]:
            text = ""
        elif st:
            text = _("The controller service is running.")
        else:
            errors = D.state().get("errors") or {}
            text = _("The controller service isn't running: {why}").format(why=errors["pads"]) if errors.get("pads") \
                else _("The controller service is starting…")
        self.status.set_text(text)
        self.status.set_visible(bool(text))
        return False
