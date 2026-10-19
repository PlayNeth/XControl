"""The 3D / gaming page: global settings and per-game profiles."""
import os
import shlex
import shutil
import subprocess

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import config, launcher, steam, vrr, widgets  # noqa: E402
from .i18n import N_, _  # noqa: E402

LAUNCH_OPTION = "xcontrol-run %command%"

TRAA_LABELS = [
    N_("Off"),
    N_("Multisample (alpha-to-coverage)"),
    N_("Supersample (best quality)"),
]
D3D_LABELS = [
    N_("DXVK (default)"),
    N_("WineD3D (needed for forced MSAA)"),
]
VSYNC_LABELS = [
    N_("Application decides"),
    N_("Always off"),
    N_("Always on"),
    N_("Fast sync (no tearing, uncapped; Vulkan)"),
    N_("Adaptive (tears below refresh rate; Vulkan)"),
]
FREESYNC_LABELS = [
    N_("Application decides"),
    N_("Always off"),
    N_("On for fullscreen games"),
]
POST_AA_LABELS = [
    N_("Off"),
    N_("FXAA (fastest, slightly softer)"),
    N_("SMAA (cleaner edges)"),
]
SHARPEN_VALUES = [0, 25, 50, 75]
SHARPEN_LABELS = [N_("Off"), N_("Low"), N_("Medium"), N_("High")]


def _factor_label(value):
    # TRANSLATORS: slider position meaning the feature is forced off
    return _("Off") if value == 1 else _("{n}×").format(n=value)


def _hint(text):
    lbl = Gtk.Label(label=text, xalign=0, wrap=True)
    lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.set_max_width_chars(70)
    lbl.get_style_context().add_class("dim-label")
    return lbl


def _section(title):
    frame = Gtk.Frame()
    head = Gtk.Label(xalign=0)
    head.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
    frame.set_label_widget(head)
    frame.set_shadow_type(Gtk.ShadowType.NONE)
    grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_start=12, margin_top=8, margin_bottom=4)
    frame.add(grid)
    return frame, grid


class SliderSetting:
    """'Use application settings' checkbox + a notched slider (Catalyst style)."""

    def __init__(self, grid, row, label, values, default, on_change):
        self.values = values
        self.default = default
        self.on_change = on_change
        self._scroll_acc = 0.0
        self.check = Gtk.CheckButton(label=_("Use application settings"))
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, len(values) - 1, 1)
        self.scale.set_round_digits(0)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_size_request(260, -1)
        # Keyboard Page Up/Down and clicks in the trough move one notch, not ten.
        self.scale.get_adjustment().set_page_increment(1)
        for i, v in enumerate(values):
            self.scale.add_mark(i, Gtk.PositionType.BOTTOM, _factor_label(v))
        self.scale.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.scale.connect("scroll-event", self._scroll)
        name = Gtk.Label(label=label, xalign=0)
        grid.attach(name, 0, row, 1, 1)
        grid.attach(self.check, 1, row, 1, 1)
        grid.attach(self.scale, 1, row + 1, 1, 1)
        self.check.connect("toggled", self._changed)
        self.scale.connect("value-changed", self._changed)

    def set(self, value):
        self.check.set_active(value == 0)
        shown = value if value in self.values else self.default
        self.scale.set_value(self.values.index(shown))
        self.scale.set_sensitive(value != 0)

    def get(self):
        if self.check.get_active():
            return 0
        return self.values[int(round(self.scale.get_value()))]

    def _scroll(self, scale, event):
        """One wheel notch = one step. GTK's default jumps by a whole page."""
        if not widgets.wheel_allowed(scale):  # scrolling the page past the slider
            return widgets.scroll_page(scale, event)
        step = 0
        if event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.RIGHT):
            step = 1
        elif event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.LEFT):
            step = -1
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            ok, dx, dy = event.get_scroll_deltas()
            # touchpads send many small deltas; act once per notch's worth
            self._scroll_acc += (dx - dy) if ok else 0.0
            if abs(self._scroll_acc) >= 1.0:
                step = 1 if self._scroll_acc > 0 else -1
                self._scroll_acc = 0.0
        if step:
            idx = int(round(scale.get_value())) + step
            scale.set_value(max(0, min(len(self.values) - 1, idx)))
        return True  # handled; don't let GTK apply its own page-sized jump

    def _changed(self, *_args):
        self.scale.set_sensitive(not self.check.get_active())
        self.on_change()


class SteamPicker(Gtk.Dialog):
    def __init__(self, parent, games):
        super().__init__(title=_("Add Steam game"), transient_for=parent, modal=True)
        self.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Add"), Gtk.ResponseType.OK)
        self.set_default_size(420, 480)
        self.set_default_response(Gtk.ResponseType.OK)
        box = self.get_content_area()
        box.set_spacing(6)
        box.set_border_width(10)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search installed games"))
        box.pack_start(self.search, False, False, 0)
        self.listbox = Gtk.ListBox()
        self.listbox.set_filter_func(self._filter)
        for g in games:
            row = Gtk.ListBoxRow()
            row.game = g
            lbl = Gtk.Label(label=g["name"], xalign=0, margin=6)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            row.add(lbl)
            self.listbox.add(row)
        self.listbox.connect("row-activated", lambda *_a: self.response(Gtk.ResponseType.OK))
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.add(self.listbox)
        box.pack_start(sw, True, True, 0)
        self.search.connect("search-changed", lambda *_a: self.listbox.invalidate_filter())
        self.show_all()

    def _filter(self, row):
        q = self.search.get_text().strip().lower()
        return not q or q in row.game["name"].lower()

    def selected(self):
        row = self.listbox.get_selected_row()
        return row.game if row else None


class GamingPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=18)
        self.window = window
        self.data = config.load()
        self.loading = False

        # ---- profile bar
        bar = Gtk.Box(spacing=6)
        bar.pack_start(Gtk.Label(label=_("Profile:")), False, False, 0)
        self.profile_combo = Gtk.ComboBoxText()
        self.profile_combo.set_hexpand(True)
        self.profile_combo.connect("changed", self._profile_changed)
        bar.pack_start(self.profile_combo, True, True, 0)
        add_btn = Gtk.MenuButton(label=_("Add game"))
        menu = Gtk.Menu()
        for text, cb in ((_("Steam game…"), self._add_steam), (_("Program or script…"), self._add_program)):
            item = Gtk.MenuItem(label=text)
            item.connect("activate", cb)
            menu.append(item)
        menu.show_all()
        add_btn.set_popup(menu)
        bar.pack_start(add_btn, False, False, 0)
        self.delete_btn = Gtk.Button(label=_("Delete"))
        self.delete_btn.get_style_context().add_class("destructive-action")
        self.delete_btn.connect("clicked", self._delete)
        bar.pack_start(self.delete_btn, False, False, 0)
        self.pack_start(bar, False, False, 0)

        # ---- live 3D preview of the settings below
        from .preview3d import Preview3D
        self.preview = Preview3D()
        self.preview_box = Gtk.Expander(label=_("3D preview"))
        self.preview_box.set_expanded(self.data.get("ui", {}).get("preview", True))
        self.preview_box.connect("notify::expanded", self._preview_toggled)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6)
        inner.pack_start(self.preview, False, False, 0)
        inner.pack_start(_hint(_("The gears show multisampling on their edges, the floor anisotropic filtering, "
                                 "the fence transparency anti-aliasing. The frame limiter applies too. Drag to "
                                 "turn the scene; double-click to reset it.")), False, False, 0)
        self.preview_box.add(inner)
        self.pack_start(self.preview_box, False, False, 0)

        # ---- game details (hidden for the global profile)
        self.details_frame, g = _section(_("Game"))
        self.name_entry = Gtk.Entry(hexpand=True)
        self.match_entry = Gtk.Entry(hexpand=True)
        self.match_entry.set_tooltip_text(
            _("Comma-separated. steam:APPID matches a Steam game; any other entry matches the "
              "file name of the program or of one of its arguments (e.g. game.exe under Proton)."))
        self.command_entry = Gtk.Entry(hexpand=True,
                                       placeholder_text=_("Optional: command to start the game from here"))
        self.launch_btn = Gtk.Button(label=_("Launch"))
        self.launch_btn.get_style_context().add_class("suggested-action")
        self.launch_btn.connect("clicked", self._launch)
        g.attach(Gtk.Label(label=_("Name"), xalign=0), 0, 0, 1, 1)
        g.attach(self.name_entry, 1, 0, 2, 1)
        g.attach(Gtk.Label(label=_("Applies to"), xalign=0), 0, 1, 1, 1)
        g.attach(self.match_entry, 1, 1, 2, 1)
        g.attach(Gtk.Label(label=_("Command"), xalign=0), 0, 2, 1, 1)
        g.attach(self.command_entry, 1, 2, 1, 1)
        g.attach(self.launch_btn, 2, 2, 1, 1)
        for e in (self.name_entry, self.match_entry, self.command_entry):
            e.connect("changed", self._details_changed)
        self.details_frame.show_all()
        self.details_frame.set_no_show_all(True)  # visibility follows the selected profile
        self.pack_start(self.details_frame, False, False, 0)

        # ---- anti-aliasing
        frame, g = _section(_("Anti-Aliasing"))
        self.msaa = SliderSetting(g, 0, _("Multisampling"), config.MSAA_VALUES, 4, self._settings_changed)
        g.attach(Gtk.Label(label=_("Transparency"), xalign=0), 0, 2, 1, 1)
        self.traa = Gtk.ComboBoxText()
        for t in TRAA_LABELS:
            self.traa.append_text(_(t))
        self.traa.connect("changed", self._settings_changed)
        g.attach(self.traa, 1, 2, 1, 1)
        # TRANSLATORS: which Direct3D implementation Wine uses for old (DirectX 8/9) games
        g.attach(Gtk.Label(label=_("Direct3D 8/9 games"), xalign=0), 0, 3, 1, 1)
        self.d3d = Gtk.ComboBoxText()
        for t in D3D_LABELS:
            self.d3d.append_text(_(t))
        self.d3d.connect("changed", self._settings_changed)
        g.attach(self.d3d, 1, 3, 1, 1)
        g.attach(_hint(_("Forced multisampling works in OpenGL games and, with WineD3D selected, in "
                         "Direct3D 8/9 games that draw straight to the screen (mostly older titles). "
                         "DXVK cannot force it. Games with post-processing or deferred rendering "
                         "ignore it; use their own AA options. Off also disables MSAA in Direct3D 11 "
                         "games running through DXVK. Transparency AA smooths alpha-tested foliage "
                         "and fences while multisampling is active; in shader-based games, including "
                         "WineD3D, both modes supersample just those surfaces.")), 1, 4, 1, 1)
        self.pack_start(frame, False, False, 0)

        # ---- texture filtering
        frame, g = _section(_("Texture Filtering"))
        self.af = SliderSetting(g, 0, _("Anisotropic filtering"), config.AF_VALUES, 16, self._settings_changed)
        g.attach(_hint(_("Works in OpenGL, Vulkan and Proton (DXVK / VKD3D-Proton) games.")), 1, 2, 1, 1)
        self.pack_start(frame, False, False, 0)

        # ---- frame rate
        frame, g = _section(_("Frame Rate"))
        g.attach(Gtk.Label(label=_("Vertical sync"), xalign=0), 0, 0, 1, 1)
        self.vsync = Gtk.ComboBoxText()
        for t in VSYNC_LABELS:
            self.vsync.append_text(_(t))
        self.vsync.connect("changed", self._settings_changed)
        g.attach(self.vsync, 1, 0, 1, 1)
        self.fps_check = Gtk.CheckButton(label=_("Limit frame rate to"))
        self.fps_spin = Gtk.SpinButton.new_with_range(10, 1000, 1)
        self.fps_spin.set_value(60)
        fps_box = Gtk.Box(spacing=6)
        fps_box.pack_start(self.fps_check, False, False, 0)
        fps_box.pack_start(self.fps_spin, False, False, 0)
        # TRANSLATORS: frames per second, shown after the frame limit number
        fps_box.pack_start(Gtk.Label(label=_("FPS")), False, False, 0)
        g.attach(Gtk.Label(label=_("Frame limiter"), xalign=0), 0, 1, 1, 1)
        g.attach(fps_box, 1, 1, 1, 1)
        self.fps_check.connect("toggled", self._settings_changed)
        self.fps_spin.connect("value-changed", self._settings_changed)
        # TRANSLATORS: AMD's name for variable refresh rate; keep it if your language uses it
        g.attach(Gtk.Label(label=_("FreeSync"), xalign=0), 0, 2, 1, 1)
        self.freesync = Gtk.ComboBoxText()
        for t in FREESYNC_LABELS:
            self.freesync.append_text(_(t))
        self.freesync.connect("changed", self._settings_changed)
        g.attach(self.freesync, 1, 2, 1, 1)
        self.freesync_hint = _hint("")
        g.attach(self.freesync_hint, 1, 3, 1, 1)
        self.x_vrr = vrr.x_vrr_enabled()
        self.pack_start(frame, False, False, 0)

        # ---- post-processing (vkBasalt)
        frame, g = _section(_("Post-Processing"))
        self.has_vkbasalt = vrr.vkbasalt_installed()
        g.attach(Gtk.Label(label=_("Edge smoothing"), xalign=0), 0, 0, 1, 1)
        self.post_aa = Gtk.ComboBoxText()
        for t in POST_AA_LABELS:
            self.post_aa.append_text(_(t))
        self.post_aa.connect("changed", self._settings_changed)
        g.attach(self.post_aa, 1, 0, 1, 1)
        g.attach(Gtk.Label(label=_("Sharpening"), xalign=0), 0, 1, 1, 1)
        self.sharpen = Gtk.ComboBoxText()
        for t in SHARPEN_LABELS:
            self.sharpen.append_text(_(t))
        self.sharpen.connect("changed", self._settings_changed)
        g.attach(self.sharpen, 1, 1, 1, 1)
        if self.has_vkbasalt:
            post_hint = _("Applied by vkBasalt after the game draws each frame, so it works where forced "
                          "multisampling can't: Vulkan games and Windows games through DXVK or VKD3D-Proton. "
                          "Not OpenGL. Press Home in the game to compare with it off.")
        else:
            post_hint = _("Needs vkBasalt, which isn't installed. It smooths edges and sharpens the image "
                          "in Vulkan games and Windows games through DXVK or VKD3D-Proton.")
            self.post_aa.set_sensitive(False)
            self.sharpen.set_sensitive(False)
        g.attach(_hint(post_hint), 1, 2, 1, 1)
        self.pack_start(frame, False, False, 0)

        # line up the label column across all sections
        group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        for frame in (self.details_frame,) + tuple(c for c in self.get_children() if isinstance(c, Gtk.Frame)):
            grid = frame.get_child()
            for child in grid.get_children():
                if grid.child_get_property(child, "left-attach") == 0:
                    group.add_widget(child)

        # ---- footer
        foot = Gtk.Box(spacing=6)
        foot.pack_start(_hint(_("Settings apply to games started through the panel's launcher. "
                                "For Steam games, use these launch options:")), True, True, 0)
        opt = Gtk.Entry(text=LAUNCH_OPTION, editable=False, width_chars=len(LAUNCH_OPTION) + 1)
        foot.pack_start(opt, False, False, 0)
        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON)
        copy_btn.set_tooltip_text(_("Copy launch options"))
        copy_btn.connect("clicked", self._copy_launch_option)
        foot.pack_start(copy_btn, False, False, 0)
        self.pack_end(foot, False, False, 0)

        test = Gtk.Box(spacing=6, margin_top=12)
        for prog in ("glxgears", "vkcube"):
            if shutil.which(prog):
                # TRANSLATORS: {program} is glxgears or vkcube
                b = Gtk.Button(label=_("Test with {program}").format(program=prog))
                b.connect("clicked", self._test, prog)
                test.pack_start(b, False, False, 0)
        self.pack_end(test, False, False, 0)

        self._fill_profiles(0)

    # ---- model <-> view
    def _current(self):
        idx = self.profile_combo.get_active()
        if idx <= 0:
            return None, self.data["global"]
        game = self.data["games"][idx - 1]
        return game, game["settings"]

    def _fill_profiles(self, select):
        self.loading = True
        self.profile_combo.remove_all()
        self.profile_combo.append_text(_("Global settings (all games)"))
        for g in self.data["games"]:
            self.profile_combo.append_text(g["name"])
        self.loading = False
        self.profile_combo.set_active(select)

    def _profile_changed(self, *_args):
        if self.loading:
            return
        game, s = self._current()
        self.loading = True
        self.details_frame.set_visible(game is not None)
        self.delete_btn.set_sensitive(game is not None)
        if game:
            self.name_entry.set_text(game["name"])
            self.match_entry.set_text(", ".join(game["match"]))
            self.command_entry.set_text(game["command"])
            self.launch_btn.set_sensitive(bool(game["command"].strip()))
        self.msaa.set(s["msaa"])
        self.af.set(s["af"])
        self.traa.set_active(config.TRAA_VALUES.index(s["traa"]))
        self.d3d.set_active(config.D3D_RENDERERS.index(s["d3d_renderer"]))
        self.vsync.set_active(config.VSYNC_VALUES.index(s["vsync"]))
        self.fps_check.set_active(s["fps_limit"] > 0)
        if s["fps_limit"]:
            self.fps_spin.set_value(s["fps_limit"])
        self.fps_spin.set_sensitive(s["fps_limit"] > 0)
        self.freesync.set_active(config.FREESYNC_VALUES.index(s["freesync"]))
        self.post_aa.set_active(config.POST_AA_VALUES.index(s["post_aa"]))
        self.sharpen.set_active(min(range(len(SHARPEN_VALUES)), key=lambda i: abs(SHARPEN_VALUES[i] - s["sharpen"])))
        self._update_freesync_hint(s)
        self.preview.set_settings(s)
        self.loading = False

    def _settings_changed(self, *_args):
        if self.loading:
            return
        _game, s = self._current()
        s["msaa"] = self.msaa.get()
        s["af"] = self.af.get()
        s["traa"] = config.TRAA_VALUES[max(0, self.traa.get_active())]
        s["d3d_renderer"] = config.D3D_RENDERERS[max(0, self.d3d.get_active())]
        s["vsync"] = config.VSYNC_VALUES[max(0, self.vsync.get_active())]
        self.fps_spin.set_sensitive(self.fps_check.get_active())
        s["fps_limit"] = int(self.fps_spin.get_value()) if self.fps_check.get_active() else 0
        s["freesync"] = config.FREESYNC_VALUES[max(0, self.freesync.get_active())]
        s["post_aa"] = config.POST_AA_VALUES[max(0, self.post_aa.get_active())]
        s["sharpen"] = SHARPEN_VALUES[max(0, self.sharpen.get_active())]
        self._update_freesync_hint(s)
        self.preview.set_settings(s)
        self._save()

    def _preview_toggled(self, exp, _pspec):
        self.data.setdefault("ui", {})["preview"] = exp.get_expanded()
        self._save()

    def _update_freesync_hint(self, s):
        if s["freesync"] == "off":
            text = _("Variable refresh is turned off for these games.")
        else:
            text = _("Works in fullscreen OpenGL, Vulkan and Proton games on a FreeSync display, while the "
                     "frame rate is inside the display's FreeSync range. With a frame limit, set it a few "
                     "FPS below the display's maximum refresh rate.")
            if self.x_vrr is False:
                text += " " + _("X has it disabled: add Option \"VariableRefresh\" \"true\" to the "
                                "Device section of your xorg.conf and restart X.")
        self.freesync_hint.set_text(text)

    def _details_changed(self, *_args):
        if self.loading:
            return
        game, _s = self._current()
        if not game:
            return
        name = self.name_entry.get_text().strip()
        if name and name != game["name"]:
            game["name"] = name
            idx = self.profile_combo.get_active()
            self.loading = True
            self._rename_combo_item(idx, name)
            self.loading = False
        game["match"] = [m.strip() for m in self.match_entry.get_text().split(",") if m.strip()]
        game["command"] = self.command_entry.get_text()
        self.launch_btn.set_sensitive(bool(game["command"].strip()))
        self._save()

    def _rename_combo_item(self, idx, name):
        self.profile_combo.remove(idx)
        self.profile_combo.insert_text(idx, name)
        self.profile_combo.set_active(idx)

    def _save(self):
        try:
            # only this page's parts: other pages save their own sections in the same file meanwhile
            fresh = config.load()
            fresh["global"], fresh["games"] = self.data["global"], self.data["games"]
            if "ui" in self.data:
                fresh["ui"] = self.data["ui"]
            config.save(fresh)
            self.window.set_status(_("Saved"))
        except OSError as e:
            self.window.set_status(_("Could not save profiles: {error}").format(error=e))

    # ---- actions
    def _add_steam(self, *_args):
        games = steam.installed_games()
        if not games:
            self.window.message(_("No Steam games found"),
                                _("No installed Steam games were found in the usual Steam folders. "
                                  "You can still add a game with “Program or script…” and type "
                                  "steam:APPID into “Applies to”."))
            return
        dlg = SteamPicker(self.window, games)
        game = dlg.selected() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if game:
            config.new_game(self.data, game["name"], [f"steam:{game['appid']}"])
            self._save()
            self._fill_profiles(len(self.data["games"]))

    def _add_program(self, *_args):
        dlg = Gtk.FileChooserDialog(title=_("Choose the game's executable"), parent=self.window,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Add"), Gtk.ResponseType.OK)
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            base = os.path.basename(path)
            config.new_game(self.data, base, [base], shlex.quote(path))
            self._save()
            self._fill_profiles(len(self.data["games"]))

    def _delete(self, *_args):
        game, _s = self._current()
        if not game:
            return
        dlg = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.OK_CANCEL,
                                text=_("Delete the profile “{name}”?").format(name=game["name"]))
        ok = dlg.run() == Gtk.ResponseType.OK
        dlg.destroy()
        if ok:
            self.data["games"].remove(game)
            self._save()
            self._fill_profiles(0)

    def _spawn(self, argv, settings, cwd=None):
        env = dict(os.environ)
        env.update(launcher.compose_env(settings))
        try:
            launcher.write_support_files(settings)
        except OSError as e:
            self.window.message(_("Could not write the vkBasalt configuration"), str(e))
            return
        try:
            subprocess.Popen(argv, env=env, cwd=cwd, start_new_session=True)
        except OSError as e:
            self.window.message(_("Could not start the program"), str(e))

    def _launch(self, *_args):
        game, s = self._current()
        if not game or not game["command"].strip():
            return
        try:
            argv = shlex.split(game["command"])
        except ValueError as e:
            self.window.message(_("The command is not valid"), str(e))
            return
        cwd = os.path.dirname(argv[0]) if os.path.isabs(argv[0]) else None
        self._spawn(argv, s, cwd)

    def _test(self, _btn, prog):
        _game, s = self._current()
        self._spawn([prog], s)

    def _copy_launch_option(self, *_args):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(LAUNCH_OPTION, -1)
        self.window.set_status(_("Launch options copied"))
