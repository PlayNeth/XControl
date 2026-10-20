"""The Users page: accounts, full names, login names, passwords, administrator rights,
groups, login shell and picture."""
import os
import re
import tempfile
import threading
import unicodedata

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from . import users as U, widgets  # noqa: E402
from .i18n import N_, _  # noqa: E402

GROUP_LABELS = {
    "audio": N_("Use sound devices directly (rarely needed with PipeWire)"),
    "video": N_("Use video devices directly (webcams, some brightness controls)"),
    "input": N_("Read input devices directly (needed by sc-controller and some gamepad tools)"),
    "storage": N_("Mount removable drives"),
    "optical": N_("Use CD/DVD drives"),
    "scanner": N_("Use scanners"),
    "lp": N_("Manage printers"),
    "games": N_("Games that keep shared high scores"),
    "network": N_("Change network settings"),
    "rfkill": N_("Turn Wi-Fi and Bluetooth radios on and off"),
    "uucp": N_("Use serial ports (Arduino, modems, consoles)"),
    "kvm": N_("Use hardware virtualization directly"),
    "libvirt": N_("Manage virtual machines (libvirt)"),
    "docker": N_("Use Docker (gives root-equivalent access)"),
    "wireshark": N_("Capture network traffic (Wireshark)"),
}
STRENGTH = {0: "", 1: N_("Weak: use at least 8 characters"), 2: N_("Fair"), 3: N_("Good")}
ERRORS = {"chars": N_("Only lowercase letters, digits, - and _ (starting with a letter)."),
          "long": N_("At most 32 characters.")}


def _dim(text):
    lbl = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
    lbl.set_can_focus(False)
    lbl.set_max_width_chars(70)
    lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.get_style_context().add_class("dim-label")
    return lbl


def _avatar(user, size):
    path = U.picture_path(user)
    if path:
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
            return Gtk.Image.new_from_pixbuf(pb)
        except GLib.Error:
            pass
    img = Gtk.Image.new_from_icon_name("avatar-default", Gtk.IconSize.DIALOG)
    img.set_pixel_size(size)
    return img


def suggest_login(full_name):
    """'Ana Lúcia Mendes' -> 'ana'."""
    first = (full_name.strip().split() or [""])[0]
    ascii_ = unicodedata.normalize("NFKD", first).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[^a-z0-9_-]", "", ascii_)
    return name if name and name[0].isalpha() else ""


class PasswordFields(Gtk.Grid):
    """New password + confirmation, with a strength bar; `valid()` and `password()`."""

    def __init__(self, on_change):
        super().__init__(column_spacing=12, row_spacing=8)
        self.on_change = on_change
        self.pw = self._entry()
        self.again = self._entry()
        self.bar = Gtk.LevelBar(min_value=0, max_value=3, hexpand=True)
        self.bar.set_mode(Gtk.LevelBarMode.DISCRETE)
        self.note = Gtk.Label(xalign=0)
        self.note.get_style_context().add_class("dim-label")
        self.attach(Gtk.Label(label=_("New password"), xalign=0), 0, 0, 1, 1)
        self.attach(self.pw, 1, 0, 1, 1)
        self.attach(self.bar, 1, 1, 1, 1)
        self.attach(Gtk.Label(label=_("Repeat it"), xalign=0), 0, 2, 1, 1)
        self.attach(self.again, 1, 2, 1, 1)
        self.attach(self.note, 1, 3, 1, 1)
        self._changed()

    def _entry(self):
        e = Gtk.Entry(visibility=False, hexpand=True, input_purpose=Gtk.InputPurpose.PASSWORD)
        e.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
        e.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, _("Show or hide"))
        e.connect("icon-press", lambda w, *_a: self._toggle())
        e.connect("changed", self._changed)
        return e

    def _toggle(self):
        show = not self.pw.get_visibility()
        for e in (self.pw, self.again):
            e.set_visibility(show)

    def _changed(self, *_a):
        pw = self.pw.get_text()
        level = U.strength(pw)
        self.bar.set_value(level)
        if "\n" in pw:
            note = _("No line breaks.")
        elif self.again.get_text() and self.again.get_text() != pw:
            note = _("The two passwords are different.")
        else:
            note = _(STRENGTH[level]) if level else ""
        self.note.set_text(note)
        self.on_change()

    def valid(self):
        pw = self.pw.get_text()
        return bool(pw) and "\n" not in pw and pw == self.again.get_text()

    def password(self):
        return self.pw.get_text()


class UsersPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(spacing=16, border_width=18)
        self.window = window
        self.users = []
        self.selected = None
        self.busy = False

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        frame = Gtk.Frame()
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.connect("row-selected", self._row_selected)
        frame.add(self.list)
        left.pack_start(frame, False, False, 0)
        buttons = Gtk.Box(spacing=6)
        self.add_btn = Gtk.Button(label=_("Add user…"))
        self.add_btn.connect("clicked", self._add_user)
        buttons.pack_start(self.add_btn, False, False, 0)
        self.remove_btn = Gtk.Button(label=_("Remove…"))
        self.remove_btn.connect("clicked", self._remove_user)
        buttons.pack_start(self.remove_btn, False, False, 0)
        left.pack_start(buttons, False, False, 0)
        self.spinner = Gtk.Spinner(halign=Gtk.Align.START)
        left.pack_start(self.spinner, False, False, 0)
        left.set_size_request(240, -1)
        self.pack_start(left, False, False, 0)

        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, hexpand=True)
        self.pack_start(self.details, True, True, 0)
        self.reload()

    # ---------------------------------------------------------------- list
    def reload(self, keep=None):
        keep = keep or (self.selected.name if self.selected else None)
        for row in self.list.get_children():
            row.destroy()
        self.users = U.list_users()
        me_first = sorted(self.users, key=lambda u: (not u.me, u.uid))
        target = None
        for u in me_first:
            row = Gtk.ListBoxRow()
            row.user = u
            box = Gtk.Box(spacing=10, border_width=8)
            box.pack_start(_avatar(u, 40), False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            title = Gtk.Label(xalign=0)
            title.set_markup(f"<b>{GLib.markup_escape_text(u.display())}</b>")
            title.set_ellipsize(Pango.EllipsizeMode.END)
            text.pack_start(title, False, False, 0)
            bits = [u.name, _("Administrator") if u.admin else _("Standard")]
            if u.me:
                bits.append(_("you"))
            sub = Gtk.Label(label=" · ".join(bits), xalign=0)
            sub.get_style_context().add_class("dim-label")
            text.pack_start(sub, False, False, 0)
            box.pack_start(text, True, True, 0)
            row.add(box)
            self.list.add(row)
            if u.name == keep or (target is None and keep is None and u.me):
                target = row
        self.list.show_all()
        self.list.select_row(target or self.list.get_row_at_index(0))
        if not self.users:
            self._show(None)

    def _row_selected(self, _lb, row):
        self.selected = row.user if row else None
        self._show(self.selected)

    # ---------------------------------------------------------------- details
    def _show(self, u):
        for child in self.details.get_children():
            child.destroy()
        can = U.can_change()
        self.remove_btn.set_sensitive(bool(u) and not u.me and can)
        self.add_btn.set_sensitive(can)
        if not u:
            self.details.pack_start(_dim(_("No regular user accounts were found.")), False, False, 0)
            self.details.show_all()
            return
        if not can:
            self.details.pack_start(_dim(_("pkexec (polkit) is needed to change accounts; only your own picture "
                                           "can be changed without it.")), False, False, 0)

        head = Gtk.Box(spacing=14)
        pic = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        pic.add(_avatar(u, 96))
        pic.set_tooltip_text(_("Change the picture"))
        pic.connect("clicked", self._picture, u)
        head.pack_start(pic, False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=2)
        big = Gtk.Label(xalign=0, selectable=True)
        big.set_can_focus(False)
        big.set_markup(f"<span size='x-large' weight='bold'>{GLib.markup_escape_text(u.display())}</span>")
        names.pack_start(big, False, False, 0)
        names.pack_start(_dim(f"{u.name} · UID {u.uid} · {u.home}"), False, False, 0)
        head.pack_start(names, True, True, 0)
        self.details.pack_start(head, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        r = 0

        def row(label, widget, button=None):
            nonlocal r
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            grid.attach(widget, 1, r, 1, 1)
            if button:
                grid.attach(button, 2, r, 1, 1)
            r += 1

        full = Gtk.Entry(text=u.full_name, hexpand=True)
        save_full = Gtk.Button(label=_("Save"), sensitive=False)
        full.connect("changed", lambda e: save_full.set_sensitive(
            can and e.get_text().strip() != u.full_name and U.check_full_name(e.get_text().strip()) is None))
        save_full.connect("clicked", lambda *_a: self._call(["realname", u.name, full.get_text().strip()],
                                                            _("Full name saved"), keep=u.name))
        full.connect("activate", lambda *_a: save_full.get_sensitive() and save_full.clicked())
        row(_("Full name"), full, save_full)

        login = Gtk.Entry(text=u.name, hexpand=True)
        rename = Gtk.Button(label=_("Rename"), sensitive=False)
        busy = u.me or U.logged_in(u)
        login.set_sensitive(can and not busy)
        login.connect("changed", lambda e: rename.set_sensitive(
            e.get_text() != u.name and U.check_username(e.get_text()) is None and
            e.get_text() not in {x.name for x in self.users}))
        rename.connect("clicked", lambda *_a: self._rename(u, login.get_text()))
        row(_("Login name"), login, rename)
        if busy:
            grid.attach(_dim(_("You can't rename the account you're logged in with; log in as another "
                               "administrator to do it.") if u.me else
                             _("This account has programs running; log it out to rename it.")), 1, r, 2, 1)
            r += 1

        pw = Gtk.Button(label=_("Change password…"), halign=Gtk.Align.START, sensitive=can)
        pw.connect("clicked", self._password, u)
        row(_("Password"), pw)

        admin = Gtk.Switch(halign=Gtk.Align.START, active=u.admin)
        admin.set_sensitive(can and not (u.me and u.admin))
        admin.connect("state-set", lambda _s, state: self._call(["admin", u.name, "1" if state else "0"],
                                                                 _("Administrator rights changed"), keep=u.name)
                      or True)
        row(_("Administrator"), admin)
        grid.attach(_dim(_("Administrators (the wheel group) can use sudo and approve system changes like these.") +
                         (" " + _("You can't remove this from your own account.") if u.me and u.admin else "")),
                    1, r, 2, 1)
        r += 1

        shell = Gtk.ComboBoxText(hexpand=True)
        for s in U.shells():
            shell.append(s, s)
        if not shell.set_active_id(u.shell):
            shell.append(u.shell, u.shell)
            shell.set_active_id(u.shell)
        shell.set_sensitive(can)
        shell.connect("changed", lambda c: c.get_active_id() != u.shell and self._call(
            ["shell", u.name, c.get_active_id()], _("Login shell changed (from the next login)"), keep=u.name))
        row(_("Login shell"), shell)
        self.details.pack_start(grid, False, False, 0)

        groups = U.available_groups()
        if groups:
            head = Gtk.Label(xalign=0)
            head.set_markup(f"<b>{GLib.markup_escape_text(_('Groups'))}</b>")
            self.details.pack_start(head, False, False, 0)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            checks = {}
            save = Gtk.Button(label=_("Save groups"), halign=Gtk.Align.START, sensitive=False)

            def changed(*_a):
                save.set_sensitive(can and sorted(g for g, c in checks.items() if c.get_active()) != sorted(u.groups))
            for g in groups:
                c = Gtk.CheckButton()
                lbl = Gtk.Label(xalign=0, wrap=True)
                lbl.set_markup(f"<tt>{g}</tt>  {GLib.markup_escape_text(_(GROUP_LABELS[g]))}")
                c.add(lbl)
                c.set_active(g in u.groups)
                c.set_sensitive(can)
                c.connect("toggled", changed)
                checks[g] = c
                box.pack_start(c, False, False, 0)
            save.connect("clicked", lambda *_a: self._call(
                ["groups", u.name] + [g for g, c in checks.items() if c.get_active()],
                _("Groups saved; they apply from the next login"), keep=u.name))
            box.pack_start(save, False, False, 4)
            self.details.pack_start(box, False, False, 0)
            self.details.pack_start(_dim(_("Group changes take effect after logging out and back in.")),
                                    False, False, 0)
        self.details.show_all()
        widgets.protect(self.details)

    # ---------------------------------------------------------------- actions
    def _call(self, args, done_text, stdin=None, keep=None, after=None):
        """Run the helper in the background (the password prompt comes from polkit)."""
        if self.busy:
            return
        self.busy = True
        self.spinner.start()

        def work():
            ok, msg = U.run_helper(*args, stdin=stdin)
            GLib.idle_add(finish, ok, msg)

        def finish(ok, msg):
            self.busy = False
            self.spinner.stop()
            if ok:
                self.window.set_status(done_text)
            elif msg == "cancelled":
                self.window.set_status(_("Cancelled"))
            else:
                self.window.message(_("That didn't work"), msg)
            self.reload(keep=keep)
            if after:
                after(ok)
            return False
        threading.Thread(target=work, daemon=True).start()

    def _rename(self, u, new):
        dlg = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.OK_CANCEL,
                                text=_("Rename {old} to {new}?").format(old=u.name, new=new))
        moves = u.home == f"/home/{u.name}"
        dlg.format_secondary_text(
            (_("The home folder moves to /home/{new}. ").format(new=new) if moves else "") +
            _("Programs that saved the old path (some games, scripts) may need fixing."))
        ok = dlg.run() == Gtk.ResponseType.OK
        dlg.destroy()
        if ok:
            self._call(["rename", u.name, new], _("Renamed"), keep=new)

    def _password(self, _btn, u):
        dlg = Gtk.Dialog(title=_("Password for {user}").format(user=u.display()), transient_for=self.window,
                         modal=True)
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = dlg.add_button(_("Change"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        box = dlg.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)
        fields = PasswordFields(lambda: None)
        box.pack_start(fields, False, False, 0)
        box.pack_start(_dim(_("You'll be asked for an administrator's password (yours, if you're one) to confirm.")),
                       False, False, 0)
        ok.set_sensitive(False)
        fields.on_change = lambda: ok.set_sensitive(fields.valid())
        dlg.set_default_response(Gtk.ResponseType.OK)
        dlg.show_all()
        resp = dlg.run()
        password = fields.password() if fields.valid() else None
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and password:
            self._call(["password", u.name], _("Password changed"), stdin=password + "\n", keep=u.name)

    def _add_user(self, *_a):
        dlg = Gtk.Dialog(title=_("Add a user"), transient_for=self.window, modal=True)
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = dlg.add_button(_("Add"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        box = dlg.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        full = Gtk.Entry(hexpand=True)
        login = Gtk.Entry(hexpand=True)
        note = _dim("")
        admin = Gtk.CheckButton(label=_("Administrator"))
        grid.attach(Gtk.Label(label=_("Full name"), xalign=0), 0, 0, 1, 1)
        grid.attach(full, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label=_("Login name"), xalign=0), 0, 1, 1, 1)
        grid.attach(login, 1, 1, 1, 1)
        grid.attach(note, 1, 2, 1, 1)
        grid.attach(admin, 1, 3, 1, 1)
        box.pack_start(grid, False, False, 0)
        fields = PasswordFields(lambda: None)
        box.pack_start(fields, False, False, 0)
        state = {"auto": True}
        existing = {u.name for u in self.users}

        def check(*_a):
            name = login.get_text()
            err = U.check_username(name) if name else None
            if name in existing:
                note.set_text(_("That login name is taken."))
            else:
                note.set_text(_(ERRORS[err]) if err else "")
            ok.set_sensitive(bool(name) and err is None and name not in existing and
                             U.check_full_name(full.get_text().strip()) is None and fields.valid())

        def full_changed(*_a):
            if state["auto"]:
                login.handler_block(login_handler)
                login.set_text(suggest_login(full.get_text()))
                login.handler_unblock(login_handler)
            check()

        def login_changed(*_a):
            state["auto"] = False
            check()
        full.connect("changed", full_changed)
        login_handler = login.connect("changed", login_changed)
        fields.on_change = check
        check()
        dlg.show_all()
        resp = dlg.run()
        args = ["add", login.get_text(), full.get_text().strip(), "1" if admin.get_active() else "0"]
        password = fields.password()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK:
            self._call(args, _("User added"), stdin=password + "\n", keep=args[1])

    def _remove_user(self, *_a):
        u = self.selected
        if not u or u.me:
            return
        dlg = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.NONE,
                                text=_("Remove {user}?").format(user=u.display()))
        dlg.format_secondary_text(_("The account is deleted. Its home folder ({home}) can be kept, so its files "
                                    "stay on the disk.").format(home=u.home))
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dlg.add_button(_("Keep the files"), 1)
        delete = dlg.add_button(_("Delete the files too"), 2)
        delete.get_style_context().add_class("destructive-action")
        resp = dlg.run()
        dlg.destroy()
        if resp in (1, 2):
            self._call(["delete", u.name, "keep" if resp == 1 else "remove"], _("User removed"))

    def _picture(self, _btn, u):
        dlg = Gtk.FileChooserDialog(title=_("Choose a picture"), transient_for=self.window,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Open"), Gtk.ResponseType.OK)
        flt = Gtk.FileFilter()
        flt.set_name(_("Pictures"))
        flt.add_pixbuf_formats()
        dlg.add_filter(flt)
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if not path:
            return
        try:
            if u.me:
                face = U.make_face(path, os.path.join(u.home, ".face"))
            else:
                fd, face = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                U.make_face(path, face)
                os.chmod(face, 0o644)
        except Exception as e:  # noqa: BLE001
            self.window.message(_("Could not use that picture"), str(e))
            return
        if u.me:
            # your own picture needs no password: ~/.face is yours, and AccountsService lets
            # you change your own account's picture (login screens read either)
            U.set_own_picture(face)
            self.window.set_status(_("Picture changed"))
            self.reload(keep=u.name)
            return

        def cleanup(_ok):
            if not u.me:
                try:
                    os.remove(face)
                except OSError:
                    pass
        # login screens (LightDM, GDM, SDDM through AccountsService) read the system copy
        self._call(["icon", u.name, face], _("Picture changed"), keep=u.name, after=cleanup)
