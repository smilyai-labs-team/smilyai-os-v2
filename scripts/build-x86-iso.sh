#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${SMILYAI_OUTPUT_DIR:-$PROJECT_DIR/dist}"
[[ "$(id -u)" == 0 ]] || { echo "Run in a disposable Debian 13 amd64 build VM as root."; exit 1; }
[[ "$(dpkg --print-architecture)" == amd64 ]] || { echo "An amd64 builder is required."; exit 1; }
for tool in lb python3 xorriso; do command -v "$tool" >/dev/null || { echo "Missing: $tool"; exit 1; }; done
mkdir -p "$OUTPUT_DIR" "$PROJECT_DIR/build"
BUILD_DIR="$(mktemp -d "$PROJECT_DIR/build/x86.XXXXXXXX")"
echo "Fresh build directory: $BUILD_DIR (kept for diagnostics)"
cp -a "$PROJECT_DIR/packaging/image/debian/config" "$BUILD_DIR/config"
python3 "$PROJECT_DIR/scripts/stage-runtime.py" "$BUILD_DIR/config/includes.chroot"
install -m755 "$PROJECT_DIR/packaging/image/debian/auto/config" "$BUILD_DIR/auto-config"
chmod 755 "$BUILD_DIR/config/hooks/live/0500-smilyai.hook.chroot"
cd "$BUILD_DIR"
./auto-config
lb build
test -s live-image-amd64.hybrid.iso
ISO_TARGET="$OUTPUT_DIR/SmilyAI-OS-0.3.1-x86_64.iso"
xorriso -indev live-image-amd64.hybrid.iso -report_el_torito plain 2>&1 | tee boot-report.txt
grep -q 'BIOS' boot-report.txt
grep -q 'UEFI' boot-report.txt
test ! -e "$ISO_TARGET" || { echo "Output already exists: $ISO_TARGET"; exit 1; }
install -m644 live-image-amd64.hybrid.iso "$ISO_TARGET"
cp boot-report.txt "$ISO_TARGET.boot-report.txt"
cp config/includes.chroot/opt/smilyai-os/runtime-manifest.json "$ISO_TARGET.runtime-manifest.json"
sha256sum "$ISO_TARGET" > "$ISO_TARGET.sha256"
echo "Built $ISO_TARGET; boot in a VM before distribution."
