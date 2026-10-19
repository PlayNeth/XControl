# Maintainer: Your Name <you@example.com>
#
# Local build: run `makepkg -si` from this directory.
# For the AUR, replace the $startdir paths with a source=() tarball or git URL.

pkgname=xcontrol
pkgver=0.15.0
pkgrel=1
pkgdesc="Catalyst-style X11 control panel: per-game graphics settings, displays, input devices and system information"
arch=('x86_64')
url="https://github.com/yourname/xcontrol"
license=('MIT')
provides=('mesa-panel')
conflicts=('mesa-panel')
replaces=('mesa-panel')
depends=('glibc' 'python' 'python-gobject' 'python-cairo' 'gtk3' 'xorg-xrandr' 'xorg-xinput' 'xorg-setxkbmap' 'xorg-xset')
makedepends=('vulkan-headers' 'gettext')
optdepends=(
  'vulkan-icd-loader: Vulkan and Proton game overrides'
  'wine: Direct3D 8/9 games with forced MSAA (WineD3D renderer)'
  'vkbasalt: post-process anti-aliasing and sharpening for Vulkan and DXVK games'
  'libratbag: gaming mouse DPI, polling rate, buttons and lighting (ratbagd)'
  'xf86-input-libinput: mouse and touchpad settings (the usual X input driver)'
  'xsettingsd: open apps follow theme changes right away (Appearance)'
  'xorg-xrdb: cursor and font settings for X programs (Appearance)'
  'xorg-xsetroot: desktop cursor (Appearance)'
  'xorg-xprop: "Check an app" troubleshooter (Appearance)'
  'qt5ct: Qt 5 apps follow the icon theme and font'
  'qt6ct: Qt 6 apps follow the icon theme and font'
  'kmod: module descriptions and parameter help on the System page (modinfo)'
  'xss-lock: screen lock when idle and before suspend (Desktop page)'
  'i3lock: screen locker that can show the wallpaper (or xsecurelock, slock)'
  'hwdata: full monitor manufacturer, graphics card and network adapter names'
  'polkit: EDID overrides, kernel module parameters and user accounts (needs a polkit agent, e.g. polkit-gnome)'
  'mesa-utils: OpenGL and Mesa versions on the System page, "Test with glxgears" button'
  'vulkan-tools: Vulkan version on the System page, "Test with vkcube" button'
)
source=()
sha256sums=()

build() {
  make -C "$startdir" BUILDDIR="$srcdir/build"
}

package() {
  make -C "$startdir" BUILDDIR="$srcdir/build" DESTDIR="$pkgdir" PREFIX=/usr install
  install -Dm644 "$startdir/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
