"""The Bar & Compositor page: XControl's own polybar and picom."""
import shutil

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import bar as B, compositor as C, desktop as D, i3cfg as I3, widgets  # noqa: E402
from .i18n import N_, _  # noqa: E402

MODULE_LABELS = {
    "workspaces": (N_("i3 workspaces"),
                   N_("polybar's i3 module: i3 names and modes (resize...), urgent workspaces; click to switch")),
    "xworkspaces": (N_("Workspaces (other window managers)"),
                    N_("polybar's generic module for bspwm, Openbox, Xfwm and others; on i3, "
                       "\"i3 workspaces\" is recommended")),
    "title": (N_("Window title"), N_("title of the focused window")),
    "clock": (N_("Clock"), N_("click to show the date")),
    "cpu": (N_("CPU"), N_("processor usage")),
    "memory": (N_("Memory"), N_("RAM in use")),
    "temperature": (N_("Temperature"), N_("CPU temperature, red above the warning level")),
    "volume": (N_("Volume"), N_("scroll to change, click to mute (PipeWire or PulseAudio)")),
    "network": (N_("Network"), N_("local address, or offline")),
    "disk": (N_("Disk"), N_("space used on a drive")),
    "keyboard": (N_("Keyboard layout"), N_("current layout, and Caps Lock")),
    "battery": (N_("Battery"), N_("charge and charging")),
    "tray": (N_("System tray"), N_("icons of programs like Steam, Discord, nm-applet")),
}
POS_LABELS = {"left": N_("Left"), "center": N_("Center"), "right": N_("Right")}
BACKEND_LABELS = {"glx": N_("OpenGL (glx, recommended)"), "xrender": N_("XRender (most compatible, no blur)"),
                  "egl": N_("EGL (experimental, picom 10 or newer)")}
BLUR_LABELS = {"off": N_("Off"), "light": N_("Light"), "medium": N_("Medium"), "strong": N_("Strong")}


def _hint(text):
    lbl = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
    lbl.set_can_focus(False)
    lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.set_max_width_chars(80)
    lbl.get_style_context().add_class("dim-label")
    return lbl


def _rgba(text):
    c = Gdk.RGBA()
    c.parse(text or "#000000")
    return c


def _hex(rgba):
    return "#{:02x}{:02x}{:02x}".format(*(round(v * 255) for v in (rgba.red, rgba.green, rgba.blue)))


def _section(box, title):
    frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
    head = Gtk.Label(xalign=0)
    head.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
    frame.set_label_widget(head)
    grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_start=12, margin_top=8, margin_bottom=4)
    frame.add(grid)
    box.pack_start(frame, False, False, 0)
    return grid


def _scale(lo, hi, step, digits=0):
    s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    s.set_digits(digits)
    s.set_hexpand(True)
    s.set_value_pos(Gtk.PositionType.RIGHT)
    return s


class PanelPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.desk = D.load()
        self.loading = True
        self._timer = None
        self.labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=stack, halign=Gtk.Align.CENTER, margin_top=10, margin_bottom=4)
        self.pack_start(switcher, False, False, 0)
        for name, title, build in (("bar", _("Bar (polybar)"), self._build_bar),
                                   ("compositor", _("Compositor (picom)"), self._build_compositor)):
            sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
            build(box)
            sw.add(box)
            stack.add_titled(sw, name, title)
        self.pack_start(stack, True, True, 0)
        self.connect("map", lambda *_a: self._status())
        self._fill()
        widgets.protect(self)
        self.loading = False
        GLib.timeout_add_seconds(3, self._poll)

    def _row(self, grid, r, label, widget):
        lbl = Gtk.Label(label=label, xalign=0)
        self.labels.add_widget(lbl)
        grid.attach(lbl, 0, r, 1, 1)
        grid.attach(widget, 1, r, 1, 1)

    def _status_area(self, box):
        status = _hint("")
        box.pack_start(status, False, False, 0)
        bar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        text = _hint("")
        text.get_style_context().remove_class("dim-label")
        bar.get_content_area().add(text)
        bar.text = text
        bar.set_no_show_all(True)
        box.pack_start(bar, False, False, 0)
        return status, bar

    # ---------------------------------------------------------------- bar tab
    def _build_bar(self, box):
        head = Gtk.Box(spacing=10)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>{}</b>".format(GLib.markup_escape_text(_("Use XControl's bar"))))
        head.pack_start(lbl, False, False, 0)
        self.bar_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.bar_switch.connect("notify::active", self._changed)
        head.pack_start(self.bar_switch, False, False, 0)
        box.pack_start(head, False, False, 0)
        box.pack_start(_hint(_("XControl writes its own polybar setup from scratch and starts one bar per display. "
                               "Your own polybar config isn't used or changed.")), False, False, 0)
        self.bar_status, self.bar_warn = self._status_area(box)
        self.bar_stop = self.bar_warn.add_button(_("Stop them"), 1)
        self.bar_warn.connect("response", lambda *_a: self._stop_foreign(["polybar"]))

        g = _section(box, _("Layout"))
        self.bar_widgets = [g]
        self.position = Gtk.ComboBoxText()
        self.position.append("top", _("Top"))
        self.position.append("bottom", _("Bottom"))
        self.position.connect("changed", self._changed)
        self._row(g, 0, _("Position"), self.position)
        self.height = Gtk.SpinButton.new_with_range(16, 64, 1)
        self.height.connect("value-changed", self._changed)
        hb = Gtk.Box(spacing=6)
        hb.pack_start(self.height, False, False, 0)
        self.height_unit = Gtk.ComboBoxText()
        self.height_unit.append("px", _("pixels"))
        self.height_unit.append("pt", _("points"))
        self.height_unit.connect("changed", self._changed)
        hb.pack_start(self.height_unit, False, False, 0)
        hb.pack_start(Gtk.Label(label=_("Rounded corners")), False, False, 12)
        self.radius = Gtk.SpinButton.new_with_range(0, 30, 1)
        self.radius.connect("value-changed", self._changed)
        hb.pack_start(self.radius, False, False, 0)
        self._row(g, 1, _("Height"), hb)
        self.displays = Gtk.ComboBoxText()
        self.displays.append("all", _("Every display"))
        self.displays.append("primary", _("Only the primary display"))
        self.displays.connect("changed", self._changed)
        self._row(g, 2, _("Show on"), self.displays)
        self.font = Gtk.FontButton(hexpand=True)
        self.font.connect("font-set", self._changed)
        self._row(g, 3, _("Font"), self.font)
        self.labels_combo = Gtk.ComboBoxText()
        self.labels_combo.append("words", _("Words (CPU, RAM, VOL)"))
        self.labels_combo.append("icons", _("Icons (needs a Nerd Font)"))
        self.labels_combo.connect("changed", self._changed)
        self._row(g, 4, _("Labels"), self.labels_combo)
        self.nerd = B.nerd_font()
        g.attach(_hint(_("Icons use {font}.").format(font=self.nerd) if self.nerd else
                       _("No Nerd Font is installed (e.g. ttf-nerd-fonts-symbols), so labels are words.")),
                 1, 5, 1, 1)
        self.separator = Gtk.Entry(width_chars=6, halign=Gtk.Align.START)
        self.separator.set_tooltip_text(_("Spaces count: \" | \" keeps a space on each side. Empty: none."))
        self.separator.connect("changed", self._changed)
        self._row(g, 6, _("Between modules"), self.separator)
        self.scroll_ws = Gtk.CheckButton(label=_("Scrolling anywhere on the bar switches workspaces"))
        self.scroll_ws.connect("toggled", self._changed)
        g.attach(self.scroll_ws, 1, 7, 1, 1)
        self.clock_locale = Gtk.ComboBoxText()
        sys_loc = B.system_locale()
        self.clock_locale.append("", _("Same as the system ({locale})").format(locale=sys_loc or "C"))
        for loc in B.locales():
            self.clock_locale.append(loc, loc)
        self.clock_locale.connect("changed", self._changed)
        self._row(g, 8, _("Clock language"), self.clock_locale)
        more = Gtk.Button(label=_("Extra bar settings…"), halign=Gtk.Align.START)
        more.connect("clicked", lambda *_a: self._module_settings(None, "bar"))
        g.attach(more, 1, 9, 1, 1)

        g = _section(box, _("Colors"))
        self.bar_widgets.append(g)
        self.colors = {}
        for r, (key, label) in enumerate((("background", _("Background")), ("foreground", _("Text")),
                                          ("accent", _("Accent (labels, current workspace)")),
                                          ("secondary", _("Second accent (Caps Lock)")),
                                          ("highlight", _("Highlight (current workspace)")),
                                          ("urgent", _("Urgent")), ("dim", _("Dim (separators)")))):
            btn = Gtk.ColorButton(halign=Gtk.Align.START)
            btn.props.use_alpha = False
            if key == "highlight":  # automatic until picked: follows the background and text colors
                btn.connect("color-set", lambda *_a: setattr(self, "_highlight_set", True))
            btn.connect("color-set", self._changed)
            self.colors[key] = btn
            self._row(g, r, label, btn)
        self.opacity = _scale(0, 100, 5)
        self.opacity.connect("value-changed", self._changed)
        self._row(g, 7, _("Background opacity"), self.opacity)
        g.attach(_hint(_("Below 100 the bar is see-through when a compositor runs (see the other tab).")),
                 1, 8, 1, 1)

        g = _section(box, _("Modules"))
        self.bar_widgets.append(g)
        g.attach(_hint(_("Tick what the bar shows, pick its side, use the arrows to change the order, and the "
                         "gear for each module's settings.")), 0, 0, 2, 1)
        self.mod_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        frame = Gtk.Frame()
        frame.add(self.mod_list)
        g.attach(frame, 0, 1, 2, 1)

        self.bar_conflicts = _hint("")
        self.bar_conflicts.set_no_show_all(True)
        box.pack_start(self.bar_conflicts, False, False, 0)

    def _fill_modules(self):
        for row in self.mod_list.get_children():
            row.destroy()
        b = self.desk["bar"]
        can = B.available(b)
        ver = B.version()
        for i, (mid, pos, enabled) in enumerate(b["modules"]):
            row = Gtk.ListBoxRow(activatable=False)
            box = Gtk.Box(spacing=8, border_width=4)
            check = Gtk.CheckButton(active=enabled, valign=Gtk.Align.CENTER)
            check.connect("toggled", self._module_toggled, mid)
            box.pack_start(check, False, False, 0)
            name, about = MODULE_LABELS[mid]
            text = Gtk.Label(xalign=0, hexpand=True, wrap=True)
            note = ""
            if mid not in can:
                note = " — " + (_("no battery here") if mid == "battery" else
                                _("polybar {v} puts the tray at the right end").format(
                                    v=".".join(map(str, ver)) if ver else "?"))
            text.set_markup("<b>{}</b>  <span alpha='65%'>{}</span>".format(
                GLib.markup_escape_text(_(name)), GLib.markup_escape_text(_(about) + note)))
            box.pack_start(text, True, True, 0)
            combo = Gtk.ComboBoxText(valign=Gtk.Align.CENTER)
            for p in B.POSITIONS:
                combo.append(p, _(POS_LABELS[p]))
            combo.set_active_id(pos)
            combo.connect("changed", self._module_side, mid)
            box.pack_start(combo, False, False, 0)
            gear = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
            gear.set_relief(Gtk.ReliefStyle.NONE)
            gear.set_tooltip_text(_("Settings of this module"))
            gear.connect("clicked", self._module_settings, mid)
            box.pack_start(gear, False, False, 0)
            for icon, delta in (("go-up-symbolic", -1), ("go-down-symbolic", 1)):
                btn = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
                btn.set_relief(Gtk.ReliefStyle.NONE)
                btn.set_sensitive(0 <= i + delta < len(b["modules"]))
                btn.connect("clicked", self._module_move, mid, delta)
                box.pack_start(btn, False, False, 0)
            if mid not in can and mid == "battery":
                check.set_sensitive(False)
                combo.set_sensitive(False)
            row.add(box)
            self.mod_list.add(row)
        self.mod_list.show_all()
        widgets.protect(self.mod_list)

    def _module_settings(self, _btn, mid):
        from .bar_module_dialog import ModuleDialog
        title = _("Bar settings") if mid == "bar" else _("{module} settings").format(module=_(MODULE_LABELS[mid][0]))
        dlg = ModuleDialog(self.window, self.desk["bar"], mid, title)
        if dlg.run() == Gtk.ResponseType.OK:
            dlg.save()
            self._commit_later()
        dlg.destroy()

    def _module_toggled(self, check, mid):
        other = {"workspaces": "xworkspaces", "xworkspaces": "workspaces"}.get(mid)
        refill = False
        for m in self.desk["bar"]["modules"]:
            if m[0] == mid:
                m[2] = check.get_active()
            elif m[0] == other and check.get_active() and m[2]:
                m[2] = False   # both would show the same workspaces twice
                refill = True
        if refill:
            GLib.idle_add(lambda: self._fill_modules() and False)
        self._commit_later()

    def _module_side(self, combo, mid):
        for m in self.desk["bar"]["modules"]:
            if m[0] == mid:
                m[1] = combo.get_active_id()
        self._commit_later()

    def _module_move(self, _btn, mid, delta):
        mods = self.desk["bar"]["modules"]
        i = next(k for k, m in enumerate(mods) if m[0] == mid)
        j = i + delta
        if 0 <= j < len(mods):
            mods[i], mods[j] = mods[j], mods[i]
            self._fill_modules()
            self._commit_later()

    # ---------------------------------------------------------------- compositor tab
    def _build_compositor(self, box):
        head = Gtk.Box(spacing=10)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>{}</b>".format(GLib.markup_escape_text(_("Use XControl's compositor"))))
        head.pack_start(lbl, False, False, 0)
        self.pic_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.pic_switch.connect("notify::active", self._changed)
        head.pack_start(self.pic_switch, False, False, 0)
        box.pack_start(head, False, False, 0)
        box.pack_start(_hint(_("A compositor adds shadows, fading, transparency and rounded corners, and stops "
                               "tearing. XControl writes its own picom setup; your picom.conf isn't used or "
                               "changed.")), False, False, 0)
        self.pic_status, self.pic_warn = self._status_area(box)
        self.pic_warn.add_button(_("Stop them"), 1)
        self.pic_warn.connect("response", lambda *_a: self._stop_foreign(["picom", "compton", "xcompmgr"]))

        g = _section(box, _("Drawing"))
        self.pic_widgets = [g]
        self.backend = Gtk.ComboBoxText()
        for k in C.BACKENDS:
            self.backend.append(k, _(BACKEND_LABELS[k]))
        self.backend.connect("changed", self._changed)
        self._row(g, 0, _("Backend"), self.backend)
        self.vsync = Gtk.CheckButton(label=_("VSync (no tearing)"))
        self.vsync.connect("toggled", self._changed)
        g.attach(self.vsync, 1, 1, 1, 1)
        self.unredir = Gtk.CheckButton(label=_("Let full-screen games skip the compositor"))
        self.unredir.connect("toggled", self._changed)
        g.attach(self.unredir, 1, 2, 1, 1)
        g.attach(_hint(_("Recommended: full-screen games get lower input lag, and FreeSync only works for them "
                         "this way.")), 1, 3, 1, 1)

        g = _section(box, _("Effects"))
        self.pic_widgets.append(g)
        self.shadows = Gtk.CheckButton(label=_("Shadows"))
        self.shadows.connect("toggled", self._changed)
        g.attach(self.shadows, 1, 0, 1, 1)
        self.sh_radius = _scale(2, 40, 1)
        self.sh_radius.connect("value-changed", self._changed)
        self._row(g, 1, _("Shadow size"), self.sh_radius)
        self.sh_opacity = _scale(5, 100, 5)
        self.sh_opacity.connect("value-changed", self._changed)
        self._row(g, 2, _("Shadow strength"), self.sh_opacity)
        self.fading = Gtk.CheckButton(label=_("Fade windows in and out"))
        self.fading.connect("toggled", self._changed)
        g.attach(self.fading, 1, 3, 1, 1)
        self.fade_speed = _scale(1, 30, 1)
        self.fade_speed.connect("value-changed", self._changed)
        self._row(g, 4, _("Fade speed"), self.fade_speed)
        self.corners = _scale(0, 30, 1)
        self.corners.connect("value-changed", self._changed)
        self._row(g, 5, _("Rounded corners"), self.corners)
        self.blur = Gtk.ComboBoxText()
        for k in C.BLUR:
            self.blur.append(k, _(BLUR_LABELS[k]))
        self.blur.connect("changed", self._changed)
        self._row(g, 6, _("Blur behind see-through windows"), self.blur)

        g = _section(box, _("Transparency"))
        self.pic_widgets.append(g)
        self.active = _scale(30, 100, 5)
        self.active.connect("value-changed", self._changed)
        self._row(g, 0, _("Focused window"), self.active)
        self.inactive = _scale(30, 100, 5)
        self.inactive.connect("value-changed", self._changed)
        self._row(g, 1, _("Other windows"), self.inactive)
        g.attach(_hint(_("Percent opacity. Full-screen windows and the lock screen are never see-through.")),
                 1, 2, 1, 1)

        self.pic_conflicts = _hint("")
        self.pic_conflicts.set_no_show_all(True)
        box.pack_start(self.pic_conflicts, False, False, 0)

    # ---------------------------------------------------------------- model <-> view
    def _fill(self):
        b, p = self.desk["bar"], self.desk["picom"]
        self.bar_switch.set_active(b["enabled"])
        self.position.set_active_id(b["position"])
        self.height.set_value(b["height"])
        self.displays.set_active_id(b["displays"])
        self.font.set_font(b["font"])
        self.labels_combo.set_active_id(b["labels"] if self.nerd else "words")
        self.labels_combo.set_sensitive(bool(self.nerd))
        for key, btn in self.colors.items():
            btn.set_rgba(_rgba(b[key] or (B._mix(b["background"], b["foreground"], 0.12) if key == "highlight"
                                          else "#000000")))
        self._highlight_set = bool(b["highlight"])
        self.opacity.set_value(b["opacity"])
        self.height_unit.set_active_id(b["height_unit"])
        self.radius.set_value(b["radius"])
        self.separator.set_text(b["separator"])
        self.scroll_ws.set_active(b["scroll_workspaces"])
        if not self.clock_locale.set_active_id(b["clock_locale"]):
            self.clock_locale.append(b["clock_locale"], b["clock_locale"])
            self.clock_locale.set_active_id(b["clock_locale"])
        self._fill_modules()

        self.pic_switch.set_active(p["enabled"])
        self.backend.set_active_id(p["backend"])
        self.vsync.set_active(p["vsync"])
        self.unredir.set_active(p["unredirect"])
        self.shadows.set_active(p["shadows"])
        self.sh_radius.set_value(p["shadow_radius"])
        self.sh_opacity.set_value(p["shadow_opacity"])
        self.fading.set_active(p["fading"])
        self.fade_speed.set_value(p["fade_speed"])
        self.corners.set_value(p["corner_radius"])
        self.blur.set_active_id(p["blur"])
        self.active.set_value(p["active_opacity"])
        self.inactive.set_value(p["inactive_opacity"])
        self._sensitivity()

    def _sensitivity(self):
        for g in self.bar_widgets:
            g.set_sensitive(self.bar_switch.get_active())
        for g in self.pic_widgets:
            g.set_sensitive(self.pic_switch.get_active())
        self.sh_radius.set_sensitive(self.shadows.get_active())
        self.sh_opacity.set_sensitive(self.shadows.get_active())
        self.fade_speed.set_sensitive(self.fading.get_active())
        self.blur.set_sensitive(self.backend.get_active_id() != "xrender")

    def _changed(self, *_a):
        if self.loading:
            return
        b, p = self.desk["bar"], self.desk["picom"]
        b["enabled"] = self.bar_switch.get_active()
        b["position"] = self.position.get_active_id() or "bottom"
        b["height"] = int(self.height.get_value())
        b["displays"] = self.displays.get_active_id() or "all"
        b["font"] = self.font.get_font() or b["font"]
        b["labels"] = self.labels_combo.get_active_id() or "words"
        for key, btn in self.colors.items():
            b[key] = _hex(btn.get_rgba()) if key != "highlight" or self._highlight_set else ""
        b["opacity"] = int(self.opacity.get_value())
        b["height_unit"] = self.height_unit.get_active_id() or "px"
        b["radius"] = int(self.radius.get_value())
        b["separator"] = self.separator.get_text()
        b["scroll_workspaces"] = self.scroll_ws.get_active()
        b["clock_locale"] = self.clock_locale.get_active_id() or ""
        p["enabled"] = self.pic_switch.get_active()
        p["backend"] = self.backend.get_active_id() or "glx"
        p["vsync"] = self.vsync.get_active()
        p["unredirect"] = self.unredir.get_active()
        p["shadows"] = self.shadows.get_active()
        p["shadow_radius"] = int(self.sh_radius.get_value())
        p["shadow_opacity"] = int(self.sh_opacity.get_value())
        p["fading"] = self.fading.get_active()
        p["fade_speed"] = int(self.fade_speed.get_value())
        p["corner_radius"] = int(self.corners.get_value())
        p["blur"] = self.blur.get_active_id() or "off"
        p["active_opacity"] = int(self.active.get_value())
        p["inactive_opacity"] = int(self.inactive.get_value())
        self._sensitivity()
        self._commit_later()

    def _commit_later(self):
        if self.loading:
            return
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(500, self._commit)   # sliders: wait until they stop moving

    def _commit(self):
        self._timer = None
        fresh = D.load()   # other pages (Desktop) keep their part
        fresh["bar"], fresh["picom"] = self.desk["bar"], self.desk["picom"]
        try:
            D.save(fresh)
            D.notify_daemon(fresh)
            ok, errors = I3.refresh()   # i3's own bar comes and goes with this one
            if not ok:
                self.window.message(_("The i3 config wasn't updated"), "\n".join(errors))
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not save the settings"), str(e))
            return False
        self.window.set_status(_("Applied"))
        GLib.timeout_add(2500, lambda: self._status() and False)
        return False

    def _poll(self):
        if self.get_mapped():
            self._status()
        return True

    def _stop_foreign(self, names):
        D.stop_foreign(names)
        GLib.timeout_add(800, lambda: self._status() and False)

    # ---------------------------------------------------------------- status
    def _status(self):
        st = D.state()
        kids = st.get("children") or {}
        errors = st.get("errors") or {}
        conflicts = D.session_conflicts()

        b = self.desk["bar"]
        bars = sorted(k[4:] or _("the screen") for k in kids if k.startswith("bar:"))
        if not shutil.which("polybar"):
            text = _("polybar isn't installed.")
        elif not b["enabled"]:
            text = ""
        elif bars:
            text = _("Running on {displays}.").format(displays=", ".join(bars))
        else:
            err = next((v for k, v in errors.items() if k.startswith("bar:")), "")
            text = _("Not running: {why}").format(why=err) if err else _("Starting…")
        self.bar_status.set_text(text)
        self.bar_status.set_visible(bool(text))
        foreign = D.foreign(["polybar"])
        lines = [line for kind, line in conflicts if kind in ("bar", "i3bar")]
        self._warn(self.bar_warn, b["enabled"] and foreign,
                   _("Another polybar is running (started by your i3 config or a script); it will sit on top "
                     "of XControl's."))
        self._conflict(self.bar_conflicts, b["enabled"] and lines,
                       _("Remove these from your i3 config, or there will be two bars after the next login:"), lines)

        p = self.desk["picom"]
        if not shutil.which("picom"):
            text = _("picom isn't installed.")
        elif not p["enabled"]:
            text = ""
        elif "picom" in kids:
            text = _("Running (picom {v}).").format(v=".".join(map(str, C.version() or ())) or "?")
        else:
            err = errors.get("picom", "")
            text = _("Not running: {why}").format(why=err) if err else _("Starting…")
        self.pic_status.set_text(text)
        self.pic_status.set_visible(bool(text))
        foreign = D.foreign(["picom", "compton", "xcompmgr"])
        lines = [line for kind, line in conflicts if kind == "compositor"]
        self._warn(self.pic_warn, p["enabled"] and foreign,
                   _("Another compositor is running, so XControl's can't start. Stop it, and remove it from "
                     "your i3 config."))
        self._conflict(self.pic_conflicts, p["enabled"] and lines,
                       _("Remove these from your i3 config, or the other compositor starts first after the next "
                         "login:"), lines)
        return False

    def _warn(self, bar, show, text):
        bar.text.set_text(text)
        widgets.reveal(bar, bool(show))

    def _conflict(self, label, show, text, lines):
        if show:
            label.set_markup("⚠ " + GLib.markup_escape_text(text) + "\n" +
                             "\n".join(f"<tt>{GLib.markup_escape_text(line)}</tt>" for line in lines[:6]))
        label.set_visible(bool(show))
