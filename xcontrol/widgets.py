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
