# Maintainer: Your Name <you@example.com>
#
# Local build: run `makepkg -si` from this directory.
# For the AUR, replace the $startdir paths with a source=() tarball or git URL.

pkgname=mesa-panel
pkgver=0.6.0
pkgrel=1
pkgdesc="Catalyst-style control panel for Mesa: per-game AA, anisotropic filtering, VSync and FPS limit, plus xrandr display settings"
arch=('x86_64')
url="https://github.com/yourname/mesa-panel"
license=('MIT')
depends=('glibc' 'python' 'python-gobject' 'python-cairo' 'gtk3' 'xorg-xrandr')
makedepends=('vulkan-headers' 'gettext')
optdepends=(
  'vulkan-icd-loader: Vulkan and Proton game overrides'
  'wine: Direct3D 8/9 games with forced MSAA (WineD3D renderer)'
  'vkbasalt: post-process anti-aliasing and sharpening for Vulkan and DXVK games'
  'hwdata: full monitor manufacturer names'
  'polkit: test and install EDID overrides (system-wide mode list)'
  'mesa-utils: "Test with glxgears" button'
  'vulkan-tools: "Test with vkcube" button'
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
