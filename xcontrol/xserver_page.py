"""System > X server: which X server runs, the modules it loaded, and its options."""
import os
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import xserver as X  # noqa: E402
from .i18n import N_, _  # noqa: E402

SERVER = "#server"       # the list's first row: the server itself (no module has a # in its name)
KINDS = {"video": N_("Video driver"), "input": N_("Input driver"), "extension": N_("Extension"),
         "other": N_("Module")}


def _dim(text, mono=False):
    lbl = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
    lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.set_can_focus(False)
    lbl.get_style_context().add_class("dim-label")
    if mono:
        lbl.get_style_context().add_class("monospace")
    return lbl


def _heading(text):
    lbl = Gtk.Label(xalign=0)
    lbl.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
    return lbl


class OptionsDialog(Gtk.Dialog):
    """Set options (documented ones, plus any other by name); empty means the default."""

    def __init__(self, parent, title, intro, options, ours, now):
        super().__init__(title=title, transient_for=parent, modal=True)
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = self.add_button(_("Save"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        self.set_default_size(780, 640)
        self.widgets = {}
        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)
        lbl = Gtk.Label(label=intro, xalign=0, wrap=True)
        lbl.set_max_width_chars(95)
        box.pack_start(lbl, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=4, border_width=4, hexpand=True)
        r = 0
        documented = {o.name.lower() for o in options}
        for o in options:
            name = Gtk.Label(label=o.name, xalign=0, yalign=0)
            name.get_style_context().add_class("monospace")
            mine = next((v for k, v in ours.items() if k.lower() == o.name.lower()), "")
            if o.type.lower() == "boolean":
                w = Gtk.ComboBoxText()
                w.append("", _("Default"))
                w.append("true", _("On"))
                w.append("false", _("Off"))
                low = mine.lower()
                w.set_active_id("true" if low in ("true", "on", "1", "yes") else
                                "false" if low in ("false", "off", "0", "no") else "")
            else:
                w = Gtk.Entry(text=mine, placeholder_text=_("default"), width_chars=16)
                w.set_tooltip_text(_("Type: {type}").format(type=o.type) if o.type else None)
            cur = now.get(o.name.lower())
            state = (_("now: {value}").format(value=cur[0] or "—") if cur and cur[1] == "config" else
                     _("now: default"))
            st = _dim(state)
            st.set_hexpand(True)
            desc = _dim(o.description)
            desc.set_max_width_chars(90)
            grid.attach(name, 0, r, 1, 1)
            grid.attach(w, 1, r, 1, 1)
            grid.attach(st, 2, r, 1, 1)
            grid.attach(desc, 0, r + 1, 3, 1)
            sep = Gtk.Separator(margin_top=4, margin_bottom=4)
            grid.attach(sep, 0, r + 2, 3, 1)
            self.widgets[o.name] = w
            r += 3
        sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.add(grid)
        box.pack_start(sw, True, True, 0)

        box.pack_start(_heading(_("Other options")), False, False, 0)
        box.pack_start(_dim(_("For options the manual doesn't list (one per line: Name value). XControl "
                              "can't check these, so only add what you know the driver takes.")), False, False, 0)
        self.extra = Gtk.TextView(monospace=True)
        self.extra.set_size_request(-1, 70)
        self.extra.get_buffer().set_text("\n".join(f"{k} {v}" for k, v in ours.items()
                                                   if k.lower() not in documented))
        frame = Gtk.Frame()
        frame.add(self.extra)
        box.pack_start(frame, False, False, 0)
        self.error = Gtk.Label(xalign=0, wrap=True)
        box.pack_start(self.error, False, False, 0)
        self.show_all()
        self.error.hide()

    def values(self):
        """{name: value} to save, or None when something typed isn't allowed."""
        out = {}
        for name, w in self.widgets.items():
            v = w.get_active_id() if isinstance(w, Gtk.ComboBoxText) else w.get_text().strip()
            if v:
                out[name] = v
        buf = self.extra.get_buffer()
        for line in buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).splitlines():
            parts = line.split()
            if not parts:
                continue
            out[parts[0]] = parts[1] if len(parts) > 1 else "true"
        bad = [f"{k} {v}" for k, v in out.items() if not X.NAME.match(k) or not X.VALUE.match(v)]
        if bad:
            self.error.set_markup("⚠ " + GLib.markup_escape_text(
                _("Not allowed (names are letters, digits and _; values can't have spaces or quotes): "
                  "{items}").format(items=", ".join(bad))))
            self.error.show()
            return None
        return out

    def ask(self):
        while True:
            if self.run() != Gtk.ResponseType.OK:
                self.destroy()
                return None
            v = self.values()
            if v is not None:
                self.destroy()
                return v


class XServerTab(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, border_width=18)
        self.window = window
        self.current = None
        self.info = None

        frame = Gtk.Frame()
        frame.get_style_context().add_class("view")
        self.head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, border_width=10)
        frame.add(self.head)
        self.pack_start(frame, False, False, 0)

        self.store = Gtk.ListStore(str, str, str)       # name, shown name, kind
        self.view = Gtk.TreeView(model=self.store, headers_visible=True)
        for title, col in ((_("Module"), 1), (_("Kind"), 2)):
            cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if col == 1 else Pango.EllipsizeMode.NONE)
            column = Gtk.TreeViewColumn(title, cell, markup=col) if col == 1 else \
                Gtk.TreeViewColumn(title, cell, text=col)
            column.set_resizable(True)
            column.set_expand(col == 1)
            self.view.append_column(column)
        self.view.get_selection().connect("changed", self._selected)
        left = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        left.set_shadow_type(Gtk.ShadowType.IN)
        left.set_min_content_width(220)
        left.add(self.view)
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, border_width=14)
        right = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        right.set_shadow_type(Gtk.ShadowType.IN)
        right.set_min_content_width(380)
        right.add(self.details)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        paned.pack1(left, False, False)
        paned.pack2(right, True, False)
        paned.set_position(340)
        self.pack_start(paned, True, True, 0)
        bar = Gtk.Box(spacing=8)
        refresh = Gtk.Button(label=_("Refresh"))
        refresh.connect("clicked", lambda *_a: self.reload())
        bar.pack_end(refresh, False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.reload()

    # ---------------------------------------------------------------- loading
    def reload(self):
        self.info = X.read_log()
        self.ours, self.server_ours, self.ours_for = X.read_ours()
        self.picks = X.read_picks()
        self.others, self.flag_files = X.elsewhere()
        self.kdrivers = X.kernel_drivers()
        self._fill_head()
        keep = self.current
        self.store.clear()
        if self.info:
            self.store.append([SERVER, f"<b>{GLib.markup_escape_text(self._server_name())}</b>", ""])
            in_use = {m.name for m in X.video_drivers(self.info)}
            for m in self.info.modules:
                kind = _(KINDS[m.kind])
                if m.kind == "video":
                    kind = _("Video driver, in use") if m.name in in_use else _("Video driver, not used")
                shown = GLib.markup_escape_text(m.name)
                if m.unloaded or (m.kind == "video" and m.name not in in_use):
                    shown = f"<span alpha='55%'>{shown}</span>"
                self.store.append([m.name, shown, kind])
        self._select(keep if keep else (X.video_drivers(self.info)[0].name
                                        if self.info and X.video_drivers(self.info) else SERVER))

    def _server_name(self):
        i = self.info
        return f"{i.server or 'X'} {i.version}".strip() if i else "X"

    def _fill_head(self):
        for c in self.head.get_children():
            c.destroy()
        if not self.info:
            self.head.pack_start(_dim(_("No X server log found for this display, so XControl can't tell what X "
                                        "loaded. (Is this an X session?)")), False, False, 0)
            self.head.show_all()
            return
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>{}</b>".format(GLib.markup_escape_text(self._server_name())))
        self.head.pack_start(lbl, False, False, 0)
        self.head.pack_start(_dim(_("From its log: {path}").format(path=self.info.path)), False, False, 0)
        notes = []
        if self.ours or self.server_ours or self.picks:
            notes.append(_("XControl's options are in {file}. They take effect the next time X starts. If X ever "
                           "won't start, undo them from a text console (Ctrl+Alt+F3): sudo rm {file}").format(
                               file=X.all_ours()))
        in_use = [m.name for m in X.video_drivers(self.info)]
        if self.ours and self.ours_for not in ("", "-") and in_use and self.ours_for not in in_use:
            notes.append("⚠ " + _("They were chosen for the {old} X driver, but X now runs {new}; options {new} "
                                  "doesn't know are ignored.").format(old=self.ours_for, new=", ".join(in_use)))
        ours_names = {k.lower() for opts in self.ours.values() for k in opts} | \
            {k.lower() for k in self.server_ours}
        unused = sorted({name for _scope, name in self.info.unused if name.lower() in ours_names})
        if unused:
            notes.append("⚠ " + _("X ignored these options of XControl's at its last start: {names}").format(
                names=", ".join(unused)))
        for n in notes:
            self.head.pack_start(_dim(n), False, False, 0)
        self.head.show_all()

    def _select(self, name):
        it = self.store.get_iter_first()
        while it:
            if self.store[it][0] == name:
                self.view.get_selection().select_iter(it)
                return
            it = self.store.iter_next(it)
        self._show(None)

    def _selected(self, selection):
        model, it = selection.get_selected()
        name = model[it][0] if it else None
        self.current = name
        self._show(name)

    # ---------------------------------------------------------------- details
    def _clear(self):
        for c in self.details.get_children():
            c.destroy()

    def _grid(self, rows):
        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        for r, (k, v) in enumerate(rows):
            kl = Gtk.Label(label=k, xalign=0, yalign=0)
            kl.get_style_context().add_class("dim-label")
            vl = Gtk.Label(label=v, xalign=0, yalign=0, selectable=True, wrap=True, hexpand=True)
            vl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            vl.set_can_focus(False)
            grid.attach(kl, 0, r, 1, 1)
            grid.attach(vl, 1, r, 1, 1)
        return grid

    def _options_list(self, options, scope):
        """The documented options with what X used; options set elsewhere are named too."""
        grid = Gtk.Grid(column_spacing=14, row_spacing=6)
        used = self.info.used if self.info else {}
        for r, o in enumerate(options):
            k = Gtk.Label(label=o.name, xalign=0, yalign=0, selectable=True)
            k.set_can_focus(False)
            k.get_style_context().add_class("monospace")
            cur = used.get((scope, o.name.lower()))
            v = Gtk.Label(xalign=0, yalign=0)
            if cur and cur[1] == "config":
                v.set_markup("<tt>{}</tt>".format(GLib.markup_escape_text(cur[0] or "—")))
            else:
                v.set_text(_("default"))
                v.get_style_context().add_class("dim-label")
            about = " ".join(x for x in (o.description, f"({o.type})" if o.type else "") if x)
            n = Gtk.Label(label=about, xalign=0, yalign=0, wrap=True, hexpand=True)
            n.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            n.set_max_width_chars(60)
            n.get_style_context().add_class("dim-label")
            grid.attach(k, 0, r, 1, 1)
            grid.attach(v, 1, r, 1, 1)
            grid.attach(n, 2, r, 1, 1)
        return grid

    def _set_elsewhere(self, section_match):
        rows = [(path, f'Option "{name}" "{value}"') for path, section, name, value in self.others
                if section_match(section)]
        if not rows:
            return None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(_heading(_("Also set in other files")), False, False, 0)
        for path, line in rows[:12]:
            lbl = Gtk.Label(xalign=0, selectable=True, wrap=True)
            lbl.set_can_focus(False)
            lbl.set_markup(f"<tt>{GLib.markup_escape_text(line)}</tt>  "
                           f"<span alpha='60%'>{GLib.markup_escape_text(path)}</span>")
            box.pack_start(lbl, False, False, 0)
        return box

    def _show(self, name):
        self._clear()
        if not name or not self.info:
            self.details.pack_start(_dim(_("Select the server or a module.")), False, False, 0)
            self.details.show_all()
            return
        if name == SERVER:
            self._show_server()
        else:
            self._show_module(next((m for m in self.info.modules if m.name == name), None))
        self.details.show_all()

    def _show_server(self):
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<span size='large' weight='bold'>{GLib.markup_escape_text(self._server_name())}</span>")
        self.details.pack_start(title, False, False, 0)
        vids = X.video_drivers(self.info)
        rows = [(_("Video driver"), ", ".join(m.name for m in vids) or "—"),
                (_("GPUs"), ", ".join(f"{card} ({kd})" for card, kd in self.kdrivers.items()) or "—")]
        self.details.pack_start(self._grid(rows), False, False, 0)
        self._driver_choice()
        flags = X.server_flags()
        head = Gtk.Box(spacing=8)
        head.pack_start(_heading(_("Server-wide options")), False, False, 0)
        if flags and X.can_save():
            b = Gtk.Button(label=_("Change…"))
            b.connect("clicked", lambda *_a: self._change_server(flags))
            head.pack_end(b, False, False, 0)
        self.details.pack_start(head, False, False, 0)
        if self.flag_files:
            note = _("{files} has its own ServerFlags section; X may use that one instead of XControl's.")
            self.details.pack_start(_dim("⚠ " + note.format(files=", ".join(self.flag_files))), False, False, 0)
        if flags:
            self.details.pack_start(self._options_list(flags, "server"), False, False, 0)
        else:
            self.details.pack_start(_dim(_("xorg.conf's manual isn't installed, so the options can't be listed "
                                           "(it comes with the X server's package).")), False, False, 0)
        other = self._set_elsewhere(lambda s: s.lower() == "serverflags")
        if other:
            self.details.pack_start(other, False, False, 0)

    def _gpus(self):
        """The GPUs' kernel drivers X could drive (not firmware framebuffers)."""
        return sorted({kd for kd in self.kdrivers.values() if kd not in ("simpledrm", "efifb", "vgem", "vkms")})

    def _auto(self, kd, installed):
        """What X picks by itself: a vendor driver's package adds a rule for its GPUs; else modesetting."""
        vendor = [d for d in X.choices(kd, installed) if d != "modesetting"]
        return vendor[0] if vendor else "modesetting"

    def _driver_choice(self):
        dirs = X.search_dirs(self.info)
        found = X.find_drivers(dirs)
        abi = X.server_video_abi(self.info)
        installed = X.loadable(found, abi)
        gpus = self._gpus()
        if not gpus or not installed:
            return
        self.details.pack_start(_heading(_("Video driver")), False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        in_use = {self.kdrivers.get(c): m.name for m in X.video_drivers(self.info)
                  for c in self.info.cards.get(m.name, ())}
        # XLibre 25 crashes in its bus probe with XControl's Device section (seen on 25.1.9, with and
        # without a BusID): there only going back to automatic is offered, until that's understood
        blocked = self.info.server == "XLibre"
        for r, kd in enumerate(gpus):
            lbl = Gtk.Label(label=_("GPU with {driver}").format(driver=kd), xalign=0)
            combo = Gtk.ComboBoxText(hexpand=True)
            # (when XControl picks nothing, what runs now is what "automatic" gives: X's own rules and yours)
            auto = in_use.get(kd) if not self.picks.get(kd) and in_use.get(kd) else self._auto(kd, installed)
            combo.append("", _("Automatic ({driver})").format(driver=auto))
            for d in X.choices(kd, installed):
                if not blocked or d == self.picks.get(kd):
                    combo.append(d, d)
            combo.set_active_id(self.picks.get(kd, ""))
            if combo.get_active() < 0:
                combo.set_active_id("")
            apply = Gtk.Button(label=_("Switch…"))
            apply.set_sensitive(False)
            combo.connect("changed", lambda c, b=apply, k=kd: b.set_sensitive((c.get_active_id() or "") !=
                                                                              self.picks.get(k, "")))
            apply.connect("clicked", lambda _b, c=combo, k=kd: self._switch(k, c.get_active_id() or "",
                                                                            installed))
            grid.attach(lbl, 0, r, 1, 1)
            grid.attach(combo, 1, r, 1, 1)
            grid.attach(apply, 2, r, 1, 1)
            now = in_use.get(kd)
            if now:
                grid.attach(_dim(_("now: {driver}").format(driver=now)), 3, r, 1, 1)
        self.details.pack_start(grid, False, False, 0)
        if blocked:
            self.details.pack_start(_dim("⚠ " + _(
                "Choosing the driver here is turned off on XLibre for now: XLibre 25 crashed at start with "
                "XControl's Device section. To pick one, set the Driver line in your own Device section "
                "instead (the drivers it would load are listed below).")), False, False, 0)
        self._driver_notes()
        rows = []
        for name, (path, mabi) in sorted(found.items()):
            if not any(name == "modesetting" or kd in X.SUITS.get(name, ()) for kd in gpus):
                continue
            built = f"{mabi[0]}.{mabi[1]}" if mabi else "?"
            ok = name in installed
            rows.append((name, f"{path}  ·  " + (_("video ABI {abi}").format(abi=built)) +
                         ("" if ok else "  ·  " + _("not loadable"))))
        if rows:
            self.details.pack_start(self._grid(rows), False, False, 0)
        notes = [_("These are the X drivers {server} finds (it looks in {folders}, in that order), with the "
                   "driver interface version each was built for; it takes video ABI {abi}.").format(
                       server=self.info.server or "X", folders=", ".join(dirs), abi=abi if abi else "?")]
        for name, (path, mabi) in sorted(found.items()):
            if name not in installed and any(kd in X.SUITS.get(name, ()) for kd in gpus):
                notes.append(_("{driver} was built for video ABI {built}, so {server} won't load it; install its "
                               "build for {server}.").format(driver=name, built=f"{mabi[0]}.{mabi[1]}",
                                                             server=self.info.server or "X"))
        for n in notes:
            self.details.pack_start(_dim(n), False, False, 0)

    def _driver_notes(self):
        """Whether XControl's choice is the one X used, and what in other files could win over it."""
        notes = []
        ours = {f"XControl: {kd}" for kd in self.picks}
        used = self.info.device
        if self.picks and used and used not in ours:
            notes.append("⚠ " + _("At its last start X used the Device section \"{name}\", not XControl's. If you "
                                  "picked the driver after that, log out and back in.").format(name=used))
        elif self.picks and used in ours:
            notes.append(_("X used XControl's choice at its last start."))
        devices, screens = X.device_sections()
        for path, screen, dev in screens:
            notes.append("⚠ " + _("{file} has a Screen section that names its own Device (\"{device}\"); X uses "
                                  "that one, so XControl's choice can't apply.").format(file=path, device=dev))
        ours_dir = os.path.dirname(X.driver_path())     # (X reads /usr/share's, then /etc's in order, then xorg.conf)
        before = [(p, i, d) for p, i, d in devices if p.startswith("/usr/share/") or
                  (os.path.dirname(p) == ours_dir and os.path.basename(p) < X.DRIVER_FILE)]
        for path, ident, drv in before:
            notes.append("⚠ " + _("{file} has a Device section (\"{name}\") that X reads before XControl's, so "
                                  "it wins.").format(file=path, name=ident))
        if self.picks and not screens:
            notes.append(_("XControl picks the driver with a Device section in {file}: X uses the first one it "
                           "reads instead of guessing. Delete that file to go back to automatic.").format(
                               file=X.driver_path()))
        for n in notes:
            self.details.pack_start(_dim(n), False, False, 0)

    def _switch(self, kd, xd, installed):
        old = self.picks.get(kd) or self._in_use_for(kd) or self._auto(kd, installed)
        new = xd or (self._in_use_for(kd) if not self.picks.get(kd) else "") or self._auto(kd, installed)
        md = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.QUESTION,
                               buttons=Gtk.ButtonsType.OK_CANCEL,
                               text=_("Use {new} instead of {old}?").format(new=new, old=old))
        md.format_secondary_text(_(
            "It takes effect the next time X starts (log out and back in). The outputs get other names "
            "(DP-1 with modesetting is DisplayPort-0 with amdgpu); XControl moves your saved display settings "
            "over. Options you set for {old} are kept for when you switch back. If X won't start, undo it from "
            "a text console (Ctrl+Alt+F3): sudo rm {file}").format(old=old, file=X.all_ours()))
        ok = md.run() == Gtk.ResponseType.OK
        md.destroy()
        if not ok:
            return
        X.remember(old, {kd: dict(self.ours.get(kd, {}))})
        mine = X.remembered().get(new, {})
        drivers = dict(self.ours)
        drivers[kd] = dict(mine.get(kd, {}))
        picks = dict(self.picks)
        if xd:
            picks[kd] = xd
        else:
            picks.pop(kd, None)
        self._save(drivers, self.server_ours, new, picks)

    def _in_use_for(self, kd):
        for m in X.video_drivers(self.info):
            if any(self.kdrivers.get(c) == kd for c in self.info.cards.get(m.name, ())):
                return m.name
        return ""

    def _show_module(self, m):
        if not m:
            return
        title = Gtk.Label(xalign=0, wrap=True)
        title.set_markup(f"<span size='large' weight='bold'>{GLib.markup_escape_text(m.name)}</span>\n"
                         f"<span size='small'>{GLib.markup_escape_text(_(KINDS[m.kind]))}</span>")
        self.details.pack_start(title, False, False, 0)
        rows = []
        if m.path:
            rows.append((_("File"), m.path))
        if m.version:
            rows.append((_("Version"), m.version))
        if m.abi:
            rows.append((_("ABI"), m.abi))
        in_use = m in X.video_drivers(self.info)
        if m.kind == "video":
            cards = sorted(self.info.cards.get(m.name, ()))
            if in_use:
                rows.append((_("Drives"), ", ".join(
                    [_("screen {n}").format(n=s) for s in m.screens] +
                    [f"{c} ({self.kdrivers.get(c, '?')})" for c in cards])))
            else:
                rows.append((_("State"), _("Loaded, then let go: it didn't find hardware of its own")
                             if m.unloaded else _("Loaded, but drives no screen")))
        elif m.unloaded:
            rows.append((_("State"), _("Loaded, then let go")))
        if rows:
            self.details.pack_start(self._grid(rows), False, False, 0)
        if m.kind == "input":
            self.details.pack_start(_dim(_("Input devices' settings are on the Input page.")), False, False, 0)
            return
        if m.kind != "video" or not in_use:
            return
        options = X.driver_options(m.name)
        head = Gtk.Box(spacing=8)
        head.pack_start(_heading(_("Options")), False, False, 0)
        if X.can_save():
            b = Gtk.Button(label=_("Change…"))
            b.set_tooltip_text(_("Saved for the next time X starts (needs your password)"))
            b.connect("clicked", lambda *_a: self._change_driver(m, options))
            head.pack_end(b, False, False, 0)
        self.details.pack_start(head, False, False, 0)
        if options:
            self.details.pack_start(self._options_list(options, m.name), False, False, 0)
        else:
            self.details.pack_start(_dim(_("{driver}'s manual isn't installed, so its options can't be listed. "
                                           "Other options can still be set by name.").format(driver=m.name)),
                                    False, False, 0)
        other = self._set_elsewhere(lambda s: s.lower() in ("device", "outputclass", "screen"))
        if other:
            self.details.pack_start(other, False, False, 0)

    # ---------------------------------------------------------------- changing
    def _targets(self, m):
        """The kernel drivers of the GPUs this X driver drives (all GPUs when the log doesn't say)."""
        kds = {self.kdrivers[c] for c in self.info.cards.get(m.name, ()) if c in self.kdrivers}
        return sorted(kds or set(self.kdrivers.values()))

    def _change_driver(self, m, options):
        kds = self._targets(m)
        if not kds:
            self.window.message(_("No GPU found"), _("XControl couldn't tell which GPU's driver to set options "
                                                     "for."))
            return
        current = {}
        for kd in kds:
            current.update(self.ours.get(kd, {}))
        now = {name: v for (scope, name), v in self.info.used.items() if scope == m.name}
        intro = _("For the {driver} X driver on {gpus}. Saved in {file}; they take effect the next time X starts "
                  "(log out and back in, or restart your login screen).").format(
                      driver=m.name, gpus=", ".join(kds), file=X.our_path())
        new = OptionsDialog(self.window, _("{driver} options").format(driver=m.name), intro, options, current,
                            now).ask()
        if new is None:
            return
        drivers = dict(self.ours)
        for kd in kds:
            drivers[kd] = dict(new)
        self._save(drivers, self.server_ours, m.name)

    def _change_server(self, flags):
        now = {name: v for (scope, name), v in self.info.used.items() if scope == "server"}
        intro = _("For the whole X server. Saved in {file}; they take effect the next time X starts.").format(
            file=X.our_path())
        new = OptionsDialog(self.window, _("Server-wide options"), intro, flags, self.server_ours, now).ask()
        if new is None:
            return
        vids = X.video_drivers(self.info)
        self._save(self.ours, new, self.ours_for if self.ours_for not in ("", "-") else
                   (vids[0].name if vids else ""))

    def _save(self, drivers, server, xdriver, picks=None):
        picks = self.picks if picks is None else picks

        def work():
            ok, msg = X.save(drivers, server, xdriver, picks, X.gpus())
            GLib.idle_add(done, ok, msg)

        def done(ok, msg):
            if ok:
                self.window.set_status(_("Saved; X uses it the next time it starts"))
                self.reload()
            elif msg:
                self.window.message(_("Could not save the X options"), msg)
            return False
        self.window.set_status(_("Saving…"))
        threading.Thread(target=work, daemon=True).start()
