"""The Default Apps page: which program opens what."""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import defaults as DF, widgets  # noqa: E402
from .desktop_page import _hint  # noqa: E402
from .i18n import N_, _  # noqa: E402

LABELS = {"browser": N_("Web browser"), "mail": N_("Email"), "files": N_("Files and folders"),
          "text": N_("Text files"), "images": N_("Pictures"), "video": N_("Videos"), "music": N_("Music"),
          "pdf": N_("PDF documents"), "archives": N_("Archives"), "office": N_("Office documents")}
HINTS = {"browser": N_("Links in other programs, and web pages"), "mail": N_("Email links (mailto:)"),
         "files": N_("Opening a folder"), "text": N_("Plain text, code, logs, settings files"),
         "images": N_("PNG, JPEG, WebP, GIF, SVG…"), "video": N_("MP4, MKV, WebM…"),
         "music": N_("MP3, FLAC, Ogg, playlists…"), "pdf": N_("PDF, EPUB, DjVu, PostScript"),
         "archives": N_("ZIP, tar, 7z, RAR…"), "office": N_("Writer, Word, spreadsheets, presentations")}


def _two_lines(title, small):
    lbl = Gtk.Label(xalign=0)
    lbl.set_markup("{}\n<small>{}</small>".format(GLib.markup_escape_text(title), GLib.markup_escape_text(small)))
    return lbl


class DefaultsPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.loading = True
        self.pack_start(_hint(_("Which program opens links and files: in file managers, browsers, xdg-open and "
                                "everything else that asks. Saved in ~/.config/mimeapps.list.")), False, False, 0)

        self.browser_warn = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        self.browser_text = _hint("")
        self.browser_text.get_style_context().remove_class("dim-label")
        self.browser_warn.get_content_area().add(self.browser_text)
        self.browser_warn.set_no_show_all(True)
        self.pack_start(self.browser_warn, False, False, 0)
        self.broken_bar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        self.broken_text = _hint("")
        self.broken_text.get_style_context().remove_class("dim-label")
        self.broken_bar.get_content_area().add(self.broken_text)
        self.broken_bar.add_button(_("Clean up"), 1)
        self.broken_bar.connect("response", self._clean)
        self.broken_bar.set_no_show_all(True)
        self.pack_start(self.broken_bar, False, False, 0)

        frame, g = self._section(_("Opens with"))
        self.choosers = {}
        r = 0
        for cid, _label, types in DF.CATEGORIES:
            g.attach(_two_lines(_(LABELS[cid]), _(HINTS[cid])), 0, r, 1, 1)
            ch = Gtk.AppChooserButton(content_type=types[0], hexpand=True)
            ch.set_show_dialog_item(True)
            ch.set_heading(_("Open {what} with").format(what=_(LABELS[cid]).lower()))
            ch.connect("changed", self._chosen, cid, types)
            g.attach(ch, 1, r, 1, 1)
            self.choosers[cid] = ch
            r += 1
        g.attach(_two_lines(_("Terminal"), _("Apps that run in a terminal, and the i3 terminal key")), 0, r, 1, 1)
        self.term = Gtk.ComboBoxText(hexpand=True)
        self.term.connect("changed", self._terminal)
        g.attach(self.term, 1, r, 1, 1)
        self.pack_start(frame, False, False, 0)

        frame, g = self._section(_("Every file type"))
        self.search = Gtk.SearchEntry(placeholder_text=_("Search, e.g. epub, flac, torrent"))
        self.search.connect("search-changed", lambda *_a: self.filter.refilter())
        g.attach(self.search, 0, 0, 1, 1)
        self.store = Gtk.ListStore(str, str, str)   # description, type, app
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        view = Gtk.TreeView(model=self.filter)
        for i, title in enumerate((_("Kind"), _("Type"), _("Opens with"))):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            col.set_expand(i == 0)
            view.append_column(col)
        view.connect("row-activated", self._type_activated)
        sw = Gtk.ScrolledWindow(min_content_height=260, hexpand=True)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(view)
        g.attach(sw, 0, 1, 1, 1)
        g.attach(_hint(_("Double-click a type to choose its program.")), 0, 2, 1, 1)
        self.types_loaded = False
        self.types_frame = frame
        self.pack_start(frame, True, True, 0)

        self.connect("map", lambda *_a: self._refresh())
        widgets.protect(self)
        self.loading = False

    def _section(self, title):
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        head = Gtk.Label(xalign=0)
        head.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        frame.set_label_widget(head)
        grid = Gtk.Grid(column_spacing=16, row_spacing=10, margin_start=12, margin_top=8, margin_bottom=4)
        frame.add(grid)
        return frame, grid

    # ---------------------------------------------------------------- values
    def _refresh(self):
        DF.refresh_user_apps()   # so your own launchers are offered too
        self.loading = True
        for cid, _label, types in DF.CATEGORIES:
            ch = self.choosers[cid]
            ch.refresh()
            cur = Gio.AppInfo.get_default_for_type(types[0], False)
            if cur is not None:
                self._select(ch, cur.get_id())
        self.term.remove_all()
        chosen = DF.terminal()
        terms = DF.terminals()
        self.term.append("", _("Automatic (i3-sensible-terminal)"))
        for tid, name in terms:
            self.term.append(tid, name)
        if chosen and chosen not in [t for t, _n in terms]:
            self.term.append(chosen, chosen + " " + _("(not installed)"))
        self.term.set_active_id(chosen or "")
        self.loading = False
        env = DF.browser_env()
        self.browser_text.set_text(_("$BROWSER is set to \"{value}\" in your session; xdg-open and many programs "
                                     "use it instead of the web browser chosen here. Remove it from ~/.xprofile, "
                                     "~/.bashrc or wherever it's set.").format(value=env) if env else "")
        widgets.reveal(self.browser_warn, bool(env))
        bad = DF.broken()
        self.broken_text.set_text(_("{n} file types are set to open with programs that are no longer installed "
                                    "(e.g. {example}).").format(n=len(bad), example=next(iter(bad.values()))[0])
                                  if bad else "")
        widgets.reveal(self.broken_bar, bool(bad))
        self._load_types()

    def _select(self, ch, app_id):
        model = ch.get_model()
        it = model.get_iter_first() if model else None
        while it is not None:
            info = model[it][0] if model.get_n_columns() > 0 else None
            if isinstance(info, Gio.AppInfo) and info.get_id() == app_id:
                ch.set_active_iter(it)
                return
            it = model.iter_next(it)

    def _load_types(self):
        self.store.clear()
        for t, desc, app in DF.all_types():
            self.store.append([desc, t, app])

    def _visible(self, model, it, _data):
        q = self.search.get_text().strip().lower()
        if not q:
            return True
        return q in (model[it][0] or "").lower() or q in (model[it][1] or "").lower() or \
            q in (model[it][2] or "").lower()

    # ---------------------------------------------------------------- changes
    def _chosen(self, ch, cid, types):
        if self.loading:
            return
        app = ch.get_app_info()
        if app is None:
            return
        try:
            DF.set_default(cid, types, app.get_id())
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not set it"), str(e))
            return
        self.window.set_status(_("{app} opens {what} now").format(app=app.get_display_name(),
                                                                  what=_(LABELS[cid]).lower()))
        self._load_types()

    def _terminal(self, combo):
        if self.loading:
            return
        tid = combo.get_active_id()
        if tid:
            DF.set_terminal(tid)
        else:
            import os
            try:
                os.remove(DF.terminals_list_path())
            except OSError:
                pass
        from . import i3cfg
        ok, errors = i3cfg.refresh()   # the i3 terminal key follows
        if not ok:
            self.window.message(_("The i3 config wasn't updated"), "\n".join(errors))
        self.window.set_status(_("Terminal set"))

    def _type_activated(self, view, path, _col):
        t = self.filter[path][1]
        dlg = Gtk.AppChooserDialog.new_for_content_type(self.get_toplevel(), Gtk.DialogFlags.MODAL, t)
        dlg.set_heading(_("Open {what} with").format(what=self.filter[path][0]))
        if dlg.run() == Gtk.ResponseType.OK:
            app = dlg.get_app_info()
            if app is not None:
                DF.set_default_type(t, app.get_id())
                self._load_types()
                self.window.set_status(_("{app} opens {what} now").format(app=app.get_display_name(),
                                                                          what=self.filter[path][0]))
        dlg.destroy()

    def _clean(self, *_a):
        n = DF.clean_broken()
        self.window.set_status(_("Removed {n} broken entries").format(n=n))
        self._refresh()
