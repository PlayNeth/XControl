"""Main window."""
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import __version__, widgets, wm  # noqa: E402
from .i18n import _  # noqa: E402
from .appearance_page import AppearancePage  # noqa: E402
from .desktop_page import DesktopPage  # noqa: E402
from .display_page import DisplayPage  # noqa: E402
from .gaming_page import GamingPage  # noqa: E402
from .input_page import InputPage  # noqa: E402
from .monitors_page import MonitorsPage  # noqa: E402
from .panel_page import PanelPage  # noqa: E402
from .i3_page import I3Page  # noqa: E402
from .notify_page import NotifyPage  # noqa: E402
from .defaults_page import DefaultsPage  # noqa: E402
from .region_page import RegionPage  # noqa: E402
from .audio_page import AudioPage  # noqa: E402
from .system_page import SystemPage  # noqa: E402
from .users_page import UsersPage  # noqa: E402

APP_ID = "io.github.xcontrol"
PAGES = ("gaming", "displays", "input", "appearance", "sound", "desktop", "panel", "notifications", "defaults", "i3", "region", "users", "system")


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="XControl")
        self.set_default_size(940, 780)
        self._fit_to_screen()
        self.set_icon_name("video-display")

        self.status = Gtk.Label()
        self.status.get_style_context().add_class("dim-label")
        self._status_timer = None
        self.header_bar = wm.use_header_bar()
        if self.header_bar:  # GNOME-style desktops: our own title bar, status at its end
            header = Gtk.HeaderBar(show_close_button=True, title="XControl")
            layout = wm.decoration_layout()
            if layout is not None:
                header.set_decoration_layout(layout)
            header.pack_end(self.status)
            self.set_titlebar(header)
        # otherwise the window manager draws the title bar, like it does for Thunar

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        sidebar = Gtk.StackSidebar(stack=stack)
        sidebar.set_size_request(170, -1)

        gaming = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        gaming.add(GamingPage(self))
        stack.add_titled(gaming, "gaming", _("Gaming"))

        displays = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        displays.add(DisplayPage(self))
        stack.add_titled(displays, "displays", _("Displays"))

        inputs = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        inputs.add(InputPage(self))
        stack.add_titled(inputs, "input", _("Input"))

        appearance = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        appearance.add(AppearancePage(self))
        stack.add_titled(appearance, "appearance", _("Appearance"))

        sound = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        sound.add(AudioPage(self))
        stack.add_titled(sound, "sound", _("Sound"))

        desktop = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        desktop.add(DesktopPage(self))
        stack.add_titled(desktop, "desktop", _("Desktop"))

        stack.add_titled(PanelPage(self), "panel", _("Bar & Compositor"))  # scrolls inside its tabs
        notifications = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        notifications.add(NotifyPage(self))
        stack.add_titled(notifications, "notifications", _("Notifications"))
        defaults = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        defaults.add(DefaultsPage(self))
        stack.add_titled(defaults, "defaults", _("Default Apps"))
        stack.add_titled(I3Page(self), "i3", _("Window Manager (i3)"))  # scrolls inside its tabs

        region = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        region.add(RegionPage(self))
        stack.add_titled(region, "region", _("Date & Language"))

        users = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        users.add(UsersPage(self))
        stack.add_titled(users, "users", _("Users"))

        stack.add_titled(SystemPage(self), "system", _("System"))  # scrolls inside its tabs

        self.stack = stack
        widgets.protect(stack)  # the wheel scrolls pages instead of changing settings under the pointer
        box = Gtk.Box()
        box.pack_start(sidebar, False, False, 0)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        box.pack_start(stack, True, True, 0)
        if self.header_bar:
            self.add(box)
        else:  # status messages in a small bar at the bottom instead
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            outer.pack_start(box, True, True, 0)
            outer.pack_start(Gtk.Separator(), False, False, 0)
            self.status.set_xalign(1.0)
            self.status.set_margin_start(8)
            self.status.set_margin_end(8)
            self.status.set_margin_top(3)
            self.status.set_margin_bottom(3)
            self.status.set_text(" ")  # keep the bar's height when empty
            outer.pack_start(self.status, False, False, 0)
            self.add(outer)

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
        """What the display reports about itself (EDID), in a window of its own."""
        dlg = Gtk.Dialog(title=_("Display details"), transient_for=self, modal=True)
        dlg.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        area = self.get_display().get_monitor_at_window(self.get_window()).get_workarea()
        dlg.set_default_size(min(900, area.width - 60), min(700, area.height - 80))
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
        sw.add(MonitorsPage(self, only=output_name))
        dlg.get_content_area().pack_start(sw, True, True, 0)
        dlg.show_all()
        dlg.run()
        dlg.destroy()

    def set_status(self, text):
        self.status.set_text(text)
        if self._status_timer:
            GLib.source_remove(self._status_timer)

        def clear():
            self.status.set_text("" if self.header_bar else " ")
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


def spawn(flag):
    """Start `xcontrol FLAG` in the background, detached from this process."""
    import os
    import shutil
    import subprocess
    exe = shutil.which("xcontrol")
    if exe:
        cmd, env = [exe, flag], None
    else:  # running from the source folder
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [sys.executable, "-c", f"import sys; from xcontrol.app import main; sys.exit(main(['xcontrol', '{flag}']))"]
        env = dict(os.environ, PYTHONPATH=here + os.pathsep + os.environ.get("PYTHONPATH", ""))
    subprocess.Popen(cmd, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def session(everything=False, wanted=()):
    """xcontrol --session (or several login flags together): restore the display layout,
    start xsettingsd and the input watcher, then run the desktop service in the foreground.
    Each part only does something when its settings are in use."""
    import os
    import shutil
    import subprocess
    from . import desktop, input_devices, theming
    if everything or "--apply-display" in wanted:
        from .display_page import apply_saved_layout
        apply_saved_layout()  # first, so the wallpaper is drawn for the final layout
    if everything and os.path.exists(theming.xsettingsd_autostart()) and shutil.which("xsettingsd") \
            and theming.xsettings_manager()[0] is None:
        subprocess.Popen(["xsettingsd", "-c", theming.xsettingsd_conf()], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if everything or "--watch-input" in wanted:
        if not input_devices.watcher_running():
            spawn("--watch-input")
    if everything or "--desktop-daemon" in wanted:
        return desktop.daemon()  # stays running (exits at once when nothing is set up)
    return 0


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"xcontrol {__version__}")
        return 0
    if "--sysinfo" in argv:  # the System page as text, e.g. for bug reports
        from . import sysinfo
        print(sysinfo.as_text(sysinfo.snapshot(), english="--english" in argv), end="")
        return 0
    helpers = [f for f in ("--apply-display", "--watch-input", "--desktop-daemon") if f in argv]
    if "--session" in argv or len(helpers) > 1:  # one line in the i3 config for everything
        return session(everything="--session" in argv, wanted=helpers)
    if "--desktop-daemon" in argv:  # login helper: wallpaper, blanking, screen lock (xss-lock)
        from . import desktop
        return desktop.daemon()
    if "--lock" in argv:  # lock the screen now (bind it to a key in i3)
        from . import desktop
        return 0 if desktop.lock_now() else 1
    if "--awake" in argv:  # keep the screen on: on, off, toggle, a number of minutes, or status
        from . import desktop
        i = argv.index("--awake")
        how = argv[i + 1] if i + 1 < len(argv) else "toggle"
        if how not in ("on", "off", "toggle", "status") and not how.isdigit():
            print("xcontrol: --awake takes on, off, toggle, status or a number of minutes", file=sys.stderr)
            return 2
        until = desktop.set_awake(how)
        if until is None:
            print("awake: off")
        elif until == 0:
            print("awake: on")
        else:
            import time
            print(f"awake: on until {time.strftime('%H:%M', time.localtime(until))}")
        return 0
    if "--night" in argv:  # night light by hand: on, off, toggle (until the schedule next changes), auto
        from . import desktop
        i = argv.index("--night")
        how = argv[i + 1] if i + 1 < len(argv) else "toggle"
        if how not in ("on", "off", "toggle", "auto", "status"):
            print("xcontrol: --night takes on, off, toggle, auto or status", file=sys.stderr)
            return 2
        result = desktop.set_night(how)
        print("night light: " + (result or "following the schedule"))
        return 0
    if "--dnd" in argv:  # notifications: do not disturb on, off or toggle (critical ones can still show)
        from . import notify
        i = argv.index("--dnd")
        how = argv[i + 1] if i + 1 < len(argv) else "toggle"
        on = (not notify.paused()) if how == "toggle" else how == "on"
        if not notify.set_paused(on):
            print("xcontrol: dunst isn't running", file=sys.stderr)
            return 1
        print("do not disturb: " + ("on" if on else "off"))
        return 0
    if "--apply-display" in argv:
        from .display_page import apply_saved_layout
        return apply_saved_layout()
    if "--watch-input" in argv:  # login helper: re-apply input settings now and on hotplug
        from . import input_devices, keyboard
        return input_devices.watch(apply_keyboard=keyboard.apply_saved)
    page = "gaming"
    if "--page" in argv[:-1]:
        page = argv[argv.index("--page") + 1]
    if page not in PAGES:
        print("xcontrol: --page must be one of: " + ", ".join(PAGES), file=sys.stderr)
        return 2
    return App(page).run(argv[:1])
