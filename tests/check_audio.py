"""Sound: the PipeWire and WirePlumber drop-ins (0.5 and 0.4 forms)."""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, "config"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from xcontrol import audio as A  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


expect("nothing set, nothing written", (A.pipewire_conf(A.normalize({})), A.pulse_conf(A.normalize({})),
                                        A.wireplumber_conf(A.normalize({}), (0, 5))), (None, None, None))
a = A.normalize({"rate": 44100, "follow_rate": True, "latency": "low", "no_suspend": True,
                 "devices": {"alsa_output.pci-0000_0b_00.6.analog-stereo": {"name": 'CRT "speakers"', "priority": 3000},
                             "alsa_card.pci-0000_0b_00.1": {"hidden": True},
                             "bad name; rm": {"name": "x"}, "alsa_input.usb-mic": {}}})
expect("bad and empty device entries dropped", sorted(a["devices"]),
       ["alsa_card.pci-0000_0b_00.1", "alsa_output.pci-0000_0b_00.6.analog-stereo"])
pw = A.pipewire_conf(a)
for line in ("default.clock.rate = 44100", "default.clock.allowed-rates = [ 44100 48000 88200 96000 176400 192000 ]",
             "default.clock.quantum = 256", "default.clock.min-quantum = 64"):
    expect(f"pipewire: {line}", line in pw, True)
expect("pulse", "pulse.default.req = 256/44100" in A.pulse_conf(a), True)
wp5 = A.wireplumber_conf(a, (0, 5))
for line in ('matches = [ { node.name = "~alsa_output.*" } ]', "session.suspend-timeout-seconds = 0",
             'matches = [ { device.name = "alsa_card.pci-0000_0b_00.1" } ]', "device.disabled = true",
             'node.description = "CRT \\"speakers\\""', "priority.session = 3000"):
    expect(f"wireplumber 0.5: {line}", line in wp5, True)
expect("braces balance", wp5.count("{") == wp5.count("}") and wp5.count("[") == wp5.count("]"), True)
wp4 = A.wireplumber_conf(a, (0, 4))
for line in ('{ "node.name", "matches", "alsa_output.*" }', '["device.disabled"] = true',
             '["node.description"] = "CRT \\"speakers\\"",'):
    expect(f"wireplumber 0.4: {line}", line in wp4, True)

expect("written", A.write(a, (0, 5)), {"pipewire", "pulse", "wireplumber"})
expect("unchanged", A.write(a, (0, 5)), set())
expect("0.5 file", os.path.exists(os.path.join(tmp, "config", "wireplumber", "wireplumber.conf.d", "50-xcontrol.conf")),
       True)
expect("back to defaults removes them", A.write(A.normalize({}), (0, 5)), {"pipewire", "pulse", "wireplumber"})
expect("removed", os.path.exists(A.pipewire_path()), False)

# Bluetooth: its own monitor; a headset's output/input match its address, in every profile
bt = A.normalize({"devices": {"bluez_output.AC_80_0A_12_34_56.1": {"name": "My headset", "priority": 3000},
                              "bluez_input.AC_80_0A_12_34_56.0": {"hidden": True},
                              "bluez_card.AC_80_0A_12_34_56": {"name": "Headset"}}})
names = ("bluez_output.AC_80_0A_12_34_56.1", "bluez_card.X", "v4l2_input.cam")
expect("bluetooth can be configured", [A.configurable(n) for n in names], [True, True, False])
w = A.wireplumber_conf(bt, (0, 5))
for line in ("monitor.bluez.rules = [",
             'matches = [ { api.bluez5.address = "AC:80:0A:12:34:56" media.class = "Audio/Sink" } ]',
             'matches = [ { api.bluez5.address = "AC:80:0A:12:34:56" media.class = "Audio/Source" } ]',
             'node.description = "My headset"', "node.disabled = true",
             'matches = [ { device.name = "bluez_card.AC_80_0A_12_34_56" } ]', 'device.description = "Headset"'):
    expect(f"0.5 bluetooth: {line}", line in w, True)
expect("0.5: no alsa section when there's nothing for it", "monitor.alsa.rules" in w, False)
expect("0.5 braces balance", w.count("{") == w.count("}") and w.count("[") == w.count("]"), True)
expect("0.4: alsa file empty", A.wireplumber_conf(bt, (0, 4), "alsa"), None)
w4 = A.wireplumber_conf(bt, (0, 4), "bluez")
for line in ("table.insert(bluez_monitor.rules, {",
             '{ "api.bluez5.address", "equals", "AC:80:0A:12:34:56" }, { "media.class", "equals", "Audio/Sink" }, },'):
    expect(f"0.4 bluetooth: {line}", line in w4, True)
expect("0.4 bluetooth file", A.wireplumber_path((0, 4), "bluez").endswith("bluetooth.lua.d/51-xcontrol.lua"), True)
expect("0.4 written to both", (A.write(bt, (0, 4)), os.path.exists(A.wireplumber_path((0, 4), "bluez")),
                               os.path.exists(A.wireplumber_path((0, 4), "alsa"))),
       ({"wireplumber"}, True, False))
A.write(A.normalize({}), (0, 4))
expect("0.4 removed", os.path.exists(A.wireplumber_path((0, 4), "bluez")), False)

# pactl prints numbers the local way unless told otherwise (pt_BR: "0,000000" breaks its JSON)
import tempfile as _tf  # noqa: E402
_bin = _tf.mkdtemp()
with open(os.path.join(_bin, "pactl"), "w") as f:
    f.write("""#!/bin/sh
dec=,; srv='Nome do servidor'
[ "$LC_ALL" = C ] && dec=. && srv='Server Name'
case "$*" in
  "info") echo "$srv: PulseAudio (on PipeWire 1.4.9)";;
  "-f json list sinks") echo "[{\\"name\\":\\"alsa_output.pci-0000_0b_00.4.analog-stereo\\",\\"description\\":\\"Speakers\\",\\"balance\\":0${dec}000000}]";;
  *) echo "[]";;
esac
""")
os.chmod(os.path.join(_bin, "pactl"), 0o755)
_path = os.environ["PATH"]
os.environ.update(PATH=_bin + os.pathsep + _path, LC_ALL="pt_BR.UTF-8", LANG="pt_BR.UTF-8")
try:
    expect("outputs listed in pt_BR too", [o["name"] for o in A.outputs()],
           ["alsa_output.pci-0000_0b_00.4.analog-stereo"])
    expect("server found in pt_BR too", A.server() is not None and "PipeWire" in str(A.server()), True)
finally:
    os.environ["PATH"] = _path

print("check_audio:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
