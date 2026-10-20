"""The Sound page: outputs, inputs, device profiles and PipeWire's own settings."""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import audio as A, widgets  # noqa: E402
from .desktop_page import _hint  # noqa: E402
from .i18n import N_, _  # noqa: E402

RATE_LABELS = {0: N_("Automatic (48 kHz)"), 44100: "44.1 kHz", 48000: "48 kHz", 88200: "88.2 kHz",
               96000: "96 kHz", 176400: "176.4 kHz", 192000: "192 kHz"}
LATENCY_LABELS = {"default": N_("Normal (PipeWire's default)"),
                  "safe": N_("Larger: fixes crackling and dropouts"),
                  "low": N_("Small: less delay for games and music"),
                  "lowest": N_("Smallest: for recording and live music (may crackle)")}


class DeviceDialog(Gtk.Dialog):
    def __init__(self, parent, title, entry, is_card, is_output):
        super().__init__(title=title, transient_for=parent, modal=True)
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = self.add_button(_("Apply"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(14)
        g = Gtk.Grid(column_spacing=12, row_spacing=8)
        box.pack_start(g, False, False, 0)
        g.attach(Gtk.Label(label=_("Name"), xalign=0), 0, 0, 1, 1)
        self.name = Gtk.Entry(text=entry.get("name", ""), hexpand=True, width_chars=32)
        self.name.set_placeholder_text(_("The name the driver gives"))
        g.attach(self.name, 1, 0, 1, 1)
        self.hidden = Gtk.CheckButton(label=_("Don't use this device") if is_card else
                                      (_("Don't use this output") if is_output else _("Don't use this input")),
                                      active=entry.get("hidden", False))
        g.attach(self.hidden, 1, 1, 1, 1)
        self.awake = Gtk.CheckButton(label=_("Never let it sleep (no pop, and no lost first second of sound)"),
                                     active=entry.get("no_suspend", False))
        self.prefer = Gtk.CheckButton(label=_("Prefer it whenever it's connected"),
                                      active=entry.get("priority") is not None)
        if not is_card:
            g.attach(self.awake, 1, 2, 1, 1)
            g.attach(self.prefer, 1, 3, 1, 1)
        g.attach(_hint(_("Hidden devices disappear from every program. Changes restart WirePlumber, which takes a "
                         "second.")), 1, 4, 1, 1)
        self.show_all()

    def entry(self):
        return {"name": self.name.get_text().strip(), "hidden": self.hidden.get_active(),
                "no_suspend": self.awake.get_active(), "priority": 3000 if self.prefer.get_active() else None}


class AudioPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.a = A.load()
        self.loading = True
        self._sig = None
        self.status = _hint("")
        self.pack_start(self.status, False, False, 0)
        self.out_box = self._section(_("Output"))
        self.in_box = self._section(_("Input"))
        self.card_box = self._section(_("Devices"))
        self._build_system()
        self.connect("map", lambda *_a: self._refresh(force=True))
        GLib.timeout_add_seconds(3, lambda: (self._refresh() if self.get_mapped() else None) or True)
        widgets.protect(self)
        self.loading = False

    def _section(self, title, grid=False):
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        head = Gtk.Label(xalign=0)
        head.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        frame.set_label_widget(head)
        inner = Gtk.Grid(column_spacing=12, row_spacing=8, margin_start=12, margin_top=8, margin_bottom=4) if grid \
            else Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=12, margin_top=8,
                         margin_bottom=4)
        frame.add(inner)
        self.pack_start(frame, False, False, 0)
        return inner

    # ---------------------------------------------------------------- PipeWire settings
    def _build_system(self):
        g = self._section(_("Sound system (PipeWire)"), grid=True)
        self.sys_grid = g
        self.rate = Gtk.ComboBoxText()
        for r in [0] + A.RATES:
            self.rate.append(str(r), _(RATE_LABELS[r]))
        self.rate.connect("changed", self._sys_changed)
        g.attach(Gtk.Label(label=_("Sample rate"), xalign=0), 0, 0, 1, 1)
        g.attach(self.rate, 1, 0, 1, 1)
        self.follow = Gtk.CheckButton(label=_("Follow what's playing (44.1 kHz music plays at 44.1 kHz, unconverted)"))
        self.follow.connect("toggled", self._sys_changed)
        g.attach(self.follow, 1, 1, 1, 1)
        self.latency = Gtk.ComboBoxText(hexpand=True)
        for k in A.LATENCY:
            self.latency.append(k, _(LATENCY_LABELS[k]))
        self.latency.connect("changed", self._sys_changed)
        g.attach(Gtk.Label(label=_("Buffer size"), xalign=0), 0, 2, 1, 1)
        g.attach(self.latency, 1, 2, 1, 1)
        self.no_suspend = Gtk.CheckButton(label=_("Keep all outputs awake (no pops, no cut-off first second; "
                                                  "HDMI and USB DACs)"))
        self.no_suspend.connect("toggled", self._sys_changed)
        g.attach(self.no_suspend, 1, 3, 1, 1)
        g.attach(_hint(_("Sample rate and buffer size change right away; the rest restarts WirePlumber. Saved in "
                         "~/.config/pipewire and ~/.config/wireplumber.")), 1, 4, 1, 1)

    def _fill_system(self):
        self.loading, was = True, self.loading
        self.rate.set_active_id(str(self.a["rate"]))
        self.follow.set_active(self.a["follow_rate"])
        self.latency.set_active_id(self.a["latency"])
        self.no_suspend.set_active(self.a["no_suspend"])
        self.loading = was

    def _sys_changed(self, *_a):
        if self.loading:
            return
        self.a["rate"] = int(self.rate.get_active_id() or 0)
        self.a["follow_rate"] = self.follow.get_active()
        self.a["latency"] = self.latency.get_active_id() or "default"
        self.a["no_suspend"] = self.no_suspend.get_active()
        self._commit(live_clock=True)

    def _commit(self, live_clock=False):
        a = A.normalize(self.a)
        try:
            A.save(a)
            changed = A.write(a)
        except OSError as e:
            self.window.message(_("Could not save the settings"), str(e))
            return
        if live_clock:
            A.apply_clock_live(a)
        if "wireplumber" in changed and not A.restart(changed):
            self.window.message(_("Saved"), _("Restart WirePlumber (or log in again) to use it: "
                                              "systemctl --user restart wireplumber"))
        self.window.set_status(_("Applied"))
        GLib.timeout_add(1500, lambda: self._refresh(force=True) and False)

    # ---------------------------------------------------------------- devices
    def _clear(self, box):
        for c in box.get_children():
            c.destroy()

    def _refresh(self, force=False):
        srv = A.server()
        outs, ins, cards = (A.outputs(), A.inputs(), A.cards()) if srv else ([], [], [])
        sig = repr((srv, [(o["name"], o.get("description"), o.get("active_port")) for o in outs],
                    [(i["name"], i.get("description"), i.get("active_port")) for i in ins],
                    [(c["name"], c.get("active_profile")) for c in cards], A.default("sink"), A.default("source"),
                    sorted(self.a["devices"])))
        self._status(srv)
        if sig == self._sig and not force:
            return
        self._sig = sig
        self.loading = True
        self._fill_list(self.out_box, outs, "sink", True)
        self._fill_list(self.in_box, ins, "source", False)
        self._fill_cards(cards)
        self._fill_system()
        self.loading = False

    def _status(self, srv):
        if not srv:
            self.status.set_text(_("No sound server answers (PipeWire with pipewire-pulse, or PulseAudio)."))
            return
        name, pw = srv
        parts = [f"PipeWire {pw}" if pw else name]
        wp = A.wireplumber_version()
        if wp:
            parts.append("WirePlumber {}.{}".format(*wp))
        c = A.clock()
        if c.get("rate"):
            q = c.get("force_quantum") or c.get("quantum")
            ms = q / c["rate"] * 1000
            parts.append(_("running at {rate} Hz, {q} samples ({ms:.1f} ms)").format(rate=c["rate"], q=q, ms=ms))
        if not pw:
            parts.append(_("(PipeWire's own settings below need PipeWire)"))
        self.status.set_text(" · ".join(parts))
        self.sys_grid.set_sensitive(bool(pw))

    def _fill_list(self, box, devs, kind, is_output):
        self._clear(box)
        current = A.default(kind)
        group = None
        hidden = [n for n, d in self.a["devices"].items() if d["hidden"] and not n.startswith("alsa_card.")
                  and n.startswith("alsa_output." if is_output else "alsa_input.")]
        if not devs and not hidden:
            box.pack_start(_hint(_("None found.")), False, False, 0)
        for d in devs:
            row = Gtk.Box(spacing=8)
            rb = Gtk.RadioButton.new_with_label_from_widget(group, d.get("description") or d["name"])
            group = group or rb
            rb.set_active(d["name"] == current)
            rb.connect("toggled", self._default_chosen, kind, d["name"])
            rb.set_tooltip_text(d["name"])
            row.pack_start(rb, True, True, 0)
            ports = [p for p in d.get("ports") or [] if p.get("availability") != "not available"]
            if len(ports) > 1:
                pc = Gtk.ComboBoxText()
                for p in ports:
                    pc.append(p["name"], p.get("description") or p["name"])
                pc.set_active_id(d.get("active_port") or "")
                pc.connect("changed", self._port, kind, d["name"])
                row.pack_start(pc, False, False, 0)
            if is_output:
                test = Gtk.Button(label=_("Test"))
                test.connect("clicked", self._test, d["name"])
                row.pack_start(test, False, False, 0)
            row.pack_start(self._gear(d["name"], d.get("description") or d["name"], False, is_output), False, False, 0)
            box.pack_start(row, False, False, 0)
        for n in hidden:
            row = Gtk.Box(spacing=8)
            lbl = Gtk.Label(label=_("{name} (not used)").format(name=self.a["devices"][n]["name"] or n), xalign=0)
            lbl.get_style_context().add_class("dim-label")
            row.pack_start(lbl, True, True, 0)
            row.pack_start(self._gear(n, n, False, is_output), False, False, 0)
            box.pack_start(row, False, False, 0)
        box.show_all()

    def _fill_cards(self, cards):
        box = self.card_box
        self._clear(box)
        names = {c["name"] for c in cards}
        for c in cards:
            row = Gtk.Box(spacing=8)
            desc = (c.get("properties") or {}).get("device.description") or c["name"]
            lbl = Gtk.Label(label=desc, xalign=0)
            lbl.set_tooltip_text(c["name"])
            row.pack_start(lbl, True, True, 0)
            profiles = c.get("profiles") or {}
            combo = Gtk.ComboBoxText()
            for pname, p in sorted(profiles.items(), key=lambda kv: -(kv[1].get("priority") or 0)):
                if p.get("available", True) or pname == c.get("active_profile"):
                    combo.append(pname, p.get("description") or pname)
            combo.set_active_id(c.get("active_profile") or "")
            combo.connect("changed", self._profile, c["name"])
            row.pack_start(combo, False, False, 0)
            row.pack_start(self._gear(c["name"], desc, True, False), False, False, 0)
            box.pack_start(row, False, False, 0)
        for n, d in self.a["devices"].items():
            if n.startswith("alsa_card.") and d["hidden"] and n not in names:
                row = Gtk.Box(spacing=8)
                lbl = Gtk.Label(label=_("{name} (not used)").format(name=d["name"] or n), xalign=0)
                lbl.get_style_context().add_class("dim-label")
                row.pack_start(lbl, True, True, 0)
                row.pack_start(self._gear(n, n, True, False), False, False, 0)
                box.pack_start(row, False, False, 0)
        if not box.get_children():
            box.pack_start(_hint(_("None found.")), False, False, 0)
        box.pack_start(_hint(_("A profile picks how a device is used, e.g. stereo or surround, with or without its "
                               "microphone, or which HDMI output carries sound.")), False, False, 0)
        box.show_all()

    def _gear(self, name, title, is_card, is_output):
        b = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_tooltip_text(_("Name, hide, keep awake"))
        b.set_sensitive(name.startswith(("alsa_card.", "alsa_output.", "alsa_input.")))
        b.connect("clicked", self._device_settings, name, title, is_card, is_output)
        return b

    def _device_settings(self, _b, name, title, is_card, is_output):
        dlg = DeviceDialog(self.get_toplevel(), title, self.a["devices"].get(name, {}), is_card, is_output)
        if dlg.run() == Gtk.ResponseType.OK:
            self.a["devices"][name] = dlg.entry()
            self.a = A.normalize(self.a)
            self._commit()
        dlg.destroy()

    def _test(self, _b, name):
        if not A.test_sound(name):
            self.window.message(_("No test sound"), _("Install sound-theme-freedesktop and libpulse (paplay)."))

    def _port(self, combo, kind, name):
        if not self.loading and combo.get_active_id():
            A.set_port(kind, name, combo.get_active_id())

    def _profile(self, combo, card):
        if not self.loading and combo.get_active_id():
            A.set_profile(card, combo.get_active_id())

    def _default_chosen(self, rb, kind, name):
        if self.loading or not rb.get_active():
            return
        A.set_default(kind, name)
        self.window.set_status(_("Default changed"))
