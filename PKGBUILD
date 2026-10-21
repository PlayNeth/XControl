# Maintainer: Your Name <you@example.com>
#
# Local build: run `makepkg -si` from this directory.
# For the AUR, replace the $startdir paths with a source=() tarball or git URL.

pkgname=xcontrol
pkgver=0.28.6
pkgrel=1
pkgdesc="Catalyst-style X11 control panel: per-game graphics settings, displays, input devices, controllers and system information"
arch=('x86_64')
url="https://github.com/yourname/xcontrol"
license=('MIT')
provides=('mesa-panel')
conflicts=('mesa-panel')
replaces=('mesa-panel')
depends=('glibc' 'python' 'python-gobject' 'python-cairo' 'gtk3' 'libepoxy' 'libglvnd' 'libx11' 'libxext' 'libxrandr'
         'libxss' 'xorg-xrandr' 'xorg-xinput' 'xorg-setxkbmap' 'xorg-xset')
makedepends=('vulkan-headers' 'gettext')
optdepends=(
  'vulkan-icd-loader: Vulkan and Proton game overrides'
  'wine: Direct3D 8/9 games with forced MSAA (WineD3D renderer)'
  'vkbasalt: post-process anti-aliasing and sharpening for Vulkan and DXVK games (AUR)'
  'libratbag: gaming mouse DPI, polling rate, buttons and lighting (ratbagd)'
  'xf86-input-libinput: mouse and touchpad settings (the usual X input driver)'
  'xsettingsd: open apps follow theme changes right away (Appearance)'
  'xorg-xrdb: cursor and font settings for X programs (Appearance)'
  'xorg-xsetroot: desktop cursor (Appearance)'
  'xorg-xprop: "Check an app" (Appearance) and "Pick a window" (i3 page)'
  "i3-wm: XControl's i3 config (Window Manager page)"
  'qt5ct: Qt 5 apps follow the icon theme and font'
  'qt6ct: Qt 6 apps follow the icon theme and font'
  'kmod: module descriptions and parameter help on the System page (modinfo)'
  'xss-lock: screen lock when idle and before suspend (Desktop page)'
  'i3lock: screen locker that can show the wallpaper (or xsecurelock, slock)'
  "polybar: XControl's bar (Bar & Compositor page)"
  'picom: compositor: shadows, fading, transparency, no tearing (Bar & Compositor page)'
  'dunst: notifications (Notifications page)'
  "rofi: menu for a notification's actions (dmenu works too)"
  'poweralertd: battery and power alerts (Notifications page)'
  'libpulse: sound devices and profiles (pactl, Sound page)'
  'pipewire: sample rate and buffer size on the Sound page (pw-metadata), notification sounds (pw-play)'
  'pipewire-pulse: PulseAudio programs and pactl on PipeWire (Sound page)'
  'wireplumber: renaming, hiding and waking sound devices'
  'sound-theme-freedesktop: the Test sound on the Sound page'
  'desktop-file-utils: your own launchers on the Default Apps page'
  'ttf-nerd-fonts-symbols: icons in the bar'
  "pavucontrol: the mixer (Sound page, and right-click on the bar's volume)"
  'power-profiles-daemon: power saver / balanced / performance on the Power page (or tuned-ppd)'
  'polkit-gnome: a polkit agent for password prompts on i3 (any agent works)'
  'accountsservice: your own picture shows on the login screen without a password'
  'hwdata: full monitor manufacturer, graphics card and network adapter names'
  'polkit: EDID overrides, kernel modules, X server options, user accounts, time, languages, power buttons and USB controller polling (needs a polkit agent)'
  'mesa-utils: OpenGL and Mesa versions on the System page, "Test with glxgears" button'
  'vulkan-tools: Vulkan version on the System page, "Test with vkcube" button'
)
# The controller udev rules (/usr/lib/udev/rules.d/70-xcontrol-controllers.rules) apply to
# controllers connected after installing: reconnect a DualShock 4 once.
source=()
sha256sums=()

build() {
  make -C "$startdir" BUILDDIR="$srcdir/build"
}

package() {
  make -C "$startdir" BUILDDIR="$srcdir/build" DESTDIR="$pkgdir" PREFIX=/usr install
  install -Dm644 "$startdir/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
