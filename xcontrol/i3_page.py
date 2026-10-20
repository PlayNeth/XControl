"""The i3 page: XControl writes ~/.config/i3/config from these settings (see i3cfg)."""
import os
import shutil
import subprocess
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import config, i3cfg as I3, widgets, xrandr  # noqa: E402
from .i18n import N_, _  # noqa: E402
from .panel_page import _hex, _hint, _rgba, _scale, _section  # noqa: E402

LABELS = {
    "normal": N_("With title bar"), "pixel": N_("Border only"), "none": N_("None"),
    "left": N_("Left"), "center": N_("Center"), "right": N_("Right"),
    "vertical": N_("Left and right"), "horizontal": N_("Top and bottom"), "both": N_("All"),
    "smart": N_("All, when it's the only window"), "smart_no_gaps": N_("All, when it's the only window and no gaps"),
    "off": N_("Off"), "on": N_("On"), "inverse_outer": N_("Outer gaps only when there are several windows"),
    "no_gaps": N_("When the gaps are 0"),
    "output": N_("Into the display that gets focus"),
    "urgent": N_("Mark it urgent"), "focus": N_("Always switch to it"),
    "yes": N_("Wrap around"), "no": N_("Stop at the edge"), "force": N_("Always wrap, even inside containers"),
    "workspace": N_("Wrap within the workspace"),
    "auto": N_("Automatic (by the display's shape)"), "default": N_("Side by side"),
    "stacking": N_("Stacked"), "tabbed": N_("Tabbed"),
    "ignore": N_("Stay hidden behind it"), "leave_fullscreen": N_("Leave fullscreen"),
}
COLOR_CLASS_LABELS = {"focused": N_("Focused window"), "focused_inactive": N_("Focused, other container"),
                      "unfocused": N_("Unfocused"), "urgent": N_("Urgent"), "placeholder": N_("Placeholder")}
COLOR_PART_LABELS = {"border": N_("Title border"), "background": N_("Title background"), "text": N_("Title text"),
                     "indicator": N_("Split indicator"), "child_border": N_("Window border")}
COMMANDS = ["exec ", "exec --no-startup-id ", "kill", "fullscreen toggle", "floating toggle", "sticky toggle",
            "focus left", "focus right", "focus up", "focus down", "focus parent", "focus mode_toggle",
            "move left", "move right", "move up", "move down", "split h", "split v", "split toggle",
            "layout tabbed", "layout stacking", "layout toggle split", "workspace number 1", "workspace next",
            "workspace prev", "workspace back_and_forth", "move container to workspace number 1",
            "move workspace to output next", "scratchpad show", "move scratchpad", 'mode "resize"', 'mode "default"',
            "reload", "restart", "exec --no-startup-id xcontrol --lock", "exec --no-startup-id xcontrol"]
MOD_NAMES = {"Mod4": "Super", "Mod1": "Alt"}


KEY_LABELS = {   # where the same word means something else
    "focus_on_activation": {"smart": N_("Switch to it if it's on a visible workspace, else mark it urgent"),
                            "none": N_("Ignore it")},
    "popup_fullscreen": {"smart": N_("Show it if it belongs to the fullscreen window"),
                         "all": N_("Always show it on top (i3 4.24 and later)")},
    "default_orientation": {"horizontal": N_("Side by side"), "vertical": N_("One above the other")},
    "mouse_warping": {"none": N_("Never")},
}


def _combo(choices, key=None):
    w = Gtk.ComboBoxText()
    for c in choices:
        w.append(c, _(KEY_LABELS.get(key, {}).get(c) or LABELS.get(c, c)))
    return w


def pretty_keys(keys, mod):
    out = []
    for p in keys.split("+"):
        if p == "$mod":
            p = MOD_NAMES.get(mod, mod)
        elif p in MOD_NAMES:
            p = MOD_NAMES[p]
        elif p == "Control":
            p = "Ctrl"
        out.append(p)
    return "+".join(out)


class KeyDialog(Gtk.Dialog):
    """Add or change one key binding; the keys can be typed or pressed."""

    def __init__(self, parent, binding, mod, modes):
        super().__init__(title=_("Key binding"), transient_for=parent, modal=True)
        self.mod = mod
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = self.add_button(_("OK"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(560, -1)
        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)
        g = Gtk.Grid(column_spacing=12, row_spacing=8)
        box.pack_start(g, False, False, 0)

        g.attach(Gtk.Label(label=_("Keys"), xalign=0), 0, 0, 1, 1)
        kb = Gtk.Box(spacing=6)
        self.keys = Gtk.Entry(text=binding.get("keys", ""), hexpand=True, activates_default=True)
        self.keys.set_placeholder_text("$mod+Shift+q")
        kb.pack_start(self.keys, True, True, 0)
        self.capture = Gtk.ToggleButton(label=_("Press keys…"))
        self.capture.connect("toggled", self._capture_toggled)
        kb.pack_start(self.capture, False, False, 0)
        g.attach(kb, 1, 0, 1, 1)
        self.capture_hint = _hint(_("Press the combination now. Esc cancels."))
        self.capture_hint.set_no_show_all(True)
        g.attach(self.capture_hint, 1, 1, 1, 1)

        g.attach(Gtk.Label(label=_("Action"), xalign=0), 0, 2, 1, 1)
        self.command = Gtk.ComboBoxText.new_with_entry()
        for c in COMMANDS:
            self.command.append(c, c)
        self.command.get_child().set_text(binding.get("command", ""))
        self.command.get_child().set_activates_default(True)
        g.attach(self.command, 1, 2, 1, 1)
        g.attach(_hint(_("Any i3 command. \"exec\" runs a program, e.g. exec --no-startup-id flameshot gui.")),
                 1, 3, 1, 1)

        g.attach(Gtk.Label(label=_("Mode"), xalign=0), 0, 4, 1, 1)
        self.mode = Gtk.ComboBoxText.new_with_entry()
        for m in modes:
            self.mode.append(m, m)
        self.mode.get_child().set_text(binding.get("mode") or "default")
        g.attach(self.mode, 1, 4, 1, 1)
        g.attach(_hint(_("\"default\" is the normal mode. Other modes (like \"resize\") are entered with "
                         "mode \"name\" and only their own keys work there.")), 1, 5, 1, 1)
        self.release = Gtk.CheckButton(label=_("Run when the keys are released"),
                                       active=bool(binding.get("release")))
        g.attach(self.release, 1, 6, 1, 1)
        self.code = bool(binding.get("code"))
        self._grab = None
        self.connect("key-press-event", self._key)
        self.connect("response", lambda *_a: self._ungrab())
        self.show_all()

    def _capture_toggled(self, btn):
        if btn.get_active():
            self.capture_hint.show()
            # an active grab beats i3's own key grabs, so even $mod+Return reaches us
            seat = Gdk.Display.get_default().get_default_seat()
            st = seat.grab(self.get_window(), Gdk.SeatCapabilities.KEYBOARD, False, None, None, None, None)
            self._grab = seat if st == Gdk.GrabStatus.SUCCESS else None
        else:
            self._ungrab()

    def _ungrab(self):
        self.capture_hint.hide()
        if self._grab:
            self._grab.ungrab()
            self._grab = None
        if self.capture.get_active():
            self.capture.set_active(False)

    def _key(self, _w, ev):
        if not self.capture.get_active():
            return False
        name = Gdk.keyval_name(ev.keyval) or ""
        if name in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Super_L", "Super_R",
                    "Meta_L", "Meta_R", "ISO_Level3_Shift", "Hyper_L", "Hyper_R"):
            return True   # wait for the real key
        state = ev.state & Gtk.accelerator_get_default_mod_mask()
        if name == "Escape" and not state:
            self._ungrab()
            return True
        keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
        ok, keyval, *_rest = keymap.translate_keyboard_state(ev.hardware_keycode, 0, ev.group)
        if ok:
            name = Gdk.keyval_name(keyval) or name   # Shift+1 is "Shift+1" for i3, not "exclam"
        mods = []
        want = Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK
        for mask, label in ((want, "Mod4"), (Gdk.ModifierType.MOD1_MASK, "Mod1"),
                            (Gdk.ModifierType.CONTROL_MASK, "Ctrl"), (Gdk.ModifierType.SHIFT_MASK, "Shift")):
            if ev.state & mask:
                mods.append("$mod" if label == self.mod else label)
        mods.sort(key=lambda m: m != "$mod")
        self.keys.set_text("+".join(mods + [name]))
        self.code = False
        self._ungrab()
        return True

    def binding(self):
        return {"keys": self.keys.get_text().strip(), "command": self.command.get_child().get_text().strip(),
                "mode": self.mode.get_child().get_text().strip() or "default", "code": self.code,
                "release": self.release.get_active()}


class I3Page(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.c = I3.load()
        self.saved_before = "i3" in config.load()
        self.loading = True
        self._timer = None
        self.labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=18, margin_end=18,
                      margin_top=14)
        head = Gtk.Box(spacing=10)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>{}</b>".format(GLib.markup_escape_text(_("Use XControl's i3 config"))))
        head.pack_start(lbl, False, False, 0)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", self._switched)
        head.pack_start(self.switch, False, False, 0)
        self.view_btn = Gtk.Button(label=_("Show the file…"))
        self.view_btn.connect("clicked", self._show_file)
        head.pack_end(self.view_btn, False, False, 0)
        self.import_btn = Gtk.Button(label=_("Import my previous config…"))
        self.import_btn.connect("clicked", self._import)
        head.pack_end(self.import_btn, False, False, 0)
        top.pack_start(head, False, False, 0)
        top.pack_start(_hint(_("XControl writes ~/.config/i3/config from this page and reloads i3 after each change. "
                               "Your current config is kept as config.before-xcontrol and can be put back by "
                               "switching this off. Every change is checked with i3 first, so a mistake never "
                               "replaces a working config.")), False, False, 0)
        self.status = _hint("")
        top.pack_start(self.status, False, False, 0)
        self.errbar = Gtk.InfoBar(message_type=Gtk.MessageType.ERROR)
        self.errtext = _hint("")
        self.errtext.get_style_context().remove_class("dim-label")
        self.errbar.get_content_area().add(self.errtext)
        self.errbar.set_no_show_all(True)
        top.pack_start(self.errbar, False, False, 0)
        self.pack_start(top, False, False, 0)

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=stack, halign=Gtk.Align.CENTER, margin_top=10, margin_bottom=4)
        self.pack_start(switcher, False, False, 0)
        self.tabs = []
        for name, title, build in (("look", _("Look"), self._build_look),
                                   ("keys", _("Keys"), self._build_keys),
                                   ("behavior", _("Behavior & Workspaces"), self._build_behavior),
                                   ("startup", _("Startup & Rules"), self._build_startup)):
            sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
            build(box)
            sw.add(box)
            stack.add_titled(sw, name, title)
            self.tabs.append(box)
        self.pack_start(stack, True, True, 0)
        self._fill()
        widgets.protect(self)
        self.loading = False
        self.connect("map", lambda *_a: self._status())

    def _row(self, grid, r, label, widget, hint=None):
        lbl = Gtk.Label(label=label, xalign=0)
        self.labels.add_widget(lbl)
        grid.attach(lbl, 0, r, 1, 1)
        grid.attach(widget, 1, r, 1, 1)
        if hint:
            grid.attach(_hint(hint), 1, r + 1, 1, 1)
            return r + 2
        return r + 1

    # ---------------------------------------------------------------- look
    def _build_look(self, box):
        g = _section(box, _("Windows"))
        self.font = Gtk.FontButton(use_font=True, halign=Gtk.Align.START)
        self.font.connect("font-set", self._changed)
        r = self._row(g, 0, _("Title font"), self.font)
        self.border = _combo(I3.BORDERS)
        self.border_width = Gtk.SpinButton.new_with_range(0, 30, 1)
        r = self._row(g, r, _("Tiled windows"), self._pair(self.border, self.border_width))
        self.fborder = _combo(I3.BORDERS)
        self.fborder_width = Gtk.SpinButton.new_with_range(0, 30, 1)
        r = self._row(g, r, _("Floating windows"), self._pair(self.fborder, self.fborder_width))
        self.title_align = _combo(I3.CHOICES["title_align"])
        r = self._row(g, r, _("Title position"), self.title_align)
        self.hide_edges = _combo(I3.CHOICES["hide_edge_borders"])
        r = self._row(g, r, _("Hide borders at the screen edge"), self.hide_edges)
        self.smart_borders = _combo(I3.CHOICES["smart_borders"])
        self._row(g, r, _("No border when it's the only window"), self.smart_borders)
        ver = I3.version()
        if ver and ver >= (4, 24):   # i3 4.24 folded this into "Hide borders at the screen edge"
            for w in (self.smart_borders, g.get_child_at(0, r)):
                w.set_no_show_all(True)
                w.hide()
        for w in (self.border, self.fborder, self.title_align, self.hide_edges, self.smart_borders):
            w.connect("changed", self._changed)
        for w in (self.border_width, self.fborder_width):
            w.connect("value-changed", self._changed)

        g = _section(box, _("Gaps"))
        self.gaps_inner = _scale(0, 60, 1)
        r = self._row(g, 0, _("Between windows"), self.gaps_inner)
        self.gaps_outer = _scale(0, 60, 1)
        r = self._row(g, r, _("Around the edge"), self.gaps_outer, _("Added to the space between windows."))
        self.smart_gaps = _combo(I3.CHOICES["smart_gaps"])
        self._row(g, r, _("No gaps when it's the only window"), self.smart_gaps)
        self.gaps_inner.connect("value-changed", self._changed)
        self.gaps_outer.connect("value-changed", self._changed)
        self.smart_gaps.connect("changed", self._changed)

        g = _section(box, _("Colors"))
        self.colors = {}
        for col, part in enumerate(I3.COLOR_PARTS, 1):
            lbl = Gtk.Label(label=_(COLOR_PART_LABELS[part]), wrap=True, max_width_chars=10,
                            justify=Gtk.Justification.CENTER)
            lbl.get_style_context().add_class("dim-label")
            g.attach(lbl, col, 0, 1, 1)
        for row, cls in enumerate(I3.COLOR_CLASSES, 1):
            lbl = Gtk.Label(label=_(COLOR_CLASS_LABELS[cls]), xalign=0)
            self.labels.add_widget(lbl)
            g.attach(lbl, 0, row, 1, 1)
            for col, part in enumerate(I3.COLOR_PARTS, 1):
                b = Gtk.ColorButton(use_alpha=False)
                b.connect("color-set", self._changed)
                g.attach(b, col, row, 1, 1)
                self.colors[(cls, part)] = b
        self.bg = Gtk.ColorButton(use_alpha=False, halign=Gtk.Align.START)
        self.bg.connect("color-set", self._changed)
        g.attach(Gtk.Label(label=_("Behind windows"), xalign=0), 0, 6, 1, 1)
        g.attach(self.bg, 1, 6, 1, 1)
        reset = Gtk.Button(label=_("i3's colors"), halign=Gtk.Align.START)
        reset.connect("clicked", self._reset_colors)
        g.attach(reset, 1, 7, 3, 1)

    def _pair(self, combo, spin):
        b = Gtk.Box(spacing=8)
        b.pack_start(combo, False, False, 0)
        b.pack_start(spin, False, False, 0)
        b.pack_start(Gtk.Label(label=_("px")), False, False, 0)
        return b

    def _reset_colors(self, _b):
        self.c["colors"] = {k: list(v) for k, v in I3.DEFAULT_COLORS.items()}
        self.c["background"] = I3.DEFAULT["background"]
        self.loading = True
        self._fill_colors()
        self.loading = False
        self._commit_later()

    def _fill_colors(self):
        for (cls, part), b in self.colors.items():
            b.set_rgba(_rgba(self.c["colors"][cls][I3.COLOR_PARTS.index(part)]))
        self.bg.set_rgba(_rgba(self.c["background"]))

    # ---------------------------------------------------------------- keys
    def _build_keys(self, box):
        g = _section(box, _("Modifier"))
        self.mod = Gtk.ComboBoxText()
        for m, name in I3.MODS.items():
            self.mod.append(m, _(name))
        self.mod.connect("changed", self._changed)
        self._row(g, 0, _("Main key ($mod)"), self.mod,
                  _("Used by almost every shortcut. Super keeps Alt free for programs."))
        self.floating_drag = Gtk.CheckButton(label=_("Hold it and drag to move floating windows "
                                                     "(right button resizes)"))
        self.tiling_drag = Gtk.CheckButton(label=_("Drag tiled windows by their title bar to move them"))
        self.floating_drag.connect("toggled", self._changed)
        self.tiling_drag.connect("toggled", self._changed)
        g.attach(self.floating_drag, 1, 2, 1, 1)
        g.attach(self.tiling_drag, 1, 3, 1, 1)

        bar = Gtk.Box(spacing=6)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search keys or actions"))
        self.search.connect("search-changed", lambda *_a: self._fill_keys())
        bar.pack_start(self.search, True, True, 0)
        for label, cb in ((_("Add…"), self._key_add), (_("Change…"), self._key_edit),
                          (_("Remove"), self._key_remove), (_("i3's defaults"), self._key_reset)):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            bar.pack_start(b, False, False, 0)
        box.pack_start(bar, False, False, 0)
        self.clash_label = Gtk.Label(xalign=0, wrap=True)
        self.clash_label.set_no_show_all(True)
        box.pack_start(self.clash_label, False, False, 0)

        # keys, action, mode, index, foreground, tooltip
        self.key_store = Gtk.ListStore(str, str, str, int, str, str)
        self.key_view = Gtk.TreeView(model=self.key_store, enable_search=False)
        self.key_view.set_tooltip_column(5)
        for i, title in enumerate((_("Keys"), _("Action"), _("Mode"))):
            cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if i == 1 else Pango.EllipsizeMode.NONE)
            col = Gtk.TreeViewColumn(title, cell, text=i, foreground=4)
            col.set_resizable(True)
            col.set_expand(i == 1)
            col.set_sort_column_id(i)
            self.key_view.append_column(col)
        self.key_view.connect("row-activated", lambda *_a: self._key_edit(None))
        frame = Gtk.ScrolledWindow(min_content_height=360, hscrollbar_policy=Gtk.PolicyType.NEVER)
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.add(self.key_view)
        box.pack_start(frame, True, True, 0)

    def _fill_keys(self):
        self.key_store.clear()
        mod = self.c["mod"]
        clash = I3.clashes(self.c["bindings"], mod)
        q = self.search.get_text().strip().lower()
        for i, b in enumerate(self.c["bindings"]):
            keys = pretty_keys(b["keys"], mod) + (" ↑" if b["release"] else "") + (" (code)" if b["code"] else "")
            if q and q not in keys.lower() and q not in b["command"].lower() and q not in b["keys"].lower():
                continue
            tip = None
            if i in clash:
                others = ", ".join(self.c["bindings"][j]["command"] for j in clash[i])
                tip = _("Same keys as: {others}").format(others=others)
            self.key_store.append([keys, b["command"], "" if b["mode"] == "default" else b["mode"], i,
                                   "#d03030" if i in clash else None, GLib.markup_escape_text(tip) if tip else None])
        if clash:
            self.clash_label.set_markup("⚠ " + GLib.markup_escape_text(
                _("Some keys are used twice (shown in red); only one of them will work.")))
        self.clash_label.set_visible(bool(clash))

    def _selected_key(self):
        model, it = self.key_view.get_selection().get_selected()
        return model[it][3] if it else None

    def _modes(self):
        modes = ["default"]
        for b in self.c["bindings"]:
            if b["mode"] not in modes:
                modes.append(b["mode"])
        return modes

    def _edit_binding(self, binding):
        dlg = KeyDialog(self.get_toplevel(), binding, self.c["mod"], self._modes())
        widgets.protect(dlg)
        result = None
        while dlg.run() == Gtk.ResponseType.OK:
            b = dlg.binding()
            if b["keys"] and b["command"]:
                result = b
                break
        dlg.destroy()
        return result

    def _key_add(self, _b):
        b = self._edit_binding({"keys": "$mod+", "command": "exec "})
        if b:
            self.c["bindings"].append(b)
            self._fill_keys()
            self._commit_later()

    def _key_edit(self, _b):
        i = self._selected_key()
        if i is None:
            return
        b = self._edit_binding(self.c["bindings"][i])
        if b:
            self.c["bindings"][i] = b
            self._fill_keys()
            self._commit_later()

    def _key_remove(self, _b):
        i = self._selected_key()
        if i is not None:
            del self.c["bindings"][i]
            self._fill_keys()
            self._commit_later()

    def _key_reset(self, _b):
        if self._ask(_("Replace all key bindings with i3's defaults?"),
                     _("Your own bindings on this page are removed.")):
            self.c["bindings"] = None
            self.c["bindings"] = I3.normalize(self.c)["bindings"]
            self._fill_keys()
            self._commit_later()

    # ---------------------------------------------------------------- behavior & workspaces
    def _build_behavior(self, box):
        g = _section(box, _("Focus"))
        self.ffm = Gtk.CheckButton(label=_("Focus follows the mouse"))
        self.ffm.connect("toggled", self._changed)
        g.attach(self.ffm, 1, 0, 1, 1)
        self.warp = _combo(I3.CHOICES["mouse_warping"], "mouse_warping")
        r = self._row(g, 1, _("Move the mouse pointer"), self.warp)
        self.activation = _combo(I3.CHOICES["focus_on_activation"], "focus_on_activation")
        r = self._row(g, r, _("A window asks for attention"), self.activation)
        self.wrapping = _combo(I3.CHOICES["focus_wrapping"])
        self._row(g, r, _("Moving focus past the last window"), self.wrapping)

        g = _section(box, _("Windows"))
        self.orientation = _combo(I3.CHOICES["default_orientation"], "default_orientation")
        r = self._row(g, 0, _("New windows are placed"), self.orientation)
        self.ws_layout = _combo(I3.CHOICES["workspace_layout"])
        r = self._row(g, r, _("New workspaces start"), self.ws_layout)
        self.popup = _combo(I3.CHOICES["popup_fullscreen"], "popup_fullscreen")
        self._row(g, r, _("A dialog opens over a fullscreen window"), self.popup)
        for w in (self.warp, self.activation, self.wrapping, self.orientation, self.ws_layout, self.popup):
            w.connect("changed", self._changed)

        g = _section(box, _("Workspaces"))
        self.back_forth = Gtk.CheckButton(label=_("Choosing the current workspace again goes back to the previous one"))
        self.back_forth.connect("toggled", self._changed)
        g.attach(self.back_forth, 0, 0, 3, 1)
        for col, title in enumerate((_("Key"), _("Name"), _("Display"))):
            lbl = Gtk.Label(label=title, xalign=0)
            lbl.get_style_context().add_class("dim-label")
            g.attach(lbl, col, 1, 1, 1)
        try:
            outputs = [m.name for m in xrandr.query() if m.connected]
        except Exception:  # noqa: BLE001
            outputs = []
        self.ws_rows = []
        for i in range(10):
            key = Gtk.Label(xalign=0)
            g.attach(key, 0, i + 2, 1, 1)
            name = Gtk.Entry(width_chars=18)
            name.connect("changed", self._changed)
            g.attach(name, 1, i + 2, 1, 1)
            out = Gtk.ComboBoxText()
            out.append("", _("Any"))
            for o in outputs:
                out.append(o, o)
            out.connect("changed", self._changed)
            g.attach(out, 2, i + 2, 1, 1)
            self.ws_rows.append((key, name, out))
        g.attach(_hint(_("A name like \"2:web\" shows \"web\" in the bar when the bar hides numbers. "
                         "A workspace with a display opens there.")), 1, 12, 2, 1)

    # ---------------------------------------------------------------- startup & rules
    def _build_startup(self, box):
        g = _section(box, _("Start with i3"))
        fixed = _hint(_("Always first: {line} (wallpaper, bar, compositor, screen lock, input settings).")
                      .format(line="xcontrol --session"))
        g.attach(fixed, 0, 0, 1, 1)
        # command, each reload
        self.start_store = Gtk.ListStore(str, bool)
        view = Gtk.TreeView(model=self.start_store, headers_visible=True)
        cell = Gtk.CellRendererText(editable=True)
        cell.connect("edited", self._start_edited)
        col = Gtk.TreeViewColumn(_("Command"), cell, text=0)
        col.set_expand(True)
        view.append_column(col)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self._start_toggled)
        view.append_column(Gtk.TreeViewColumn(_("Also on reload"), tog, active=1))
        self.start_view = view
        g.attach(self._list(view, self._start_add, self._start_remove), 0, 1, 1, 1)
        g.attach(_hint(_("Double-click a command to change it. \"Also on reload\" runs it again on every i3 "
                         "reload, not just at login.")), 0, 2, 1, 1)

        g = _section(box, _("Window rules"))
        # kind, criteria, action
        self.rule_store = Gtk.ListStore(str, str, str)
        view = Gtk.TreeView(model=self.rule_store)
        kinds = Gtk.ListStore(str, str)
        kinds.append(["for_window", _("Do")])
        kinds.append(["assign", _("Open on")])
        kc = Gtk.CellRendererCombo(model=kinds, text_column=1, has_entry=False, editable=True)
        kc.connect("changed", self._rule_kind)
        col = Gtk.TreeViewColumn(_("Rule"), kc)
        col.set_cell_data_func(kc, lambda _c, cell, m, it, _d: cell.set_property(
            "text", _("Do") if m[it][0] == "for_window" else _("Open on")))
        view.append_column(col)
        for i, title in ((1, _("Windows (criteria)")), (2, _("Action / workspace"))):
            cell = Gtk.CellRendererText(editable=True)
            cell.connect("edited", self._rule_edited, i)
            c = Gtk.TreeViewColumn(title, cell, text=i)
            c.set_expand(True)
            c.set_resizable(True)
            view.append_column(c)
        self.rule_view = view
        lst = self._list(view, self._rule_add, self._rule_remove)
        if shutil.which("xprop"):
            pick = Gtk.Button(label=_("Pick a window…"))
            pick.set_tooltip_text(_("Click a window to add a rule for its program"))
            pick.connect("clicked", self._pick)
            lst.get_children()[-1].pack_start(pick, False, False, 0)
        g.attach(lst, 0, 0, 1, 1)
        g.attach(_hint(_("Criteria like class=\"Steam\" or title=\"Picture-in-Picture\". "
                         "\"Do\" runs i3 commands on matching windows, e.g. floating enable, border none, "
                         "move to workspace number 3. \"Open on\" puts them on a workspace, e.g. number 2.")),
                 0, 1, 1, 1)

        g = _section(box, _("i3's bar"))
        self.i3bar = Gtk.CheckButton(label=_("Show i3's own bar (i3bar) when XControl's bar is off"))
        self.i3bar.connect("toggled", self._changed)
        g.attach(self.i3bar, 0, 0, 1, 1)

        g = _section(box, _("Extra i3 config"))
        g.attach(_hint(_("Anything else from i3's user guide, as in an i3 config file. Checked with i3 like "
                         "everything else.")), 0, 0, 1, 1)
        self.extra = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.NONE, accepts_tab=False)
        self.extra.get_buffer().connect("changed", self._changed)
        sw = Gtk.ScrolledWindow(min_content_height=140, hexpand=True)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(self.extra)
        g.attach(sw, 0, 1, 1, 1)

    def _list(self, view, add, remove):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        sw = Gtk.ScrolledWindow(min_content_height=150, hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(view)
        box.pack_start(sw, True, True, 0)
        buttons = Gtk.Box(spacing=6)
        for label, cb in ((_("Add"), add), (_("Remove"), remove)):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            buttons.pack_start(b, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        return box

    def _start_add(self, _b):
        self.c["startup"].append({"command": "", "always": False, "no_startup_id": True})
        self.start_store.append(["", False])
        path = Gtk.TreePath(len(self.start_store) - 1)
        self.start_view.set_cursor(path, self.start_view.get_column(0), True)

    def _start_remove(self, _b):
        _m, it = self.start_view.get_selection().get_selected()
        if it:
            i = self.start_store.get_path(it)[0]
            del self.c["startup"][i]
            self.start_store.remove(it)
            self._commit_later()

    def _start_edited(self, _cell, path, text):
        i = int(path)
        text = text.strip()
        for prefix in ("exec_always ", "exec "):
            if text.startswith(prefix):
                text = text[len(prefix):]
        if text.startswith("--no-startup-id "):
            text = text[len("--no-startup-id "):]
        self.start_store[i][0] = text
        self.c["startup"][i]["command"] = text
        self._commit_later()

    def _start_toggled(self, _cell, path):
        i = int(path)
        self.start_store[i][1] = not self.start_store[i][1]
        self.c["startup"][i]["always"] = self.start_store[i][1]
        self._commit_later()

    def _rule_add(self, _b, criteria="class=\"\"", action="floating enable"):
        self.c["rules"].append({"kind": "for_window", "criteria": criteria, "action": action})
        self.rule_store.append(["for_window", criteria, action])
        path = Gtk.TreePath(len(self.rule_store) - 1)
        self.rule_view.set_cursor(path, self.rule_view.get_column(1 if criteria == "class=\"\"" else 2), True)
        self._commit_later()

    def _rule_remove(self, _b):
        _m, it = self.rule_view.get_selection().get_selected()
        if it:
            i = self.rule_store.get_path(it)[0]
            del self.c["rules"][i]
            self.rule_store.remove(it)
            self._commit_later()

    def _rule_kind(self, _cell, path, it):
        kind = _cell.get_property("model")[it][0]
        i = int(path)
        self.rule_store[i][0] = kind
        self.c["rules"][i]["kind"] = kind
        if kind == "assign" and self.c["rules"][i]["action"] == "floating enable":
            self.c["rules"][i]["action"] = self.rule_store[i][2] = "number 2"
        self._commit_later()

    def _rule_edited(self, _cell, path, text, col):
        i = int(path)
        text = text.strip()
        if col == 1 and text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
        self.rule_store[i][col] = text
        self.c["rules"][i]["criteria" if col == 1 else "action"] = text
        self._commit_later()

    def _pick(self, btn):
        btn.set_sensitive(False)
        self.window.set_status(_("Click the window…"))

        def run():
            try:
                out = subprocess.run(["xprop", "WM_CLASS"], capture_output=True, text=True, timeout=60).stdout
            except (OSError, subprocess.SubprocessError):
                out = ""
            GLib.idle_add(done, out)

        def done(out):
            btn.set_sensitive(True)
            parts = [p.strip().strip('"') for p in out.split("=", 1)[-1].split(",")] if "=" in out else []
            if len(parts) >= 2:
                self._rule_add(None, f'class="{parts[1]}"', "floating enable")
            return False
        threading.Thread(target=run, daemon=True).start()

    # ---------------------------------------------------------------- values
    def _fill(self):
        c = self.c
        self.loading = True
        self.switch.set_active(c["enabled"])
        self.font.set_font(c["font"])
        self.border.set_active_id(c["border"])
        self.border_width.set_value(c["border_width"])
        self.fborder.set_active_id(c["float_border"])
        self.fborder_width.set_value(c["float_border_width"])
        self.title_align.set_active_id(c["title_align"])
        self.hide_edges.set_active_id(c["hide_edge_borders"])
        self.smart_borders.set_active_id(c["smart_borders"])
        self.gaps_inner.set_value(c["gaps_inner"])
        self.gaps_outer.set_value(c["gaps_outer"])
        self.smart_gaps.set_active_id(c["smart_gaps"])
        self._fill_colors()
        self.mod.set_active_id(c["mod"])
        self.floating_drag.set_active(c["floating_drag"])
        self.tiling_drag.set_active(c["tiling_drag"])
        self._fill_keys()
        self.ffm.set_active(c["focus_follows_mouse"])
        self.warp.set_active_id(c["mouse_warping"])
        self.activation.set_active_id(c["focus_on_activation"])
        self.wrapping.set_active_id(c["focus_wrapping"])
        self.orientation.set_active_id(c["default_orientation"])
        self.ws_layout.set_active_id(c["workspace_layout"])
        self.popup.set_active_id(c["popup_fullscreen"])
        self.back_forth.set_active(c["back_and_forth"])
        for i, (key, name, out) in enumerate(self.ws_rows):
            ws = c["workspaces"][i]
            key.set_text(f"{MOD_NAMES.get(c['mod'], c['mod'])}+{(i + 1) % 10}")
            name.set_text(ws["name"])
            if ws["output"] and not out.set_active_id(ws["output"]):
                out.append(ws["output"], ws["output"])
            out.set_active_id(ws["output"])
        self.start_store.clear()
        for s in c["startup"]:
            self.start_store.append([s["command"], s["always"]])
        self.rule_store.clear()
        for r in c["rules"]:
            self.rule_store.append([r["kind"], r["criteria"], r["action"]])
        self.i3bar.set_active(c["i3bar"])
        self.extra.get_buffer().set_text(c["extra"])
        self._sensitivity()
        self.loading = False

    def _sensitivity(self):
        on = self.switch.get_active()
        for t in self.tabs:
            t.set_sensitive(on)
        self.view_btn.set_sensitive(on)

    def _changed(self, *_a):
        if self.loading:
            return
        c = self.c
        c["font"] = self.font.get_font() or c["font"]
        c["border"] = self.border.get_active_id()
        c["border_width"] = int(self.border_width.get_value())
        c["float_border"] = self.fborder.get_active_id()
        c["float_border_width"] = int(self.fborder_width.get_value())
        c["title_align"] = self.title_align.get_active_id()
        c["hide_edge_borders"] = self.hide_edges.get_active_id()
        c["smart_borders"] = self.smart_borders.get_active_id()
        c["gaps_inner"] = int(self.gaps_inner.get_value())
        c["gaps_outer"] = int(self.gaps_outer.get_value())
        c["smart_gaps"] = self.smart_gaps.get_active_id()
        for (cls, part), b in self.colors.items():
            c["colors"][cls][I3.COLOR_PARTS.index(part)] = _hex(b.get_rgba())
        c["background"] = _hex(self.bg.get_rgba())
        mod = self.mod.get_active_id() or "Mod4"
        if mod != c["mod"]:
            c["mod"] = mod
            self._fill_keys()
            for i, (key, _n, _o) in enumerate(self.ws_rows):
                key.set_text(f"{MOD_NAMES.get(mod, mod)}+{(i + 1) % 10}")
        c["floating_drag"] = self.floating_drag.get_active()
        c["tiling_drag"] = self.tiling_drag.get_active()
        c["focus_follows_mouse"] = self.ffm.get_active()
        c["mouse_warping"] = self.warp.get_active_id()
        c["focus_on_activation"] = self.activation.get_active_id()
        c["focus_wrapping"] = self.wrapping.get_active_id()
        c["default_orientation"] = self.orientation.get_active_id()
        c["workspace_layout"] = self.ws_layout.get_active_id()
        c["popup_fullscreen"] = self.popup.get_active_id()
        c["back_and_forth"] = self.back_forth.get_active()
        for i, (_k, name, out) in enumerate(self.ws_rows):
            c["workspaces"][i] = {"name": name.get_text().strip() or str(i + 1), "output": out.get_active_id() or ""}
        c["i3bar"] = self.i3bar.get_active()
        buf = self.extra.get_buffer()
        c["extra"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self._commit_later()

    def _commit_later(self, delay=700):
        if self.loading:
            return
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(delay, self._commit)

    def _commit(self):
        self._timer = None
        c = I3.normalize(self.c)
        try:
            I3.save(c)
            self.saved_before = True
            ok, errors = I3.write(c, I3.bar_enabled()) if c["enabled"] else (True, [])
        except Exception as e:  # noqa: BLE001
            ok, errors = False, [str(e)]
        self._errors(errors if not ok else [])
        if ok and c["enabled"]:
            self.window.set_status(_("Applied, i3 reloaded"))
        self._status()
        return False

    def _errors(self, errors):
        if errors:
            self.errtext.set_text(_("i3 doesn't accept this, so nothing was changed:") + "\n" + "\n".join(errors[:6]))
        widgets.reveal(self.errbar, bool(errors))

    # ---------------------------------------------------------------- switching, import, restore
    def _ask(self, title, body, yes=None, no=None):
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.NONE, text=title)
        dlg.format_secondary_text(body)
        dlg.add_button(no or _("Cancel"), Gtk.ResponseType.NO)
        dlg.add_button(yes or _("OK"), Gtk.ResponseType.YES)
        r = dlg.run()
        dlg.destroy()
        return r == Gtk.ResponseType.YES

    def _switched(self, *_a):
        if self.loading:
            return
        on = self.switch.get_active()
        self.c["enabled"] = on   # before an import refills the page
        if on:
            if not shutil.which("i3"):
                self.window.message(_("i3 isn't installed"), _("Install the i3-wm package first."))
                self._set_switch(False)
                return
            prev = I3.previous()
            if not self.saved_before and prev and self._ask(
                    _("Start from your current i3 config?"),
                    _("Its keys, startup programs, window rules and look are brought over to this page. "
                      "Otherwise the page starts from i3's defaults. Either way your file is kept as a backup."),
                    _("Import it"), _("i3's defaults")):
                self._do_import(prev, quiet=False)
        elif I3.is_ours() and I3.can_restore():
            if self._ask(_("Put your previous i3 config back?"),
                         _("XControl's config is kept as config.xcontrol."), _("Put it back"), _("Keep XControl's")):
                I3.restore()
        self.c["enabled"] = on
        self._sensitivity()
        self._commit_later(0)

    def _set_switch(self, on):
        self.loading = True
        self.switch.set_active(on)
        self.loading = False
        self._sensitivity()

    def _import(self, _b):
        prev = I3.previous()
        if not prev:
            self.window.message(_("Nothing to import"), _("No i3 config other than XControl's was found."))
            return
        if self._ask(_("Import {path}?").format(path=prev.replace(os.path.expanduser("~"), "~")),
                     _("The settings on this page are replaced by the ones in that file."), _("Import")):
            self._do_import(prev, quiet=False)
            self._commit_later(0)

    def _do_import(self, path, quiet=True):
        try:
            with open(path, errors="replace") as f:
                text = f.read()
        except OSError as e:
            self.window.message(_("Could not read the config"), str(e))
            return
        c, skipped = I3.import_config(text, self.c)
        c["enabled"] = self.c["enabled"]
        self.c = c
        self._fill()
        if skipped and not quiet:
            self.window.message(_("Imported"), _("Left out because XControl takes care of them now:") + "\n\n" +
                                "\n".join(skipped[:12]))

    def _show_file(self, _b):
        text = I3.generate(I3.normalize(self.c), I3.bar_enabled())
        dlg = Gtk.Dialog(title=I3.target().replace(os.path.expanduser("~"), "~"), transient_for=self.get_toplevel(),
                         modal=True)
        dlg.add_button(_("Copy"), 1)
        dlg.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        dlg.set_default_size(720, 560)
        view = Gtk.TextView(monospace=True, editable=False)
        view.get_buffer().set_text(text)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.add(view)
        dlg.get_content_area().pack_start(sw, True, True, 0)
        dlg.show_all()
        while dlg.run() == 1:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        dlg.destroy()

    def _status(self):
        v = I3.version()
        if not v:
            text = _("i3 isn't installed.")
        else:
            text = "i3 {}.{}".format(*v)
            if self.c["enabled"]:
                if I3.loaded_path() != I3.target():
                    text += " · " + _("~/.i3/config is in the way; it's moved aside on the next change.")
                elif I3.is_ours():
                    text += " · " + _("XControl's config is in use.")
            if I3.can_restore():
                text += " · " + _("Your previous config is kept as config.before-xcontrol.")
        self.status.set_text(text)
        self.import_btn.set_sensitive(bool(I3.previous()))
        return False
