"""Gather what each connected monitor reports about itself and describe it.

Sources, merged by identical EDID:
  - xrandr --verbose  (X11 output names, driver properties like vrr_capable, max bpc)
  - /sys/class/drm    (kernel connectors; works on Wayland too)
"""
import os
from dataclasses import dataclass, field

from . import edid, i18n, output_names, vrr, xrandr

TIMES = " × "  # 2560 × 1440


@dataclass
class MonitorRecord:
    x_name: str = ""
    drm_name: str = ""
    raw: bytes = b""
    info: edid.EdidInfo = None
    props: dict = field(default_factory=dict)
    xmon: xrandr.Monitor = None
    card: str = ""

    @property
    def name(self):
        return self.x_name or self.drm_name

    def title(self):
        if self.info:
            return self.info.display_name()
        return self.name


def collect():
    records = []
    xinfo, xmons = {}, {}
    if xrandr.available() and os.environ.get("DISPLAY") and os.environ.get("XDG_SESSION_TYPE") != "wayland":
        try:
            xinfo = xrandr.query_verbose()
            xmons = {m.name: m for m in xrandr.query()}
        except Exception:  # noqa: BLE001 - fall back to sysfs only
            xinfo, xmons = {}, {}
    sysfs = edid.read_sysfs_full()  # [(card, connector, edid)]

    for name, data in xinfo.items():
        mon = xmons.get(name)
        if not (mon and mon.connected):
            continue
        records.append(MonitorRecord(x_name=name, raw=data["edid"] or b"", props=data["props"], xmon=mon))
    # Match X outputs to kernel connectors by EDID. Two identical monitors have the same EDID,
    # so a connector whose name fits the X name goes first, and each connector is used once.
    free = list(sysfs)
    for by_name in (True, False):
        for rec in records:
            if rec.drm_name or not rec.raw:
                continue
            names = output_names.kernel_candidates(rec.x_name) if by_name else None
            hit = next((s for s in free if s[2] == rec.raw and (names is None or s[1] in names)), None)
            if hit:
                free.remove(hit)
                rec.card, rec.drm_name = hit[0], hit[1]
    records += [MonitorRecord(drm_name=conn, raw=raw, card=card) for card, conn, raw in free]
    for r in records:
        r.info = edid.parse(r.raw) if r.raw else None
    return records


def describe(rec, tr=None):
    """[(section title, [(label, value), ...]), ...] for display and copying.
    `tr` picks the language: the user's (default) or i18n.ENGLISH."""
    tr = tr or i18n.CURRENT
    _ = tr.gettext
    num, hz = tr.num, tr.hz
    i = rec.info
    p = rec.props
    sections = []

    names = []
    if rec.x_name:
        names.append(f"{rec.x_name} (X11)")
    if rec.drm_name and rec.drm_name != rec.x_name:
        # TRANSLATORS: the Linux kernel's name for the connector, e.g. "DP-1 (kernel)"
        names.append(_("{output} (kernel)").format(output=rec.drm_name))

    if not i:
        return [(_("Connection"), [(_("Output"), ", ".join(names) or rec.name),
                                   ("EDID", _("This display did not report any information."))])]
    not_reported = _("Not reported")

    # Identity
    if i.model_year:
        made = _("Model year {year}").format(year=i.year)
    elif 1 <= i.week <= 54:
        made = _("Week {week}, {year}").format(week=i.week, year=i.year)
    else:
        made = str(i.year)
    edid_text = _("version {version}").format(version=i.version)
    if i.extensions:
        edid_text += ", " + tr.ngettext("{list} extension", "{list} extensions",
                                        len(i.extensions)).format(list=", ".join(i.extensions))
    if not i.checksum_ok:
        edid_text += " " + _("(bad checksum)")
    ident = [
        (_("Model"), i.model or not_reported),
        (_("Manufacturer"), f"{i.vendor} ({i.vendor_id})" if i.vendor != i.vendor_id else i.vendor_id),
        (_("Product code"), f"0x{i.product_code:04X}"),
        (_("Serial number"), i.serial or not_reported),
        (_("Manufactured"), made),
        ("EDID", edid_text),
    ]
    sections.append((_("Identity"), ident))

    # Panel
    panel = []
    if i.preferred:
        t = i.preferred
        native = f"{t.width} × {t.height} @ {hz(t.refresh)}"
        if i.aspect():
            native += f" ({i.aspect()})"
        if t.interlaced:
            native += " " + _("interlaced")
        panel.append((_("Native resolution"), native))
    w, h = i.size_mm()
    if w and h:
        panel.append((_("Screen size"), _("{inches}″ ({width} × {height} mm)").format(
            inches=num(i.diagonal_inches(), 1), width=w, height=h)))
        if i.ppi():
            panel.append((_("Pixel density"), _("{ppi} PPI").format(ppi=num(i.ppi()))))
    depth = (tr.ngettext("{n} bit per color", "{n} bits per color", i.bit_depth).format(n=i.bit_depth)
             if i.bit_depth else not_reported)
    if "max bpc" in p:
        rng = p.get("max bpc (range)", "").strip("()").replace(", ", "–")
        if rng:
            depth += " " + _("(driver limit: {limit}, adjustable {range})").format(limit=p["max bpc"], range=rng)
        else:
            depth += " " + _("(driver limit: {limit})").format(limit=p["max bpc"])
    panel.append((_("Color depth"), depth))
    if i.gamma:
        panel.append((_("Gamma"), num(i.gamma, 2)))
    sections.append((_("Panel"), panel))

    # Refresh and sync
    sync = []
    if rec.xmon and rec.xmon.modes:
        best = max(((float(r), m) for m, rates in rec.xmon.modes.items() for r in rates
                    if not m.endswith("i")), default=None)
        if best:
            sync.append((_("Highest refresh rate"), f"{hz(best[0])} ({best[1].replace('x', TIMES)})"))
        biggest = max(rec.xmon.modes, key=lambda m: rec.xmon.mode_size(m)[0] * rec.xmon.mode_size(m)[1])
        sync.append((_("Highest resolution"), biggest.replace("x", " × ")))
    else:
        progressive = [t for t in i.timings if not t.interlaced]
        best = max(progressive, key=lambda t: (round(t.refresh), t.width * t.height), default=None)
        if best:
            sync.append((_("Highest refresh rate"), f"{hz(best.refresh)} ({best.width} × {best.height})"))
        big = max(progressive, key=lambda t: (t.width * t.height, round(t.refresh)), default=None)
        if big:
            sync.append((_("Highest resolution"), f"{big.width} × {big.height} @ {hz(big.refresh)}"))
    if i.vrange:
        sync.append((_("Supported refresh range"), f"{i.vrange[0]}–{i.vrange[1]} Hz"))
    if i.hrange:
        sync.append((_("Horizontal scan range"), f"{i.hrange[0]}–{i.hrange[1]} kHz"))
    vrr_cap = p.get("vrr_capable")
    if vrr_cap == "1" or (vrr_cap is None and i.freesync):
        vrr_text = _("Supported")
    elif vrr_cap == "0":
        vrr_text = _("Not available on this connection")
    else:
        vrr_text = not_reported
    if i.freesync:
        lo, hi = i.freesync
        vrr_text += " " + (_("(FreeSync {low}–{high} Hz)").format(low=lo, high=hi) if lo else
                           _("(FreeSync up to {high} Hz)").format(high=hi))
    sync.append((_("Variable refresh rate"), vrr_text))
    if vrr_cap == "1":
        x_on = vrr.x_vrr_enabled()
        if x_on is not None:
            sync.append((_("Variable refresh in X"),
                         _("Enabled") if x_on else
                         _("Disabled (add Option \"VariableRefresh\" \"true\" to the Device section)")))
    if i.max_pixel_clock_mhz:
        sync.append((_("Max pixel clock"), f"{i.max_pixel_clock_mhz} MHz"))
    sections.append((_("Refresh & Sync"), sync))

    # Color and HDR
    color = []
    hdr = [e for e in i.hdr_eotfs if e in ("HDR10 (PQ)", "HLG")]
    if i.hdr10plus:
        hdr.append("HDR10+")
    if i.dolby_vision:
        hdr.append("Dolby Vision")
    color.append(("HDR", ", ".join(hdr) if hdr else _("Not supported")))
    if i.max_luminance:
        lum = _("{nits} cd/m² peak").format(nits=num(i.max_luminance))
        if i.max_frame_avg:
            lum += ", " + _("{nits} full-frame").format(nits=num(i.max_frame_avg))
        if i.min_luminance:
            lum += ", " + _("{nits} minimum").format(nits=num(i.min_luminance, 3))
        color.append((_("Brightness (HDR metadata)"), lum))
    cov = i.gamut_coverage()
    if cov:
        color.append((_("Gamut (EDID primaries)"),
                      ", ".join(f"{k} {num(min(v, 100))}%" for k, v in cov.items())))
    if i.white[0]:
        color.append((_("White point"), f"x {num(i.white[0], 3)}, y {num(i.white[1], 3)}"))
    if i.colorimetry:
        color.append((_("Wide color signaling"), ", ".join(i.colorimetry)))
    if "Colorspace" in p:
        color.append((_("Driver colorspace"), p["Colorspace"]))
    sections.append((_("Color & HDR"), color))

    # Connection
    conn = [(_("Output"), ", ".join(names) or rec.name)]
    if rec.xmon and rec.xmon.enabled and rec.xmon.mode:
        conn.append((_("Current mode"),
                     f"{rec.xmon.mode.replace('x', TIMES)} @ {hz(float(rec.xmon.rate or 0))}"))
    conn.append((_("Input type"), i.interface if i.interface and i.digital else
                 (_("Digital") if i.digital else _("Analog (VGA)"))))
    if i.hdmi:
        if i.frl:
            hdmi = _("HDMI 2.1 capable")
        elif i.hdmi_forum:
            hdmi = _("HDMI 2.0 capable")
        else:
            hdmi = "HDMI 1.x"
        conn.append((_("HDMI support"), hdmi))
    if i.max_tmds_mhz:
        conn.append((_("Max TMDS clock"), f"{i.max_tmds_mhz} MHz"))
    if i.frl in edid.FRL_RATES:
        lanes = 3 if i.frl <= 2 else 4
        conn.append((_("HDMI FRL bandwidth"), tr.ngettext(
            "{rate} Gbps × {lanes} lane ({total} Gbps)", "{rate} Gbps × {lanes} lanes ({total} Gbps)",
            lanes).format(rate=edid.FRL_GBPS[i.frl] // lanes, lanes=lanes, total=edid.FRL_GBPS[i.frl])))
    if "CTA-861" in i.extensions:
        conn.append((_("Audio"), _("Yes") if i.audio else _("No")))
        ycc = [n for n, ok in (("4:4:4", i.ycbcr444), ("4:2:2", i.ycbcr422), ("4:2:0", i.ycbcr420)) if ok]
        conn.append(("YCbCr", ", ".join(ycc) if ycc else _("RGB only")))
    if i.dpms:
        dpms = {"standby": _("standby"), "suspend": _("suspend"), "off": _("off")}
        conn.append((_("Power saving"), ", ".join(dpms[d] for d in i.dpms)))
    sections.append((_("Connection"), conn))
    return sections


def as_text(rec, english=False):
    tr = i18n.ENGLISH if english else i18n.CURRENT
    title = rec.title()
    lines = [title, "=" * len(title)]
    for section, rows in describe(rec, tr):
        lines.append("")
        lines.append(section)
        width = max(len(k) for k, _v in rows)
        lines += [f"  {k.ljust(width)}  {v}" for k, v in rows]
    return "\n".join(lines) + "\n"
