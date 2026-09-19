# Maintainer: Davide Galassi <davxy@datawok.net>
pkgname=corral
pkgver=0.1.0
pkgrel=1
pkgdesc="Run a shell with the current directory writable and the rest of the host read only"
arch=('any')
url="https://github.com/davxy/corral"
license=('MIT')
depends=('python' 'bubblewrap')
optdepends=('passt: the private network mode')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
# Run 'updpkgsums' once the tag exists.
sha256sums=('SKIP')

package() {
    cd "$pkgname-$pkgver"
    install -Dm755 corral "$pkgdir/usr/bin/corral"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
    install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}
