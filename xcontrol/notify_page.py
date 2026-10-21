"""The Notifications page: XControl's own dunst setup."""
import os
import shutil
import signal

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import desktop as D, notify as N, poweralerts as PA, widgets  # noqa: E402
from .desktop_page import _command  # noqa: E402
from .i18n import N_, _  # noqa: E402
from .panel_page import _hex, _hint, _rgba, _scale  # noqa: E402

POS_LABELS = {"top-left": N_("Top left"), "top-center": N_("Top center"), "top-right": N_("Top right"),
              "left-center": N_("Left, middle"), "center": N_("Center"), "right-center": N_("Right, middle"),
              "bottom-left": N_("Bottom left"), "bottom-center": N_("Bottom center"),
              "bottom-right": N_("Bottom right")}
FOLLOW_LABELS = {"keyboard": N_("The one with the focused window"), "mouse": N_("The one with the mouse pointer"),
                 "none": N_("Always the first one")}
ICON_LABELS = {"left": N_("Left"), "right": N_("Right"), "top": N_("Above the text"), "off": N_("No icons")}
ALIGN_LABELS = {"left": N_("Left"), "center": N_("Center"), "right": N_("Right")}
FORMAT_LABELS = {"title_body": N_("Title and text"), "app_title_body": N_("App name, title and text"),
                 "title": N_("Title only"), "title_body_progress": N_("Title, progress and text"),
                 "custom": N_("Custom…")}
CLICK_LABELS = {"close_current": N_("Close it"), "do_action, close_current": N_("Open it (default action)"),
                "close_all": N_("Close all"), "context": N_("Choose an action from a menu"),
                "open_url": N_("Open its link"), "none": N_("Nothing")}
URGENCY_LABELS = {"low": N_("Low"), "normal": N_("Normal"), "critical": N_("Critical")}
RULE_LABELS = {"hide": N_("Don't show, don't keep"), "history_only": N_("Only keep in the history"),
               "no_timeout": N_("Stay until clicked"), "low": N_("Treat as low"), "critical": N_("Treat as critical"),
               "no_sound": N_("No sound")}
AGE_CHOICES = [(-1, N_("Never")), (30, N_("After 30 seconds")), (60, N_("After 1 minute")),
               (300, N_("After 5 minutes"))]
IDLE_CHOICES = [(0, N_("Off")), (60, N_("After 1 minute")), (120, N_("After 2 minutes")),
                (300, N_("After 5 minutes"))]


def _combo(labels, keys=None):
    w = Gtk.ComboBoxText()
    for k in keys or labels:
        w.append(str(k), _(labels[k]))
    return w


def _spin(lo, hi, step=1):
    s = Gtk.SpinButton.new_with_range(lo, hi, step)
    s.set_halign(Gtk.Align.START)
    return s


class NotifyPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.desk = D.load()
        self.n = self.desk["notify"]
        self.pa = self.desk["power_alerts"]
        self.loading = True
        self._timer = None
        self._version = None
        self.labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        head = Gtk.Box(spacing=10)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>{}</b>".format(GLib.markup_escape_text(_("Use XControl's notifications (dunst)"))))
        head.pack_start(lbl, False, False, 0)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", self._changed)
        head.pack_start(self.switch, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.pack_start(_hint(_("XControl writes its own dunst setup and runs dunst for the session. Your own "
                                "~/.config/dunst/dunstrc isn't used or changed. Changes show on the next "
                                "notification.")), False, False, 0)
        self.status = _hint("")
        self.pack_start(self.status, False, False, 0)
        self.warn = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        self.warn_text = _hint("")
        self.warn_text.get_style_context().remove_class("dim-label")
        self.warn.get_content_area().add(self.warn_text)
        self.warn.add_button(_("Stop it"), 1)
        self.warn.connect("response", self._stop_other)
        self.warn.set_no_show_all(True)
        self.pack_start(self.warn, False, False, 0)
        self.conflicts = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.conflicts.set_no_show_all(True)
        self.pack_start(self.conflicts, False, False, 0)

        self.sections = []
        self._build_try()
        self._build_position()
        self._build_look()
        self._build_colors()
        self._build_behavior()
        self._build_rules()
        self._build_power_alerts()
        self._build_keys()
        self._build_extra()
        self._fill()
        self.loading = False
        widgets.protect(self)
        self.connect("map", lambda *_a: self._status())
        GLib.timeout_add_seconds(3, lambda: (self._status() if self.get_mapped() else None) or True)

    # ---------------------------------------------------------------- layout helpers
    def _section(self, title, always=False):
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        head = Gtk.Label(xalign=0)
        head.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        frame.set_label_widget(head)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_start=12, margin_top=8, margin_bottom=4)
        frame.add(grid)
        self.pack_start(frame, False, False, 0)
        if not always:
            self.sections.append(frame)
        return grid

    def _row(self, g, r, label, widget, hint=None):
        lbl = Gtk.Label(label=label, xalign=0)
        self.labels.add_widget(lbl)
        g.attach(lbl, 0, r, 1, 1)
        g.attach(widget, 1, r, 1, 1)
        if hint:
            g.attach(_hint(hint), 1, r + 1, 1, 1)
            return r + 2
        return r + 1

    def _connect(self, *ws):
        for w in ws:
            if isinstance(w, Gtk.SpinButton):
                w.connect("value-changed", self._changed)
            elif isinstance(w, Gtk.ComboBox):
                w.connect("changed", self._changed)
            elif isinstance(w, Gtk.ToggleButton):
                w.connect("toggled", self._changed)
            elif isinstance(w, Gtk.Range):
                w.connect("value-changed", self._changed)
            elif isinstance(w, Gtk.ColorButton):
                w.connect("color-set", self._changed)
            elif isinstance(w, Gtk.FontButton):
                w.connect("font-set", self._changed)
            elif isinstance(w, Gtk.Entry):
                w.connect("changed", self._changed)

    # ---------------------------------------------------------------- sections
    def _build_try(self):
        g = self._section(_("Try it"))
        box = Gtk.Box(spacing=6)
        for u in N.URGENCIES:
            b = Gtk.Button(label=_(URGENCY_LABELS[u]))
            b.connect("clicked", self._test, u)
            box.pack_start(b, False, False, 0)
        self._row(g, 0, _("Send a test notification"), box)
        dnd = Gtk.Box(spacing=10)
        self.dnd = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.dnd.connect("notify::active", self._dnd_toggled)
        dnd.pack_start(self.dnd, False, False, 0)
        self._row(g, 1, _("Do not disturb"), dnd,
                  _("Notifications wait while it's on and show when you turn it off."))

    def _build_position(self):
        g = self._section(_("Where they show"))
        self.position = _combo(POS_LABELS, N.POSITIONS)
        r = self._row(g, 0, _("Corner"), self.position)
        off = Gtk.Box(spacing=6)
        self.off_x, self.off_y = _spin(0, 2000), _spin(0, 2000)
        for label, w in ((_("sideways"), self.off_x), (_("up/down"), self.off_y)):
            off.pack_start(w, False, False, 0)
            off.pack_start(Gtk.Label(label=_("px {direction}").format(direction=label)), False, False, 6)
        r = self._row(g, r, _("Distance from the edge"), off)
        self.follow = _combo(FOLLOW_LABELS, N.FOLLOW)
        r = self._row(g, r, _("Display"), self.follow)
        self.width = _spin(100, 2000, 10)
        r = self._row(g, r, _("Width (px)"), self.width)
        self.max_height = _spin(40, 2000, 10)
        r = self._row(g, r, _("Tallest (px)"), self.max_height)
        self.limit = _spin(0, 50)
        r = self._row(g, r, _("Most at once"), self.limit, _("0 shows them all; the rest wait their turn."))
        self.gap = _spin(0, 100)
        self._row(g, r, _("Space between them (px)"), self.gap)
        self._connect(self.position, self.off_x, self.off_y, self.follow, self.width, self.max_height, self.limit,
                      self.gap)

    def _build_look(self):
        g = self._section(_("Look"))
        fb = Gtk.Box(spacing=10)
        self.same_font = Gtk.CheckButton(label=_("The interface font"))
        self.font = Gtk.FontButton(use_font=True)
        fb.pack_start(self.same_font, False, False, 0)
        fb.pack_start(self.font, False, False, 0)
        r = self._row(g, 0, _("Font"), fb)
        self.radius = _spin(0, 50)
        r = self._row(g, r, _("Rounded corners (px)"), self.radius)
        self.frame = _spin(0, 20)
        r = self._row(g, r, _("Border (px)"), self.frame)
        self.padding = _spin(0, 60)
        r = self._row(g, r, _("Space inside (px)"), self.padding)
        self.icon_pos = _combo(ICON_LABELS, N.ICON_POSITIONS)
        r = self._row(g, r, _("Icon"), self.icon_pos)
        self.icon_size = _spin(16, 256, 4)
        r = self._row(g, r, _("Largest icon (px)"), self.icon_size)
        self.align = _combo(ALIGN_LABELS, N.ALIGN)
        r = self._row(g, r, _("Text alignment"), self.align)
        self.format = _combo(FORMAT_LABELS, list(N.FORMATS) + ["custom"])
        r = self._row(g, r, _("Shows"), self.format)
        self.custom = Gtk.Entry(hexpand=True, placeholder_text="<b>%a</b>: %s\\n%b")
        r = self._row(g, r, "", self.custom,
                      _("%a app, %s title, %b text, %p progress, \\n a new line; Pango markup like <b>, <i>."))
        self.transparency = _scale(0, 100, 5)
        r = self._row(g, r, _("See-through (%)"), self.transparency, _("Needs the compositor."))
        self.separator = Gtk.CheckButton(label=_("A line between notifications shown together"))
        g.attach(self.separator, 1, r, 1, 1)
        self._connect(self.same_font, self.font, self.radius, self.frame, self.padding, self.icon_pos,
                      self.icon_size, self.align, self.format, self.custom, self.transparency, self.separator)

    def _build_colors(self):
        g = self._section(_("Colors and timing"))
        heads = (_("Background"), _("Text"), _("Border"), _("Disappears after (s)"))
        for col, t in enumerate(heads, 1):
            lbl = Gtk.Label(label=t)
            lbl.get_style_context().add_class("dim-label")
            g.attach(lbl, col, 0, 1, 1)
        self.colors, self.timeouts = {}, {}
        for row, u in enumerate(N.URGENCIES, 1):
            lbl = Gtk.Label(label=_(URGENCY_LABELS[u]), xalign=0)
            self.labels.add_widget(lbl)
            g.attach(lbl, 0, row, 1, 1)
            for i in range(3):
                b = Gtk.ColorButton(use_alpha=False)
                self._connect(b)
                g.attach(b, i + 1, row, 1, 1)
                self.colors[(u, i)] = b
            t = _spin(0, 3600)
            self._connect(t)
            g.attach(t, 4, row, 1, 1)
            self.timeouts[u] = t
        g.attach(_hint(_("0 seconds: it stays until you click it. Programs choose how urgent a notification is "
                         "(a finished download is low, a low battery critical).")), 1, 4, 4, 1)
        self.critical_dnd = Gtk.CheckButton(label=_("Critical ones show even with \"Do not disturb\" on"))
        self._connect(self.critical_dnd)
        g.attach(self.critical_dnd, 1, 5, 4, 1)
        reset = Gtk.Button(label=_("Default colors"), halign=Gtk.Align.START)
        reset.connect("clicked", self._reset_colors)
        g.attach(reset, 1, 6, 2, 1)

    def _build_behavior(self):
        g = self._section(_("Behavior"))
        self.show_age = _combo({k: v for k, v in AGE_CHOICES}, [k for k, _v in AGE_CHOICES])
        r = self._row(g, 0, _("Show how old it is"), self.show_age)
        self.idle = _combo({k: v for k, v in IDLE_CHOICES}, [k for k, _v in IDLE_CHOICES])
        r = self._row(g, r, _("Keep them while you're away"), self.idle,
                      _("When you haven't touched the mouse or keyboard for this long, notifications don't "
                        "disappear until you're back."))
        self.history = _spin(0, 1000)
        r = self._row(g, r, _("History keeps"), self.history)
        self.checks = {}
        for key, label in (("stack_duplicates", _("Show repeated notifications once, with a count")),
                           ("sticky_history", _("Ones brought back from the history stay until clicked")),
                           ("indicate_hidden", _("Show how many are waiting")),
                           ("show_indicators", _("Mark ones that have actions (A) or links (U)")),
                           ("progress_bar", _("Show progress bars (e.g. volume, downloads)"))):
            w = Gtk.CheckButton(label=label)
            self._connect(w)
            g.attach(w, 1, r, 1, 1)
            self.checks[key] = w
            r += 1
        self.clicks = {}
        for key, label in (("left_click", _("Left click")), ("middle_click", _("Middle click")),
                           ("right_click", _("Right click"))):
            w = _combo(CLICK_LABELS, N.CLICKS)
            self._connect(w)
            r = self._row(g, r, label, w)
            self.clicks[key] = w
        sb = Gtk.Box(spacing=6)
        self.sound = Gtk.FileChooserButton(title=_("Notification sound"), action=Gtk.FileChooserAction.OPEN)
        f = Gtk.FileFilter()
        f.set_name(_("Sounds"))
        for pat in ("*.oga", "*.ogg", "*.wav", "*.flac", "*.mp3", "*.opus"):
            f.add_pattern(pat)
        self.sound.add_filter(f)
        if os.path.isdir("/usr/share/sounds"):
            self.sound.set_current_folder("/usr/share/sounds")
        self.sound.connect("file-set", self._changed)
        sb.pack_start(self.sound, True, True, 0)
        clear = Gtk.Button.new_from_icon_name("edit-clear-symbolic", Gtk.IconSize.BUTTON)
        clear.set_tooltip_text(_("No sound"))
        clear.connect("clicked", self._clear_sound)
        sb.pack_start(clear, False, False, 0)
        self._row(g, r, _("Sound"), sb, _("Played for normal and critical notifications (pw-play or paplay)."))

    def _build_rules(self):
        g = self._section(_("Per app"))
        self.rule_store = Gtk.ListStore(str, str)   # app, action
        view = Gtk.TreeView(model=self.rule_store)
        cell = Gtk.CellRendererText(editable=True)
        cell.connect("edited", self._rule_app)
        col = Gtk.TreeViewColumn(_("App"), cell, text=0)
        col.set_expand(True)
        view.append_column(col)
        actions = Gtk.ListStore(str, str)
        for k in N.RULE_ACTIONS:
            actions.append([k, _(RULE_LABELS[k])])
        cc = Gtk.CellRendererCombo(model=actions, text_column=1, has_entry=False, editable=True)
        cc.connect("changed", self._rule_action)
        col = Gtk.TreeViewColumn(_("What happens"), cc)
        col.set_cell_data_func(cc, lambda _c, cell, m, it, _d: cell.set_property(
            "text", _(RULE_LABELS.get(m[it][1], m[it][1]))))
        col.set_expand(True)
        view.append_column(col)
        self.rule_view = view
        sw = Gtk.ScrolledWindow(min_content_height=120, hexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(view)
        g.attach(sw, 0, 0, 2, 1)
        bb = Gtk.Box(spacing=6)
        add = Gtk.Button(label=_("Add"))
        add.connect("clicked", self._rule_add)
        rm = Gtk.Button(label=_("Remove"))
        rm.connect("clicked", self._rule_remove)
        bb.pack_start(add, False, False, 0)
        bb.pack_start(rm, False, False, 0)
        self.recent = Gtk.ComboBoxText()
        self.recent.set_no_show_all(True)
        self.recent.connect("changed", self._rule_recent)
        bb.pack_start(self.recent, False, False, 0)
        g.attach(bb, 0, 1, 2, 1)
        g.attach(_hint(_("The app name is the one the program gives (as shown with \"App name, title and text\"); "
                         "* matches anything, e.g. Steam*.")), 0, 2, 2, 1)

    def _build_power_alerts(self):
        g = self._section(_("Power alerts"), always=True)
        self.pa_on = Gtk.CheckButton(label=_("Alert about batteries and power (poweralertd)"))
        g.attach(self.pa_on, 0, 0, 2, 1)
        g.attach(_hint(_("A notification when the battery starts or stops charging, gets low or critical, or the "
                         "charger is plugged in or out, also for wireless devices with their own battery. XControl "
                         "runs poweralertd for the session; any notification program shows its alerts (they're "
                         "in English), and \"poweralertd\" works in the Per app rules above.")), 0, 1, 2, 1)
        self.pa_status = _hint("")
        g.attach(self.pa_status, 0, 2, 2, 1)
        self.pa_warn = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        self.pa_warn_text = _hint("")
        self.pa_warn_text.get_style_context().remove_class("dim-label")
        self.pa_warn.get_content_area().add(self.pa_warn_text)
        self.pa_warn.add_button(_("Stop it"), 1)
        self.pa_warn.connect("response", self._pa_stop_other)
        self.pa_warn.set_no_show_all(True)
        g.attach(self.pa_warn, 0, 3, 2, 1)
        self.pa_skip = Gtk.CheckButton(label=_("Only for changes, not for how things are when the session starts"))
        g.attach(self.pa_skip, 0, 4, 2, 1)
        self.pa_devices = Gtk.CheckButton(label=_("Devices with their own battery too, besides the computer's:"))
        g.attach(self.pa_devices, 0, 5, 2, 1)
        grid = Gtk.Grid(column_spacing=18, row_spacing=4, margin_start=24)
        self.pa_groups = {}
        labels = {"mouse": _("Mice"), "keyboard": _("Keyboards"), "gaming": _("Game controllers"),
                  "audio": _("Headsets, headphones and speakers"), "phone": _("Phones, tablets and watches"),
                  "pen": _("Pens and touchpads"), "other": _("Everything else")}
        for i, k in enumerate(PA.GROUP_ORDER):
            b = Gtk.CheckButton(label=labels[k])
            grid.attach(b, i % 2, i // 2, 1, 1)
            self.pa_groups[k] = b
        g.attach(grid, 0, 6, 2, 1)
        for w in [self.pa_on, self.pa_skip, self.pa_devices] + list(self.pa_groups.values()):
            w.connect("toggled", self._pa_changed)
        self.pa_conflicts = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.pa_conflicts.set_no_show_all(True)
        g.attach(self.pa_conflicts, 0, 7, 2, 1)

    def _pa_changed(self, *_a):
        if self.loading:
            return
        pa = self.pa
        pa["enabled"] = self.pa_on.get_active()
        pa["skip_startup"] = self.pa_skip.get_active()
        pa["devices"] = self.pa_devices.get_active()
        pa["ignore"] = [k for k, b in self.pa_groups.items() if not b.get_active()]
        self._pa_sensitivity()
        self._commit_later()

    def _pa_sensitivity(self):
        on = self.pa_on.get_active() and PA.installed()
        self.pa_on.set_sensitive(PA.installed() or self.pa_on.get_active())
        for w in (self.pa_skip, self.pa_devices):
            w.set_sensitive(on)
        for b in self.pa_groups.values():
            b.set_sensitive(on and self.pa_devices.get_active())

    def _pa_stop_other(self, *_a):
        enabled, active = PA.service_state()
        if enabled or active:
            ok, msg = PA.disable_service()
            if not ok and msg:
                self.window.message(_("Could not turn off poweralertd's service"), msg)
        theirs = D.foreign(["poweralertd"])
        if theirs:
            D.stop_foreign(["poweralertd"])
        GLib.timeout_add(1500, lambda: self._status() and False)

    def _pa_status(self):
        pa = self.pa
        st = D.state()
        kids = st.get("children") or {}
        err = (st.get("errors") or {}).get("poweralertd", "")
        if not PA.installed():
            text = _("poweralertd isn't installed (pacman -S poweralertd).")
        elif not pa["enabled"]:
            text = ""
        elif kids.get("poweralertd"):
            text = _("Running.")
        else:
            text = _("Not running: {why}").format(why=err) if err else _("Starting…")
        self.pa_status.set_text(text)
        self.pa_status.set_visible(bool(text))
        if pa["enabled"]:
            enabled, active = PA.service_state()
            theirs = D.foreign(["poweralertd"])
        else:
            enabled = active = False
            theirs = {}
        if enabled or active:
            warn = _("poweralertd's own service is also enabled, so every alert would show twice. \"Stop it\" "
                     "turns that service off (systemctl --user disable --now poweralertd).")
        elif theirs:
            warn = _("Another poweralertd (process {pid}) is running besides XControl's, so every alert shows "
                     "twice. Stop it, and remove it from your i3 config or autostart.").format(pid=min(theirs))
        else:
            warn = ""
        self.pa_warn_text.set_text(warn)
        widgets.reveal(self.pa_warn, bool(warn))
        lines = [line for kind, line in D.session_conflicts() if kind == "power_alerts"]
        show = pa["enabled"] and lines
        if show:
            self.pa_conflicts.set_markup("⚠ " + GLib.markup_escape_text(
                _("Remove these from your i3 config, or a second poweralertd starts after the next login:")) + "\n" +
                "\n".join(f"<tt>{GLib.markup_escape_text(x)}</tt>" for x in lines[:4]))
        self.pa_conflicts.set_visible(bool(show))

    def _build_keys(self):
        g = self._section(_("Keyboard shortcuts"), always=True)
        g.attach(_hint(_("These commands control the notifications. Bind them to keys in your i3 config (or on the "
                         "Window Manager page):")), 0, 0, 1, 1)
        for i, (cmd, what) in enumerate((("dunstctl close", _("Close the newest notification:")),
                                         ("dunstctl close-all", _("Close all of them:")),
                                         ("dunstctl history-pop", _("Bring back the last closed one:")),
                                         ("dunstctl context", _("Choose one of its actions from a menu:")),
                                         ("xcontrol --dnd toggle", _("Do not disturb on/off:"))), 1):
            g.attach(_command(what, f"bindsym $mod+... exec --no-startup-id {cmd}", self.window), 0, i, 1, 1)

    def _build_extra(self):
        g = self._section(_("Extra dunst settings"))
        g.attach(_hint(_("Anything else from dunst's documentation, as in a dunstrc. Lines before any [section] "
                         "go into [global] and replace XControl's line with the same key; [sections] are added as "
                         "they are.")), 0, 0, 1, 1)
        self.extra = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.NONE, accepts_tab=False)
        self.extra.get_buffer().connect("changed", self._changed)
        sw = Gtk.ScrolledWindow(min_content_height=110, hexpand=True)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(self.extra)
        g.attach(sw, 0, 1, 1, 1)

    # ---------------------------------------------------------------- values
    def _fill(self):
        n = self.n
        self.loading = True
        self.switch.set_active(n["enabled"])
        self.position.set_active_id(n["position"])
        self.off_x.set_value(n["offset_x"])
        self.off_y.set_value(n["offset_y"])
        self.follow.set_active_id(n["follow"])
        self.width.set_value(n["width"])
        self.max_height.set_value(n["max_height"])
        self.limit.set_value(n["limit"])
        self.gap.set_value(n["gap"])
        self.same_font.set_active(not n["font"])
        self.font.set_font(n["font"] or N._gtk_setting("gtk-font-name") or "Sans 10")
        self.radius.set_value(n["corner_radius"])
        self.frame.set_value(n["frame_width"])
        self.padding.set_value(n["padding"])
        self.icon_pos.set_active_id(n["icon_position"])
        self.icon_size.set_value(n["icon_size"])
        self.align.set_active_id(n["alignment"])
        self.format.set_active_id(n["format"])
        self.custom.set_text(n["custom_format"])
        self.transparency.set_value(n["transparency"])
        self.separator.set_active(n["separator"])
        self._fill_colors()
        self.critical_dnd.set_active(n["critical_in_dnd"])
        if not self.show_age.set_active_id(str(n["show_age"])):
            self.show_age.append(str(n["show_age"]), _("After {n} seconds").format(n=n["show_age"]))
            self.show_age.set_active_id(str(n["show_age"]))
        if not self.idle.set_active_id(str(n["idle_pause"])):
            self.idle.append(str(n["idle_pause"]), _("After {n} seconds").format(n=n["idle_pause"]))
            self.idle.set_active_id(str(n["idle_pause"]))
        self.history.set_value(n["history_length"])
        for k, w in self.checks.items():
            w.set_active(n[k])
        for k, w in self.clicks.items():
            w.set_active_id(n[k])
        if n["sound"]:
            self.sound.set_filename(n["sound"])
        else:
            self.sound.unselect_all()
        self.rule_store.clear()
        for r in n["rules"]:
            self.rule_store.append([r["app"], r["action"]])
        self.extra.get_buffer().set_text(n["extra"])
        pa = self.pa
        self.pa_on.set_active(pa["enabled"])
        self.pa_skip.set_active(pa["skip_startup"])
        self.pa_devices.set_active(pa["devices"])
        for k, b in self.pa_groups.items():
            b.set_active(k not in pa["ignore"])
        self._pa_sensitivity()
        self._sensitivity()
        self.loading = False

    def _fill_colors(self):
        for (u, i), b in self.colors.items():
            b.set_rgba(_rgba(self.n["colors"][u][i]))
        for u, t in self.timeouts.items():
            t.set_value(self.n["timeouts"][u])

    def _sensitivity(self):
        on = self.switch.get_active()
        for s in self.sections:
            s.set_sensitive(on)
        self.font.set_sensitive(not self.same_font.get_active())
        self.custom.set_visible(self.format.get_active_id() == "custom")

    def _changed(self, *_a):
        if self.loading:
            return
        n = self.n
        n["enabled"] = self.switch.get_active()
        n["position"] = self.position.get_active_id()
        n["offset_x"], n["offset_y"] = int(self.off_x.get_value()), int(self.off_y.get_value())
        n["follow"] = self.follow.get_active_id()
        n["width"], n["max_height"] = int(self.width.get_value()), int(self.max_height.get_value())
        n["limit"], n["gap"] = int(self.limit.get_value()), int(self.gap.get_value())
        n["font"] = "" if self.same_font.get_active() else (self.font.get_font() or "")
        n["corner_radius"], n["frame_width"] = int(self.radius.get_value()), int(self.frame.get_value())
        n["padding"] = int(self.padding.get_value())
        n["icon_position"], n["icon_size"] = self.icon_pos.get_active_id(), int(self.icon_size.get_value())
        n["alignment"], n["format"] = self.align.get_active_id(), self.format.get_active_id()
        n["custom_format"] = self.custom.get_text()
        n["transparency"] = int(self.transparency.get_value())
        n["separator"] = self.separator.get_active()
        for (u, i), b in self.colors.items():
            n["colors"][u][i] = _hex(b.get_rgba())
        for u, t in self.timeouts.items():
            n["timeouts"][u] = int(t.get_value())
        n["critical_in_dnd"] = self.critical_dnd.get_active()
        n["show_age"] = int(self.show_age.get_active_id() or 60)
        n["idle_pause"] = int(self.idle.get_active_id() or 0)
        n["history_length"] = int(self.history.get_value())
        for k, w in self.checks.items():
            n[k] = w.get_active()
        for k, w in self.clicks.items():
            n[k] = w.get_active_id()
        n["sound"] = self.sound.get_filename() or ""
        buf = self.extra.get_buffer()
        n["extra"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self._sensitivity()
        self._commit_later()

    def _commit_later(self):
        if self.loading:
            return
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(600, self._commit)

    def _commit(self):
        self._timer = None
        try:
            fresh = D.load()   # other pages keep their parts
            fresh["notify"] = N.normalize(self.n)
            fresh["power_alerts"] = PA.normalize(self.pa)
            D.save(fresh)
            D.notify_daemon(fresh)
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not save the settings"), str(e))
            return False
        self.window.set_status(_("Applied"))
        GLib.timeout_add(1500, lambda: self._status() and False)
        return False

    def _reset_colors(self, _b):
        self.n["colors"] = {u: list(c) for u, c in N.DEFAULT_COLORS.items()}
        self.n["timeouts"] = dict(N.DEFAULT_TIMEOUTS)
        self.loading = True
        self._fill_colors()
        self.loading = False
        self._commit_later()

    def _clear_sound(self, _b):
        self.sound.unselect_all()
        self._changed()

    # ---------------------------------------------------------------- rules
    def _rule_add(self, _b, app=""):
        self.n["rules"].append({"app": app, "action": "history_only"})
        self.rule_store.append([app, "history_only"])
        if not app:
            path = Gtk.TreePath(len(self.rule_store) - 1)
            self.rule_view.set_cursor(path, self.rule_view.get_column(0), True)
        else:
            self._commit_later()

    def _rule_remove(self, _b):
        _m, it = self.rule_view.get_selection().get_selected()
        if it:
            i = self.rule_store.get_path(it)[0]
            del self.n["rules"][i]
            self.rule_store.remove(it)
            self._commit_later()

    def _rule_app(self, _cell, path, text):
        i = int(path)
        self.rule_store[i][0] = text.strip()
        self.n["rules"][i]["app"] = text.strip()
        self._commit_later()

    def _rule_action(self, cell, path, it):
        i = int(path)
        action = cell.get_property("model")[it][0]
        self.rule_store[i][1] = action
        self.n["rules"][i]["action"] = action
        self._commit_later()

    def _rule_recent(self, combo):
        app = combo.get_active_id()
        if app:
            self._rule_add(None, app)
            combo.set_active(0)

    def _fill_recent(self):
        apps = recent_apps()
        current = [self.recent.get_model()[i][1] for i in range(1, len(self.recent.get_model()))] \
            if self.recent.get_model() is not None and len(self.recent.get_model()) else []
        if apps == current:
            return
        self.recent.remove_all()
        self.recent.append("", _("Add a recent app…"))
        for a in apps:
            self.recent.append(a, a)
        self.recent.set_active(0)
        self.recent.set_visible(bool(apps))

    # ---------------------------------------------------------------- live
    def _test(self, _b, urgency):
        text = {"low": (_("A low notification"), _("Like a finished download.")),
                "normal": (_("A normal notification"), _("Like a new message. <i>Formatting</i> works too.")),
                "critical": (_("A critical notification"), _("Like a low battery. It stays until clicked."))}
        try:
            N.send_test(urgency, *text[urgency])
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Nothing shows notifications right now"), str(e))

    def _dnd_toggled(self, *_a):
        if self.loading:
            return
        if not N.set_paused(self.dnd.get_active()):
            self.window.message(_("Could not change it"), _("dunst isn't running."))

    def _stop_other(self, *_a):
        o = N.owner()
        if o:
            try:
                os.kill(o[0], signal.SIGTERM)
            except OSError:
                pass
        GLib.timeout_add(1500, lambda: self._status() and False)

    def _status(self):
        self._pa_status()
        n = self.n
        st = D.state()
        kids = st.get("children") or {}
        err = (st.get("errors") or {}).get("dunst", "")
        owner = N.owner()
        ours = owner and kids.get("dunst") == owner[0]
        if ours and not self._version:   # (this runs every 3 s: ask dunst once)
            self._version = N.version()
        v = self._version
        if not shutil.which("dunst"):
            text = _("dunst isn't installed.")
        elif not n["enabled"]:
            text = (_("Notifications are shown by {name} now.").format(name=owner[1]) if owner else
                    _("Nothing shows notifications right now."))
        elif ours:
            text = _("Running (dunst {v}).").format(v=".".join(map(str, v)) if v else "?")
        else:
            text = _("Not running: {why}").format(why=err) if err else _("Starting…")
        self.status.set_text(text)
        other = n["enabled"] and owner and not ours
        self.warn_text.set_text(_("{name} (process {pid}) is showing notifications, so XControl's dunst can't "
                                  "start. Stop it, and remove it from your i3 config or autostart.")
                                .format(name=owner[1], pid=owner[0]) if other else "")
        widgets.reveal(self.warn, bool(other))
        lines = [line for kind, line in D.session_conflicts() if kind == "notifications"]
        show = n["enabled"] and lines
        if show:
            self.conflicts.set_markup("⚠ " + GLib.markup_escape_text(
                _("Remove these from your i3 config, or another notification program starts first after the next "
                  "login:")) + "\n" + "\n".join(f"<tt>{GLib.markup_escape_text(x)}</tt>" for x in lines[:4]))
        self.conflicts.set_visible(bool(show))
        self.loading, was = True, self.loading
        self.dnd.set_active(bool(ours) and N.paused())
        self.dnd.set_sensitive(bool(ours) or (owner is not None and owner[1] == "dunst"))
        self.loading = was
        if owner and owner[1] == "dunst":   # dunstctl would start a dunst through D-Bus otherwise
            self._fill_recent()
        return False


def recent_apps():
    """App names from dunst's history, newest first."""
    import json
    out = N.dunstctl("history")
    if not out:
        return []
    try:
        data = json.loads(out)["data"][0]
    except (ValueError, KeyError, IndexError):
        return []
    names = []
    for item in data:
        name = (item.get("appname") or {}).get("data", "")
        if name and name not in names and name != "XControl":
            names.append(name)
    return names[:15]
