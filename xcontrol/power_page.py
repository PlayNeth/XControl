"""The Power page: sleeping when idle, the power and sleep buttons, power profiles."""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import desktop as D, power as P, widgets  # noqa: E402
from .desktop_page import _hint  # noqa: E402
from .i18n import N_, _  # noqa: E402

SLEEP_CHOICES = [0, 10, 15, 20, 30, 45, 60, 90, 120, 180]
ACTION_LABELS = {"poweroff": N_("Shut down"), "suspend": N_("Sleep (suspend)"), "hibernate": N_("Hibernate"),
                 "hybrid-sleep": N_("Hybrid sleep"), "suspend-then-hibernate": N_("Sleep, then hibernate"),
                 "lock": N_("Lock the screen"), "reboot": N_("Restart"), "ignore": N_("Nothing")}
BUTTON_LABELS = {"HandlePowerKey": N_("Power button"), "HandleSuspendKey": N_("Sleep key"),
                 "HandleHibernateKey": N_("Hibernate key"), "HandleLidSwitch": N_("Closing the lid"),
                 "HandleLidSwitchExternalPower": N_("Closing the lid, plugged in"),
                 "HandleLidSwitchDocked": N_("Closing the lid, with a monitor connected")}
PROFILE_LABELS = {"power-saver": (N_("Power saver"), N_("Quieter and cooler, slower")),
                  "balanced": (N_("Balanced"), N_("The usual")),
                  "performance": (N_("Performance"), N_("Fastest, louder and warmer"))}


def _minutes(n):
    if n == 0:
        return _("Never")
    if n % 60 == 0:
        h = n // 60
        return (_("After {n} hour") if h == 1 else _("After {n} hours")).format(n=h)
    return _("After {n} minutes").format(n=n)


class PowerPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.desk = D.load()
        self.loading = True
        self.labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        self._build_sleep()
        self._build_buttons()
        self._build_profiles()
        self.connect("map", lambda *_a: self._refresh())
        widgets.protect(self)
        self.loading = False

    def _section(self, title):
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        head = Gtk.Label(xalign=0)
        head.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        frame.set_label_widget(head)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_start=12, margin_top=8, margin_bottom=4)
        frame.add(grid)
        self.pack_start(frame, False, False, 0)
        return grid

    def _row(self, g, r, label, widget):
        lbl = Gtk.Label(label=label, xalign=0)
        self.labels.add_widget(lbl)
        g.attach(lbl, 0, r, 1, 1)
        g.attach(widget, 1, r, 1, 1)
        return lbl

    # ---------------------------------------------------------------- sleep
    def _build_sleep(self):
        g = self._section(_("Sleep"))
        self.sleep = Gtk.ComboBoxText(hexpand=True)
        for n in SLEEP_CHOICES:
            self.sleep.append(str(n), _minutes(n))
        self.sleep.connect("changed", self._sleep_changed)
        self._row(g, 0, _("Sleep when idle"), self.sleep)
        self.not_sound = Gtk.CheckButton(label=_("Not while sound is playing (music, a video call)"))
        self.not_sound.connect("toggled", self._sleep_changed)
        g.attach(self.not_sound, 1, 1, 1, 1)
        g.attach(_hint(_("Counted from the last time you used the mouse, keyboard or a gamepad. Nothing sleeps "
                         "while the screen is kept on (Desktop page, Keep the screen on). The screen lock, if it's "
                         "on, locks first.")), 1, 2, 1, 1)
        self.sleep_note = _hint("")
        g.attach(self.sleep_note, 1, 3, 1, 1)
        sleep_now = Gtk.Button(label=_("Sleep now"), halign=Gtk.Align.START)
        sleep_now.connect("clicked", lambda *_a: P.suspend() or self.window.message(
            _("Could not sleep"), _("systemd-logind refused, or something is holding sleep off.")))
        g.attach(sleep_now, 1, 4, 1, 1)

    def _sleep_changed(self, *_a):
        if self.loading:
            return
        p = self.desk["power"]
        p["sleep_minutes"] = int(self.sleep.get_active_id() or 0)
        p["not_while_sound"] = self.not_sound.get_active()
        try:
            fresh = D.load()
            fresh["power"] = P.normalize(p)
            D.save(fresh)
            D.notify_daemon(fresh)
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not save the settings"), str(e))
            return
        self.window.set_status(_("Applied"))

    # ---------------------------------------------------------------- buttons
    def _build_buttons(self):
        g = self._section(_("Buttons"))
        self.button_grid = g
        self.combos = {}
        self.button_labels = {}
        for r, key in enumerate(P.BUTTON_KEYS):
            combo = Gtk.ComboBoxText(hexpand=True)
            for a in P.ACTIONS:
                combo.append(a, _(ACTION_LABELS[a]))
            self.combos[key] = combo
            self.button_labels[key] = self._row(g, r, _(BUTTON_LABELS[key]), combo)
        bb = Gtk.Box(spacing=6)
        self.apply = Gtk.Button(label=_("Apply"))
        self.apply.get_style_context().add_class("suggested-action")
        self.apply.connect("clicked", self._apply_buttons)
        bb.pack_end(self.apply, False, False, 0)
        g.attach(bb, 1, len(P.BUTTON_KEYS), 1, 1)
        self.buttons_note = _hint("")
        g.attach(self.buttons_note, 1, len(P.BUTTON_KEYS) + 1, 1, 1)

    def _apply_buttons(self, *_a):
        values = {k: c.get_active_id() for k, c in self.combos.items()
                  if c.get_active_id() and c.get_active_id() != P.LOGIND_DEFAULTS.get(k)}
        ok, msg = P.set_buttons(values)
        if ok:
            self.window.set_status(_("Saved"))
        elif msg:
            self.window.message(_("Could not change the buttons"), msg)
        GLib.timeout_add(800, lambda: self._refresh() and False)

    # ---------------------------------------------------------------- profiles
    def _build_profiles(self):
        g = self._section(_("Power profile"))
        self.profile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        g.attach(self.profile_box, 0, 0, 2, 1)

    def _fill_profiles(self):
        for c in self.profile_box.get_children():
            c.destroy()
        info = P.profiles()
        if info is None:
            self.profile_box.pack_start(_hint(_("Install power-profiles-daemon (or tuned-ppd) to switch between "
                                                "power saver, balanced and performance.")), False, False, 0)
        else:
            active, names, degraded = info
            group = None
            for n in names:
                label, about = PROFILE_LABELS.get(n, (n, ""))
                rb = Gtk.RadioButton.new_from_widget(group)
                group = group or rb
                lbl = Gtk.Label(xalign=0)
                lbl.set_markup("{}  <span alpha='65%'>{}</span>".format(
                    GLib.markup_escape_text(_(label)), GLib.markup_escape_text(_(about) if about else "")))
                rb.add(lbl)
                rb.set_active(n == active)
                rb.connect("toggled", self._profile, n)
                self.profile_box.pack_start(rb, False, False, 0)
            if degraded:
                self.profile_box.pack_start(_hint(_("Performance is held back right now ({why}).").format(
                    why=degraded)), False, False, 0)
        self.profile_box.show_all()

    def _profile(self, rb, name):
        if self.loading or not rb.get_active():
            return

        def done(err):
            if err:
                GLib.idle_add(lambda: self.window.message(_("Could not change the profile"), err) and False)
            else:
                GLib.idle_add(lambda: self.window.set_status(_("Power profile changed")) and False)
        P.set_profile(name, done)

    # ---------------------------------------------------------------- refresh
    def _refresh(self):
        self.loading = True
        p = self.desk["power"]
        if not self.sleep.set_active_id(str(p["sleep_minutes"])):
            self.sleep.append(str(p["sleep_minutes"]), _minutes(p["sleep_minutes"]))
            self.sleep.set_active_id(str(p["sleep_minutes"]))
        self.not_sound.set_active(p["not_while_sound"])
        can = P.can("Suspend")
        self.sleep_note.set_text(_("This computer can't sleep (systemd-logind says no).") if can == "no" else "")
        self.sleep_note.set_visible(can == "no")

        current = P.buttons()
        lid = P.has_lid()
        for key, combo in self.combos.items():
            combo.set_active_id(current.get(key) or P.LOGIND_DEFAULTS.get(key, "ignore"))
            show = lid or "Lid" not in key
            combo.set_visible(show)
            self.button_labels[key].set_visible(show)
            combo.set_sensitive(bool(current) and P.can_set_buttons())
        self.apply.set_sensitive(bool(current) and P.can_set_buttons())
        notes = []
        if not current:
            notes.append(_("systemd-logind isn't reachable, so the buttons can't be read or changed here."))
        elif not P.can_set_buttons():
            notes.append(_("Changing them needs pkexec (polkit)."))
        else:
            notes.append(_("Saved for the whole computer (/etc/systemd/logind.conf.d), asks for your password."))
        self.buttons_note.set_text(" ".join(notes))
        self._fill_profiles()
        self.loading = False
