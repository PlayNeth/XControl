"""Gaming mice through ratbagd (libratbag's D-Bus service): DPI stages, polling rate,
debounce, angle snapping, button mapping and LEDs.

Changes are made on ratbagd's copy of the settings and only written to the mouse
by Device.commit() (the "Save to mouse" button), as libratbag recommends.
API: https://libratbag.github.io/ (doc/dbus.rst), version 2.
"""
import os

from gi.repository import Gio, GLib

BUS_NAME = "org.freedesktop.ratbag1"
MANAGER_PATH = "/org/freedesktop/ratbag1"
IFACE = "org.freedesktop.ratbag1."
API_VERSION = 2
# ratbagd answers nothing while it writes to a mouse, which can take several seconds;
# XControl calls it from a background thread, so waiting longer is fine
TIMEOUT = 30000

# Button ActionTypes
ACTION_NONE, ACTION_BUTTON, ACTION_SPECIAL, ACTION_KEY, ACTION_MACRO, ACTION_UNKNOWN = 0, 1, 2, 3, 4, 1000
SPECIAL_BASE = 0x40000000
# special functions (offset from SPECIAL_BASE) that make sense to pick from a list
SPECIALS = {
    1: "Double click", 2: "Wheel left", 3: "Wheel right", 4: "Wheel up", 5: "Wheel down",
    6: "Ratchet mode switch", 7: "DPI cycle up", 8: "DPI cycle down", 9: "DPI up", 10: "DPI down",
    11: "DPI shift (sniper)", 12: "Default DPI", 13: "Profile cycle up", 14: "Profile cycle down",
    15: "Profile up", 16: "Profile down", 17: "Second mode", 18: "Battery level",
}
# logical button numbers, HID order (what libratbag drivers and Piper use)
BUTTON_NAMES = {1: "Left click", 2: "Right click", 3: "Middle click", 4: "Back", 5: "Forward"}
# LED modes
LED_OFF, LED_ON, LED_CYCLE, LED_BREATHING = 0, 1, 2, 3
# LED color depth -> bits per channel (None = no color)
COLOR_BITS = {0: None, 1: 8, 2: 1}


class RatbagError(RuntimeError):
    pass


def _bus():
    kind = Gio.BusType.SESSION if os.environ.get("XCONTROL_RATBAG_BUS") == "session" else Gio.BusType.SYSTEM
    return Gio.bus_get_sync(kind, None)


class _Object:
    """A ratbagd object: properties of one interface, read once and cached."""

    def __init__(self, conn, path, iface):
        self.conn, self.path, self.iface = conn, path, IFACE + iface
        self.props = {}
        self.refresh()

    def refresh(self):
        try:
            res = self.conn.call_sync(BUS_NAME, self.path, "org.freedesktop.DBus.Properties", "GetAll",
                                      GLib.Variant("(s)", (self.iface,)), GLib.VariantType("(a{sv})"),
                                      Gio.DBusCallFlags.NONE, TIMEOUT, None)
        except GLib.Error as e:
            raise RatbagError(e.message) from e
        self.props = res.unpack()[0]

    def set(self, name, variant):
        try:
            self.conn.call_sync(BUS_NAME, self.path, "org.freedesktop.DBus.Properties", "Set",
                                GLib.Variant("(ssv)", (self.iface, name, variant)), None,
                                Gio.DBusCallFlags.NONE, TIMEOUT, None)
        except GLib.Error as e:
            raise RatbagError(e.message) from e
        self.props[name] = variant.unpack()

    def call(self, method, timeout=None):
        try:
            self.conn.call_sync(BUS_NAME, self.path, self.iface, method, None, None,
                                Gio.DBusCallFlags.NONE, timeout or TIMEOUT, None)
        except GLib.Error as e:
            raise RatbagError(e.message) from e

    def __getitem__(self, name):
        return self.props[name]

    def get(self, name, default=None):
        return self.props.get(name, default)


class Resolution(_Object):
    def __init__(self, conn, path):
        super().__init__(conn, path, "Resolution")

    @property
    def dpi(self):
        v = self["Resolution"]
        return v[0] if isinstance(v, tuple) else v

    @property
    def separate_xy(self):
        return isinstance(self["Resolution"], tuple)

    @property
    def choices(self):
        return list(self.get("Resolutions", []))

    @property
    def can_disable(self):
        return bool(self.get("Capabilities") and 2 in self["Capabilities"])

    def set_dpi(self, dpi):
        # the type must stay the same: (uu) stays (uu), u stays u
        # "Resolution" is itself a variant property, so the value is wrapped twice (like Piper does)
        inner = GLib.Variant("(uu)", (dpi, dpi)) if self.separate_xy else GLib.Variant("u", dpi)
        self.set("Resolution", GLib.Variant("v", inner))

    def set_disabled(self, disabled):
        self.set("IsDisabled", GLib.Variant("b", disabled))

    def make_active(self):
        self.call("SetActive")
        self.props["IsActive"] = True

    def make_default(self):
        self.call("SetDefault")
        self.props["IsDefault"] = True


class Button(_Object):
    def __init__(self, conn, path):
        super().__init__(conn, path, "Button")

    @property
    def mapping(self):
        return tuple(self["Mapping"])   # (action type, value)

    @property
    def action_types(self):
        return list(self.get("ActionTypes", []))

    def set_button(self, number):
        self.set("Mapping", GLib.Variant("(uv)", (ACTION_BUTTON, GLib.Variant("u", number))))

    def set_special(self, special):
        self.set("Mapping", GLib.Variant("(uv)", (ACTION_SPECIAL, GLib.Variant("u", special))))

    def set_none(self):
        self.set("Mapping", GLib.Variant("(uv)", (ACTION_NONE, GLib.Variant("u", 0))))


class Led(_Object):
    def __init__(self, conn, path):
        super().__init__(conn, path, "Led")

    @property
    def color_bits(self):
        return COLOR_BITS.get(self.get("ColorDepth", 0))

    def set_mode(self, mode):
        self.set("Mode", GLib.Variant("u", mode))

    def set_color(self, rgb):
        """rgb as 0-255 values; scaled down to the LED's color depth."""
        bits = self.color_bits
        if not bits:
            return
        scale = (1 << bits) - 1
        self.set("Color", GLib.Variant("(uuu)", tuple(round(c * scale / 255) for c in rgb)))

    @property
    def rgb(self):
        bits = self.color_bits or 8
        scale = (1 << bits) - 1
        return tuple(round(c * 255 / scale) for c in self.get("Color", (0, 0, 0)))

    def set_brightness(self, value):
        self.set("Brightness", GLib.Variant("u", max(0, min(255, int(value)))))

    def set_duration(self, ms):
        self.set("EffectDuration", GLib.Variant("u", max(0, min(10000, int(ms)))))


class Profile(_Object):
    def __init__(self, conn, path):
        super().__init__(conn, path, "Profile")
        self.resolutions = [Resolution(conn, p) for p in self.get("Resolutions", [])]
        self.buttons = [Button(conn, p) for p in self.get("Buttons", [])]
        self.leds = [Led(conn, p) for p in self.get("Leds", [])]

    @property
    def report_rates(self):
        return list(self.get("ReportRates", []))

    @property
    def debounces(self):
        return list(self.get("Debounces", []))

    @property
    def angle_snapping(self):
        """True/False, or None if the mouse can't do it."""
        v = self.get("AngleSnapping", -1)
        return None if v == -1 else bool(v)

    def set_report_rate(self, hz):
        self.set("ReportRate", GLib.Variant("u", hz))

    def set_debounce(self, ms):
        self.set("Debounce", GLib.Variant("i", ms))

    def set_angle_snapping(self, on):
        self.set("AngleSnapping", GLib.Variant("i", 1 if on else 0))

    def make_active(self):
        self.call("SetActive")
        self.props["IsActive"] = True


class Device(_Object):
    def __init__(self, conn, path):
        super().__init__(conn, path, "Device")
        self.profiles = [Profile(conn, p) for p in self.get("Profiles", [])]

    @property
    def name(self):
        return self.get("Name", "")

    def active_profile(self):
        return next((p for p in self.profiles if p.get("IsActive")), self.profiles[0] if self.profiles else None)

    def commit(self):
        """Write the changes to the mouse (asynchronous inside ratbagd)."""
        self.call("Commit", timeout=20000)


def available():
    """None if ratbagd can be used, otherwise a short reason."""
    try:
        conn = _bus()
        res = conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                             "ListActivatableNames", None, GLib.VariantType("(as)"),
                             Gio.DBusCallFlags.NONE, 3000, None)
        res2 = conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "NameHasOwner", GLib.Variant("(s)", (BUS_NAME,)), GLib.VariantType("(b)"),
                              Gio.DBusCallFlags.NONE, 3000, None)
    except GLib.Error as e:
        return e.message
    if BUS_NAME not in res.unpack()[0] and not res2.unpack()[0]:
        return "not-installed"
    return None


def devices():
    conn = _bus()
    manager = _Object(conn, MANAGER_PATH, "Manager")
    if manager.get("APIVersion") != API_VERSION:
        raise RatbagError(f"ratbagd API version {manager.get('APIVersion')} (XControl understands {API_VERSION})")
    return [Device(conn, p) for p in manager.get("Devices", [])]


def describe_mapping(mapping):
    """(action type, value) -> (label key, number) for the UI."""
    kind, value = mapping
    if kind == ACTION_BUTTON:
        return "button", value
    if kind == ACTION_SPECIAL:
        return "special", value - SPECIAL_BASE if value >= SPECIAL_BASE else value
    if kind == ACTION_NONE:
        return "none", 0
    if kind == ACTION_KEY:
        return "key", value
    if kind == ACTION_MACRO:
        return "macro", 0
    return "unknown", 0
