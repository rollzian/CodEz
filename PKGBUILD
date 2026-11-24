pkgname=codez
pkgver=0.7.7
pkgrel=1
pkgdesc='CodEz terminal coding agent'
arch=('x86_64')
url='https://github.com/rollzian/CodEz'
license=('MIT')
depends=('ca-certificates' 'coreutils')
optdepends=('git: repository tools')
makedepends=('go>=1.23')
source=()
sha256sums=()

prepare() {
  local work="$srcdir/codez-build"
  rm -rf -- "$work"
  mkdir -p "$work"
  cp -a -- "$startdir"/{cmd,internal,go.mod,release.env,LICENSE} "$work/"
  if [[ -f "$startdir/go.sum" ]]; then
    cp -a -- "$startdir/go.sum" "$work/"
  fi
}

build() {
  cd "$srcdir/codez-build"
  source release.env
  export CGO_ENABLED=0
  go build -trimpath -buildvcs=false -ldflags="-s -w -X main.version=$VERSION -X main.build=$VBUILD -X main.release=$VRELEASE" -o codez ./cmd/codez
}

check() {
  cd "$srcdir/codez-build"
  go test ./...
}

package() {
  cd "$srcdir/codez-build"
  install -Dm755 codez "$pkgdir/usr/bin/codez"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/codez/LICENSE"
}
