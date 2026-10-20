"""The session check: everything that quietly breaks other pages, found in one place.

Each check gives (level, title, detail, fix): level ok/info/warn/error; fix is None, a
("copy", text) pair, or a (label, callable) pair the page shows as a button.
"""
import glob
import os
import shutil
import subprocess

from . import desktop as D
from .i18n import N_, _

SESSION_LINE = "exec --no-startup-id xcontrol --session"
POLKIT_AGENTS = ("polkit-gnome-authentication-agent-1", "polkit-kde-authentication-agent-1", "lxpolkit",
                 "lxqt-policykit-agent", "polkit-mate-authentication-agent-1", "xfce-polkit", "mate-polkit",
                 "hyprpolkitagent", "soteria", "polkit-efl-authentication-agent-1", "ts-polkitagent",
                 "polkit-dumb-agent", "cinnamon-polkit-agent", "gnome-shell")
AGENT_PATHS = ["/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1",
               "/usr/libexec/polkit-gnome-authentication-agent-1",
               "/usr/lib/polkit-kde-authentication-agent-1", "/usr/lib/xfce-polkit/xfce-polkit",
               "/usr/bin/lxpolkit", "/usr/bin/lxqt-policykit-agent",
               "/usr/lib/mate-polkit/polkit-mate-authentication-agent-1"]


def _cmdlines():
    out = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            if os.stat(d).st_uid != os.getuid():
                continue
            with open(os.path.join(d, "cmdline"), "rb") as f:
                args = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
            with open(os.path.join(d, "comm")) as f:
                comm = f.read().strip()
        except OSError:
            continue
        out[int(os.path.basename(d))] = (comm, args)
    return out


def polkit_agent(procs=None):
    """The running polkit agent's name, or None."""
    for comm, args in (procs or _cmdlines()).values():
        names = {comm} | {os.path.basename(a) for a in args[:2]}
        hit = names & set(POLKIT_AGENTS)
        if hit:
            return sorted(hit)[0]
    return None


def installed_agent():
    return next((p for p in AGENT_PATHS if os.access(p, os.X_OK)), None)


def start_agent(path):
    subprocess.Popen([path], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _start_xsettingsd():
    from . import theming
    look = None
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        look = theming.current(Gtk.Settings.get_default())
    except (ImportError, ValueError):
        pass
    theming.start_xsettingsd(look)


def checks():
    """All checks, worst first."""
    from . import audio, i3cfg, night, notify, poweralerts, theming
    out = []
    desk = D.load()
    st = D.state()
    procs = _cmdlines()

    # ---- does XControl start at login?
    runs = D.autostart_runs()
    if D.wanted(desk) or desk["bar"]["enabled"]:
        if runs is False:
            out.append(("error", _("XControl doesn't start when you log in"),
                        _("Your i3 config doesn't run xcontrol --session, so after the next login the wallpaper, "
                        "bar, compositor, screen lock and other desktop settings won't start. Add this line:"),
                        ("copy", SESSION_LINE)))
        else:
            out.append(("ok", _("XControl starts when you log in"), "", None))
        if not st.get("daemon"):
            out.append(("error", _("XControl's desktop service isn't running"),
                        _("The wallpaper, bar, compositor, lock and the rest of the Desktop pages' settings are "
                        "handled by it."), (_("Start it"), lambda: D.notify_daemon(D.load()))))
        else:
            out.append(("ok", _("The desktop service is running"), "", None))
    for key, err in (st.get("errors") or {}).items():
        out.append(("error", _("{program} keeps stopping").format(program=key.split(":")[0]), err, None))

    # ---- password prompts
    if shutil.which("pkexec"):
        agent = polkit_agent(procs)
        if agent:
            out.append(("ok", _("Password prompts work"), _("The polkit agent is {agent}.").format(agent=agent), None))
        else:
            path = installed_agent()
            detail = _("No polkit agent is running, so everything that asks for a password (users, kernel "
                       "modules, EDID, power buttons, languages, time) fails without a word. i3 doesn't start one.")
            if path:
                out.append(("error", _("Password prompts can't appear"),
                            detail + " " + _("Start it now, and add this to your i3 config:"),
                            (_("Start it"), lambda: start_agent(path))))
                out.append(("info", _("Start the polkit agent at login"), "",
                            ("copy", f"exec --no-startup-id {path}")))
            else:
                out.append(("error", _("Password prompts can't appear"),
                            detail + " " + _("Install one, e.g. polkit-gnome, and start it from your i3 config."),
                            None))

    # ---- duplicates
    managed = [(N_("Another bar is running besides XControl's"), ["polybar"], desk["bar"]["enabled"]),
               (N_("Another compositor is running besides XControl's"), ["picom", "compton", "xcompmgr"],
                desk["picom"]["enabled"]),
               (N_("Another notification program is running besides XControl's"),
                ["dunst", "xfce4-notifyd", "notify-osd", "mako"], desk["notify"]["enabled"]),
               (N_("Another screen lock is running besides XControl's"), ["xss-lock", "xautolock"],
                desk["lock"]["enabled"]),
               (N_("Another poweralertd is running besides XControl's"), ["poweralertd"],
                desk["power_alerts"]["enabled"])]
    for title, names, on in managed:
        extra = D.foreign(names) if on else {}
        if extra:
            out.append(("warn", _(title),
                        "\n".join(sorted(set(extra.values())))[:400],
                        (_("Stop the extra ones"), lambda n=names: D.stop_foreign(n))))
    conflicts = [line for kind, line in D.session_conflicts()
                 if (kind == "bar" and desk["bar"]["enabled"]) or (kind == "i3bar" and desk["bar"]["enabled"])
                 or (kind == "compositor" and desk["picom"]["enabled"])
                 or (kind == "wallpaper" and desk["wallpaper"]["enabled"])
                 or (kind == "lock" and desk["lock"]["enabled"])
                 or (kind == "notifications" and desk["notify"]["enabled"])
                 or (kind == "power_alerts" and desk["power_alerts"]["enabled"])]
    if conflicts and not i3cfg.is_ours():
        out.append(("warn", _("Your i3 config starts things XControl also starts"),
                    _("Remove these lines, or there'll be two of each after the next login:") + "\n" +
                    "\n".join(conflicts[:6]), None))
    if desk["power_alerts"]["enabled"] and poweralerts.service_state()[0]:
        out.append(("warn", _("poweralertd's own service is enabled too"),
                    _("It starts a second poweralertd at login, so every power alert shows twice."),
                    (_("Turn it off"), poweralerts.disable_service)))
    others = night.conflicting()
    if desk["night"]["enabled"] and others:
        out.append(("warn", _("Another night-light program is running"),
                    _("{programs} also changes the colors; the two will fight.").format(programs=", ".join(others)),
                    None))

    # ---- live theme changes
    kind, _pid = theming.xsettings_manager()
    if kind is None:
        if shutil.which("xsettingsd"):
            out.append(("warn", _("Open apps don't follow theme changes"),
                        _("xsettingsd is installed but not running, so open apps keep their old theme, font and "
                          "cursor until they restart. Start it now; xcontrol --session starts it at every login."),
                        (_("Start xsettingsd"), _start_xsettingsd)))
        else:
            out.append(("info", _("Open apps don't follow theme changes"),
                        _("Nothing provides XSETTINGS. Install xsettingsd; XControl starts it at login."), None))
    else:
        out.append(("ok", _("Open apps follow theme changes"), _("XSETTINGS from {kind}.").format(kind=kind), None))

    # ---- notifications and sound
    owner = notify.owner()
    if owner is None:
        out.append(("info", _("Nothing shows notifications"),
                    _("Programs' notifications are lost. Turn on XControl's on the Notifications page.")
                    + ("" if shutil.which("dunst") else " " + _("Install dunst first.")), None))
    else:
        out.append(("ok", _("Notifications are shown"), _("By {program}.").format(program=owner[1]), None))
    srv = audio.server()
    if srv is None:
        out.append(("warn", _("No sound server answers"), _("Install and start PipeWire (pipewire-pulse) or "
                    "PulseAudio."), None))
    else:
        out.append(("ok", _("Sound works"), srv[0], None))

    rank = {"error": 0, "warn": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda c: rank[c[0]])
