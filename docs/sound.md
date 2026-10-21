# Sound

Volumes, the default output and input, ports and card profiles are pavucontrol's job (**Open
the mixer** starts it). The Sound page covers what it can't do:

- **Devices**: each output, input and sound card's gear can **rename** it (the name every program
  shows), **hide** it from every program (e.g. the graphics card's HDMI audio you never use),
  **never let it sleep** (no pop and no lost first second, common with HDMI and USB DACs), and
  **prefer it whenever it's connected**. Hidden devices stay listed so they can come back.
  Bluetooth headsets and speakers work too; their settings follow the headset's address, so
  they hold in music and headset-with-mic mode alike.
- **Sound system (PipeWire)**: the sample rate, **follow what's playing** (music at 44.1 kHz
  plays unconverted; allowed rates), the **buffer size** (larger against crackling, smaller for
  less delay in games and music), and keeping every output awake.

Sample rate and buffer size change right away (PipeWire's settings metadata) and are saved in
`~/.config/pipewire/pipewire.conf.d/50-xcontrol.conf` (and the PulseAudio-side
`pipewire-pulse.conf.d`); device settings go to
`~/.config/wireplumber/wireplumber.conf.d/50-xcontrol.conf` (WirePlumber 0.5, or
`main.lua.d` and `bluetooth.lua.d` scripts for 0.4) and restart WirePlumber.
