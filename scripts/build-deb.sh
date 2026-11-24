#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/release.env"
ARCH="$(dpkg --print-architecture)"
case "$ARCH" in amd64|arm64) ;; *) echo "unsupported Debian architecture: $ARCH" >&2; exit 1;; esac
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PKG="$WORK/pkg"
mkdir -p "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/share/doc/codez"
CGO_ENABLED=0 go build -C "$ROOT" -trimpath -buildvcs=false -ldflags="-s -w -X main.version=$VERSION -X main.build=$VBUILD -X main.release=$VRELEASE" -o "$PKG/usr/bin/codez" ./cmd/codez
install -m644 "$ROOT/LICENSE" "$PKG/usr/share/doc/codez/copyright"
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: codez
Version: $VERSION-$VRELEASE
Section: devel
Priority: optional
Architecture: $ARCH
Maintainer: AuxiaCorp
Depends: ca-certificates, coreutils
Recommends: git
Homepage: https://github.com/AuxiaCorp/CodEz
Description: CodEz terminal coding agent
CONTROL
OUT="$ROOT/codez#$VBUILD-$VRELEASE.deb"
dpkg-deb --root-owner-group --build "$PKG" "$OUT" >/dev/null
echo "$OUT"
