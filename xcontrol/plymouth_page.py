"""System → Boot splash: Plymouth's theme (with pictures), the delay and scale, and the two
things outside XControl's reach that the splash needs (the mkinitcpio hook, `splash`)."""
import os
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from . import plymouth as P  # noqa: E402
from . import widgets  # noqa: E402
from .i18n import N_, _  # noqa: E402

THUMB_W, THUMB_H = 176, 110
SCALES = [("", N_("Automatic")), ("1", "1×"), ("2", "2×"), ("3", "3×"), ("4", "4×")]


def _dim(text):
    lbl = Gtk.Label(label=text, xalign=0, wrap=True)
    lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.get_style_context().add_class("dim-label")
    return lbl


def _heading(text):
    lbl = Gtk.Label(xalign=0)
    lbl.set_markup("<b>{}</b>".format(GLib.markup_escape_text(text)))
    return lbl


class BootSplashTab(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.busy = False
        self.selected = None
        self.shown = None      # what the tab was built from
        self.connect("map", lambda *_a: self.refresh())

    # ---------------------------------------------------------------- building
    def refresh(self, force=False):
        """Build the tab; on later visits only when something changed outside (so a theme picked
        but not applied yet stays picked when you come back)."""
        if self.busy:
            return
        state = (P.installed(), P.settings(), tuple(P.read_hooks()), P.cmdline(), tuple(P.themes()))
        if state == self.shown and not force:
            return
        self.shown = state
        for child in self.get_children():
            child.destroy()
        if not P.installed():
            self.pack_start(_heading(_("Plymouth isn't installed")), False, False, 0)
            self.pack_start(_dim(_("Plymouth draws a picture or an animation while the computer starts, instead "
                                   "of the kernel's messages. Install the plymouth package to choose its look "
                                   "here.")), False, False, 0)
            self.show_all()
            return
        self.cur = P.settings()
        # the theme in use, when the helper would accept it (so Apply can change just the delay
        # or scale even if that theme isn't listed, e.g. an unreadable .plymouth file)
        self.selected = (self.cur.theme if P.VALID_NAME.match(self.cur.theme or "")
                         and os.path.isdir(os.path.join(P.THEMES, self.cur.theme)) else None)
        self._setup_checks()
        self._themes()
        self._options()
        self.show_all()
        widgets.protect(self)
        self._picked()

    def _check_row(self, ok, title, detail=None, line=None):
        row = Gtk.Box(spacing=10)
        icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic" if ok else "dialog-warning-symbolic",
                                            Gtk.IconSize.LARGE_TOOLBAR)
        icon.set_valign(Gtk.Align.START)
        row.pack_start(icon, False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        t = Gtk.Label(label=title, xalign=0, wrap=True)
        t.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        col.pack_start(t, False, False, 0)
        if detail:
            col.pack_start(_dim(detail), False, False, 0)
        if line:
            lb = Gtk.Box(spacing=6)
            code = Gtk.Label(label=line, xalign=0, selectable=True, wrap=True)
            code.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            code.get_style_context().add_class("monospace")
            code.set_can_focus(False)
            lb.pack_start(code, True, True, 0)
            copy = Gtk.Button.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON)
            copy.set_tooltip_text(_("Copy"))
            copy.set_valign(Gtk.Align.START)
            copy.connect("clicked", lambda *_a: self._copy(line))
            lb.pack_start(copy, False, False, 0)
            col.pack_start(lb, False, False, 0)
        row.pack_start(col, True, True, 0)
        return row

    def _setup_checks(self):
        self.pack_start(_heading(_("Showing it at boot")), False, False, 0)
        texts = P.read_hooks()
        hk = P.hooks(texts)
        state = P.hook_state(hk)
        if state == "ok":
            row = self._check_row(True, _("The plymouth hook is in /etc/mkinitcpio.conf."))
        elif state is None:
            row = self._check_row(False, _("XControl can't read mkinitcpio's HOOKS (another initramfs tool?). "
                                           "Make sure Plymouth is part of your initramfs."))
        else:
            what = {"missing": _("Add plymouth to HOOKS in /etc/mkinitcpio.conf, or the splash never starts."),
                    "early": _("In /etc/mkinitcpio.conf, plymouth comes too early in HOOKS: it has to come after "
                               "systemd (or udev)."),
                    "late": _("In /etc/mkinitcpio.conf, plymouth comes after the encryption hook: move it before "
                              "encrypt / sd-encrypt, so it can ask for the password.")}[state]
            row = self._check_row(False, what, _("Put it after kms and before any encryption hook. Your line "
                                                 "would read (edit the file as root; XControl rebuilds the "
                                                 "initramfs when you apply a theme):"),
                                  P.format_hooks(P.suggested_hooks(hk)))
        self.pack_start(row, False, False, 0)

        line = P.cmdline()
        if P.has_splash(line):
            row = self._check_row(True, _("splash is on the kernel command line."))
        else:
            where = {
                "systemd-boot": _("With systemd-boot, add splash (and quiet, to hide the kernel's messages) to the "
                                  "options line of your entry in /boot/loader/entries/ (for example arch.conf). "
                                  "It applies at the next boot. The whole line would read:"),
                "uki": _("Your kernel options are in /etc/kernel/cmdline (a unified kernel image): add splash and "
                         "quiet there, then rebuild the image. It would read:"),
                "grub": _("With GRUB, add splash and quiet to GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub, "
                          "then run grub-mkconfig -o /boot/grub/grub.cfg. The options would read:"),
            }.get(P.bootloader(), _("Add splash and quiet to the kernel options in your boot loader's "
                                    "configuration. They would read:"))
            row = self._check_row(False, _("splash isn't on the kernel command line, so the splash doesn't show."),
                                  where, "options " + P.suggested_cmdline(line) if P.bootloader() == "systemd-boot"
                                  else P.suggested_cmdline(line))
        self.pack_start(row, False, False, 0)

    def _themes(self):
        self.pack_start(_heading(_("Theme")), False, False, 0)
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, homogeneous=True,
                                min_children_per_line=1, max_children_per_line=6,
                                column_spacing=10, row_spacing=10, valign=Gtk.Align.START)
        self.flow.connect("child-activated", self._picked)
        self.flow.connect("selected-children-changed", self._picked)
        self.children = {}
        for th in P.themes():
            child = Gtk.FlowBoxChild()
            child.theme = th.name
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=4)
            box.pack_start(self._thumb(th), False, False, 0)
            name = Gtk.Label(xalign=0.5, ellipsize=Pango.EllipsizeMode.END, max_width_chars=22)
            current = _("in use") if th.name == self.cur.theme else ""
            name.set_markup("<b>{}</b>{}".format(GLib.markup_escape_text(th.title),
                                                 f" <small>({GLib.markup_escape_text(current)})</small>"
                                                 if current else ""))
            box.pack_start(name, False, False, 0)
            tip = th.description or th.title
            if th.name == "bgrt":
                tip += "\n" + _("Shows your PC maker's logo from the firmware, like Windows does.")
            elif th.name in P.TEXT_THEMES:
                tip += "\n" + _("Text mode: drawn with the console's characters.")
            child.set_tooltip_text(tip)
            child.add(box)
            self.flow.add(child)
            self.children[th.name] = child
        self.pack_start(self.flow, False, False, 0)
        if self.cur.theme in self.children:
            self.flow.select_child(self.children[self.cur.theme])
        self.pack_start(_dim(_("Pictures of the built-in themes are XControl's; on some themes your "
                               "distribution's logo appears too. Themes you add show the picture they come "
                               "with, if any.")), False, False, 0)

    def _thumb(self, th):
        path = P.picture(th.name)
        pb = None
        if path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, THUMB_W, THUMB_H, True)
            except GLib.Error:
                pb = None
        if pb is None:
            frame = Gtk.Frame(width_request=THUMB_W, height_request=THUMB_H)
            frame.add(Gtk.Label(label=_("No picture")))
            return frame
        img = Gtk.Image.new_from_pixbuf(pb)
        img.set_size_request(THUMB_W, THUMB_H)
        return img

    def _options(self):
        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        lbl = Gtk.Label(label=_("Wait before showing it"), xalign=0)
        grid.attach(lbl, 0, 0, 1, 1)
        self.delay = Gtk.SpinButton.new_with_range(0, 30, 0.5)
        self.delay.set_digits(1)
        try:
            self.delay.set_value(float(self.cur.delay or 0))
        except ValueError:
            self.delay.set_value(0)
        box = Gtk.Box(spacing=6, halign=Gtk.Align.START)
        box.pack_start(self.delay, False, False, 0)
        box.pack_start(Gtk.Label(label=_("seconds")), False, False, 0)
        grid.attach(box, 1, 0, 1, 1)
        grid.attach(_dim(_("A fast boot then never flashes the splash for a moment.")), 1, 1, 1, 1)
        grid.attach(Gtk.Label(label=_("Scale"), xalign=0), 0, 2, 1, 1)
        self.scale = Gtk.ComboBoxText(halign=Gtk.Align.START)
        for sid, label in SCALES:
            self.scale.append(sid, _(label) if sid == "" else label)
        self.scale.set_active_id(self.cur.scale if self.cur.scale in dict(SCALES) else "")
        grid.attach(self.scale, 1, 2, 1, 1)
        grid.attach(_dim(_("For high-DPI screens, when the automatic choice is too small.")), 1, 3, 1, 1)
        self.pack_start(grid, False, False, 0)

        bb = Gtk.Box(spacing=10)
        self.apply_btn = Gtk.Button(label=_("Apply"))
        self.apply_btn.get_style_context().add_class("suggested-action")
        self.apply_btn.connect("clicked", self._apply)
        bb.pack_start(self.apply_btn, False, False, 0)
        self.preview_btn = Gtk.Button(label=_("Preview"))
        self.preview_btn.set_tooltip_text(_("Plays the selected theme for a few seconds in a window "
                                            "(asks for your password: Plymouth only runs as root)."))
        self.preview_btn.connect("clicked", self._preview)
        bb.pack_start(self.preview_btn, False, False, 0)
        self.state = _dim(_("Applying rebuilds the initramfs, which takes a minute."))
        bb.pack_start(self.state, True, True, 0)
        self.pack_start(bb, False, False, 0)

    # ---------------------------------------------------------------- actions
    def _picked(self, *_a):
        sel = self.flow.get_selected_children()
        if sel:
            self.selected = sel[0].theme
        if hasattr(self, "preview_btn"):
            self.preview_btn.set_sensitive(bool(self.selected) and P.can_preview(self.selected) and not self.busy)
            self.apply_btn.set_sensitive(bool(self.selected) and not self.busy)

    def _preview(self, *_a):
        if not self.selected or self.busy:
            return
        self.busy = True
        self._picked()
        self.state.set_text(_("Playing the preview…"))
        theme = self.selected

        def work():
            ok, out = P.preview(theme)
            GLib.idle_add(self._previewed, ok, out)
        threading.Thread(target=work, daemon=True).start()

    def _previewed(self, ok, out):
        self.busy = False
        self._picked()
        self.state.set_text("" if ok else _("No preview."))
        if not ok and out is not None:     # (None: the password prompt was cancelled)
            self.window.message(_("Could not play the preview"), out[-2000:] or _("No details."))
        return False

    def _copy(self, text):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self.window.set_status(_("Copied"))

    def _apply(self, *_a):
        if not self.selected or self.busy:
            return
        delay = self.delay.get_value()
        delay = "" if delay == 0 and not self.cur.delay else (f"{delay:g}")
        scale = self.scale.get_active_id() or ""
        self.busy = True
        self._picked()
        self.state.set_text(_("Rebuilding the initramfs…"))
        theme = self.selected

        def work():
            ok, out = P.apply(theme, delay, scale)
            GLib.idle_add(self._done, ok, out)
        threading.Thread(target=work, daemon=True).start()

    def _done(self, ok, out):
        self.busy = False
        self._picked()
        if ok:
            self.window.set_status(_("Boot splash set; it shows at the next boot"))
            self.refresh(force=True)
        else:
            self.state.set_text(_("Not applied."))
            if out is not None:   # (None: the password prompt was cancelled)
                self.window.message(_("Could not set the boot splash"), out[-2000:] or _("No details."))
        return False
