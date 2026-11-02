"""Keep the mouse wheel from changing settings while scrolling a page.

GTK3 dropdowns, number fields and sliders change their value when the wheel turns over
them, even if you only meant to scroll the page past them. That silently remapped mouse
buttons once. Here: dropdowns never take the wheel, number fields and sliders only once
you've clicked into them; otherwise the wheel scrolls the page.
"""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

_PROTECTED = "_xcontrol_scroll_guard"


def scroll_page(widget, event):
    """Scroll the page (the nearest scrolled window) instead of `widget`. Always True."""
    sw = widget.get_ancestor(Gtk.ScrolledWindow)
    if sw is None:
        return True
    adj = sw.get_vadjustment()
    dy = 0.0
    if event.direction == Gdk.ScrollDirection.UP:
        dy = -1.0
    elif event.direction == Gdk.ScrollDirection.DOWN:
        dy = 1.0
    elif event.direction == Gdk.ScrollDirection.SMOOTH:
        ok, _dx, sdy = event.get_scroll_deltas()
        dy = sdy if ok else 0.0
    if dy:
        step = max(adj.get_page_size() ** (2 / 3), 30)  # what GTK uses for one wheel notch
        upper = adj.get_upper() - adj.get_page_size()
        adj.set_value(min(max(adj.get_value() + dy * step, adj.get_lower()), upper))
    return True


def wheel_allowed(widget):
    """Number fields and sliders take the wheel only after being clicked (focused)."""
    return widget.is_focus()


def _guard(widget, event):
    if isinstance(widget, Gtk.ComboBox) or not wheel_allowed(widget):
        return scroll_page(widget, event)
    return False  # focused: let the widget change its value


def protect(root):
    """Apply the wheel guard to every dropdown, number field and slider under `root`.
    Safe to call again after widgets were added."""
    stack = [root]
    while stack:
        w = stack.pop()
        if isinstance(w, (Gtk.ComboBox, Gtk.SpinButton, Gtk.Scale)) and not getattr(w, _PROTECTED, False):
            w.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
            w.connect("scroll-event", _guard)
            setattr(w, _PROTECTED, True)
        if isinstance(w, Gtk.Container):
            stack.extend(w.get_children())


def reveal(bar, visible=True):
    """Show or hide a Gtk.InfoBar that's kept out of show_all() (set_no_show_all): show_all()
    on such a widget does nothing, so its parts are shown explicitly."""
    if not visible:
        bar.hide()
        return
    for part in (bar.get_content_area(), bar.get_action_area()):
        part.show_all()
    bar.show()


def sideways(widget):
    """`widget` in a scrolled window that only scrolls sideways, so a wide row (buttons, tab
    switchers) doesn't stop the window from getting narrow (640x480 for old games)."""
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                            vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
    sw.add(widget)
    return sw


_FITTED = "_xcontrol_fitted"


def fit_dialog(dialog):
    """Keep a dialog inside the monitor's work area (640x480 for old games): cap its size and,
    when its content is still too big, let the content scroll while the buttons stay put."""
    if getattr(dialog, _FITTED, False):
        return
    setattr(dialog, _FITTED, True)
    try:
        display = dialog.get_display()
        parent = dialog.get_transient_for()
        mon = (display.get_monitor_at_window(parent.get_window()) if parent and parent.get_window()
               else display.get_primary_monitor() or display.get_monitor(0))
        area = mon.get_workarea()
    except Exception:  # noqa: BLE001
        return
    max_w, max_h = area.width - 20, area.height - 20
    min_size, _nat = dialog.get_preferred_size()
    if min_size.width > max_w or min_size.height > max_h:
        content = dialog.get_content_area()
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=content.get_spacing())
        buttons = dialog.get_action_area()     # (GTK 3 keeps the buttons inside the content area)
        for child in content.get_children():
            if child is buttons:
                continue
            expand, fill, padding, _pack = content.query_child_packing(child)
            content.remove(child)
            inner.pack_start(child, expand, fill, padding)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True,
                                propagate_natural_width=True, propagate_natural_height=True)
        sw.set_max_content_width(max_w - 30)
        sw.set_max_content_height(max_h - 110)   # (room for the title bar and the buttons)
        sw.add(inner)
        content.pack_start(sw, True, True, 0)
        sw.show_all()
    w, h = dialog.get_size()                     # (the default size before it's shown)
    if w > max_w or h > max_h:
        dialog.set_default_size(min(w, max_w), min(h, max_h))
        dialog.resize(min(w, max_w), min(h, max_h))


_hooked = False


def fit_all_dialogs():
    """Apply fit_dialog() to every dialog XControl shows (once per process). Wraps
    Gtk.Dialog's show/show_all/run, which only XControl's own Python code calls."""
    global _hooked
    if _hooked:
        return
    _hooked = True
    orig_show, orig_show_all, orig_run = Gtk.Dialog.show, Gtk.Dialog.show_all, Gtk.Dialog.run

    def show(self):
        orig_show(self)
        fit_dialog(self)

    def show_all(self):
        orig_show_all(self)
        fit_dialog(self)

    def run(self):
        fit_dialog(self)
        return orig_run(self)
    Gtk.Dialog.show, Gtk.Dialog.show_all, Gtk.Dialog.run = show, show_all, run
