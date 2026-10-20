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

print("check_audio:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
