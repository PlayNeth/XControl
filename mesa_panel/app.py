"""Main window."""
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import __version__  # noqa: E402
from .i18n import _  # noqa: E402
from .display_page import DisplayPage  # noqa: E402
from .gaming_page import GamingPage  # noqa: E402
from .monitors_page import MonitorsPage  # noqa: E402

APP_ID = "io.github.mesa_panel"


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Mesa Panel")
        self.set_default_size(940, 780)
        self._fit_to_screen()
        self.set_icon_name("video-display")

        header = Gtk.HeaderBar(show_close_button=True, title="Mesa Panel")
        self.status = Gtk.Label()
        self.status.get_style_context().add_class("dim-label")
        header.pack_end(self.status)
        self.set_titlebar(header)
        self._status_timer = None

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        sidebar = Gtk.StackSidebar(stack=stack)
        sidebar.set_size_request(170, -1)

        gaming = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        gaming.add(GamingPage(self))
        stack.add_titled(gaming, "gaming", _("Gaming"))

        displays = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        displays.add(DisplayPage(self))
        stack.add_titled(displays, "displays", _("Displays"))

        monitors = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.monitors_page = MonitorsPage(self)
        monitors.add(self.monitors_page)
        stack.add_titled(monitors, "monitors", _("Monitor Info"))

        self.stack = stack
        box = Gtk.Box()
        box.pack_start(sidebar, False, False, 0)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        box.pack_start(stack, True, True, 0)
        self.add(box)

    def _fit_to_screen(self, *_args):
        """Never open taller or wider than the monitor's work area (e.g. 1024x768)."""
        try:
            display = self.get_display()
            mon = display.get_primary_monitor() or display.get_monitor(0)
            area = mon.get_workarea()
            w, h = self.get_default_size()
            self.set_default_size(min(w, area.width - 40), min(h, area.height - 40))
        except Exception:  # noqa: BLE001
            pass

    def show_monitor_info(self, output_name):
        self.stack.set_visible_child_name("monitors")
        self.monitors_page.show_monitor(output_name)

    def set_status(self, text):
        self.status.set_text(text)
        if self._status_timer:
            GLib.source_remove(self._status_timer)

        def clear():
            self.status.set_text("")
            self._status_timer = None
            return False

        self._status_timer = GLib.timeout_add_seconds(3, clear)

    def message(self, title, body):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
                                buttons=Gtk.ButtonsType.OK, text=title)
        dlg.format_secondary_text(body)
        dlg.run()
        dlg.destroy()


class App(Gtk.Application):
    def __init__(self, page="gaming"):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.page = page

    def do_activate(self):
        win = self.get_active_window()
        if not win:
            win = MainWindow(self)
            win.show_all()
            win.stack.set_visible_child_name(self.page)
        win.present()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"mesa-panel {__version__}")
        return 0
    if "--apply-display" in argv:
        from .display_page import apply_saved_layout
        return apply_saved_layout()
    page = "gaming"
    if "--page" in argv[:-1]:
        page = argv[argv.index("--page") + 1]
    if page not in ("gaming", "displays", "monitors"):
        print("mesa-panel: --page must be 'gaming', 'displays' or 'monitors'", file=sys.stderr)
        return 2
    return App(page).run(argv[:1])
