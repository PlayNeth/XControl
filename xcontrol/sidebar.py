"""The page list on the left, in groups (a Gtk.StackSidebar can't show headings)."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from .i18n import N_, _  # noqa: E402

GROUPS = [
    (N_("Gaming & Hardware"), ["gaming", "displays", "input", "sound"]),
    (N_("Desktop"), ["appearance", "desktop", "panel", "notifications", "i3", "defaults"]),
    (N_("System"), ["region", "power", "users", "system"]),
]


def order():
    """Page names in sidebar order."""
    return [name for _g, names in GROUPS for name in names]


class Sidebar(Gtk.ScrolledWindow):
    def __init__(self, stack):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.stack = stack
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.get_style_context().add_class("sidebar")
        self.add(self.list)
        self.rows = {}
        group_of = {name: g for g, names in GROUPS for name in names}
        names = [n for n in order() if stack.get_child_by_name(n)]
        for child in stack.get_children():
            n = stack.child_get_property(child, "name")
            if n not in names:
                names.append(n)
        for n in names:
            child = stack.get_child_by_name(n)
            title = stack.child_get_property(child, "title")
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=title, xalign=0, margin_start=14, margin_end=10, margin_top=7, margin_bottom=7)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            row.add(lbl)
            row.page, row.group = n, group_of.get(n, "")
            self.list.add(row)
            self.rows[n] = row
        self.list.set_header_func(self._header)
        self.list.connect("row-selected", self._selected)
        stack.connect("notify::visible-child-name", self._follow)
        self._follow()

    def _header(self, row, before):
        if before is not None and before.group == row.group:
            row.set_header(None)
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        if before is not None:
            box.pack_start(Gtk.Separator(margin_top=4), False, False, 0)
        lbl = Gtk.Label(xalign=0, margin_start=10, margin_top=8, margin_bottom=2)
        lbl.set_markup("<small><b>{}</b></small>".format(GLib.markup_escape_text(_(row.group).upper())))
        lbl.get_style_context().add_class("dim-label")
        box.pack_start(lbl, False, False, 0)
        box.show_all()
        row.set_header(box)

    def _selected(self, _lb, row):
        if row is not None and self.stack.get_visible_child_name() != row.page:
            self.stack.set_visible_child_name(row.page)

    def _follow(self, *_a):
        row = self.rows.get(self.stack.get_visible_child_name())
        if row is not None and self.list.get_selected_row() is not row:
            self.list.select_row(row)
