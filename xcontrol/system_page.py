"""The System page: distribution, kernel, hardware and live readings."""
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import sysinfo  # noqa: E402
from .i18n import _  # noqa: E402

REFRESH_MS = 2000


class SystemPage(Gtk.Box):
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
