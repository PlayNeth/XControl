"""The Openbox page: XControl writes ~/.config/openbox/rc.xml and autostart from these settings
(see obcfg). Shown as the Window Manager page when Openbox is the window manager."""
import os
import shutil
import subprocess
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import config, obcfg as OB, widgets  # noqa: E402
from .i18n import N_, _  # noqa: E402
from .panel_page import _hint, _section  # noqa: E402

# (action, label, kind of argument)
ACTIONS = [
    ("Execute", N_("Run a command"), "command"),
    ("Close", N_("Close the window"), None),
    ("Iconify", N_("Minimize the window"), None),
    ("ToggleMaximize", N_("Maximize or restore the window"), None),
    ("ToggleFullscreen", N_("Full screen on or off"), None),
    ("ToggleShade", N_("Roll the window up or down"), None),
    ("ToggleAlwaysOnTop", N_("Always on top on or off"), None),
    ("ToggleOmnipresent", N_("On every desktop on or off"), None),
    ("ToggleShowDesktop", N_("Show the desktop"), None),
    ("NextWindow", N_("Next window"), None),
    ("PreviousWindow", N_("Previous window"), None),
    ("GoToDesktop", N_("Go to desktop"), "desktop"),
    ("SendToDesktop", N_("Send the window to desktop"), "desktop"),
    ("ShowMenu", N_("Show a menu"), "menu"),
    ("Reconfigure", N_("Reload Openbox's config"), None),
    ("Exit", N_("Log out (quit Openbox)"), None),
]
ACTION_LABELS = {a: label for a, label, _k in ACTIONS}
ACTION_KINDS = {a: kind for a, _l, kind in ACTIONS}
DESKTOP_TARGETS = [str(n) for n in range(1, 11)] + ["left", "right", "previous"]
DESKTOP_WORDS = {"left": N_("The one to the left"), "right": N_("The one to the right"),
                 "previous": N_("The previous one")}
MENUS = [("root-menu", N_("The desktop menu")), ("client-menu", N_("The window's menu")),
         ("client-list-combined-menu", N_("The list of windows"))]
LABELS = {
    "Smart": N_("Where there's room"), "UnderMouse": N_("Under the mouse pointer"),
    "Primary": N_("The primary display"), "Mouse": N_("The display with the mouse pointer"),
    "Active": N_("The display with the focused window"), "Any": N_("Any display"),
    "ToggleMaximize": N_("Maximize or restore"), "ToggleShade": N_("Roll up or down"),
    "Iconify": N_("Minimize"), "ToggleAlwaysOnTop": N_("Always on top on or off"), "none": N_("Nothing"),
}
LAYOUT_LABELS = {   # title bar layouts: N icon, L title, I minimize, M maximize, C close, S shade, D every desktop
    "NLIMC": N_("Icon and title · minimize, maximize, close"),
    "LIMC": N_("Title · minimize, maximize, close"),
    "NLC": N_("Icon and title · close"),
    "LC": N_("Title · close"),
    "CMIL": N_("Close, maximize, minimize · title"),
    "NLSDIMC": N_("Icon and title · roll up, every desktop, minimize, maximize, close"),
}
MOD_NAMES = {"S": "Shift", "C": "Ctrl", "A": "Alt", "W": "Super", "M": "Meta", "H": "Hyper"}


def pretty_keys(keys):
    """C-A-Left -> Ctrl+Alt+Left (a chain's keys separated by commas)."""
    out = []
    for key in keys.split():
        parts = key.split("-")
        out.append("+".join([MOD_NAMES.get(p, p) for p in parts[:-1]] + parts[-1:]))
    return ", ".join(out)


def describe(xml_text):
    """What a key binding does, in words."""
    acts = OB.actions_of(xml_text)
    if not acts:
        return xml_text
    out = []
    for name, args in acts:
        if name.startswith("chain:"):
            out.append(_("then {keys}: …").format(keys=pretty_keys(name[6:])))
            continue
        text = _(ACTION_LABELS[name]) if name in ACTION_LABELS else name
        main = OB.ACTION_ARGS.get(name)
        if main and args.get(main):
            arg = args[main]
            words = dict(MENUS) if name == "ShowMenu" else DESKTOP_WORDS if main == "to" else {}
            text += ": " + (_(words[arg]) if arg in words else arg)
        out.append(text)
    return " → ".join(out)


def _font_desc(f):
    return " ".join([f["name"]] + (["Bold"] if f["weight"] == "bold" else []) +
                    ([f["slant"].title()] if f["slant"] != "normal" else []) + [str(f["size"])])


def _font_from(text, old):
    d = Pango.FontDescription.from_string(text or "")
    if not d.get_family():
        return old
    style = d.get_style()
    return {"name": d.get_family(), "size": max(4, round(d.get_size() / Pango.SCALE)) or old["size"],
            "weight": "bold" if d.get_weight() >= Pango.Weight.SEMIBOLD else "normal",
            "slant": {Pango.Style.ITALIC: "italic", Pango.Style.OBLIQUE: "oblique"}.get(style, "normal")}


def _combo(items):
    w = Gtk.ComboBoxText()
    for key, label in items:
        w.append(key, label)
    return w


class KeyDialog(Gtk.Dialog):
    """Add or change one Openbox key binding: keys typed or pressed, and what they do."""

    def __init__(self, parent, binding):
        super().__init__(title=_("Key binding"), transient_for=parent, modal=True)
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
        self.keys.set_placeholder_text("W-e")
        kb.pack_start(self.keys, True, True, 0)
        self.capture = Gtk.ToggleButton(label=_("Press keys…"))
        self.capture.connect("toggled", self._capture_toggled)
        kb.pack_start(self.capture, False, False, 0)
        g.attach(kb, 1, 0, 1, 1)
        self.capture_hint = _hint(_("Press the combination now. Esc cancels."))
        self.capture_hint.set_no_show_all(True)
        g.attach(self.capture_hint, 1, 1, 1, 1)
        g.attach(_hint(_("Openbox writes keys like W-e: W is Super, A Alt, C Ctrl, S Shift.")), 1, 2, 1, 1)

        g.attach(Gtk.Label(label=_("Action"), xalign=0), 0, 3, 1, 1)
        self.action = Gtk.ComboBoxText(hexpand=True)
        for a, label, _kind in ACTIONS:
            self.action.append(a, _(label))
        self.action.append("custom", _("Something else (Openbox's XML)"))
        self.action.connect("changed", self._action_changed)
        self._last_action = None   # what "Something else" starts from
        g.attach(self.action, 1, 3, 1, 1)
        self.command = Gtk.Entry(activates_default=True, placeholder_text="firefox")
        self.desktop = Gtk.ComboBoxText()
        for t in DESKTOP_TARGETS:
            self.desktop.append(t, _(DESKTOP_WORDS[t]) if t in DESKTOP_WORDS else t)
        self.menu = _combo([(m, _(label)) for m, label in MENUS])
        self.xml = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False)
        self.xml_sw = Gtk.ScrolledWindow(min_content_height=120, hexpand=True)
        self.xml_sw.set_shadow_type(Gtk.ShadowType.IN)
        self.xml_sw.add(self.xml)
        self.xml_hint = _hint(_("One or more <action> elements, as in rc.xml, e.g. "
                                "<action name=\"Execute\"><command>firefox</command></action>"))
        self.arg_label = Gtk.Label(xalign=0)
        g.attach(self.arg_label, 0, 4, 1, 1)
        arg = Gtk.Box()   # one of these shows, by the action
        for w in (self.command, self.desktop, self.menu):
            arg.pack_start(w, True, True, 0)
        g.attach(arg, 1, 4, 1, 1)
        g.attach(self.xml_sw, 1, 5, 1, 1)
        g.attach(self.xml_hint, 1, 6, 1, 1)
        self.error = Gtk.Label(xalign=0, wrap=True)
        self.error.get_style_context().add_class("error")
        self.error.set_no_show_all(True)
        g.attach(self.error, 1, 7, 1, 1)

        simple = OB.simple_action(binding.get("xml", "")) if binding.get("xml") else ("Execute", "")
        if simple and simple[0] in ACTION_LABELS:
            name, arg = simple
            self.action.set_active_id(name)
            kind = ACTION_KINDS[name]
            if kind == "command":
                self.command.set_text(arg)
            elif kind == "desktop":
                if not self.desktop.set_active_id(arg):
                    self.desktop.append(arg, arg)
                    self.desktop.set_active_id(arg)
            elif kind == "menu":
                if not self.menu.set_active_id(arg):
                    self.menu.append(arg, arg)
                    self.menu.set_active_id(arg)
        else:
            self.action.set_active_id("custom")
        self.xml.get_buffer().set_text(binding.get("xml", ""))
        if self.desktop.get_active_id() is None:
            self.desktop.set_active(0)
        if self.menu.get_active_id() is None:
            self.menu.set_active(0)
        self._grab = None
        self.connect("key-press-event", self._key)
        self.connect("response", lambda *_a: self._ungrab())
        self.show_all()
        self._action_changed()

    def _action_changed(self, *_a):
        a = self.action.get_active_id()
        kind = "xml" if a == "custom" else ACTION_KINDS.get(a)
        for w, k in ((self.command, "command"), (self.desktop, "desktop"), (self.menu, "menu"),
                     (self.xml_sw, "xml"), (self.xml_hint, "xml")):
            w.set_visible(kind == k)
        self.arg_label.set_text({"command": _("Command"), "desktop": _("Desktop"), "menu": _("Menu"),
                                 "xml": _("XML")}.get(kind, ""))
        if a == "custom":
            buf = self.xml.get_buffer()
            if not buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip():
                buf.set_text(self._simple_xml(self._last_action) or "")
        else:
            self._last_action = a

    def _simple_xml(self, a=None):
        a = a or self.action.get_active_id()
        kind = ACTION_KINDS.get(a)
        if not a or a == "custom":
            return None
        arg = {"command": self.command.get_text().strip(), "desktop": self.desktop.get_active_id() or "1",
               "menu": self.menu.get_active_id() or "root-menu"}.get(kind, "")
        return OB.action_xml(a, arg)

    def _capture_toggled(self, btn):
        if btn.get_active():
            self.capture_hint.show()
            # an active grab beats Openbox's own key grabs, so even its bound keys reach us
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
            name = Gdk.keyval_name(keyval) or name   # S-1, not S-exclam
        mods = [letter for mask, letter in ((Gdk.ModifierType.CONTROL_MASK, "C"), (Gdk.ModifierType.MOD1_MASK, "A"),
                                            (Gdk.ModifierType.SHIFT_MASK, "S"),
                                            (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK, "W"))
                if ev.state & mask]
        self.keys.set_text("-".join(mods + [name]))
        self._ungrab()
        return True

    def binding(self):
        """The binding, or (None, why not)."""
        keys = self.keys.get_text().strip()
        if self.action.get_active_id() == "custom":
            buf = self.xml.get_buffer()
            xml = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        else:
            xml = self._simple_xml()
            if ACTION_KINDS.get(self.action.get_active_id()) == "command" and not self.command.get_text().strip():
                return None, _("Type the command to run.")
        if not keys:
            return None, _("Type or press the keys.")
        why = OB.check_actions(xml or "")
        if why:
            return None, _("That isn't valid: {why}").format(why=why)
        return {"keys": keys, "xml": xml}, None

    def show_error(self, text):
        self.error.set_text(text)
        self.error.show()


class OpenboxPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.c = OB.load()
        self.saved_before = "openbox" in config.load()
        self.loading = True
        self._timer = None
        self.labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=18, margin_end=18,
                      margin_top=14)
        head = Gtk.Box(spacing=10)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>{}</b>".format(GLib.markup_escape_text(_("Use XControl's Openbox config"))))
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
        top.pack_start(widgets.sideways(head), False, False, 0)
        top.pack_start(_hint(_("XControl writes ~/.config/openbox/rc.xml and autostart from this page, and Openbox "
                               "reloads after each change. Your current files are kept as rc.xml.before-xcontrol "
                               "and autostart.before-xcontrol and can be put back by switching this off. What the "
                               "page doesn't cover (other mouse bindings, menus, the dock, margins) is kept as it "
                               "was.")), False, False, 0)
        self.status = _hint("")
        top.pack_start(self.status, False, False, 0)
        self.errbar = Gtk.InfoBar(message_type=Gtk.MessageType.ERROR)
        self.errtext = _hint("")
        self.errtext.get_style_context().remove_class("dim-label")
        self.errbar.get_content_area().add(self.errtext)
        self.errbar.set_no_show_all(True)
        top.pack_start(self.errbar, False, False, 0)
        self.pack_start(top, False, False, 0)

        switcher, stack, tab = widgets.tabs((("look", _("Look")), ("keys", _("Keys")),
                                             ("behavior", _("Behavior & Desktops")),
                                             ("startup", _("Startup & Rules"))))
        self.pack_start(switcher, False, False, 0)
        self.pack_start(stack, True, True, 0)
        self.tabs = list(tab.values())
        self._build_look(tab["look"])
        self._build_keys(tab["keys"])
        self._build_behavior(tab["behavior"])
        self._build_startup(tab["startup"])
        self._fill()
        widgets.protect(self)
        self.loading = False
        # (after the window's show_all, which shows every desktop name row)
        self.connect("map", lambda *_a: (self._show_names(), self._status()))

    def _row(self, grid, r, label, widget, hint=None):
        lbl = Gtk.Label(label=label, xalign=0)
        self.labels.add_widget(lbl)
        grid.attach(lbl, 0, r, 1, 1)
        grid.attach(widget, 1, r, 1, 1)
        if hint:
            grid.attach(_hint(hint), 1, r + 1, 1, 1)
            return r + 2
        return r + 1

    def _check(self, label):
        w = Gtk.CheckButton(label=label)
        w.connect("toggled", self._changed)
        return w

    # ---------------------------------------------------------------- look
    def _build_look(self, box):
        g = _section(box, _("Windows"))
        self.theme = Gtk.ComboBoxText(hexpand=True)
        self.theme.connect("changed", self._changed)
        r = self._row(g, 0, _("Theme"), self.theme,
                      _("Openbox themes draw the title bars and borders; they're folders with an openbox-3 "
                        "subfolder in ~/.themes or /usr/share/themes."))
        self.layout = _combo([(k, _(v)) for k, v in LAYOUT_LABELS.items()])
        self.layout.connect("changed", self._changed)
        r = self._row(g, r, _("Title bar"), self.layout)
        self.title_font = Gtk.FontButton(use_font=True, halign=Gtk.Align.START)
        self.title_font.connect("font-set", self._changed)
        r = self._row(g, r, _("Title font"), self.title_font)
        self.menu_font = Gtk.FontButton(use_font=True, halign=Gtk.Align.START)
        self.menu_font.connect("font-set", self._changed)
        r = self._row(g, r, _("Menu font"), self.menu_font)
        self.keep_border = self._check(_("Keep the border on windows without a title bar"))
        g.attach(self.keep_border, 1, r, 1, 1)
        self.animate = self._check(_("Animate minimizing"))
        g.attach(self.animate, 1, r + 1, 1, 1)

    # ---------------------------------------------------------------- keys
    def _build_keys(self, box):
        g = _section(box, _("Moving with the mouse"))
        self.drag_mod = _combo([(m, _(name)) for m, name in OB.DRAG_MODS.items()])
        self.drag_mod.connect("changed", self._changed)
        self._row(g, 0, _("Key to hold"), self.drag_mod,
                  _("Hold it and drag anywhere in a window to move it; with the right button, to resize it."))

        bar = Gtk.Box(spacing=6)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search keys or actions"))
        self.search.connect("search-changed", lambda *_a: self._fill_keys())
        bar.pack_start(self.search, True, True, 0)
        for label, cb in ((_("Add…"), self._key_add), (_("Change…"), self._key_edit),
                          (_("Remove"), self._key_remove), (_("Openbox's defaults"), self._key_reset)):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            bar.pack_start(b, False, False, 0)
        box.pack_start(widgets.sideways(bar), False, False, 0)
        self.clash_label = Gtk.Label(xalign=0, wrap=True)
        self.clash_label.set_no_show_all(True)
        box.pack_start(self.clash_label, False, False, 0)

        # keys, action, index, foreground, tooltip
        self.key_store = Gtk.ListStore(str, str, int, str, str)
        self.key_view = Gtk.TreeView(model=self.key_store, enable_search=False)
        self.key_view.set_tooltip_column(4)
        for i, title in enumerate((_("Keys"), _("Action"))):
            cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if i == 1 else Pango.EllipsizeMode.NONE)
            col = Gtk.TreeViewColumn(title, cell, text=i, foreground=3)
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
        clash = OB.clashes(self.c["bindings"])
        q = self.search.get_text().strip().lower()
        for i, b in enumerate(self.c["bindings"]):
            keys, what = pretty_keys(b["keys"]), describe(b["xml"])
            if q and not any(q in s.lower() for s in (keys, what, b["keys"], b["xml"])):
                continue
            tip = b["xml"]
            if i in clash:
                tip = _("Same keys as: {others}").format(
                    others=", ".join(describe(self.c["bindings"][j]["xml"]) for j in clash[i])) + "\n\n" + tip
            self.key_store.append([keys, what, i, "#d03030" if i in clash else None, GLib.markup_escape_text(tip)])
        if clash:
            self.clash_label.set_markup("⚠ " + GLib.markup_escape_text(
                _("Some keys are used twice (shown in red); only one of them will work.")))
        self.clash_label.set_visible(bool(clash))

    def _selected_key(self):
        model, it = self.key_view.get_selection().get_selected()
        return model[it][2] if it else None

    def _edit_binding(self, binding):
        dlg = KeyDialog(self.get_toplevel(), binding)
        widgets.protect(dlg)
        result = None
        while dlg.run() == Gtk.ResponseType.OK:
            b, why = dlg.binding()
            if b:
                result = b
                break
            dlg.show_error(why)
        dlg.destroy()
        return result

    def _key_add(self, _b):
        b = self._edit_binding({"keys": "W-", "xml": ""})
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
        if self._ask(_("Replace all key bindings with Openbox's defaults?"),
                     _("Your own bindings on this page are removed."), _("Use Openbox's defaults")):
            self.c["bindings"] = OB.defaults()["bindings"]
            self._fill_keys()
            self._commit_later()

    # ---------------------------------------------------------------- behavior and desktops
    def _build_behavior(self, box):
        g = _section(box, _("Focus"))
        self.follow = self._check(_("Focus follows the mouse (no click needed)"))
        g.attach(self.follow, 1, 0, 1, 1)
        self.delay = widgets.slider(0, 1000, 50, fmt=lambda v: _("{ms} ms").format(ms=int(v)))
        self.delay.connect("value-changed", self._changed)
        self.delay_label = Gtk.Label(label=_("Delay"), xalign=0)
        self.labels.add_widget(self.delay_label)
        g.attach(self.delay_label, 0, 1, 1, 1)
        g.attach(self.delay, 1, 1, 1, 1)
        self.raise_focus = self._check(_("Bring the focused window to the front"))
        g.attach(self.raise_focus, 1, 2, 1, 1)
        self.focus_new = self._check(_("Focus new windows"))
        g.attach(self.focus_new, 1, 3, 1, 1)
        # (the left column's width comes from the size group; this keeps the checkboxes lined up)
        spacer = Gtk.Label(label="")
        self.labels.add_widget(spacer)
        g.attach(spacer, 0, 0, 1, 1)

        g = _section(box, _("New windows"))
        self.placement = _combo([(p, _(LABELS[p])) for p in OB.PLACEMENT])
        self.placement.connect("changed", self._changed)
        r = self._row(g, 0, _("Open them"), self.placement)
        self.center = self._check(_("In the middle of the free space"))
        g.attach(self.center, 1, r, 1, 1)
        self.monitor = _combo([(m, _(LABELS[m])) for m in OB.PLACEMENT_MONITORS])
        self.monitor.connect("changed", self._changed)
        self._row(g, r + 1, _("Display"), self.monitor)

        g = _section(box, _("Moving windows"))
        self.resist_windows = widgets.slider(0, 50, 5, fmt=lambda v: _("Off") if v == 0 else _("{px} px").format(
            px=int(v)))
        self.resist_windows.connect("value-changed", self._changed)
        r = self._row(g, 0, _("Stick to other windows"), self.resist_windows)
        self.resist_edges = widgets.slider(0, 50, 5, fmt=lambda v: _("Off") if v == 0 else _("{px} px").format(
            px=int(v)))
        self.resist_edges.connect("value-changed", self._changed)
        r = self._row(g, r, _("Stick to the screen's edges"), self.resist_edges,
                      _("How far you have to push a window past an edge before it moves on."))
        self.double_click = _combo([(d, _(LABELS[d])) for d in OB.DOUBLE_CLICK])
        self.double_click.connect("changed", self._changed)
        self._row(g, r, _("Double-click on the title"), self.double_click)

        g = _section(box, _("Clicking the desktop"))
        self.root_menu = self._check(_("Right-click opens Openbox's menu"))
        g.attach(self.root_menu, 0, 0, 1, 1)
        self.root_list = self._check(_("Middle-click opens the list of windows"))
        g.attach(self.root_list, 0, 1, 1, 1)
        g.attach(_hint(_("Without them, a key can still open these menus (Keys tab, Show a menu).")), 0, 2, 1, 1)

        g = _section(box, _("Desktops"))
        self.desktops = Gtk.SpinButton.new_with_range(1, 10, 1)
        self.desktops.connect("value-changed", self._desktops_changed)
        r = self._row(g, 0, _("How many"), self.desktops)
        self.popup = widgets.slider(0, 2000, 125, fmt=lambda v: _("Off") if v == 0 else _("{s} s").format(
            s=f"{v / 1000:g}"))
        self.popup.connect("value-changed", self._changed)
        r = self._row(g, r, _("Show the name when switching"), self.popup)
        self.name_rows = []
        for i in range(10):
            entry = Gtk.Entry(placeholder_text=_("Desktop {n}").format(n=i + 1))
            entry.connect("changed", self._changed)
            self._row(g, r + i, _("Desktop {n}").format(n=i + 1), entry)
            self.name_rows.append((g.get_child_at(0, r + i), entry))

    def _desktops_changed(self, *_a):
        self._show_names()
        self._changed()

    def _show_names(self):
        n = int(self.desktops.get_value())
        for i, (lbl, entry) in enumerate(self.name_rows):
            lbl.set_visible(i < n)
            entry.set_visible(i < n)

    # ---------------------------------------------------------------- startup and rules
    def _build_startup(self, box):
        g = _section(box, _("Start at login"))
        self.start_store = Gtk.ListStore(str)
        self.start_view = Gtk.TreeView(model=self.start_store, headers_visible=False)
        cell = Gtk.CellRendererText(editable=True)
        cell.connect("edited", self._start_edited)
        self.start_view.append_column(Gtk.TreeViewColumn(_("Command"), cell, text=0))
        g.attach(self._list(self.start_view, self._start_add, self._start_remove), 0, 0, 1, 1)
        g.attach(_hint(_("One command per line, run in this order after XControl's own (wallpaper, bar, lock and "
                         "the rest). Each goes to the background by itself. Changes apply at the next login.")),
                 0, 1, 1, 1)

        g = _section(box, _("Window rules"))
        # match, settings
        self.rule_store = Gtk.ListStore(str, str)
        self.rule_view = Gtk.TreeView(model=self.rule_store)
        for i, title in enumerate((_("Windows"), _("Settings"))):
            cell = Gtk.CellRendererText(editable=True)
            cell.connect("edited", self._rule_edited, i)
            col = Gtk.TreeViewColumn(title, cell, text=i)
            col.set_resizable(True)
            col.set_expand(True)
            self.rule_view.append_column(col)
        lst = self._list(self.rule_view, lambda *_a: self._rule_add(), self._rule_remove)
        if shutil.which("xprop"):
            pick = Gtk.Button(label=_("Pick a window…"))
            pick.set_tooltip_text(_("Click a window to add a rule for its program"))
            pick.connect("clicked", self._pick)
            lst.get_children()[-1].pack_start(pick, False, False, 0)
        g.attach(lst, 0, 0, 1, 1)
        g.attach(_hint(_("Windows: class=\"Steam\", title=\"Friends*\", role or name (* matches anything). "
                         "Settings: desktop=2, decor=no (no title bar), maximized=yes, fullscreen=yes, "
                         "layer=above, iconic=yes (minimized), skip_taskbar=yes, focus=no, x=center y=0 "
                         "monitor=2.")), 0, 1, 1, 1)

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
        self.c["startup"].append({"command": ""})
        self.start_store.append([""])
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
        self.start_store[i][0] = text
        self.c["startup"][i]["command"] = text
        self._commit_later()

    def _rule_add(self, match=None):
        rule = {"match": match or {"class": ""}, "settings": {"desktop": "1"}, "raw": ""}
        self.c["rules"].append(rule)
        self.rule_store.append([OB.match_text(rule["match"]), OB.settings_text(rule["settings"])])
        path = Gtk.TreePath(len(self.rule_store) - 1)
        self.rule_view.set_cursor(path, self.rule_view.get_column(1 if match else 0), True)
        self._commit_later()

    def _rule_remove(self, _b):
        _m, it = self.rule_view.get_selection().get_selected()
        if it:
            i = self.rule_store.get_path(it)[0]
            del self.c["rules"][i]
            self.rule_store.remove(it)
            self._commit_later()

    def _rule_edited(self, _cell, path, text, col):
        i = int(path)
        rule = self.c["rules"][i]
        if col == 0:
            match = OB.parse_match(text)
            if not match:
                self.window.set_status(_("Say which windows, e.g. class=\"Steam\""))
                return
            rule["match"] = match
            self.rule_store[i][0] = OB.match_text(match)
        else:
            settings, unknown = OB.parse_settings(text)
            rule["settings"] = settings
            self.rule_store[i][1] = OB.settings_text(settings)
            if unknown:
                self.window.set_status(_("Left out, Openbox doesn't know them here: {names}").format(
                    names=", ".join(unknown)))
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
                self._rule_add({"class": parts[1]})
            return False
        threading.Thread(target=run, daemon=True).start()

    # ---------------------------------------------------------------- values
    def _fill(self):
        c = self.c
        self.loading = True
        self.switch.set_active(c["enabled"])
        self.theme.remove_all()
        for t in sorted(set(OB.themes()) | {c["theme"]}, key=str.lower):
            self.theme.append(t, t)
        self.theme.set_active_id(c["theme"])
        if not self.layout.set_active_id(c["title_layout"]):
            self.layout.append(c["title_layout"], c["title_layout"])
            self.layout.set_active_id(c["title_layout"])
        self.title_font.set_font(_font_desc(c["title_font"]))
        self.menu_font.set_font(_font_desc(c["menu_font"]))
        self.keep_border.set_active(c["keep_border"])
        self.animate.set_active(c["animate_iconify"])
        self.drag_mod.set_active_id(c["drag_mod"])
        self._fill_keys()
        self.follow.set_active(c["follow_mouse"])
        self.delay.set_value(c["focus_delay"])
        self.raise_focus.set_active(c["raise_on_focus"])
        self.focus_new.set_active(c["focus_new"])
        self.placement.set_active_id(c["placement"])
        self.center.set_active(c["center"])
        self.monitor.set_active_id(c["placement_monitor"])
        self.resist_windows.set_value(c["resist_windows"])
        self.resist_edges.set_value(c["resist_edges"])
        self.double_click.set_active_id(c["double_click"])
        self.root_menu.set_active(c["root_menu"])
        self.root_list.set_active(c["root_window_list"])
        self.desktops.set_value(c["desktops"])
        self.popup.set_value(c["desktop_popup"])
        for i, (_lbl, entry) in enumerate(self.name_rows):
            entry.set_text(c["desktop_names"][i] if i < len(c["desktop_names"]) else "")
        self.start_store.clear()
        for s in c["startup"]:
            self.start_store.append([s["command"]])
        self.rule_store.clear()
        for r in c["rules"]:
            self.rule_store.append([OB.match_text(r["match"]), OB.settings_text(r["settings"])])
        self._sensitivity()
        self.loading = False

    def _sensitivity(self):
        on = self.switch.get_active()
        for t in self.tabs:
            t.set_sensitive(on)
        self.view_btn.set_sensitive(on)
        follow = self.follow.get_active()
        self.delay.set_sensitive(follow)
        self.delay_label.set_sensitive(follow)
        self._show_names()

    def _changed(self, *_a):
        if self.loading:
            return
        c = self.c
        c["theme"] = self.theme.get_active_id() or c["theme"]
        c["title_layout"] = self.layout.get_active_id() or c["title_layout"]
        c["title_font"] = _font_from(self.title_font.get_font(), c["title_font"])
        c["menu_font"] = _font_from(self.menu_font.get_font(), c["menu_font"])
        c["keep_border"] = self.keep_border.get_active()
        c["animate_iconify"] = self.animate.get_active()
        c["drag_mod"] = self.drag_mod.get_active_id() or "A"
        c["follow_mouse"] = self.follow.get_active()
        c["focus_delay"] = int(self.delay.get_value())
        c["raise_on_focus"] = self.raise_focus.get_active()
        c["focus_new"] = self.focus_new.get_active()
        c["placement"] = self.placement.get_active_id() or "Smart"
        c["center"] = self.center.get_active()
        c["placement_monitor"] = self.monitor.get_active_id() or "Primary"
        c["resist_windows"] = int(self.resist_windows.get_value())
        c["resist_edges"] = int(self.resist_edges.get_value())
        c["double_click"] = self.double_click.get_active_id() or "ToggleMaximize"
        c["root_menu"] = self.root_menu.get_active()
        c["root_window_list"] = self.root_list.get_active()
        c["desktops"] = int(self.desktops.get_value())
        c["desktop_popup"] = int(self.popup.get_value())
        names = [entry.get_text().strip() for _lbl, entry in self.name_rows]
        while names and not names[-1]:
            names.pop()
        c["desktop_names"] = names
        self._sensitivity()
        self._commit_later()

    def _commit_later(self, delay=700):
        if self.loading:
            return
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(delay, self._commit)

    def _commit(self):
        self._timer = None
        c = OB.normalize(self.c)
        try:
            OB.save(c)
            self.saved_before = True
            ok, errors = OB.write(c) if c["enabled"] else (True, [])
        except Exception as e:  # noqa: BLE001
            ok, errors = False, [str(e)]
        if errors:
            self.errtext.set_text(_("Openbox's config couldn't be written, so nothing was changed:") + "\n" +
                                  "\n".join(errors[:6]))
        widgets.reveal(self.errbar, bool(errors))
        if ok and c["enabled"]:
            self.window.set_status(_("Applied, Openbox reloaded"))
        self._status()
        return False

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
        if on:
            if not shutil.which("openbox"):
                self.window.message(_("Openbox isn't installed"), _("Install the openbox package first."))
                self._set_switch(False)
                return
            rc, _auto = OB.previous()
            if not self.saved_before or not self.c["base"]:
                if rc and self._ask(_("Start from your current Openbox config?"),
                                    _("Its look, keys, desktops, window rules and autostart programs are brought "
                                      "over to this page. Otherwise the page starts from Openbox's defaults. Either "
                                      "way your files are kept as backups."), _("Import it"), _("Openbox's defaults")):
                    self.c["enabled"] = True
                    self._do_import(quiet=False)
                else:
                    self.c = OB.defaults()
                    self.c["enabled"] = True
                    self._fill()
        elif OB.is_ours():
            body = (_("XControl's files are kept as rc.xml.xcontrol and autostart.xcontrol.") if OB.can_restore()
                    else _("Openbox goes back to its own default config. XControl's files are kept as "
                           "rc.xml.xcontrol and autostart.xcontrol."))
            if self._ask(_("Put your previous Openbox config back?"), body, _("Put it back"), _("Keep XControl's")):
                OB.restore()
        self.c["enabled"] = on
        self._sensitivity()
        self._commit_later(0)

    def _set_switch(self, on):
        self.loading = True
        self.switch.set_active(on)
        self.loading = False
        self._sensitivity()

    def _import(self, _b):
        rc, _auto = OB.previous()
        if not rc:
            self.window.message(_("Nothing to import"), _("No Openbox config other than XControl's was found."))
            return
        if self._ask(_("Import {path}?").format(path=rc.replace(os.path.expanduser("~"), "~")),
                     _("The settings on this page are replaced by the ones in that file."), _("Import")):
            self._do_import(quiet=False)
            self._commit_later(0)

    def _do_import(self, quiet=True):
        rc, auto = OB.previous()
        try:
            with open(rc, encoding="utf-8", errors="replace") as f:
                text = f.read()
            auto_text = None
            if auto:
                with open(auto, encoding="utf-8", errors="replace") as f:
                    auto_text = f.read()
            c, skipped = OB.import_config(text, self.c, auto_text)
        except (OSError, ValueError) as e:
            self.window.message(_("Could not read the config"), str(e))
            return
        c["enabled"] = self.c["enabled"]
        self.c = c
        self._fill()
        if skipped and not quiet:
            self.window.message(_("Imported"), _("Left out because XControl takes care of them now:") + "\n\n" +
                                "\n".join(skipped[:12]))

    def _show_file(self, _b):
        c = OB.normalize(self.c)
        try:
            text = OB.generate(c)
        except ValueError as e:
            text = str(e)
        text += "\n\n# ---- " + OB.autostart_path().replace(os.path.expanduser("~"), "~") + "\n\n" + \
            OB.generate_autostart(c)
        dlg = Gtk.Dialog(title=OB.target().replace(os.path.expanduser("~"), "~"), transient_for=self.get_toplevel(),
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
        v = OB.version()
        if not v:
            text = _("Openbox isn't installed.")
        else:
            text = "Openbox {}.{}.{}".format(*v)
            if self.c["enabled"]:
                loaded = OB.loaded_path()
                if loaded != OB.target():
                    text += " · " + _("Openbox reads {path}, not XControl's rc.xml (LXDE does this).").format(
                        path=loaded.replace(os.path.expanduser("~"), "~"))
                elif OB.is_ours():
                    text += " · " + _("XControl's config is in use.")
            if OB.can_restore():
                text += " · " + _("Your previous config is kept as rc.xml.before-xcontrol.")
        self.status.set_text(text)
        rc, _auto = OB.previous()
        self.import_btn.set_sensitive(bool(rc))
        return False
