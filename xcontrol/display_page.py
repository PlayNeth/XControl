"""The Displays page: arrange monitors and set resolution, refresh rate,
rotation and primary display through xrandr."""
import copy
import os
import shlex

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import config, modelines, output_names, output_props, xrandr  # noqa: E402
from .display_color import ColorPanel  # noqa: E402
from .i18n import N_, _, hz, ngettext  # noqa: E402
from .paths import autostart_file  # noqa: E402
from .resolutions_dialog import ResolutionsDialog, mode_label, standard_of  # noqa: E402

ROTATION_LABELS = [N_("Normal"), N_("Rotated left"), N_("Rotated right"), N_("Upside down")]
REVERT_SECONDS = 15
SNAP_PX = 10


class Arrangement(Gtk.DrawingArea):
    """Scaled-down desktop; drag monitors to place them, edges snap."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.set_size_request(-1, 260)
        self.set_hexpand(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("motion-notify-event", self._motion)
        self.connect("button-release-event", self._release)
        self.drag = None
        self.view = (1.0, 0, 0, 0, 0)  # scale, origin x/y, offset x/y

    def _enabled(self):
        return [m for m in self.page.monitors if m.connected and m.enabled]

    def _compute_view(self):
        mons = self._enabled()
        w, h = self.get_allocated_width(), self.get_allocated_height()
        if not mons:
            return (1.0, 0, 0, 0, 0)
        x0 = min(m.x for m in mons)
        y0 = min(m.y for m in mons)
        x1 = max(m.x + m.size()[0] for m in mons)
        y1 = max(m.y + m.size()[1] for m in mons)
        margin = 24
        scale = min((w - 2 * margin) / max(1, x1 - x0), (h - 2 * margin) / max(1, y1 - y0))
        ox = (w - (x1 - x0) * scale) / 2
        oy = (h - (y1 - y0) * scale) / 2
        return (scale, x0, y0, ox, oy)

    def _rect(self, m):
        scale, x0, y0, ox, oy = self.view
        w, h = m.size()
        return (ox + (m.x - x0) * scale, oy + (m.y - y0) * scale, w * scale, h * scale)

    def _draw(self, widget, cr):
        if not self.drag:
            self.view = self._compute_view()
        ctx = widget.get_style_context()
        fg = ctx.get_color(Gtk.StateFlags.NORMAL)
        mons = self._enabled()
        if not mons:
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
            cr.select_font_face("sans")
            cr.set_font_size(14)
            msg = _("No active displays")
            ext = cr.text_extents(msg)
            cr.move_to((widget.get_allocated_width() - ext.width) / 2, widget.get_allocated_height() / 2)
            cr.show_text(msg)
            return
        sel = self.page.selected
        for m in sorted(mons, key=lambda m: m is sel):
            x, y, w, h = self._rect(m)
            if m is sel:
                cr.set_source_rgb(0.21, 0.47, 0.82)
            else:
                cr.set_source_rgb(0.42, 0.45, 0.50)
            cr.rectangle(x + 1, y + 1, w - 2, h - 2)
            cr.fill_preserve()
            cr.set_source_rgba(0, 0, 0, 0.45)
            cr.set_line_width(1.5)
            cr.stroke()
            cr.set_source_rgb(1, 1, 1)
            cr.select_font_face("sans", 0, 1)
            num = str(self.page.number_of(m))
            cr.set_font_size(max(12, min(36, h * 0.3)))
            ext = cr.text_extents(num)
            cr.move_to(x + (w - ext.width) / 2 - ext.x_bearing, y + h / 2 - 2)
            cr.show_text(num)
            cr.select_font_face("sans", 0, 0)
            cr.set_font_size(max(9, min(13, h * 0.11)))
            mw, mh = m.mode_size()
            lines = [m.name, f"{mw}×{mh}"]
            if m.primary:
                # TRANSLATORS: label drawn on the primary display in the arrangement view
                lines.append(_("Primary"))
            ty = y + h / 2 + 4
            for line in lines:
                ext = cr.text_extents(line)
                if ext.width < w - 6:
                    ty += ext.height + 3
                    cr.move_to(x + (w - ext.width) / 2 - ext.x_bearing, ty)
                    cr.show_text(line)

    def _hit(self, ex, ey):
        mons = self._enabled()
        sel = self.page.selected
        for m in sorted(mons, key=lambda m: m is not sel):  # selected one is on top
            x, y, w, h = self._rect(m)
            if x <= ex <= x + w and y <= ey <= y + h:
                return m
        return None

    def _press(self, _w, ev):
        m = self._hit(ev.x, ev.y)
        if not m:
            return False
        self.page.select(m)
        scale = self.view[0]
        self.drag = (m, ev.x, ev.y, m.x, m.y, scale)
        return True

    def _motion(self, _w, ev):
        if not self.drag:
            return False
        m, sx, sy, mx, my, scale = self.drag
        nx = mx + (ev.x - sx) / scale
        ny = my + (ev.y - sy) / scale
        nx, ny = self._snap(m, nx, ny, SNAP_PX / scale)
        m.x, m.y = int(round(nx)), int(round(ny))
        self.page.positions_changed(live=True)
        self.queue_draw()
        return True

    def _snap(self, m, nx, ny, thr):
        w, h = m.size()
        best_x = best_y = None
        for o in self._enabled():
            if o is m:
                continue
            ow, oh = o.size()
            for c in (o.x + ow, o.x - w, o.x, o.x + ow - w):
                d = abs(nx - c)
                if d < thr and (best_x is None or d < best_x[0]):
                    best_x = (d, c)
            for c in (o.y + oh, o.y - h, o.y, o.y + oh - h):
                d = abs(ny - c)
                if d < thr and (best_y is None or d < best_y[0]):
                    best_y = (d, c)
        return (best_x[1] if best_x else nx, best_y[1] if best_y else ny)

    def _release(self, _w, _ev):
        if not self.drag:
            return False
        self.drag = None
        xrandr.normalize_positions(self.page.monitors)
        self.page.positions_changed(live=False)
        self.queue_draw()
        return True


class DisplayPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, border_width=18)
        self.window = window
        self.monitors = []
        self.selected = None
        self.original = []  # the layout as read, for revert
        self.loading = False

        self.warning = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        self.warning_label = Gtk.Label(xalign=0, wrap=True)
        self.warning.get_content_area().add(self.warning_label)
        self.warning.set_no_show_all(True)
        self.pack_start(self.warning, False, False, 0)

        frame = Gtk.Frame()
        self.canvas = Arrangement(self)
        frame.add(self.canvas)
        self.pack_start(frame, False, False, 0)
        hint = Gtk.Label(label=_("Drag the displays to match how they sit on your desk."), xalign=0)
        hint.get_style_context().add_class("dim-label")
        self.pack_start(hint, False, False, 0)

        g = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.monitor_combo = Gtk.ComboBoxText(hexpand=True)
        self.monitor_combo.connect("changed", self._monitor_chosen)
        self.enabled_switch = Gtk.Switch(halign=Gtk.Align.START)
        self.enabled_switch.connect("notify::active", self._enabled_toggled)
        self.primary_check = Gtk.CheckButton(label=_("Make this the primary display"))
        self.primary_check.connect("toggled", self._primary_toggled)
        self.mode_combo = Gtk.ComboBoxText()
        self.mode_combo.connect("changed", self._mode_chosen)
        self.modes_note = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.modes_note.get_style_context().add_class("dim-label")
        self.modes_note.set_no_show_all(True)
        mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        mode_box.pack_start(self.mode_combo, False, False, 0)
        mode_box.pack_start(self.modes_note, False, False, 0)
        self.rate_combo = Gtk.ComboBoxText()
        self.rate_combo.connect("changed", self._rate_chosen)
        self.rot_combo = Gtk.ComboBoxText()
        for r in ROTATION_LABELS:
            self.rot_combo.append_text(_(r))
        self.rot_combo.connect("changed", self._rotation_chosen)
        self.x_spin = Gtk.SpinButton.new_with_range(0, 32767, 1)
        self.y_spin = Gtk.SpinButton.new_with_range(0, 32767, 1)
        self.x_spin.connect("value-changed", self._pos_typed)
        self.y_spin.connect("value-changed", self._pos_typed)
        pos = Gtk.Box(spacing=6)
        pos.pack_start(Gtk.Label(label="X"), False, False, 0)
        pos.pack_start(self.x_spin, False, False, 0)
        pos.pack_start(Gtk.Label(label="Y"), False, False, 0)
        pos.pack_start(self.y_spin, False, False, 0)

        info_btn = Gtk.Button(label=_("Details"))
        info_btn.set_tooltip_text(_("Show what this display reports: model, refresh range, HDR, color"))
        info_btn.connect("clicked", self._show_info)
        res_btn = Gtk.Button(label=_("Resolutions…"))
        res_btn.set_tooltip_text(_("Add custom resolutions, or ignore the modes the display reports"))
        res_btn.connect("clicked", self._resolutions)
        self.res_btn = res_btn
        display_row = Gtk.Box(spacing=6)
        display_row.pack_start(self.monitor_combo, True, True, 0)
        display_row.pack_start(res_btn, False, False, 0)
        display_row.pack_start(info_btn, False, False, 0)
        rows = [(_("Display"), display_row), (_("Enabled"), self.enabled_switch), ("", self.primary_check),
                (_("Resolution"), mode_box), (_("Refresh rate"), self.rate_combo),
                (_("Orientation"), self.rot_combo), (_("Position"), pos)]
        for i, (label, widget) in enumerate(rows):
            g.attach(Gtk.Label(label=label, xalign=0), 0, i, 1, 1)
            g.attach(widget, 1, i, 1, 1)
        self.controls = [w for _, w in rows[1:]]
        self.pack_start(g, False, False, 0)

        self.previewed = set()      # outputs whose colours are being previewed live
        self._preview_pending = {}
        self._preview_timer = None
        self.color = ColorPanel(self._color_changed, self._color_preview)
        # leaving without Apply puts the previewed colours back
        self.window.connect("delete-event", lambda *_a: (self._undo_preview(), False)[1])
        self.connect("destroy", lambda *_a: self._undo_preview())
        self.pack_start(self.color, False, False, 0)
        labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        for child in g.get_children():
            if g.child_get_property(child, "left-attach") == 0:
                labels.add_widget(child)
        for w in self.color.label_widgets():
            labels.add_widget(w)

        buttons = Gtk.Box(spacing=6)
        self.autostart_check = Gtk.CheckButton(label=_("Restore this layout when I log in"))
        self.autostart_check.set_active(config.load()["display"]["autostart"])
        self.autostart_check.connect("toggled", self._autostart_toggled)
        buttons.pack_start(self.autostart_check, False, False, 0)
        self.apply_btn = Gtk.Button(label=_("Apply"))
        self.apply_btn.get_style_context().add_class("suggested-action")
        self.apply_btn.connect("clicked", self._apply)
        detect = Gtk.Button(label=_("Detect displays"))
        detect.connect("clicked", lambda *_a: self.reload())
        ident = Gtk.Button(label=_("Identify"))
        ident.connect("clicked", self._identify)
        buttons.pack_end(self.apply_btn, False, False, 0)
        buttons.pack_end(detect, False, False, 0)
        buttons.pack_end(ident, False, False, 0)
        self.pack_end(buttons, False, False, 0)

        self.reload()

    # ---- state
    def number_of(self, m):
        connected = [x for x in self.monitors if x.connected]
        return connected.index(m) + 1 if m in connected else 0

    def reload(self, keep=None):
        self._undo_preview()  # a re-read discards unapplied changes, previews included
        warn = xrandr.session_warning()
        self.warning_label.set_text(warn or "")
        self.warning.set_visible(bool(warn))
        self.warning_label.set_visible(bool(warn))
        self.mode_problems = {}
        try:
            self.monitors = (xrandr.query(with_props=True)
                             if xrandr.available() and os.environ.get("DISPLAY") and not warn else [])
            if self.monitors:
                renamed = output_names.migrate_saved()
                if renamed:
                    self.window.set_status(_("Saved settings moved to the new output names: {names}").format(
                        names=", ".join(f"{a} → {b}" for a, b in renamed.items())))
            if self.monitors and self._restore_missing_modes():
                self.monitors = xrandr.query(with_props=True)
        except Exception as e:  # noqa: BLE001 - surface any xrandr failure
            self.monitors = []
            self.window.set_status("xrandr: {error}".format(error=e))
        self.original = copy.deepcopy(self.monitors)
        connected = [m for m in self.monitors if m.connected]
        self.selected = (next((m for m in connected if m.name == keep), None)
                         or next((m for m in connected if m.primary), connected[0] if connected else None))
        self._fill_monitor_combo()
        self.apply_btn.set_sensitive(bool(connected) and not warn)
        self.canvas.queue_draw()

    def _fill_monitor_combo(self):
        self.loading = True
        self.monitor_combo.remove_all()
        connected = [m for m in self.monitors if m.connected]
        for m in connected:
            self.monitor_combo.append_text(f"{self.number_of(m)}. {m.describe()}")
        self.loading = False
        if self.selected in connected:
            self.monitor_combo.set_active(connected.index(self.selected))
        else:
            self._sync_controls()

    def select(self, m):
        connected = [x for x in self.monitors if x.connected]
        if m in connected:
            self.monitor_combo.set_active(connected.index(m))

    def _refresh_combo_label(self):
        m = self.selected
        if not m:
            return
        idx = self.monitor_combo.get_active()
        self.loading = True
        self.monitor_combo.remove(idx)
        self.monitor_combo.insert_text(idx, f"{self.number_of(m)}. {m.describe()}")
        self.monitor_combo.set_active(idx)
        self.loading = False

    def _sync_controls(self):
        m = self.selected
        self.loading = True
        for w in self.controls:
            w.set_sensitive(m is not None)
        if m:
            self.enabled_switch.set_active(m.enabled)
            self.primary_check.set_active(m.primary)
            self.mode_combo.remove_all()
            for mode in self._visible_modes(m):
                self.mode_combo.append(mode, mode_label(mode, mode == m.preferred, m.modes.get(mode, ())))
            if m.mode:
                self.mode_combo.set_active_id(m.mode)
            self._fill_rates()
            self.rot_combo.set_active(xrandr.ROTATIONS.index(m.rotation))
            self.x_spin.set_value(m.x)
            self.y_spin.set_value(m.y)
            for w in (self.primary_check, self.mode_combo, self.rate_combo, self.rot_combo, self.controls[-1]):
                w.set_sensitive(m.enabled)
            # with one display on there is nothing to choose between
            others = [o for o in self.monitors if o.connected and o.enabled and o is not m]
            self.primary_check.set_sensitive(m.enabled and bool(others))
            self.primary_check.set_tooltip_text(
                None if others else _("Only matters with more than one display: it gets the panels, "
                                      "notifications and fullscreen games."))
        self.color.show_monitor(m)
        self.color.set_sensitive(bool(m and m.enabled))
        self.loading = False

    def _color_changed(self):
        self.window.set_status(_("Press Apply to use the new settings"))

    # ---- live preview of saturation and gamma
    def _color_preview(self, m):
        self._preview_pending[m.name] = m
        if self._preview_timer is None:  # at most every 120 ms while a slider moves
            self._preview_timer = GLib.timeout_add(120, self._flush_preview)

    def _flush_preview(self):
        self._preview_timer = None
        pending, self._preview_pending = self._preview_pending, {}
        for name, m in pending.items():
            args = output_props.preview_args(m)
            if not args:
                continue
            try:
                xrandr.run(["xrandr"] + args)
                self.previewed.add(name)
                self.window.set_status(_("Previewing: press Apply to keep these colors"))
            except Exception as e:  # noqa: BLE001
                self.window.set_status(_("Preview failed: {error}").format(error=e))
        return False

    def _cancel_preview_timer(self):
        if self._preview_timer is not None:
            GLib.source_remove(self._preview_timer)
            self._preview_timer = None
        self._preview_pending = {}

    def _undo_preview(self):
        """Put back the colours from before the preview (nothing was applied)."""
        self._cancel_preview_timer()
        originals = {m.name: m for m in self.original}
        for name in sorted(self.previewed):
            orig = originals.get(name)
            args = output_props.preview_args(orig) if orig else []
            if args:
                try:
                    xrandr.run(["xrandr"] + args)
                except Exception:  # noqa: BLE001 - best effort; the output may be gone
                    pass
        self.previewed.clear()

    def _restore_missing_modes(self):
        """X forgets custom modes when it restarts; put back any saved ones that
        are missing. Returns True if something was added."""
        added = False
        by_name = {m.name: m for m in self.monitors if m.connected}
        for output, modes in config.load()["display"]["custom_modes"].items():
            mon = by_name.get(output)
            if not mon:
                continue
            for d in modes:
                try:
                    ml = modelines.Modeline.from_dict(d)
                except TypeError:
                    continue
                if ml.name in mon.modes:
                    continue
                try:
                    xrandr.add_custom_mode(output, ml)
                    added = True
                except Exception as e:  # noqa: BLE001
                    self.mode_problems.setdefault(output, []).append(f"{ml.name}: {e}")
        return added

    def _visible_modes(self, m):
        """All modes, or only the custom ones when the EDID list is ignored
        (plus the current mode, so the selection never disappears)."""
        data = config.load()["display"]
        modes = list(m.modes)
        note = ""
        custom = [x for x in modes if standard_of(x)]
        if m.name not in data["edid_ignored"]:
            modes = custom + [x for x in modes if x not in custom]  # custom ones first
        else:
            if custom:
                modes = custom + ([m.mode] if m.mode and m.mode not in custom else [])
            else:
                note = _("None of your custom resolutions are active on this display, so all modes are shown.")
                problems = getattr(self, "mode_problems", {}).get(m.name)
                if problems:
                    note += "\n" + "\n".join(problems)
        self.modes_note.set_text(note)
        self.modes_note.set_visible(bool(note))
        return modes

    def _fill_rates(self):
        m = self.selected
        self.rate_combo.remove_all()
        for r in m.modes.get(m.mode, []):
            self.rate_combo.append(r, hz(float(r)))
        if m.rate in m.modes.get(m.mode, []):
            self.rate_combo.set_active_id(m.rate)
        else:
            self.rate_combo.set_active(0)

    def positions_changed(self, live):
        if self.selected:
            self.loading = True
            self.x_spin.set_value(self.selected.x)
            self.y_spin.set_value(self.selected.y)
            self.loading = False

    # ---- control handlers
    def _monitor_chosen(self, combo):
        if self.loading:
            return
        connected = [m for m in self.monitors if m.connected]
        idx = combo.get_active()
        self.selected = connected[idx] if 0 <= idx < len(connected) else None
        self._sync_controls()
        self.canvas.queue_draw()

    def _enabled_toggled(self, sw, _pspec):
        m = self.selected
        if self.loading or not m:
            return
        m.enabled = sw.get_active()
        if m.enabled:
            if not m.mode or m.mode not in m.modes:
                m.mode = m.preferred or next(iter(m.modes), "")
                m.rate = (m.modes.get(m.mode) or [""])[0]
            others = [o for o in self.monitors if o.connected and o.enabled and o is not m]
            m.x = max((o.x + o.size()[0] for o in others), default=0)
            m.y = min((o.y for o in others), default=0)
        else:
            m.primary = False
        xrandr.normalize_positions(self.monitors)
        self._sync_controls()
        self._refresh_combo_label()
        self.canvas.queue_draw()

    def _primary_toggled(self, check):
        if self.loading or not self.selected:
            return
        for o in self.monitors:
            o.primary = False
        self.selected.primary = check.get_active()
        self.canvas.queue_draw()

    def _mode_chosen(self, combo):
        if self.loading or not self.selected or not combo.get_active_id():
            return
        m = self.selected
        m.mode = combo.get_active_id()
        rates = m.modes.get(m.mode, [])
        if m.rate not in rates:
            # keep the closest refresh rate to what was set before
            old = float(m.rate or 60)
            m.rate = min(rates, key=lambda r: abs(float(r) - old)) if rates else ""
        self.loading = True
        self._fill_rates()
        self.loading = False
        self._refresh_combo_label()
        self.canvas.queue_draw()

    def _rate_chosen(self, combo):
        if self.loading or not self.selected or not combo.get_active_id():
            return
        self.selected.rate = combo.get_active_id()
        self._refresh_combo_label()

    def _rotation_chosen(self, combo):
        if self.loading or not self.selected:
            return
        self.selected.rotation = xrandr.ROTATIONS[max(0, combo.get_active())]
        self.canvas.queue_draw()

    def _pos_typed(self, *_args):
        if self.loading or not self.selected:
            return
        self.selected.x = int(self.x_spin.get_value())
        self.selected.y = int(self.y_spin.get_value())
        self.canvas.queue_draw()

    # ---- actions
    def _resolutions(self, *_args):
        if not self.selected:
            return
        name = self.selected.name
        dlg = ResolutionsDialog(self, self.selected)
        dlg.run()
        changed = dlg.changed
        dlg.destroy()
        if changed:
            self.reload(keep=name)

    def _show_info(self, *_args):
        if self.selected:
            self.window.show_monitor_info(self.selected.name)

    def _identify(self, *_args):
        for m in self.monitors:
            if not (m.connected and m.enabled):
                continue
            win = Gtk.Window(type=Gtk.WindowType.POPUP)
            lbl = Gtk.Label()
            lbl.set_markup(f"<span size='72000' weight='bold'>{self.number_of(m)}</span>\n"
                           f"<span size='14000'>{GLib.markup_escape_text(m.name)}</span>")
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_margin_start(36)
            lbl.set_margin_end(36)
            lbl.set_margin_top(18)
            lbl.set_margin_bottom(18)
            win.add(lbl)
            win.move(m.x + 40, m.y + 40)
            win.show_all()
            GLib.timeout_add_seconds(3, win.destroy)

    def _apply(self, *_args):
        if not any(m.connected and m.enabled for m in self.monitors):
            self.window.message(_("At least one display must stay on"), _("Turn on a display before applying."))
            return
        xrandr.normalize_positions(self.monitors)
        self._cancel_preview_timer()  # the full command below includes the previewed values
        try:
            cmd = xrandr.build_command(self.monitors, reference=self.original)
            previous = xrandr.build_command(self.original, reference=self.monitors) if self.original else None
        except Exception as e:  # noqa: BLE001 - never fail silently
            self.window.message(_("xrandr could not apply this layout"), f"{type(e).__name__}: {e}")
            return
        try:
            xrandr.run(cmd)
        except Exception as e:  # noqa: BLE001
            self.window.message(_("xrandr could not apply this layout"), str(e))
            self.reload()
            return
        if self._confirm_keep():
            self._remember(xrandr.build_command(self.monitors))  # only what differs from defaults
            self.previewed.clear()  # now applied for real
            self.reload()
            self.window.set_status(_("Display settings applied"))
        else:
            if previous:
                try:
                    xrandr.run(previous)
                    self.previewed.clear()  # `previous` restored the colours too
                except Exception as e:  # noqa: BLE001
                    self.window.message(_("Could not restore the previous layout"), str(e))
            self.reload()
            self.window.set_status(_("Display settings reverted"))

    def _confirm_keep(self):
        dlg = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                message_type=Gtk.MessageType.QUESTION,
                                text=_("Keep these display settings?"))
        dlg.add_buttons(_("Revert"), Gtk.ResponseType.CANCEL, _("Keep changes"), Gtk.ResponseType.OK)
        remaining = [REVERT_SECONDS]

        def countdown(n):
            return ngettext("The previous settings will be restored in {n} second.",
                            "The previous settings will be restored in {n} seconds.", n).format(n=n)

        def tick():
            remaining[0] -= 1
            if remaining[0] <= 0:
                dlg.response(Gtk.ResponseType.CANCEL)
                return False
            dlg.format_secondary_text(countdown(remaining[0]))
            return True

        dlg.format_secondary_text(countdown(REVERT_SECONDS))
        timer = GLib.timeout_add_seconds(1, tick)
        resp = dlg.run()
        if remaining[0] > 0:
            GLib.source_remove(timer)
        dlg.destroy()
        return resp == Gtk.ResponseType.OK

    def _remember(self, cmd):
        data = config.load()
        data["display"]["command"] = cmd
        config.save(data)
        sync_autostart(data)

    def _autostart_toggled(self, check):
        data = config.load()
        data["display"]["autostart"] = check.get_active()
        if check.get_active() and not data["display"]["command"] and self.monitors:
            data["display"]["command"] = xrandr.build_command(self.monitors)
        config.save(data)
        sync_autostart(data)


def sync_autostart(data=None):
    """The login entry is needed to restore the layout or to re-create custom modes."""
    data = data or config.load()
    disp = data["display"]
    write_autostart(disp["autostart"] or any(disp["custom_modes"].values()))


def write_autostart(enabled):
    path = autostart_file()
    if not enabled:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=XControl display layout\n"
                "Exec=xcontrol --apply-display\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n")


def restore_custom_modes(data=None):
    """Custom modes live only as long as the X server: re-create them."""
    data = data or config.load()
    failed = []
    for output, modes in data["display"]["custom_modes"].items():
        for d in modes:
            try:
                xrandr.add_custom_mode(output, modelines.Modeline.from_dict(d))
            except Exception as e:  # noqa: BLE001 - e.g. the output is gone
                failed.append(f"{output} {d.get('width')}x{d.get('height')}: {e}")
    return failed


def apply_saved_layout():
    """CLI entry point used at login (xcontrol --apply-display)."""
    if xrandr.session_warning():
        return 0
    output_names.migrate_saved()  # the X driver may have renamed the outputs
    data = config.load()
    for problem in restore_custom_modes(data):
        print(f"xcontrol: could not restore custom mode {problem}")
    cmd = data["display"]["command"]
    if not data["display"]["autostart"] or not cmd or cmd[0] != "xrandr":
        return 0
    try:
        xrandr.run(cmd)
    except Exception as e:  # noqa: BLE001
        print(f"xcontrol: could not restore layout ({shlex.join(cmd)}): {e}")
        return 1
    return 0

