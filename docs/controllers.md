# Controllers

A replacement for sc-controller / DS4Windows-style tools for PlayStation
controllers: the **DualShock 4** (both models and the USB adapter) and the
**DualSense** (and DualSense Edge), over USB or Bluetooth. Turn on "Use XControl
for controllers"; a small service (`xcontrol --pads`) then runs with the desktop
service and picks up controllers as they connect.

- **Light bar**: color and brightness (0 turns it off), set through the kernel
  driver's LEDs (DualShock 4: `/sys/class/leds/inputN:red|green|blue|global`;
  DualSense: the multicolor `inputN:rgb:indicator`), so rumble doesn't reset
  it. Changes apply right away.
- **DualSense player lights**: the player number (1–4, in the order controllers
  connect, with the PS5's patterns) or off.
- **DualSense adaptive triggers**: for L2 and R2, normal, resistance from a
  point of the pull on, a click like a gun's trigger between two points, or
  shaking, with the strength (and the shaking's frequency). XControl sends them
  in the controller's output report through its hidraw node, in the fields the
  kernel driver leaves alone, so they stay while the driver changes the light
  bar or rumbles. The effect formats are the ones documented by Nielk1 (as
  Steam and DSX use). The triggers go back to normal when the service stops.
- **Report rate over Bluetooth (DualShock 4)**: Linux's driver asks the
  controller for a report every 4 ms (250 Hz). XControl sends it the interval
  you pick (1, 2, 4 or 8 ms) through its hidraw node, right away and whenever
  it reconnects; the page shows the rate actually measured. Bluetooth itself is
  the ceiling: a full DualShock 4 report needs at least two radio slots, so 1 ms
  usually lands around 500–800 Hz depending on the adapter (Wi-Fi + Bluetooth
  combo cards share their radio and sit at the low end). That's still faster
  than the cable: over USB the controller itself usually won't go past 250 Hz.
  The DualSense picks its own Bluetooth rate.
- **Report rate over USB**: Linux picks the USB polling interval, so this is
  usbhid's `jspoll` setting, which covers every USB gamepad. It asks for your
  password (`xcontrol-controller-helper`), is kept for the next boots
  (`/etc/tmpfiles.d/xcontrol-usbhid.conf`, plus `/etc/modprobe.d` when usbhid is
  a module), and reconnects a plugged-in DualShock 4 so it applies now. Faster
  polling only helps if the controller has new data that often: most DualShock
  4s produce 250 reports per second over USB no matter how often they're asked
  (the measured rate on the page tells). Other USB gamepads can benefit.
- **Xbox 360 controller for games**: games see a virtual Xbox 360 pad (uinput,
  045e:028e, the same as xpad) instead of the real controller. Rumble from the
  game is passed on to the controller.
- **Hiding the real controller**: SDL, Wine/Proton and Steam find controllers
  through their device files (the raw HID one too), so grabbing the input isn't
  enough. Once the service has the controller's files open, a small root helper
  (`xcontrol-controller-hide`, allowed without a password for the active
  session, and only for PlayStation controllers' device files) takes your
  user's access to them away; it gives it back when you untick it or the
  service stops, and a reconnected controller gets it from udev as usual. Games
  already running keep what they had open. Being in the `input` group defeats
  this (every program can read every input device then). Steam has its own
  controller support: turn off "PlayStation Configuration Support" in Steam, or
  it uses the real controller as well.
- **Button remapping**: every button (the touchpad click, and the DualSense
  Edge's back paddles and Fn buttons too) can be any Xbox button, a trigger, a
  d-pad direction or nothing. L2/R2 stay analog while they're mapped to LT/RT.
- **Touchpad**: it can keep moving the mouse pointer, or be hidden and used
  for gestures: its click as one button, two halves or four corners (each its
  own button); quick swipes up, down, left and right as buttons (a short
  press); or sliding a finger as the left or right stick, from where the finger
  lands (a fifth of the touchpad's width is a full push), added to the real
  stick.
- **Gyro aiming**: turn the controller to aim, either as a separate virtual
  mouse ("XControl gyro mouse", the most precise) or added to the virtual Xbox
  pad's right stick (works in every game; set the game's stick deadzone on the
  page so small turns get past it). It can be always on, on while a button is
  held (L2 by default), toggled by a button, or off while a button is held;
  touching the touchpad counts as a button too. "Around the way you face"
  (player space) uses the accelerometer to turn around the real vertical
  however you hold the controller; plain yaw and roll are there too. Slow
  movement is smoothed and tiny movement (hand tremor) is tightened away, while
  quick turns stay raw. The gyro's drift is learned whenever the controller lies
  still for a moment, or on request with "Calibrate now". Speed is in mouse
  dots per degree turned, so it pairs with the game's mouse sensitivity.
- **Layouts per game**: a game can have its own buttons, gyro, light bar,
  triggers and touchpad gestures. The service watches which window is in front
  (`_NET_ACTIVE_WINDOW`: its class, like `steam_app_1245620`, and the program
  behind it, like `eldenring.exe` for a Proton game) and switches layouts in
  place, without the virtual pad going away. Patterns can use `*`
  (`steam_app_*`). "New for a game…" offers the programs recently in front, or
  a click on the game's window. The report rate, what games see and the player
  lights are the same for every game.

Permissions come from `/usr/lib/udev/rules.d/70-xcontrol-controllers.rules`:
`/dev/uinput`, the controllers' hidraw nodes, motion sensors and touchpads, and
their light bar and player LEDs for the logged-in user. They apply to
controllers connected after installing, so reconnect the controller once (or
reboot). Stop sc-controller (`scc-daemon`) first, or both will drive the
controller and games see an extra pad.
