# Changelog

XControl was called mesa-panel up to 0.8.0. Versions before 0.5.0 weren't kept.

## 0.5.0 (2026-10-18)

**Initial version of Mesa Panel**

- Initial version: a Catalyst-style GTK control panel for Mesa drivers on X11
- Set global and per-game graphics overrides: anisotropic filtering, forced MSAA,
  transparency AA, VSync mode (incl. fast sync and adaptive) and a frame limiter
- Match profiles by Steam AppID or by program name; add installed Steam games or any
  program, and launch games through mesa-panel-run (e.g. as Steam launch options)
- Apply settings through a GL preload shim, an implicit Vulkan layer, Mesa driver
  variables and DXVK config; use WineD3D for Direct3D 8/9 games to force MSAA
- Arrange displays with xrandr: drag monitors, change resolution, refresh rate,
  rotation, primary display and on/off, with a 15-second confirm-or-revert
- Restore the display layout at login through an autostart entry
- Add custom resolutions (CVT, CVT-RB, CVT-RBv2, GTF, DMT or manual modeline) and
  optionally hide the modes from the display's EDID
- Build a corrected EDID listing only chosen modes, test it until reboot or install
  it permanently through a small root helper
- Show what each monitor reports on a Monitor Info page (panel, refresh range, VRR,
  HDR, gamut, connection) with copy and save-EDID options
- Include a Brazilian Portuguese translation
