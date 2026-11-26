#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
root="$PWD"
mkdir -p dist
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
mkdir "$work/app"
cp -a studio_bridge "$work/app/"
find "$work/app" -type d -name __pycache__ -prune -exec rm -rf {} +
cp main.py "$work/app/__main__.py"
python3 -m zipapp "$work/app" -p '/usr/bin/env python3' -c -o "$root/dist/codez-studio-bridge.pyz"
chmod 755 "$root/dist/codez-studio-bridge.pyz"
version=$(python3 "$root/dist/codez-studio-bridge.pyz" --version)
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
if command -v dpkg-deb >/dev/null; then
    pkg="$work/pkg"
    install -d "$pkg/DEBIAN" "$pkg/usr/bin" "$pkg/usr/share/doc/codez-studio-bridge/examples"
    install -m755 dist/codez-studio-bridge.pyz "$pkg/usr/bin/codez-studio-bridge"
    install -m644 README.md "$pkg/usr/share/doc/codez-studio-bridge/README.md"
    install -m644 LICENSE "$pkg/usr/share/doc/codez-studio-bridge/copyright"
    install -m644 examples/*.json "$pkg/usr/share/doc/codez-studio-bridge/examples/"
    cat > "$pkg/DEBIAN/control" <<CONTROL
Package: codez-studio-bridge
Version: $version-1
Architecture: all
Maintainer: AuxiaCorp
Depends: python3 (>= 3.11)
Section: devel
Priority: optional
Description: Local MCP and visual automation bridge for CodEz Studio
 Local browser, desktop and DaVinci Resolve adapters; optional Python SDKs
 and target applications are installed separately by the operator.
CONTROL
    dpkg-deb --root-owner-group --build "$pkg" "$root/dist/codez-studio-bridge_${version}-1_all.deb"
fi
