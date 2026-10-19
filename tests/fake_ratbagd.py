"""A stand-in for ratbagd on the session bus, implementing the parts of the
org.freedesktop.ratbag1 API (version 2) that XControl uses, with one pretend
gaming mouse. Writes a JSON log of Set/Commit calls to $FAKE_RATBAG_LOG.

Run: dbus-run-session -- python3 tests/fake_ratbagd.py & ... (XCONTROL_RATBAG_BUS=session)
"""
import json
import os
import sys

from gi.repository import Gio, GLib

BUS = "org.freedesktop.ratbag1"
I = "org.freedesktop.ratbag1."

XML = """
<node>
 <interface name="org.freedesktop.ratbag1.Manager">
  <property name="APIVersion" type="i" access="read"/>
  <property name="Devices" type="ao" access="read"/>
 </interface>
 <interface name="org.freedesktop.ratbag1.Device">
  <property name="Model" type="s" access="read"/>
  <property name="Name" type="s" access="read"/>
  <property name="FirmwareVersion" type="s" access="read"/>
  <property name="Profiles" type="ao" access="read"/>
  <method name="Commit"/>
  <signal name="Resync"/>
 </interface>
 <interface name="org.freedesktop.ratbag1.Profile">
  <property name="Index" type="u" access="read"/>
  <property name="Name" type="s" access="readwrite"/>
  <property name="Disabled" type="b" access="readwrite"/>
  <property name="IsActive" type="b" access="read"/>
  <property name="IsDirty" type="b" access="read"/>
  <property name="Resolutions" type="ao" access="read"/>
  <property name="Buttons" type="ao" access="read"/>
  <property name="Leds" type="ao" access="read"/>
  <property name="AngleSnapping" type="i" access="readwrite"/>
  <property name="Debounce" type="i" access="readwrite"/>
  <property name="Debounces" type="au" access="read"/>
  <property name="ReportRate" type="u" access="readwrite"/>
  <property name="ReportRates" type="au" access="read"/>
  <method name="SetActive"/>
 </interface>
 <interface name="org.freedesktop.ratbag1.Resolution">
  <property name="Index" type="u" access="read"/>
  <property name="Capabilities" type="au" access="read"/>
  <property name="IsActive" type="b" access="read"/>
  <property name="IsDefault" type="b" access="read"/>
  <property name="IsDisabled" type="b" access="readwrite"/>
  <property name="Resolution" type="v" access="readwrite"/>
  <property name="Resolutions" type="au" access="read"/>
  <method name="SetActive"/>
  <method name="SetDefault"/>
 </interface>
 <interface name="org.freedesktop.ratbag1.Button">
  <property name="Index" type="u" access="read"/>
  <property name="Mapping" type="(uv)" access="readwrite"/>
  <property name="ActionTypes" type="au" access="read"/>
 </interface>
 <interface name="org.freedesktop.ratbag1.Led">
  <property name="Index" type="u" access="read"/>
  <property name="Mode" type="u" access="readwrite"/>
  <property name="Modes" type="au" access="read"/>
  <property name="Color" type="(uuu)" access="readwrite"/>
  <property name="ColorDepth" type="u" access="read"/>
  <property name="EffectDuration" type="u" access="readwrite"/>
  <property name="Brightness" type="u" access="readwrite"/>
 </interface>
</node>
"""

DPIS = list(range(100, 16001, 50))
objects = {}   # path -> (interface name, {prop: GLib.Variant})
log = []


def add(path, iface, props):
    objects[path] = (I + iface, props)


def build():
    dev = "/org/freedesktop/ratbag1/device/event5"
    profiles = []
    for p in range(2):
        pp = f"{dev}/p{p}"
        profiles.append(pp)
        res, btn, led = [], [], []
        for r, dpi in enumerate([400, 800, 1600, 3200, 6400]):
            rp = f"{pp}/r{r}"
            res.append(rp)
            add(rp, "Resolution", {
                "Index": GLib.Variant("u", r), "Capabilities": GLib.Variant("au", [2]),
                "IsActive": GLib.Variant("b", r == 1), "IsDefault": GLib.Variant("b", r == 1),
                "IsDisabled": GLib.Variant("b", False),
                "Resolution": GLib.Variant("v", GLib.Variant("u", dpi)),
                "Resolutions": GLib.Variant("au", DPIS)})
        mappings = [1, 2, 3, 4, 5]
        for b in range(8):
            bp = f"{pp}/b{b}"
            btn.append(bp)
            if b < 5:
                m = (1, GLib.Variant("u", mappings[b]))
            elif b == 5:
                m = (2, GLib.Variant("u", 0x40000007))   # DPI cycle up
            elif b == 6:
                m = (3, GLib.Variant("u", 30))            # a key (KEY_A)
            else:
                m = (0, GLib.Variant("u", 0))
            add(bp, "Button", {"Index": GLib.Variant("u", b), "Mapping": GLib.Variant("(uv)", m),
                               "ActionTypes": GLib.Variant("au", [0, 1, 2, 3, 4])})
        for li, (depth, modes) in enumerate([(1, [0, 1, 2, 3]), (0, [0, 1])]):
            lp = f"{pp}/l{li}"
            led.append(lp)
            add(lp, "Led", {"Index": GLib.Variant("u", li), "Mode": GLib.Variant("u", 1),
                            "Modes": GLib.Variant("au", modes),
                            "Color": GLib.Variant("(uuu)", (255, 0, 0) if depth == 1 else (0, 0, 0)),
                            "ColorDepth": GLib.Variant("u", depth),
                            "EffectDuration": GLib.Variant("u", 1000), "Brightness": GLib.Variant("u", 255)})
        add(pp, "Profile", {
            "Index": GLib.Variant("u", p), "Name": GLib.Variant("s", f"Profile {p + 1}"),
            "Disabled": GLib.Variant("b", False), "IsActive": GLib.Variant("b", p == 0),
            "IsDirty": GLib.Variant("b", False),
            "Resolutions": GLib.Variant("ao", res), "Buttons": GLib.Variant("ao", btn), "Leds": GLib.Variant("ao", led),
            "AngleSnapping": GLib.Variant("i", 0), "Debounce": GLib.Variant("i", 4),
            "Debounces": GLib.Variant("au", [2, 4, 6, 8, 10]),
            "ReportRate": GLib.Variant("u", 1000), "ReportRates": GLib.Variant("au", [125, 250, 500, 1000])})
    add(dev, "Device", {"Model": GLib.Variant("s", "usb:046d:c08b:0"),
                        "Name": GLib.Variant("s", "Logitech G Pro Gaming Mouse"),
                        "FirmwareVersion": GLib.Variant("s", "1.2"), "Profiles": GLib.Variant("ao", profiles)})
    add("/org/freedesktop/ratbag1", "Manager", {"APIVersion": GLib.Variant("i", 2),
                                                "Devices": GLib.Variant("ao", [dev])})


def dump():
    path = os.environ.get("FAKE_RATBAG_LOG")
    if path:
        with open(path, "w") as f:
            json.dump(log, f)


def on_call(conn, sender, path, iface, method, params, inv):
    log.append({"call": method, "path": path})
    if method == "SetActive":
        kind = objects[path][0]
        parent = path.rsplit("/", 1)[0]
        for p, (k, props) in objects.items():
            if k == kind and p.rsplit("/", 1)[0] == parent:
                props["IsActive"] = GLib.Variant("b", p == path)
    elif method == "SetDefault":
        parent = path.rsplit("/", 1)[0]
        for p, (k, props) in objects.items():
            if k == I + "Resolution" and p.rsplit("/", 1)[0] == parent:
                props["IsDefault"] = GLib.Variant("b", p == path)
    dump()
    inv.return_value(None)


def on_get(conn, sender, path, iface, prop):
    v = objects[path][1][prop]
    return v


def on_set(conn, sender, path, iface, prop, value):
    props = objects[path][1]
    if prop == "Resolution":
        if value.get_type_string() != "v":
            raise GLib.Error("Resolution must be a variant")
        inner = value.unpack()
        dpi = inner[0] if isinstance(inner, tuple) else inner
        if dpi not in DPIS:
            raise GLib.Error("invalid resolution")
    props[prop] = value
    log.append({"set": prop, "path": path, "value": value.unpack()})
    dump()
    return True


def main():
    build()
    info = Gio.DBusNodeInfo.new_for_xml(XML)

    def acquired(conn, name):
        for path, (iface, _props) in objects.items():
            conn.register_object(path, info.lookup_interface(iface), on_call, on_get, on_set)
        print("ready", flush=True)

    Gio.bus_own_name(Gio.BusType.SESSION, BUS, Gio.BusNameOwnerFlags.NONE, acquired, None,
                     lambda *_a: sys.exit("could not own the name"))
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
