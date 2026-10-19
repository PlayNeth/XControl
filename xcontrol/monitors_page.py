"""What each connected display reports about itself (shown from Displays → Details)."""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import monitor_info  # noqa: E402
from .i18n import _  # noqa: E402


class MonitorsPage(Gtk.Box):
    def __init__(self, window, only=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.only = only  # output name: show just that display
        self.cards = {}

        bar = Gtk.Box(spacing=6)
        intro = Gtk.Label(label=_("Information reported by each connected display (EDID) and its driver."),
                          xalign=0, wrap=True)
        intro.get_style_context().add_class("dim-label")
        bar.pack_start(intro, True, True, 0)
        refresh = Gtk.Button(label=_("Refresh"))
        refresh.connect("clicked", lambda *_a: self.reload())
        bar.pack_end(refresh, False, False, 0)
        self.pack_start(bar, False, False, 0)

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.pack_start(self.list, False, False, 0)
        self.reload()

    def reload(self):
        for child in self.list.get_children():
            child.destroy()
        self.cards = {}
        try:
            records = monitor_info.collect()
            if self.only:
                records = [r for r in records if self.only in (r.x_name, r.drm_name)] or records
        except Exception as e:  # noqa: BLE001
            records = []
            self.window.set_status(_("Could not read monitor information: {error}").format(error=e))
        if not records:
            empty = Gtk.Label(label=_("No connected displays with readable information were found."), xalign=0)
            empty.get_style_context().add_class("dim-label")
            self.list.pack_start(empty, False, False, 0)
        for n, rec in enumerate(records, 1):
            card = self._card(None if len(records) == 1 else n, rec)
            self.list.pack_start(card, False, False, 0)
            for key in (rec.x_name, rec.drm_name):
                if key:
                    self.cards[key] = card
        self.list.show_all()

    def _card(self, n, rec):
        frame = Gtk.Frame()
        frame.get_style_context().add_class("view")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, border_width=14)
        frame.add(box)

        head = Gtk.Box(spacing=8)
        title = Gtk.Label(xalign=0)
        number = f"{n}. " if n else ""
        title.set_markup(f"<span size='x-large' weight='bold'>{number}{GLib.markup_escape_text(rec.title())}</span>")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        head.pack_start(title, True, True, 0)
        copy_box = Gtk.Box()
        copy_box.get_style_context().add_class("linked")
        copy_btn = Gtk.Button(label=_("Copy details"))
        copy_btn.connect("clicked", self._copy, rec, False)
        copy_box.pack_start(copy_btn, False, False, 0)
        more = Gtk.MenuButton()
        more.set_tooltip_text(_("More copy options"))
        menu = Gtk.Menu()
        item = Gtk.MenuItem(label=_("Copy in English (for bug reports)"))
        item.connect("activate", lambda _i: self._copy(None, rec, True))
        menu.append(item)
        menu.show_all()
        more.set_popup(menu)
        copy_box.pack_start(more, False, False, 0)
        head.pack_end(copy_box, False, False, 0)
        if rec.raw:
            save_btn = Gtk.Button(label=_("Save EDID…"))
            save_btn.set_tooltip_text(_("Save the raw EDID, e.g. for edid-decode or a bug report"))
            save_btn.connect("clicked", self._save_edid, rec)
            head.pack_end(save_btn, False, False, 0)
        box.pack_start(head, False, False, 0)

        # two columns, each section goes to whichever column is shorter so far
        cols = Gtk.Box(spacing=28, homogeneous=True)
        columns = [Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16) for _ in range(2)]
        heights = [0, 0]
        for col in columns:
            cols.pack_start(col, True, True, 0)
        for section, rows in monitor_info.describe(rec):
            grid = Gtk.Grid(column_spacing=12, row_spacing=4)
            head_lbl = Gtk.Label(xalign=0)
            head_lbl.set_markup(f"<b>{GLib.markup_escape_text(section)}</b>")
            grid.attach(head_lbl, 0, 0, 2, 1)
            for r, (key, val) in enumerate(rows, 1):
                k = Gtk.Label(label=key, xalign=0, yalign=0)
                k.get_style_context().add_class("dim-label")
                v = Gtk.Label(label=val, xalign=0, yalign=0, selectable=True, wrap=True, hexpand=True)
                v.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                v.set_width_chars(12)
                v.set_max_width_chars(30)
                grid.attach(k, 0, r, 1, 1)
                grid.attach(v, 1, r, 1, 1)
            target = 0 if heights[0] <= heights[1] else 1
            columns[target].pack_start(grid, False, False, 0)
            heights[target] += len(rows) + 2
        box.pack_start(cols, False, False, 0)
        return frame

    def show_monitor(self, name):
        """Scroll to the card for an output (used by the Displays page)."""
        card = self.cards.get(name)
        if not card:
            return
        scrolled = self.get_parent()
        while scrolled and not isinstance(scrolled, Gtk.ScrolledWindow):
            scrolled = scrolled.get_parent()

        def scroll():
            coords = card.translate_coordinates(self, 0, 0)
            if scrolled and coords:
                scrolled.get_vadjustment().set_value(max(0, coords[1] - 12))
            return False

        GLib.idle_add(scroll)

    def _copy(self, _btn, rec, english):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(monitor_info.as_text(rec, english), -1)
        self.window.set_status(_("Monitor details copied"))

    def _save_edid(self, _btn, rec):
        dlg = Gtk.FileChooserDialog(title=_("Save EDID"), parent=self.window, action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Save"), Gtk.ResponseType.OK)
        dlg.set_do_overwrite_confirmation(True)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in rec.title())
        dlg.set_current_name(f"{safe or rec.name}.bin")
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(rec.raw)
                self.window.set_status(_("EDID saved"))
            except OSError as e:
                self.window.message(_("Could not save the EDID"), str(e))
