#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${SMILYAI_OUTPUT_DIR:-$PROJECT_DIR/dist}"
: "${PI_GEN_REF:?Set PI_GEN_REF to a reviewed 40-character pi-gen arm64 commit}"
[[ "$PI_GEN_REF" =~ ^[0-9a-f]{40}$ ]] || { echo "PI_GEN_REF must be a full commit SHA."; exit 1; }
[[ "$(uname -m)" == aarch64 ]] || { echo "Use a native ARM64 Debian/Raspberry Pi OS builder with Docker."; exit 1; }
for tool in git python3 docker openssl xz; do command -v "$tool" >/dev/null || { echo "Missing: $tool"; exit 1; }; done
docker info >/dev/null
mkdir -p "$PROJECT_DIR/build" "$OUTPUT_DIR"
PI_GEN_DIR="$(mktemp -d "$PROJECT_DIR/build/pi-gen.XXXXXXXX")"
echo "Fresh build directory: $PI_GEN_DIR"
git clone --branch arm64 --single-branch https://github.com/RPi-Distro/pi-gen.git "$PI_GEN_DIR"
git -C "$PI_GEN_DIR" merge-base --is-ancestor "$PI_GEN_REF" origin/arm64
git -C "$PI_GEN_DIR" checkout --detach "$PI_GEN_REF"
cp -a "$PROJECT_DIR/packaging/image/raspberrypi/stage-smily" "$PI_GEN_DIR/stage-smily"
python3 "$PROJECT_DIR/scripts/stage-runtime.py" "$PI_GEN_DIR/stage-smily/00-install/files/rootfs"
chmod 755 "$PI_GEN_DIR/stage-smily/prerun.sh" "$PI_GEN_DIR/stage-smily/"*/*.sh
touch "$PI_GEN_DIR/stage2/SKIP_IMAGES"
PI_PASSWORD="${SMILYAI_PI_PASSWORD:-$(openssl rand -hex 16)}"
[[ "$PI_PASSWORD" =~ ^[A-Za-z0-9._-]{16,128}$ ]] || { echo "Password: 16–128 letters/digits/dot/underscore/hyphen."; exit 1; }
CREDENTIALS="$OUTPUT_DIR/SmilyAI-OS-0.3.1-rpi-arm64.credentials.txt"
test ! -e "$CREDENTIALS" || { echo "Credentials output already exists."; exit 1; }
printf 'Username: smily\nInitial password: %s\nChange with passwd after first login. Do not distribute this file.\n' "$PI_PASSWORD" > "$CREDENTIALS"
chmod 600 "$CREDENTIALS"
sed "s/@@FIRST_USER_PASS@@/$PI_PASSWORD/" "$PROJECT_DIR/packaging/image/raspberrypi/config" > "$PI_GEN_DIR/config"
trap 'sed -i "/^FIRST_USER_PASS=/d" "$PI_GEN_DIR/config"' EXIT
unset PI_PASSWORD SMILYAI_PI_PASSWORD
cd "$PI_GEN_DIR"
CONTAINER_NAME="smilyai-$(basename "$PI_GEN_DIR")" PRESERVE_CONTAINER=0 ./build-docker.sh
shopt -s nullglob
images=(deploy/*SmilyAI-OS-0.3.1*.img.xz)
[[ "${#images[@]}" == 1 ]] || { echo "Expected exactly one custom-stage image; inspect deploy/."; exit 1; }
xz -t "${images[0]}"
IMAGE_TARGET="$OUTPUT_DIR/SmilyAI-OS-0.3.1-rpi-arm64.img.xz"
test ! -e "$IMAGE_TARGET" || { echo "Output image already exists."; exit 1; }
install -m644 "${images[0]}" "$IMAGE_TARGET"
printf '%s\n' "$PI_GEN_REF" > "$IMAGE_TARGET.pi-gen-commit.txt"
sha256sum "$IMAGE_TARGET" > "$IMAGE_TARGET.sha256"
echo "Built $IMAGE_TARGET. Private initial login is in $CREDENTIALS."
