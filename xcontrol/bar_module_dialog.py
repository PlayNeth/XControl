"""Settings of one bar module (and of the bar itself): the options XControl knows, plus an
'Extra polybar settings' box for anything else polybar offers."""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import bar as B, widgets  # noqa: E402
from .i18n import N_, _  # noqa: E402

LABELS = {
    ("workspaces", "label"): N_("Workspace label"),
    ("workspaces", "pin_workspaces"): N_("Only the workspaces of this display"),
    ("workspaces", "show_urgent"): N_("Also show urgent workspaces from other displays"),
    ("workspaces", "strip_wsnumbers"): N_("Hide the number in names like \"1:web\""),
    ("workspaces", "index_sort"): N_("Sort by number"),
    ("workspaces", "enable_click"): N_("Click to switch"),
    ("workspaces", "enable_scroll"): N_("Scroll over them to switch"),
    ("workspaces", "wrapping_scroll"): N_("Scrolling wraps around"),
    ("workspaces", "reverse_scroll"): N_("Reverse the scroll direction"),
    ("workspaces", "separator"): N_("Separator between workspaces"),
    ("workspaces", "padding"): N_("Space around each label"),
    ("workspaces", "focused_fg"): N_("Current: text"),
    ("workspaces", "focused_bg"): N_("Current: background"),
    ("workspaces", "focused_underline"): N_("Current: underline"),
    ("workspaces", "unfocused_fg"): N_("Others: text"),
    ("workspaces", "visible_underline"): N_("Shown on another display: underline"),
    ("workspaces", "urgent_fg"): N_("Urgent: text"),
    ("workspaces", "urgent_bg"): N_("Urgent: background"),
    ("workspaces", "mode_bg"): N_("i3 mode (e.g. resize): background"),
    ("xworkspaces", "label"): N_("Workspace label"),
    ("xworkspaces", "pin_workspaces"): N_("Only the workspaces of this display"),
    ("xworkspaces", "show_empty"): N_("Also show empty workspaces"),
    ("xworkspaces", "enable_click"): N_("Click to switch"),
    ("xworkspaces", "enable_scroll"): N_("Scroll over them to switch"),
    ("xworkspaces", "reverse_scroll"): N_("Reverse the scroll direction"),
    ("xworkspaces", "padding"): N_("Space around each label"),
    ("xworkspaces", "active_fg"): N_("Current: text"),
    ("xworkspaces", "active_bg"): N_("Current: background"),
    ("xworkspaces", "active_underline"): N_("Current: underline"),
    ("xworkspaces", "occupied_fg"): N_("With windows: text"),
    ("xworkspaces", "empty_fg"): N_("Empty: text"),
    ("xworkspaces", "urgent_bg"): N_("Urgent: background"),
    ("title", "max_length"): N_("Longest title (characters)"),
    ("clock", "format"): N_("Format"),
    ("clock", "alt"): N_("After a click"),
    ("clock", "color"): N_("Text color"),
    ("cpu", "interval"): N_("Update every (seconds)"),
    ("memory", "show"): N_("Show"),
    ("memory", "interval"): N_("Update every (seconds)"),
    ("temperature", "warn"): N_("Warning at (degrees)"),
    ("temperature", "units"): N_("Units"),
    ("volume", "step"): N_("Volume step per scroll (%)"),
    ("volume", "right_click"): N_("Right-click runs"),
    ("network", "kind"): N_("Interface"),
    ("network", "show"): N_("Show"),
    ("disk", "mount"): N_("Drive (mount point)"),
    ("keyboard", "show_layout"): N_("Show the layout name"),
    ("keyboard", "show_indicators"): N_("Show Caps Lock when it's on"),
    ("battery", "full_at"): N_("Counts as full at (%)"),
    ("tray", "spacing"): N_("Space between icons (pt)"),
    ("tray", "margin"): N_("Space around the tray (pt)"),
    ("tray", "size"): N_("Icon size (% of the bar height)"),
}
CHOICES = {
    "name": N_("Name (as i3 calls it)"), "index": N_("Number only"), "name_ws": N_("Name"),
    "percent": N_("Percent used"), "amount": N_("Used / total (GB)"),
    "c": "°C", "f": "°F",
    "auto": N_("The one in use"), "wired": N_("Wired"), "wireless": N_("Wi-Fi"),
    "ip": N_("Local address"), "speed": N_("Download / upload speed"), "name_if": N_("Interface name"),
}
HINTS = {
    "clock": N_("%H hours, %M minutes, %S seconds, %a weekday, %d day, %b month, %Y year (like the date "
                "command). Spaces at the start or end are kept."),
    "volume": N_("Empty: pavucontrol when it's installed. Any command works, e.g. alacritty -e wiremix."),
    "workspaces": N_("Colors left on Automatic follow the bar's colors."),
    "xworkspaces": N_("Colors left on Automatic follow the bar's colors."),
}


class ColorChoice(Gtk.Box):
    """'Automatic' (the bar's colors) or a chosen color."""

    def __init__(self, value):
        super().__init__(spacing=8)
        self.custom = Gtk.CheckButton(label=_("Custom"))
        self.button = Gtk.ColorButton()
        self.button.props.use_alpha = False
        c = Gdk.RGBA()
        c.parse(value or "#888888")
        self.button.set_rgba(c)
        self.custom.set_active(bool(value))
        self.button.set_sensitive(bool(value))
        self.custom.connect("toggled", lambda w: self.button.set_sensitive(w.get_active()))
        self.pack_start(self.custom, False, False, 0)
        self.pack_start(self.button, False, False, 0)
        self.auto = Gtk.Label(label=_("Automatic"))
        self.auto.get_style_context().add_class("dim-label")

    def value(self):
        if not self.custom.get_active():
            return ""
        c = self.button.get_rgba()
        return "#{:02x}{:02x}{:02x}".format(round(c.red * 255), round(c.green * 255), round(c.blue * 255))


class ModuleDialog(Gtk.Dialog):
    """Edit `b["options"][mid]` and `b["extra"][mid]` (mid "bar" edits only the extra lines)."""

    def __init__(self, parent, b, mid, title):
        super().__init__(title=title, transient_for=parent, modal=True)
        self.b, self.mid = b, mid
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = self.add_button(_("Apply"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        self.set_default_size(620, -1)
        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)

        self.widgets = {}
        if mid != "bar":
            opts = B.module_options(b, mid)
            grid = Gtk.Grid(column_spacing=12, row_spacing=8)
            r = 0
            for key, kind, _default in B.OPTIONS.get(mid, []):
                label = _(LABELS.get((mid, key), key))
                value = opts[key]
                if kind == "bool":
                    w = Gtk.CheckButton(label=label, active=bool(value))
                    grid.attach(w, 1, r, 1, 1)
                else:
                    grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
                    if isinstance(kind, list):
                        w = Gtk.ComboBoxText()
                        for choice in kind:
                            renamed = {("network", "name"): "name_if", ("xworkspaces", "name"): "name_ws"}
                            key = renamed.get((mid, choice), choice)
                            name = CHOICES.get(key, choice)
                            w.append(choice, _(name))
                        w.set_active_id(value)
                    elif kind == "int":
                        w = Gtk.SpinButton.new_with_range(0, 999, 1)
                        w.set_value(value)
                        w.set_halign(Gtk.Align.START)
                    elif kind == "color":
                        w = ColorChoice(value)
                    elif (mid, key) == ("clock", "format"):
                        w = Gtk.ComboBoxText.new_with_entry()
                        for f in B.CLOCK_FORMATS:
                            w.append(f, f)
                        w.get_child().set_text(value)
                    else:
                        w = Gtk.Entry(text=str(value), hexpand=True)
                        if (mid, key) == ("volume", "right_click"):
                            w.set_placeholder_text("pavucontrol")
                    grid.attach(w, 1, r, 1, 1)
                self.widgets[key] = (kind, w)
                r += 1
            if mid in HINTS:
                hint = Gtk.Label(label=_(HINTS[mid]), xalign=0, wrap=True)
                hint.set_max_width_chars(70)
                hint.get_style_context().add_class("dim-label")
                grid.attach(hint, 0, r, 2, 1)
            if B.OPTIONS.get(mid):
                sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
                sw.set_max_content_height(460)
                sw.add(grid)
                box.pack_start(sw, True, True, 0)

        exp = Gtk.Expander(label=_("Extra polybar settings"), expanded=bool((b.get("extra") or {}).get(mid)) or
                           mid == "bar")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6)
        section = "bar/xcontrol" if mid == "bar" else f"module/{B.SECTIONS[mid]}"
        hint = Gtk.Label(xalign=0, wrap=True)
        hint.set_max_width_chars(70)
        hint.set_markup(GLib.markup_escape_text(
            _("Any other setting from polybar's documentation, one per line as in a polybar config "
              "(key = value). They go into the [{section}] section and replace XControl's own line with the "
              "same key.").format(section=section)))
        hint.get_style_context().add_class("dim-label")
        inner.pack_start(hint, False, False, 0)
        self.extra = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.NONE, accepts_tab=False)
        self.extra.get_buffer().set_text((b.get("extra") or {}).get(mid, ""))
        frame = Gtk.ScrolledWindow(min_content_height=110)
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.add(self.extra)
        inner.pack_start(frame, True, True, 0)
        exp.add(inner)
        box.pack_start(exp, mid == "bar", True, 0)
        self.show_all()
        widgets.protect(self)

    def save(self):
        """Copy the dialog's values into the settings."""
        if self.mid != "bar":
            opts = {}
            for key, (kind, w) in self.widgets.items():
                if kind == "bool":
                    opts[key] = w.get_active()
                elif isinstance(kind, list):
                    opts[key] = w.get_active_id()
                elif kind == "int":
                    opts[key] = int(w.get_value())
                elif kind == "color":
                    opts[key] = w.value()
                elif isinstance(w, Gtk.ComboBoxText):
                    opts[key] = w.get_child().get_text()
                else:
                    opts[key] = w.get_text()
            self.b.setdefault("options", {})[self.mid] = opts
        buf = self.extra.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        extra = self.b.setdefault("extra", {})
        if text:
            extra[self.mid] = text
        else:
            extra.pop(self.mid, None)
