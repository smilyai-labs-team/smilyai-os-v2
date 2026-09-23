#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
while IFS= read -r file; do bash -n "$file"; done < <(find scripts packaging -type f \( -name '*.sh' -o -name '*.hook.chroot' -o -name 'autostart' -o -path '*/usr/local/bin/*' \))
bash -n packaging/image/debian/auto/config
grep -q -- '--binary-image iso-hybrid' packaging/image/debian/auto/config
grep -q -- '--debian-installer live' packaging/image/debian/auto/config
grep -q "DEPLOY_COMPRESSION='xz'" packaging/image/raspberrypi/config
grep -q 'copy_previous' packaging/image/raspberrypi/stage-smily/prerun.sh
grep -q -- '--branch arm64' scripts/build-rpi-image.sh
test -f packaging/rootfs/usr/share/wayland-sessions/smilyai.desktop
test -f shell/assets/smilyai-logo.png
echo "Image definitions: syntax and structural checks passed; image creation not exercised."
