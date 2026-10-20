"""The Date & Language page: time zone, clock, language and formats."""
import datetime

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import region as R, widgets  # noqa: E402
from .desktop_page import _hint  # noqa: E402
from .i18n import _  # noqa: E402


class RegionPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.loading = True
        self.labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        self._build_time()
        self._build_language()
        self.connect("map", lambda *_a: self._refresh())
        GLib.timeout_add_seconds(1, self._tick)
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

    # ---------------------------------------------------------------- date and time
    def _build_time(self):
        g = self._section(_("Date and time"))
        self.now = Gtk.Label(xalign=0)
        self._row(g, 0, _("Now"), self.now)
        tzbox = Gtk.Box(spacing=6)
        self.tz = Gtk.ComboBoxText.new_with_entry()
        self.tz.set_hexpand(True)
        self.zones = R.timezones()
        store = Gtk.ListStore(str)
        for z in self.zones:
            self.tz.append_text(z)
            store.append([z])
        comp = Gtk.EntryCompletion(model=store, text_column=0, inline_completion=False, popup_completion=True)
        comp.set_match_func(lambda _c, key, it, _d: key.lower().replace(" ", "_") in store[it][0].lower(), None)
        self.tz.get_child().set_completion(comp)
        self.tz.get_child().set_placeholder_text(_("Type a city, e.g. Sao_Paulo"))
        tzbox.pack_start(self.tz, True, True, 0)
        self.tz_btn = Gtk.Button(label=_("Set"))
        self.tz_btn.connect("clicked", self._set_tz)
        tzbox.pack_start(self.tz_btn, False, False, 0)
        self._row(g, 1, _("Time zone"), tzbox)

        self.ntp = Gtk.CheckButton(label=_("Set the time automatically from the internet"))
        self.ntp.connect("toggled", self._ntp)
        g.attach(self.ntp, 1, 2, 1, 1)
        self.ntp_note = _hint("")
        g.attach(self.ntp_note, 1, 3, 1, 1)

        man = Gtk.Box(spacing=6)
        self.date_btn = Gtk.MenuButton()
        self.cal = Gtk.Calendar()
        pop = Gtk.Popover()
        pop.add(self.cal)
        self.cal.show()
        self.date_btn.set_popover(pop)
        self.cal.connect("day-selected", self._date_picked)
        self.hh = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.mm = Gtk.SpinButton.new_with_range(0, 59, 1)
        for s in (self.hh, self.mm):
            s.set_wrap(True)
            s.set_numeric(True)
            s.connect("output", lambda sp: (sp.set_text(f"{int(sp.get_value()):02d}"), True)[1])
        man.pack_start(self.date_btn, False, False, 0)
        man.pack_start(self.hh, False, False, 0)
        man.pack_start(Gtk.Label(label=":"), False, False, 0)
        man.pack_start(self.mm, False, False, 0)
        self.time_btn = Gtk.Button(label=_("Set"))
        self.time_btn.connect("clicked", self._set_time)
        man.pack_start(self.time_btn, False, False, 0)
        self.manual = man
        self._row(g, 4, _("Set by hand"), man)
        self.rtc = Gtk.CheckButton(label=_("The computer's clock keeps local time (for dual boot with Windows)"))
        self.rtc.connect("toggled", self._rtc)
        g.attach(self.rtc, 1, 5, 1, 1)
        g.attach(_hint(_("Linux keeps the hardware clock in UTC; Windows uses local time, so with both installed "
                         "one of them shows the wrong time. Either tick this, or set Windows to UTC.")), 1, 6, 1, 1)
        self.time_note = _hint("")
        g.attach(self.time_note, 1, 7, 1, 1)

    def _done(self, what):
        def cb(err):
            if err and "cancel" not in err.lower() and "not authorized" not in err.lower():
                self.window.message(_("Could not change it"), err)
            elif not err:
                self.window.set_status(what)
            GLib.idle_add(lambda: self._refresh() and False)
        return cb

    def _set_tz(self, *_a):
        tz = self.tz.get_child().get_text().strip()
        if tz not in self.zones:
            self.window.message(_("Unknown time zone"), _("Pick one from the list, e.g. America/Sao_Paulo."))
            return
        R.set_timezone(tz, self._done(_("Time zone set to {tz}").format(tz=tz)))

    def _ntp(self, check):
        if self.loading:
            return
        R.set_ntp(check.get_active(), self._done(_("Network time on") if check.get_active() else
                                                 _("Network time off")))

    def _rtc(self, check):
        if self.loading:
            return
        R.set_local_rtc(check.get_active(), self._done(_("Hardware clock setting changed")))

    def _date_picked(self, cal):
        y, m, d = cal.get_date()
        self.date_btn.set_label(datetime.date(y, m + 1, d).strftime("%x"))

    def _set_time(self, *_a):
        y, m, d = self.cal.get_date()
        local = datetime.datetime(y, m + 1, d, int(self.hh.get_value()), int(self.mm.get_value())).astimezone()
        R.set_time(local.timestamp() * 1_000_000, self._done(_("Time set")))

    def _tick(self):
        if self.get_mapped():
            now = datetime.datetime.now().astimezone()
            self.now.set_text(now.strftime("%A %x  %X  (UTC%z)").replace("(UTC+0000)", "(UTC)"))
        return True

    # ---------------------------------------------------------------- language
    def _build_language(self):
        g = self._section(_("Language and formats"))
        self.scope = Gtk.ComboBoxText()
        self.scope.append("user", _("Just for me"))
        self.scope.append("system", _("Everyone on this computer"))
        self.scope.set_active_id("user")
        self.scope.connect("changed", lambda *_a: self._fill_language())
        self._row(g, 0, _("Change it for"), self.scope)
        self.lang = Gtk.ComboBoxText(hexpand=True)
        self.lang.connect("changed", self._preview)
        self._row(g, 1, _("Language"), self.lang)
        g.attach(_hint(_("Menus and messages of programs that are translated.")), 1, 2, 1, 1)
        self.formats = Gtk.ComboBoxText(hexpand=True)
        self.formats.connect("changed", self._preview)
        self._row(g, 3, _("Formats"), self.formats)
        self.example = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.example.set_can_focus(False)
        g.attach(self.example, 1, 4, 1, 1)
        bb = Gtk.Box(spacing=6)
        more = Gtk.Button(label=_("More languages…"))
        more.connect("clicked", self._more)
        bb.pack_start(more, False, False, 0)
        self.apply = Gtk.Button(label=_("Apply"))
        self.apply.get_style_context().add_class("suggested-action")
        self.apply.connect("clicked", self._apply_language)
        bb.pack_end(self.apply, False, False, 0)
        g.attach(bb, 1, 5, 1, 1)
        self.lang_note = _hint("")
        g.attach(self.lang_note, 1, 6, 1, 1)

    def _fill_language(self):
        self.loading, was = True, self.loading
        user = self.scope.get_active_id() == "user"
        values = R.user_locale() if user else R.system_locale()
        if user and not values:
            values = R.system_locale()
        self.installed = R.installed()
        cur_lang = R._norm(values.get("LANG", "")) if values.get("LANG") else ""
        cur_fmt = R._norm(values.get("LC_TIME", "")) if values.get("LC_TIME") else ""
        for combo, cur, same in ((self.lang, cur_lang, None), (self.formats, cur_fmt, _("Same as the language"))):
            combo.remove_all()
            if same:
                combo.append("", same)
            names = {loc: R.describe(loc) for loc in self.installed}
            for loc in sorted(self.installed, key=lambda x: names[x].lower()):
                combo.append(loc, f"{names[loc]}  —  {loc}")
            if cur and cur not in self.installed:
                combo.append(cur, cur + " " + _("(not installed)"))
            combo.set_active_id(cur if cur else "")
            if combo.get_active() < 0:
                combo.set_active(0)
        self.loading = was
        sess = R.session_locale().get("LANG", "")
        notes = [_("Takes effect when you log in again.")]
        if sess:
            notes.append(_("This session runs in {loc}.").format(loc=sess))
        if not user and R.user_locale():
            notes.append(_("Your own settings (~/.config/locale.conf) win over these for you."))
        self.lang_note.set_text(" ".join(notes))
        self._preview()

    def _preview(self, *_a):
        loc = self.formats.get_active_id() or self.lang.get_active_id()
        if not loc:
            self.example.set_text("")
            return
        p = R.preview(loc)
        if not p:
            self.example.set_text("")
            return
        bits = [p.get("date", ""), p.get("time", ""), p.get("number", "")] + ([p["money"]] if p.get("money") else [])
        self.example.set_markup("<span alpha='75%'>{}</span>".format(
            GLib.markup_escape_text(_("Looks like: {examples}").format(examples="   ·   ".join(b for b in bits if b)))))

    def _apply_language(self, *_a):
        lang = self.lang.get_active_id()
        fmt = self.formats.get_active_id() or ""
        if not lang:
            return
        values = {"LANG": lang}
        for v in R.FORMAT_VARS:
            if fmt and fmt != lang:
                values[v] = fmt
        if self.scope.get_active_id() == "user":
            try:
                R.write_user_locale(values)
            except (OSError, ValueError) as e:
                self.window.message(_("Could not save it"), str(e))
                return
            self.window.set_status(_("Saved; log in again to use it"))
            self._fill_language()
        else:
            R.set_system_locale(values, self._done(_("Saved; log in again to use it")))

    def _more(self, *_a):
        if not R.can_enable():
            self.window.message(_("Can't add languages here"),
                                _("This needs pkexec (polkit) and /usr/share/i18n/SUPPORTED (glibc)."))
            return
        have = set(self.installed)
        avail = [loc for loc in R.supported() if loc not in have]
        dlg = Gtk.Dialog(title=_("More languages"), transient_for=self.get_toplevel(), modal=True)
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = dlg.add_button(_("Add"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        dlg.set_default_size(560, 520)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(_hint(_("Tick the languages to make available. They're generated for the whole computer "
                               "(locale-gen), which takes a moment.")), False, False, 0)
        search = Gtk.SearchEntry(placeholder_text=_("Search"))
        box.pack_start(search, False, False, 0)
        store = Gtk.ListStore(bool, str, str)
        for loc in avail:
            store.append([False, R.describe(loc), loc])
        store.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        flt = store.filter_new()
        flt.set_visible_func(lambda m, it, _d: (search.get_text().lower() in m[it][1].lower()
                                                or search.get_text().lower() in m[it][2].lower()))
        search.connect("search-changed", lambda *_a: flt.refilter())
        view = Gtk.TreeView(model=flt)
        tog = Gtk.CellRendererToggle()

        def toggled(_c, path):
            it = flt.convert_iter_to_child_iter(flt.get_iter(path))
            store[it][0] = not store[it][0]
        tog.connect("toggled", toggled)
        view.append_column(Gtk.TreeViewColumn("", tog, active=0))
        col = Gtk.TreeViewColumn(_("Language"), Gtk.CellRendererText(), text=1)
        col.set_expand(True)
        view.append_column(col)
        view.append_column(Gtk.TreeViewColumn(_("Code"), Gtk.CellRendererText(), text=2))
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.add(view)
        box.pack_start(sw, True, True, 0)
        dlg.show_all()
        picked = []
        if dlg.run() == Gtk.ResponseType.OK:
            picked = [r[2] for r in store if r[0]]
        dlg.destroy()
        if not picked:
            return
        self.window.set_status(_("Adding languages…"))
        while Gtk.events_pending():
            Gtk.main_iteration()
        ok, msg = R.enable(picked)
        if ok:
            self.window.set_status(_("Languages added"))
        elif msg:
            self.window.message(_("Could not add the languages"), msg)
        self._fill_language()

    # ---------------------------------------------------------------- refresh
    def _refresh(self):
        st = R.time_state()
        self.loading = True
        if st:
            tz = st.get("Timezone", "")
            self.tz.get_child().set_text(tz)
            self.ntp.set_active(bool(st.get("NTP")))
            self.ntp.set_sensitive(bool(st.get("CanNTP")))
            self.rtc.set_active(bool(st.get("LocalRTC")))
            notes = []
            if not st.get("CanNTP"):
                notes.append(_("No time sync service is installed (systemd-timesyncd, chrony or ntpd)."))
            elif st.get("NTP"):
                notes.append(_("Synchronized.") if st.get("NTPSynchronized") else _("Not synchronized yet."))
            self.ntp_note.set_text(" ".join(notes))
            self.ntp_note.set_visible(bool(notes))
            self.manual.set_sensitive(not st.get("NTP"))
            self.time_note.set_visible(False)
        else:
            for w in (self.tz, self.tz_btn, self.ntp, self.manual, self.rtc):
                w.set_sensitive(False)
            self.time_note.set_text(_("systemd's timedated isn't available, so the time can't be changed here."))
            self.time_note.set_visible(True)
        now = datetime.datetime.now()
        self.cal.select_month(now.month - 1, now.year)
        self.cal.select_day(now.day)
        self.date_btn.set_label(now.strftime("%x"))
        self.hh.set_value(now.hour)
        self.mm.set_value(now.minute)
        self.loading = False
        self._fill_language()
        self._tick()
