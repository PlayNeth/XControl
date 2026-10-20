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
        top = Gtk.Box(spacing=10)
        self.status = _hint("")
        top.pack_start(self.status, True, True, 0)
        self.mixer = Gtk.Button(label=_("Open the mixer"), valign=Gtk.Align.START)
        self.mixer.set_tooltip_text(_("Volumes, the default output and input, ports and card profiles"))
        self.mixer.connect("clicked", self._open_mixer)
        top.pack_start(self.mixer, False, False, 0)
        self.pack_start(top, False, False, 0)
        self.dev_box = self._section(_("Devices"))
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
        sig = repr((srv, [(o["name"], o.get("description")) for o in outs], [(i["name"], i.get("description"))
                                                                             for i in ins],
                    [c["name"] for c in cards], self.a))
        self._status(srv)
        if sig == self._sig and not force:
            return
        self._sig = sig
        self.loading = True
        self._fill_devices(outs, ins, cards)
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

    def _fill_devices(self, outs, ins, cards):
        box = self.dev_box
        self._clear(box)
        box.pack_start(_hint(_("What the mixer can't do: give a device your own name, hide it from every program, "
                               "keep it from sleeping, or prefer it whenever it's connected.")), False, False, 0)
        groups = [
            (_("Outputs"), [(o["name"], o.get("description") or o["name"]) for o in outs], "alsa_output.", False, True),
            (_("Inputs"), [(i["name"], i.get("description") or i["name"]) for i in ins], "alsa_input.", False, False),
            (_("Sound cards"), [(c["name"], (c.get("properties") or {}).get("device.description") or c["name"])
                                for c in cards], "alsa_card.", True, False),
        ]
        for title, devs, prefix, is_card, is_output in groups:
            present = {n for n, _d in devs}
            hidden = [n for n, d in self.a["devices"].items() if d["hidden"] and n.startswith(prefix)
                      and n not in present]
            if not devs and not hidden:
                continue
            head = Gtk.Label(xalign=0, margin_top=4)
            head.set_markup("<small><b>{}</b></small>".format(GLib.markup_escape_text(title)))
            head.get_style_context().add_class("dim-label")
            box.pack_start(head, False, False, 0)
            for name, desc in devs:
                box.pack_start(self._device_row(name, desc, is_card, is_output, hidden=False), False, False, 0)
            for name in hidden:
                desc = self.a["devices"][name]["name"] or name
                box.pack_start(self._device_row(name, desc, is_card, is_output, hidden=True), False, False, 0)
        if len(box.get_children()) == 1:
            box.pack_start(_hint(_("None found.")), False, False, 0)
        box.show_all()

    def _device_row(self, name, desc, is_card, is_output, hidden):
        row = Gtk.Box(spacing=8)
        entry = self.a["devices"].get(name, {})
        notes = []
        if hidden:
            notes.append(_("not used"))
        if entry.get("no_suspend") or (self.a["no_suspend"] and not is_card):
            notes.append(_("never sleeps"))
        if entry.get("priority") is not None:
            notes.append(_("preferred"))
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(GLib.markup_escape_text(desc) + ("  <span alpha='60%'>{}</span>".format(
            GLib.markup_escape_text(" · ".join(notes))) if notes else ""))
        lbl.set_tooltip_text(name)
        if hidden:
            lbl.get_style_context().add_class("dim-label")
        row.pack_start(lbl, True, True, 0)
        row.pack_start(self._gear(name, desc, is_card, is_output), False, False, 0)
        return row

    def _open_mixer(self, *_a):
        import shutil
        import subprocess
        mixer = next((m for m in ("pavucontrol", "pwvucontrol", "pavucontrol-qt") if shutil.which(m)), None)
        if mixer is None:
            self.window.message(_("No mixer installed"), _("Install pavucontrol (or pwvucontrol)."))
            return
        subprocess.Popen([mixer], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
