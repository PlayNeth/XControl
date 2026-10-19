"""The System page: an overview (distribution, kernel, hardware, live readings) and the
kernel modules in use."""
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk, Pango  # noqa: E402

from . import kmods, sysinfo  # noqa: E402
from .i18n import _  # noqa: E402

REFRESH_MS = 2000


class SystemPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=stack, halign=Gtk.Align.CENTER, margin_top=10, margin_bottom=4)
        self.pack_start(switcher, False, False, 0)
        overview = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
        overview.add(OverviewTab(window))
        stack.add_titled(overview, "overview", _("Overview"))
        # the tab fills the height itself (its lists scroll); scroll sideways when the window is narrow
        modules = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                     vscrollbar_policy=Gtk.PolicyType.NEVER)
        modules.add(ModulesTab(window))
        stack.add_titled(modules, "modules", _("Kernel modules"))
        self.pack_start(stack, True, True, 0)


class OverviewTab(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16, border_width=18)
        self.window = window
        self.info = sysinfo.collect()
        sysinfo.live(self.info)
        self.values = {}       # (section id, label) -> value Gtk.Label
        self.layout_key = None

        # ---- header: logo, distribution, kernel, copy buttons
        head = Gtk.Box(spacing=14)
        logo = Gtk.Image()
        icon = self.info.os.get("LOGO") or ""
        theme = Gtk.IconTheme.get_default()
        logo.set_from_icon_name(icon if icon and theme.has_icon(icon) else "computer", Gtk.IconSize.DIALOG)
        logo.set_pixel_size(64)
        head.pack_start(logo, False, False, 0)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<span size='xx-large' weight='bold'>"
                         f"{GLib.markup_escape_text(sysinfo.headline(self.info))}</span>")
        titles.pack_start(title, False, False, 0)
        sub = Gtk.Label(xalign=0)
        sub.get_style_context().add_class("dim-label")
        sub.set_text(" · ".join(x for x in (self.info.hostname, f"Linux {self.info.kernel}",
                                            self.info.cpu_model) if x))
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        titles.pack_start(sub, False, False, 0)
        head.pack_start(titles, True, True, 0)

        copy_box = Gtk.Box(valign=Gtk.Align.CENTER)
        copy_box.get_style_context().add_class("linked")
        copy_btn = Gtk.Button(label=_("Copy"))
        copy_btn.set_tooltip_text(_("Copy this information (without your computer and user names)"))
        copy_btn.connect("clicked", lambda *_a: self._copy(False))
        copy_box.pack_start(copy_btn, False, False, 0)
        more = Gtk.MenuButton()
        more.set_tooltip_text(_("More copy options"))
        menu = Gtk.Menu()
        item = Gtk.MenuItem(label=_("Copy in English (for bug reports)"))
        item.connect("activate", lambda _i: self._copy(True))
        menu.append(item)
        menu.show_all()
        more.set_popup(menu)
        copy_box.pack_start(more, False, False, 0)
        head.pack_end(copy_box, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.columns = Gtk.Box(spacing=16, homogeneous=True)
        self.pack_start(self.columns, False, False, 0)
        self._render()

        threading.Thread(target=self._slow, daemon=True).start()
        self.timer = GLib.timeout_add(REFRESH_MS, self._tick)
        self.connect("destroy", self._stop)

    # ---- data
    def _slow(self):
        try:
            sysinfo.slow(self.info)
        except Exception:  # noqa: BLE001
            self.info.slow_done = True
        GLib.idle_add(self._render)

    def _tick(self):
        if self.get_mapped():  # only while the page is on screen
            sysinfo.live(self.info)
            self._render()
        return True

    def _stop(self, *_args):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    # ---- view
    def _render(self):
        sections = sysinfo.describe(self.info)
        key = [(sid, tuple(k for k, _v in rows)) for sid, _t, rows in sections]
        if key == self.layout_key:
            for sid, _title, rows in sections:
                for label, value in rows:
                    w = self.values.get((sid, label))
                    if w and w.get_text() != value:
                        w.set_text(value)
            return False
        self.layout_key = key
        for child in self.columns.get_children():
            child.destroy()
        self.values = {}
        cols = [Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16) for _ in range(2)]
        for col in cols:
            self.columns.pack_start(col, True, True, 0)
        heights = [0, 0]
        for sid, title, rows in sections:
            target = 0 if heights[0] <= heights[1] else 1
            cols[target].pack_start(self._card(sid, title, rows), False, False, 0)
            heights[target] += len(rows) + 3
        self.columns.show_all()
        return False

    def _card(self, sid, title, rows):
        frame = Gtk.Frame()
        frame.get_style_context().add_class("view")
        grid = Gtk.Grid(column_spacing=12, row_spacing=4, border_width=12)
        frame.add(grid)
        head = Gtk.Label(xalign=0)
        head.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        head.set_margin_bottom(4)
        grid.attach(head, 0, 0, 2, 1)
        for r, (label, value) in enumerate(rows, 1):
            k = Gtk.Label(label=label, xalign=0, yalign=0)
            k.get_style_context().add_class("dim-label")
            k.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            k.set_max_width_chars(22)
            v = Gtk.Label(label=value, xalign=0, yalign=0, selectable=True, wrap=True, hexpand=True)
            v.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            v.set_width_chars(12)
            v.set_max_width_chars(34)
            v.set_can_focus(False)  # selectable labels would otherwise grab focus and scroll the page
            grid.attach(k, 0, r, 1, 1)
            grid.attach(v, 1, r, 1, 1)
            self.values[(sid, label)] = v
        return frame

    def _copy(self, english):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(sysinfo.as_text(self.info, english), -1)
        self.window.set_status(_("System information copied"))


class ModulesTab(Gtk.Box):
    """Loaded kernel modules; select one for its devices, parameters and modprobe.d options."""
    COLS = (0, 1, 2, 3)  # name, size text, used-by text, size (for sorting)

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, border_width=18)
        self.window = window
        self.current = None

        frame = Gtk.Frame()
        frame.get_style_context().add_class("view")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, border_width=10)
        head = Gtk.Label(xalign=0)
        head.set_markup(f"<b>{GLib.markup_escape_text(_('Kernel command line'))}</b>")
        box.pack_start(head, False, False, 0)
        cmd = Gtk.Label(label=kmods.cmdline() or "—", xalign=0, selectable=True, wrap=True)
        cmd.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        cmd.set_can_focus(False)
        cmd.get_style_context().add_class("monospace")
        box.pack_start(cmd, False, False, 0)
        frame.add(box)
        self.pack_start(frame, False, False, 0)

        bar = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search modules, devices or parameters"))
        self.search.connect("search-changed", self._search)
        bar.pack_start(self.search, True, True, 0)
        self.builtin = Gtk.CheckButton(label=_("Include parts built into the kernel"))
        self.builtin.set_tooltip_text(_("Parts of the kernel that can't be unloaded but still have parameters"))
        self.builtin.connect("toggled", lambda *_a: self.reload())
        bar.pack_start(self.builtin, False, False, 0)
        refresh = Gtk.Button(label=_("Refresh"))
        refresh.connect("clicked", lambda *_a: self.reload())
        bar.pack_start(refresh, False, False, 0)
        self.pack_start(bar, False, False, 0)

        # name, size, used by, size bytes, built-in, search text
        self.store = Gtk.ListStore(str, str, str, GObject.TYPE_INT64, bool, str)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        sorted_model = Gtk.TreeModelSort(model=self.filter)
        self.view = Gtk.TreeView(model=sorted_model, headers_visible=True, enable_search=False)
        for i, (title, col, sort, expand) in enumerate(((_("Module"), 0, 0, False), (_("Size"), 1, 3, False),
                                                        (_("Used by"), 2, 2, True))):
            cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE)
            if i == 1:
                cell.set_property("xalign", 1.0)
            column = Gtk.TreeViewColumn(title, cell, text=col)
            column.set_sort_column_id(sort)
            column.set_resizable(True)
            column.set_expand(expand)
            self.view.append_column(column)
        sorted_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        self.view.get_selection().connect("changed", self._selected)
        left = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        left.set_shadow_type(Gtk.ShadowType.IN)
        left.set_min_content_width(220)
        left.add(self.view)

        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, border_width=14)
        right = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        right.set_shadow_type(Gtk.ShadowType.IN)
        right.set_min_content_width(380)  # below this the whole tab scrolls sideways instead
        right.add(self.details)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        paned.pack1(left, False, False)
        paned.pack2(right, True, False)
        paned.set_position(300)
        self.pack_start(paned, True, True, 0)
        self.count = Gtk.Label(xalign=0)
        self.count.get_style_context().add_class("dim-label")
        self.pack_start(self.count, False, False, 0)
        self.reload()

    def reload(self):
        selected = self.current
        self.store.clear()
        mods = kmods.modules(include_builtin=self.builtin.get_active())
        for m in mods:
            if m.builtin:
                size, used = "", _("built into the kernel")
            else:
                size = f"{m.size / 1024:,.0f} KiB".replace(",", "\u202f")
                used = ", ".join(m.used_by)  # other modules that need it
            words = [m.name, used]
            words += [d[2] for d in kmods.devices(m.name)]
            self.store.append([m.name, size, used, m.size, m.builtin, " ".join(words).lower()])
        loaded = sum(1 for m in mods if not m.builtin)
        self.count.set_text(_("{n} modules loaded").format(n=loaded) if loaded else
                            _("No loadable modules are in use (the kernel was started without them)."))
        self._select(selected)
        if self.current is None:
            self._show(None)

    def _search(self, *_args):
        self.filter.refilter()
        model = self.view.get_model()
        it = model.get_iter_first()
        if it and model.iter_n_children(None) == 1:   # one match: show it right away
            self.view.get_selection().select_iter(it)

    def _visible(self, model, it, _data):
        q = self.search.get_text().strip().lower()
        if not q:
            return True
        if q in model[it][5]:
            return True
        # also match parameter names, but only cheaply (no modinfo)
        return any(q in prm.name.lower() for prm in kmods.params(model[it][0]))

    def _select(self, name):
        model = self.view.get_model()
        it = model.get_iter_first()
        while it:
            if model[it][0] == name:
                self.view.get_selection().select_iter(it)
                self.view.scroll_to_cell(model.get_path(it), None, False, 0, 0)
                return
            it = model.iter_next(it)

    def _selected(self, selection):
        model, it = selection.get_selected()
        name = model[it][0] if it else None
        if name != self.current:
            self.current = name
            self._show(name)

    def _show(self, name):
        for child in self.details.get_children():
            child.destroy()
        if not name:
            hint = Gtk.Label(label=_("Select a module to see what it drives and its parameters."), xalign=0,
                             wrap=True)
            hint.get_style_context().add_class("dim-label")
            self.details.pack_start(hint, False, False, 0)
            self.details.show_all()
            return
        d = kmods.details(name)
        head = Gtk.Box(spacing=8)
        title = Gtk.Label(xalign=0, wrap=True, selectable=True)
        title.set_can_focus(False)
        desc = f"\n<span size='small'>{GLib.markup_escape_text(d.description)}</span>" if d.description else ""
        title.set_markup(f"<span size='large' weight='bold'>{GLib.markup_escape_text(name)}</span>{desc}")
        head.pack_start(title, True, True, 0)
        copy = Gtk.Button(label=_("Copy"), valign=Gtk.Align.START)
        copy.connect("clicked", lambda *_a: self._copy(d))
        head.pack_end(copy, False, False, 0)
        self.details.pack_start(head, False, False, 0)

        rows = []
        if d.filename:
            rows.append((_("File"), d.filename))
        if d.version:
            rows.append((_("Version"), d.version))
        if d.license:
            rows.append((_("License"), d.license))
        if d.holders:
            rows.append((_("Used by"), ", ".join(d.holders)))
        if d.depends:
            rows.append((_("Needs"), ", ".join(d.depends)))
        if d.firmware:
            rows.append((_("Firmware files"), str(len(d.firmware))))
        if rows:
            self.details.pack_start(self._grid(rows), False, False, 0)

        if d.devices:
            self.details.pack_start(self._heading(_("Devices it drives")), False, False, 0)
            self.details.pack_start(self._grid([(f"{bus} {addr}", desc or "—") for bus, addr, desc in d.devices]),
                                    False, False, 0)

        phead = Gtk.Box(spacing=8)
        phead.pack_start(self._heading(_("Parameters")), False, False, 0)
        if d.params and not kmods.is_builtin(name):
            change = Gtk.Button(label=_("Change…"))
            change.set_tooltip_text(_("Set parameters for every time the module loads (needs your password)"))
            change.connect("clicked", lambda *_a: self._change(d))
            phead.pack_end(change, False, False, 0)
        self.details.pack_start(phead, False, False, 0)
        if d.params and kmods.is_builtin(name):
            self.details.pack_start(self._dim(_("This part is built into the kernel, so modprobe.d doesn't reach "
                                                "it. Set it on the kernel command line as {example}.").format(
                                                    example=f"{name}.{d.params[0].name}=VALUE")), False, False, 0)
        if d.params:
            grid = Gtk.Grid(column_spacing=14, row_spacing=6)
            for r, prm in enumerate(d.params):
                k = Gtk.Label(label=prm.name, xalign=0, yalign=0, selectable=True)
                k.set_can_focus(False)
                k.get_style_context().add_class("monospace")
                if prm.value is kmods.UNREADABLE:
                    v = Gtk.Label(label=_("(only readable by root)"), xalign=0, yalign=0)
                    v.get_style_context().add_class("dim-label")
                else:
                    v = Gtk.Label(label=prm.value or "\u2014", xalign=0, yalign=0, selectable=True, wrap=True)
                    v.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                    v.set_max_width_chars(24)
                    v.set_can_focus(False)
                    v.get_style_context().add_class("monospace")
                about = " ".join(x for x in (prm.description, f"({prm.type})" if prm.type else "") if x)
                n = Gtk.Label(label=about, xalign=0, yalign=0, wrap=True, hexpand=True)
                n.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                n.set_max_width_chars(50)
                n.get_style_context().add_class("dim-label")
                grid.attach(k, 0, r, 1, 1)
                grid.attach(v, 1, r, 1, 1)
                grid.attach(n, 2, r, 1, 1)
            self.details.pack_start(grid, False, False, 0)
        else:
            self.details.pack_start(self._dim(_("This module has no parameters.")), False, False, 0)

        self.details.pack_start(self._heading(_("Set in modprobe.d")), False, False, 0)
        if d.options:
            for path, line in d.options:
                lbl = Gtk.Label(xalign=0, selectable=True, wrap=True)
                lbl.set_can_focus(False)
                lbl.set_markup(f"<tt>{GLib.markup_escape_text(line)}</tt>  "
                               f"<span alpha='60%'>{GLib.markup_escape_text(path)}</span>")
                self.details.pack_start(lbl, False, False, 0)
        else:
            self.details.pack_start(self._dim(_("Nothing; the module runs with its defaults and anything on the "
                                                "kernel command line.")), False, False, 0)
        self.details.show_all()

    def _change(self, d):
        from .module_params_dialog import ModuleParamsDialog
        dlg = ModuleParamsDialog(self.window, d)
        dlg.run()
        changed = dlg.changed
        dlg.destroy()
        if changed:
            self._show(d.name)

    def _heading(self, text):
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        return lbl

    def _dim(self, text):
        lbl = Gtk.Label(label=text, xalign=0, wrap=True)
        lbl.get_style_context().add_class("dim-label")
        return lbl

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

    def _copy(self, d):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(kmods.as_text(d), -1)
        self.window.set_status(_("Module details copied"))
