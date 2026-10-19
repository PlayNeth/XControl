"""Change a kernel module's parameters: saved to /etc/modprobe.d/xcontrol-MODULE.conf
through the root helper (pkexec), optionally applied live and to the initramfs."""
import os
import shutil
import subprocess
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import kmods, widgets  # noqa: E402
from .i18n import _  # noqa: E402


class ModuleParamsDialog(Gtk.Dialog):
    def __init__(self, parent, details):
        super().__init__(title=_("Parameters for {module}").format(module=details.name), transient_for=parent,
                         modal=True)
        self.d = details
        self.name = details.name
        self.changed = False
        self.entries = {}
        self.ours = kmods.our_values(self.name)
        self.others = kmods.other_values(self.name)
        self.cmdline = kmods.cmdline_values(self.name)
        area = self.get_display().get_monitor_at_window(parent.get_window()).get_workarea() \
            if parent.get_window() else None
        self.set_default_size(760, min(720, area.height - 80) if area else 640)

        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)
        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_max_width_chars(90)
        intro.set_markup(_("Values are saved in <tt>{file}</tt> and used every time the module loads. Leave a "
                           "field empty to use the module's default.").format(
                               file=GLib.markup_escape_text(kmods.our_file(self.name))))
        box.pack_start(intro, False, False, 0)
        if self.cmdline:
            warn = Gtk.Label(xalign=0, wrap=True)
            warn.set_max_width_chars(90)
            items = " ".join(f"{self.name}.{k}={v}" for k, v in sorted(self.cmdline.items()))
            warn.set_markup("⚠ " + GLib.markup_escape_text(
                _("The kernel command line sets {items}. Those win over anything saved here.").format(items=items)))
            box.pack_start(warn, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        r = 0
        for prm in details.params:
            name = Gtk.Label(label=prm.name, xalign=0)
            name.get_style_context().add_class("monospace")
            entry = Gtk.Entry(hexpand=True, placeholder_text=_("default"))
            entry.set_text(self.ours.get(prm.name, ""))
            entry.connect("changed", self._validate)
            entry.prm = prm
            self.entries[prm.name] = entry
            now = _("(only readable by root)") if prm.value is kmods.UNREADABLE else prm.value
            now_lbl = Gtk.Label(label=_("now: {value}").format(value=now or "—"), xalign=0)
            now_lbl.get_style_context().add_class("dim-label")
            now_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            now_lbl.set_max_width_chars(22)
            grid.attach(name, 0, r, 1, 1)
            grid.attach(entry, 1, r, 1, 1)
            grid.attach(now_lbl, 2, r, 1, 1)
            notes = []
            if prm.description or prm.type:
                notes.append(" ".join(x for x in (prm.description, f"({prm.type})" if prm.type else "") if x))
            if prm.name in self.others:
                value, path = self.others[prm.name]
                notes.append(_("Also set to {value} in {file}.").format(value=value, file=path))
            if prm.name in self.cmdline:
                notes.append(_("Set to {value} on the kernel command line, which wins.").format(
                    value=self.cmdline[prm.name]))
            if not kmods.live_writable(self.name, prm.name):
                notes.append(_("Takes effect when the module loads (reboot)."))
            note = Gtk.Label(label="  ".join(notes), xalign=0, wrap=True)
            note.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            note.set_max_width_chars(80)
            note.get_style_context().add_class("dim-label")
            note.set_margin_bottom(6)
            grid.attach(note, 1, r + 1, 2, 1)
            r += 2
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sw.add(grid)
        box.pack_start(sw, True, True, 0)

        any_live = any(kmods.live_writable(self.name, prm.name) for prm in details.params)
        self.live = Gtk.CheckButton(label=_("Also change it now, where the kernel allows it while running"))
        self.live.set_active(any_live)
        self.live.set_sensitive(any_live)
        box.pack_start(self.live, False, False, 0)
        tool = kmods.initramfs_tool()
        early = kmods.loads_early(self.name)
        self.initramfs = Gtk.CheckButton(label=_("Rebuild the boot image (initramfs) with {tool}").format(
            tool=tool or "—"))
        self.initramfs.set_active(bool(tool) and early)
        self.initramfs.set_sensitive(bool(tool))
        box.pack_start(self.initramfs, False, False, 0)
        if early:
            hint = Gtk.Label(label=_("{module} loads early in boot, from the initramfs, which holds its own copy "
                                     "of modprobe.d: rebuild it or the change won't reach the module. That takes "
                                     "a minute.").format(module=self.name), xalign=0, wrap=True)
            hint.set_max_width_chars(90)
            hint.get_style_context().add_class("dim-label")
            box.pack_start(hint, False, False, 0)

        status = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        status.pack_start(self.spinner, False, False, 0)
        self.result = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.result.set_max_width_chars(90)
        self.result.set_can_focus(False)
        status.pack_start(self.result, True, True, 0)
        box.pack_start(status, False, False, 0)

        self.remove_btn = self.add_button(_("Remove XControl's settings"), 1)
        self.remove_btn.set_visible(bool(self.ours))
        self.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        self.save_btn = self.add_button(_("Save"), Gtk.ResponseType.OK)
        self.save_btn.get_style_context().add_class("suggested-action")
        self.connect("response", self._response)
        if not (shutil.which("pkexec") and os.path.exists(kmods.HELPER)):
            self.save_btn.set_sensitive(False)
            self.remove_btn.set_sensitive(False)
            self.result.set_text(_("pkexec (polkit) is needed to change module parameters."))
        self.show_all()
        self.remove_btn.set_visible(bool(self.ours))
        widgets.protect(self)
        self._validate()

    def _values(self):
        return {name: e.get_text().strip() for name, e in self.entries.items()}

    def _validate(self, *_args):
        ok = True
        for e in self.entries.values():
            problem = kmods.check_value(e.get_text().strip(), e.prm.type)
            ctx = e.get_style_context()
            if problem:
                ctx.add_class("error")
                e.set_tooltip_text(_("Only letters, digits and . , : + / - _ are allowed, without spaces.")
                                   if problem == "chars" else
                                   _("Not a valid {type} value.").format(type=e.prm.type))
                ok = False
            else:
                ctx.remove_class("error")
                e.set_tooltip_text(None)
        self.save_btn.set_sensitive(ok and bool(shutil.which("pkexec")) and os.path.exists(kmods.HELPER))
        return ok

    def _response(self, _dlg, response):
        if response == Gtk.ResponseType.OK:
            if self._validate():
                self._run(self._values())
            self.stop_emission_by_name("response")
        elif response == 1:
            self._run({})
            self.stop_emission_by_name("response")

    def _run(self, values):
        live = self.live.get_active() and bool(values)
        args = kmods.helper_args(self.name, values, live=live, initramfs=self.initramfs.get_active())
        for w in (self.save_btn, self.remove_btn):
            w.set_sensitive(False)
        self.spinner.start()
        self.result.set_text(_("Rebuilding the initramfs, this takes a minute…") if self.initramfs.get_active()
                             else _("Saving…"))

        def work():
            try:
                out = subprocess.run(["pkexec", kmods.HELPER, *args], capture_output=True, text=True, timeout=900)
                if out.returncode in (126, 127) and not out.stderr.strip():
                    ok, text = False, _("Authorization was cancelled.")
                else:
                    ok, text = out.returncode == 0, (out.stdout + out.stderr).strip()
            except (OSError, subprocess.SubprocessError) as e:
                ok, text = False, str(e)
            GLib.idle_add(self._done, ok, text, bool(values))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, ok, text, saved):
        self.spinner.stop()
        self._validate()
        self.remove_btn.set_sensitive(True)
        lines = [line for line in text.splitlines() if line.strip()]
        if ok:
            self.changed = True
            self.ours = kmods.our_values(self.name)
            self.remove_btn.set_visible(bool(self.ours))
            head = _("Saved. It applies the next time the module loads (usually: after a reboot).") if saved \
                else _("XControl's settings for this module were removed.")
            live = [line[6:] for line in lines if line.startswith("live: ")]
            self.result.set_text("\n".join([head] + live))
        else:
            self.result.set_text(_("That didn't work: {error}").format(error=lines[-1] if lines else "?"))
        return False
