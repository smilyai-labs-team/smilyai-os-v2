#!/usr/bin/env bash
set -euo pipefail

REPO="${SMILYAI_REPO:-smilyai-labs-team/smilyai-os}"
ARTIFACT_NAME="${SMILYAI_ARTIFACT:-smilyai-0.3-x86_64-preview}"

STATE_DIR="${HOME}/.cache/smilyai-cloud-vm"
ARTIFACT_DIR="${STATE_DIR}/artifact"

QEMU_PID="${STATE_DIR}/qemu.pid"
NOVNC_PID="${STATE_DIR}/novnc.pid"
MONITOR="${STATE_DIR}/qemu-monitor.sock"
SERIAL_LOG="${STATE_DIR}/serial.log"

mkdir -p "${STATE_DIR}" "${ARTIFACT_DIR}"

echo "🔥 SmilyAI OS Cloud VM"
echo "Repository: ${REPO}"
echo "Artifact:   ${ARTIFACT_NAME}"
echo

# Don't accidentally launch two VMs.
if [[ -f "${QEMU_PID}" ]] && kill -0 "$(cat "${QEMU_PID}")" 2>/dev/null; then
    echo "QEMU is already running."
    echo "Run scripts/stop-cloud-vm.sh first if you want a fresh VM."
    exit 0
fi

if [[ -f "${NOVNC_PID}" ]] && kill -0 "$(cat "${NOVNC_PID}")" 2>/dev/null; then
    kill "$(cat "${NOVNC_PID}")" 2>/dev/null || true
fi

# Find an existing extracted ISO.
ISO="$(find "${ARTIFACT_DIR}" -maxdepth 2 -type f -name '*.iso' -print -quit 2>/dev/null || true)"

if [[ -z "${ISO}" ]]; then
    echo "Finding newest GitHub Actions artifact..."

    ARTIFACT_ID="$(
        gh api \
          -H "Accept: application/vnd.github+json" \
          "/repos/${REPO}/actions/artifacts?per_page=100" \
        | jq -r \
          --arg NAME "${ARTIFACT_NAME}" \
          '.artifacts
           | map(select(.name == $NAME and .expired == false))
           | sort_by(.created_at)
           | reverse
           | .[0].id // empty'
    )"

    if [[ -z "${ARTIFACT_ID}" ]]; then
        echo "ERROR: Could not find a non-expired artifact named:"
        echo "  ${ARTIFACT_NAME}"
        echo
        echo "Check that the workflow completed successfully."
        exit 1
    fi

    echo "Artifact ID: ${ARTIFACT_ID}"
    echo "Downloading artifact in the cloud..."

    rm -rf "${ARTIFACT_DIR}"
    mkdir -p "${ARTIFACT_DIR}"

    gh api \
      -H "Accept: application/vnd.github+json" \
      "/repos/${REPO}/actions/artifacts/${ARTIFACT_ID}/zip" \
      > "${STATE_DIR}/artifact.zip"

    echo "Extracting..."
    unzip -q "${STATE_DIR}/artifact.zip" -d "${ARTIFACT_DIR}"

    ISO="$(find "${ARTIFACT_DIR}" -type f -name '*.iso' -print -quit)"

    if [[ -z "${ISO}" ]]; then
        echo "ERROR: Artifact downloaded, but no .iso was found."
        exit 1
    fi
else
    echo "Reusing cached ISO."
fi

echo "ISO: ${ISO}"

rm -f "${MONITOR}" "${SERIAL_LOG}"

if [[ -r /dev/kvm && -w /dev/kvm ]]; then
    ACCEL="kvm"
    echo "Acceleration: KVM 🚀"
else
    ACCEL="tcg"
    echo "Acceleration: TCG (software emulation)"
fi

echo "Starting QEMU..."

qemu-system-x86_64 \
    -machine "q35,accel=${ACCEL}" \
    -cpu max \
    -smp 2 \
    -m 4096 \
    -boot d \
    -cdrom "${ISO}" \
    -vga std \
    -display none \
    -vnc 127.0.0.1:0 \
    -monitor "unix:${MONITOR},server,nowait" \
    -serial "file:${SERIAL_LOG}" \
    -daemonize \
    -pidfile "${QEMU_PID}"

echo "Starting noVNC..."

NOVNC_ROOT="/usr/share/novnc"

websockify \
    --web "${NOVNC_ROOT}" \
    0.0.0.0:6080 \
    127.0.0.1:5900 \
    > "${STATE_DIR}/novnc.log" 2>&1 &

echo $! > "${NOVNC_PID}"

sleep 1

echo
echo "✅ SmilyAI OS VM started."
echo
echo "Open:"
echo
echo "  http://localhost:6080/vnc.html?autoconnect=1&resize=scale"
echo
echo "If Codespaces forwards port 6080, open that forwarded URL"
echo "and append:"
echo
echo "  /vnc.html?autoconnect=1&resize=scale"
echo
echo "Serial log:"
echo "  ${SERIAL_LOG}"
