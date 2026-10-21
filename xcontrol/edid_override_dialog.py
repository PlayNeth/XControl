"""System-wide mode list: build an EDID override with only the chosen modes,
test it until reboot, or install it for every boot."""
import os
import shutil
import subprocess
import tempfile

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import edid, edid_override, monitor_info, widgets, xrandr  # noqa: E402
from . import edid_override_status as status  # noqa: E402
from .i18n import _, num  # noqa: E402
from .paths import LIBDIR  # noqa: E402
from .resolutions_dialog import SHORT_NAMES, standard_of  # noqa: E402

HELPER = os.path.join(LIBDIR, "xcontrol-edid-helper")


class EdidOverrideDialog(Gtk.Dialog):
    def __init__(self, window, output):
        super().__init__(title=_("System-wide mode list for {output}").format(output=output),
                         transient_for=window, modal=True)
        self.main_window = window
        self.output = output
        self.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        self.set_default_size(660, -1)

        self.record = next((r for r in monitor_info.collect() if r.x_name == output), None)
        self.original = self.record.raw if self.record and self.record.raw else None
        self.modes = self._collect_modes()

        area = self.get_content_area()
        outer = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        outer.set_propagate_natural_height(True)
        outer.set_max_content_height(max(320, _work_area_height(window) - 140))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, border_width=16)
        outer.add(box)
        area.pack_start(outer, True, True, 0)

        box.pack_start(self._hint(_(
            "Builds a corrected EDID for this display that lists only the modes you tick. The kernel then "
            "reports exactly these modes to X, games and every other program. The display's name, serial "
            "number and colour data are kept.")), False, False, 0)

        # ---- is an override in use?
        self.status_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.status_label.set_max_width_chars(72)
        self.status_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        box.pack_start(self.status_label, False, False, 0)

        # ---- mode list
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(260)
        scroll.set_min_content_height(190)  # never squeezed below ~5 rows; the dialog scrolls instead
        scroll.add(self.listbox)
        box.pack_start(scroll, False, False, 0)
        self.checks = []
        for m in self.modes:
            row = Gtk.Box(spacing=8, margin=6)
            check = Gtk.CheckButton()
            check.set_active(True)
            check.connect("toggled", self._changed)
            label = Gtk.Label(xalign=0)
            title = f"{m.width} × {m.height} @ {num(m.refresh, 2)} Hz"
            std = standard_of(m.source_name)
            origin = (_("custom, {standard}").format(standard=_(SHORT_NAMES[std])) if std
                      else _("from the display / driver"))
            extra = "  " + _("(current)") if m.current else ""
            label.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>  "
                             f"<small>{GLib.markup_escape_text(origin + extra)}</small>")
            check.add(label)
            row.pack_start(check, True, True, 0)
            self.listbox.add(row)
            self.checks.append((check, m))

        # ---- preferred mode
        pref_row = Gtk.Box(spacing=8)
        pref_row.pack_start(Gtk.Label(label=_("Native (preferred) mode"), xalign=0), False, False, 0)
        self.pref_combo = Gtk.ComboBoxText(hexpand=True)
        pref_row.pack_start(self.pref_combo, True, True, 0)
        box.pack_start(pref_row, False, False, 0)

        self.summary = self._hint("")
        box.pack_start(self.summary, False, False, 0)

        # ---- actions
        actions = Gtk.Box(spacing=6)
        self.save_btn = Gtk.Button(label=_("Save EDID file…"))
        self.save_btn.connect("clicked", self._save_file)
        self.test_btn = Gtk.Button(label=_("Test now"))
        self.test_btn.set_tooltip_text(_("Load it into the kernel until the next reboot (asks for your password)"))
        self.test_btn.connect("clicked", self._test)
        self.undo_btn = Gtk.Button(label=_("Undo test"))
        self.undo_btn.connect("clicked", self._undo)
        self.install_btn = Gtk.Button(label=_("Make permanent…"))
        self.install_btn.get_style_context().add_class("suggested-action")
        self.install_btn.connect("clicked", self._install)
        for b in (self.save_btn, self.test_btn, self.undo_btn):
            actions.pack_start(b, False, False, 0)
        actions.pack_end(self.install_btn, False, False, 0)
        box.pack_start(actions, False, False, 0)

        self.result = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.result.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        box.pack_start(self.result, False, False, 0)

        can_root = bool(shutil.which("pkexec")) and os.path.exists(HELPER)
        has_conn = bool(self.record and self.record.drm_name and self.record.card)
        for b in (self.test_btn, self.undo_btn, self.install_btn):
            b.set_sensitive(can_root and has_conn)
        if not has_conn:
            self._set_result(_("Could not match {output} to a kernel connector, so the override can only be "
                               "saved as a file.").format(output=output))
        elif not can_root:
            self._set_result(_("pkexec (polkit) is needed to test or install the override; you can still "
                               "save the file."))
        self.show_all()
        widgets.protect(self)
        self._changed()
        self._update_status()

    # ---- data
    def _collect_modes(self):
        try:
            names = next((m.modes for m in xrandr.query() if m.name == self.output), {})
            verbose = xrandr.query_verbose().get(self.output, {})
        except Exception:  # noqa: BLE001
            return []
        modes = edid_override.modes_from_verbose(verbose, names)
        seen, out = set(), []
        for m in sorted(modes, key=lambda m: (-m.width * m.height, -m.refresh)):
            k = edid_override.timing_key(m)
            if k not in seen:
                seen.add(k)
                out.append(m)
        return out

    def _chosen(self):
        return [m for check, m in self.checks if check.get_active()]

    def _build(self):
        chosen = self._chosen()
        idx = self.pref_combo.get_active()
        preferred = chosen[idx] if 0 <= idx < len(chosen) else None
        return edid_override.build(self.original, chosen, preferred)

    # ---- ui
    @staticmethod
    def _hint(text):
        lbl = Gtk.Label(label=text, xalign=0, wrap=True)
        lbl.set_max_width_chars(72)
        lbl.get_style_context().add_class("dim-label")
        return lbl

    def _set_result(self, text, error=False):
        if error:
            self.result.set_markup(f"<span foreground='#c01c28'>{GLib.markup_escape_text(text)}</span>")
        else:
            self.result.set_text(text)

    def _changed(self, *_args):
        chosen = self._chosen()
        prev = None
        idx = self.pref_combo.get_active()
        if 0 <= idx < self.pref_combo.get_model().iter_n_children(None):
            prev = self.pref_combo.get_active_text()
        self.pref_combo.remove_all()
        current = 0
        for n, m in enumerate(chosen):
            text = f"{m.width} × {m.height} @ {num(m.refresh, 2)} Hz"
            self.pref_combo.append_text(text)
            if (prev and text == prev) or (not prev and (m.preferred or m.current)):
                current = n
        if chosen:
            self.pref_combo.set_active(current)
        try:
            data = self._build()
            info = edid.parse(data)
            self.summary.set_text(_("{count} modes · {blocks} EDID blocks · refresh range {low}–{high} Hz").format(
                count=len(chosen), blocks=len(data) // 128, low=info.vrange[0], high=info.vrange[1]))
            ok = True
        except edid_override.OverrideError as e:
            self.summary.set_markup(f"<span foreground='#c01c28'>{GLib.markup_escape_text(str(e))}</span>")
            ok = False
        self.save_btn.set_sensitive(ok)
        for b in (self.test_btn, self.install_btn):
            b.set_sensitive(ok and bool(shutil.which("pkexec")) and os.path.exists(HELPER)
                            and bool(self.record and self.record.card))

    def _update_status(self, current=None):
        conn = self._connector()
        if not conn:
            self.status_label.hide()
            return
        if current is None:
            current = next((raw for _card, name, raw in edid.read_sysfs_full() if name == conn), b"")
        st = status.check(conn, current)
        param = f"drm.edid_firmware={st.expected}"
        ok = st.state == status.ACTIVE_PERMANENT
        text = {
            status.ACTIVE_PERMANENT: _("The kernel is using the installed override, and it loads at every boot."),
            status.ACTIVE_TEST_ONLY: _("The kernel is using the installed override, but only until the next reboot: "
                                       "the kernel parameter {param} is missing."),
            status.NOT_INSTALLED: _("No permanent override is installed for {connector}. “Test now” lasts only "
                                    "until the next reboot."),
            status.NO_PARAMETER: _("An override is installed, but the kernel isn't using it because the kernel "
                                   "parameter {param} is missing. Add it and reboot."),
            status.WRONG_PARAMETER: _("An override is installed, but the kernel parameter is {current} instead of "
                                      "{param}. Fix it and reboot."),
            status.NOT_IN_INITRAMFS: _("The override is installed and the kernel parameter is set, but the file is "
                                       "not in the initramfs, so the graphics driver can't read it at boot. Add "
                                       "FILES=({file}) to /etc/mkinitcpio.conf, run “sudo mkinitcpio -P” and reboot."),
            status.STALE_INITRAMFS: _("The override file changed after the initramfs was built, so the old one is "
                                      "still loaded at boot. Run “sudo mkinitcpio -P” and reboot."),
            status.NOT_LOADED: _("The override is installed and set up, but the kernel isn't using it. If you "
                                 "haven't rebooted since, reboot. Otherwise “sudo dmesg | grep -i edid” shows why."),
        }[st.state].format(param=param, connector=conn, file=st.file,
                           current=f"drm.edid_firmware={st.parameter}")
        if ok:
            self.status_label.set_text("✓ " + text)
        elif st.state == status.NOT_INSTALLED:
            self.status_label.set_text(text)
        else:
            self.status_label.set_markup(f"<span foreground='#c64600'>{GLib.markup_escape_text(text)}</span>")
        self.status_label.show()

    # ---- actions
    def _write_temp(self):
        data = self._build()
        fd, path = tempfile.mkstemp(prefix="xcontrol-edid-", suffix=".bin",
                                    dir=os.environ.get("XDG_RUNTIME_DIR") or None)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return path

    def _run_helper(self, *args):
        try:
            out = subprocess.run(["pkexec", HELPER, *args], capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        if out.returncode in (126, 127) and not out.stderr.strip():
            return False, _("Authorization was cancelled.")
        return out.returncode == 0, (out.stdout + out.stderr).strip()

    def _save_file(self, *_args):
        dlg = Gtk.FileChooserDialog(title=_("Save EDID"), parent=self, action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Save"), Gtk.ResponseType.OK)
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_name(f"xcontrol-{self._connector() or self.output}.bin")
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(self._build())
                self._set_result(_("Saved {path}").format(path=path))
            except (OSError, edid_override.OverrideError) as e:
                self._set_result(str(e), error=True)

    def _connector(self):
        return self.record.drm_name if self.record else ""

    def _test(self, *_args):
        try:
            path = self._write_temp()
        except edid_override.OverrideError as e:
            self._set_result(str(e), error=True)
            return
        ok, msg = self._run_helper("test", self.record.card, self._connector(), path)
        os.unlink(path)
        self._update_status()
        if ok:
            self._set_result(_("Loaded until reboot. The display was re-detected; check the Displays page "
                               "or run xrandr. Use “Undo test” to go back."))
        else:
            self._set_result(msg, error=True)

    def _undo(self, *_args):
        ok, msg = self._run_helper("reset", self.record.card, self._connector())
        self._set_result(_("The display's own EDID is back.") if ok else msg, error=not ok)
        self._update_status()

    def _install(self, *_args):
        conn = self._connector()
        name = f"xcontrol-{conn}.bin"
        try:
            path = self._write_temp()
        except edid_override.OverrideError as e:
            self._set_result(str(e), error=True)
            return
        ok, msg = self._run_helper("install", name, path)
        os.unlink(path)
        if not ok:
            self._set_result(msg, error=True)
            return
        param = f"drm.edid_firmware={conn}:edid/{name}"
        fw = f"/usr/lib/firmware/edid/{name}"
        steps = _(
            "Installed {file}.\n\n"
            "To load it at every boot, add this kernel parameter:\n"
            "    {param}\n\n"
            "GRUB: add it to GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub, then run\n"
            "    sudo grub-mkconfig -o /boot/grub/grub.cfg\n"
            "systemd-boot: add it to the “options” line of your entry in /boot/loader/entries/.\n\n"
            "Arch loads the graphics driver early (the kms hook), so also put the file in the initramfs: add\n"
            "    FILES=({file})\n"
            "to /etc/mkinitcpio.conf, then run\n"
            "    sudo mkinitcpio -P\n\n"
            "Reboot afterwards. If you had already set this up, the initramfs still holds the old file: "
            "run “sudo mkinitcpio -P” and reboot.\n\n"
            "To undo, remove the parameter and the FILES entry, rebuild, and reboot."
        ).format(file=fw, param=param)
        self.result.set_markup(GLib.markup_escape_text(steps).replace(
            GLib.markup_escape_text(param), f"<b><tt>{GLib.markup_escape_text(param)}</tt></b>"))
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(param, -1)
        self._update_status()
        self.main_window.set_status(_("Kernel parameter copied"))


def _work_area_height(window):
    try:
        display = window.get_display()
        mon = display.get_monitor_at_window(window.get_window()) or display.get_primary_monitor()
        return mon.get_workarea().height
    except Exception:  # noqa: BLE001
        return 768
