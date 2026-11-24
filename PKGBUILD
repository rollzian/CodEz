pkgname=codez
pkgver=0.7.2
pkgrel=1
pkgdesc='CodEz terminal coding agent'
arch=('x86_64')
url='https://github.com/AuxiaCorp/CodEz'
license=('MIT')
depends=('ca-certificates' 'coreutils')
optdepends=('git: repository tools')
makedepends=('go>=1.23')
source=()
sha256sums=()

build() {
  cd "$startdir"
  source release.env
  export CGO_ENABLED=0
  go build -trimpath -buildvcs=false -ldflags="-s -w -X main.version=$VERSION -X main.build=$VBUILD -X main.release=$VRELEASE" -o codez ./cmd/codez
}

check() {
  cd "$startdir"
  go test ./...
}

package() {
  cd "$startdir"
  install -Dm755 codez "$pkgdir/usr/bin/codez"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/codez/LICENSE"
}
