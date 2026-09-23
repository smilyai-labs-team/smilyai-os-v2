#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# SmilyAI OS — Codespaces/QEMU cloud VM launcher
# ─────────────────────────────────────────────────────────────

REPO="${SMILYAI_REPO:-smilyai-labs-team/smilyai-os-v2}"
ARTIFACT_NAME="${SMILYAI_ARTIFACT:-smilyai-0.3-x86_64-preview}"

STATE_DIR="${HOME}/.cache/smilyai-cloud-vm"
ARTIFACT_DIR="${STATE_DIR}/artifact"

QEMU_PID="${STATE_DIR}/qemu.pid"
NOVNC_PID="${STATE_DIR}/novnc.pid"
MONITOR="${STATE_DIR}/qemu-monitor.sock"
SERIAL_LOG="${STATE_DIR}/serial.log"
NOVNC_LOG="${STATE_DIR}/novnc.log"

mkdir -p "${STATE_DIR}" "${ARTIFACT_DIR}"

echo
echo "══════════════════════════════════════════"
echo "🔥 SmilyAI OS Cloud VM"
echo "══════════════════════════════════════════"
echo "Repository: ${REPO}"
echo "Artifact:   ${ARTIFACT_NAME}"
echo

# ─────────────────────────────────────────────────────────────
# Check dependencies
# ─────────────────────────────────────────────────────────────

for command in gh jq unzip qemu-system-x86_64 websockify; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        echo "❌ Missing required command: ${command}"
        echo
        echo "If you're in Codespaces, rebuild the container so the"
        echo ".devcontainer/Dockerfile is applied."
        exit 1
    fi
done

# ─────────────────────────────────────────────────────────────
# Prevent duplicate VMs
# ─────────────────────────────────────────────────────────────

if [[ -f "${QEMU_PID}" ]]; then
    OLD_PID="$(cat "${QEMU_PID}" 2>/dev/null || true)"

    if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
        echo "⚠️ QEMU is already running (PID ${OLD_PID})."
        echo
        echo "For a fresh boot run:"
        echo
        echo "  bash scripts/stop-cloud-vm.sh"
        echo "  bash scripts/start-cloud-vm.sh"
        exit 0
    else
        rm -f "${QEMU_PID}"
    fi
fi

# Kill stale noVNC process if necessary.
if [[ -f "${NOVNC_PID}" ]]; then
    OLD_NOVNC_PID="$(cat "${NOVNC_PID}" 2>/dev/null || true)"

    if [[ -n "${OLD_NOVNC_PID}" ]] &&
       kill -0 "${OLD_NOVNC_PID}" 2>/dev/null; then
        echo "Stopping stale noVNC process..."
        kill "${OLD_NOVNC_PID}" 2>/dev/null || true
    fi

    rm -f "${NOVNC_PID}"
fi

# ─────────────────────────────────────────────────────────────
# Find newest GitHub Actions artifact
# ─────────────────────────────────────────────────────────────

echo "🔎 Finding newest non-expired x86_64 artifact..."

ARTIFACT_JSON="$(
    gh api \
        -H "Accept: application/vnd.github+json" \
        "/repos/${REPO}/actions/artifacts?per_page=100"
)"

ARTIFACT_ID="$(
    printf '%s' "${ARTIFACT_JSON}" |
        jq -r \
            --arg NAME "${ARTIFACT_NAME}" \
            '
            .artifacts
            | map(
                select(
                    .name == $NAME
                    and .expired == false
                )
            )
            | sort_by(.created_at)
            | reverse
            | .[0].id // empty
            '
)"

ARTIFACT_CREATED="$(
    printf '%s' "${ARTIFACT_JSON}" |
        jq -r \
            --arg NAME "${ARTIFACT_NAME}" \
            '
            .artifacts
            | map(
                select(
                    .name == $NAME
                    and .expired == false
                )
            )
            | sort_by(.created_at)
            | reverse
            | .[0].created_at // empty
            '
)"

if [[ -z "${ARTIFACT_ID}" ]]; then
    echo
    echo "❌ Could not find a non-expired artifact named:"
    echo
    echo "   ${ARTIFACT_NAME}"
    echo
    echo "Repository:"
    echo
    echo "   ${REPO}"
    echo
    echo "Make sure the x86_64 workflow completed successfully."
    exit 1
fi

echo "✅ Artifact ID: ${ARTIFACT_ID}"
echo "   Created:     ${ARTIFACT_CREATED}"

# ─────────────────────────────────────────────────────────────
# Cache artifact by ID
# ─────────────────────────────────────────────────────────────

CACHED_ID_FILE="${STATE_DIR}/artifact-id"
CACHED_ID=""

if [[ -f "${CACHED_ID_FILE}" ]]; then
    CACHED_ID="$(cat "${CACHED_ID_FILE}" 2>/dev/null || true)"
fi

ISO=""

if [[ "${CACHED_ID}" == "${ARTIFACT_ID}" ]]; then
    ISO="$(
        find "${ARTIFACT_DIR}" \
            -type f \
            -name '*.iso' \
            -print \
            -quit 2>/dev/null || true
    )"

    if [[ -n "${ISO}" ]]; then
        echo "♻️ Reusing cached copy of this exact artifact."
    fi
fi

# ─────────────────────────────────────────────────────────────
# Download if necessary
# ─────────────────────────────────────────────────────────────

if [[ -z "${ISO}" ]]; then
    echo
    echo "☁️ Downloading artifact inside Codespaces..."
    echo "   (Your local internet does NOT need to download the ISO.)"

    rm -rf "${ARTIFACT_DIR}"
    mkdir -p "${ARTIFACT_DIR}"
    rm -f "${STATE_DIR}/artifact.zip"

    gh api \
        -H "Accept: application/vnd.github+json" \
        "/repos/${REPO}/actions/artifacts/${ARTIFACT_ID}/zip" \
        > "${STATE_DIR}/artifact.zip"

    echo
    echo "📦 Extracting artifact..."

    unzip -q \
        "${STATE_DIR}/artifact.zip" \
        -d "${ARTIFACT_DIR}"

    ISO="$(
        find "${ARTIFACT_DIR}" \
            -type f \
            -name '*.iso' \
            -print \
            -quit
    )"

    if [[ -z "${ISO}" ]]; then
        echo
        echo "❌ Artifact downloaded successfully, but no ISO was found."
        echo
        echo "Contents:"
        find "${ARTIFACT_DIR}" -maxdepth 3 -type f -print
        exit 1
    fi

    printf '%s\n' "${ARTIFACT_ID}" > "${CACHED_ID_FILE}"
fi

echo
echo "💿 ISO:"
echo "   ${ISO}"

# ─────────────────────────────────────────────────────────────
# Choose acceleration
# ─────────────────────────────────────────────────────────────

if [[ -r /dev/kvm && -w /dev/kvm ]]; then
    ACCEL="kvm"
    CPU="host"

    echo
    echo "🚀 Hardware acceleration: KVM"
else
    ACCEL="tcg"
    CPU="max"

    echo
    echo "🐌 Hardware acceleration unavailable."
    echo "   Falling back to QEMU TCG software emulation."
    echo "   Booting may take a while."
fi

# ─────────────────────────────────────────────────────────────
# Clean old runtime state
# ─────────────────────────────────────────────────────────────

rm -f \
    "${MONITOR}" \
    "${SERIAL_LOG}" \
    "${NOVNC_LOG}"

# ─────────────────────────────────────────────────────────────
# Start QEMU
# ─────────────────────────────────────────────────────────────

echo
echo "🖥️ Starting SmilyAI OS..."

qemu-system-x86_64 \
    -machine "q35,accel=${ACCEL}" \
    -cpu "${CPU}" \
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

sleep 1

if [[ ! -f "${QEMU_PID}" ]]; then
    echo "❌ QEMU did not create a PID file."
    exit 1
fi

QEMU_PROCESS="$(cat "${QEMU_PID}")"

if ! kill -0 "${QEMU_PROCESS}" 2>/dev/null; then
    echo "❌ QEMU exited immediately."
    echo
    echo "Serial output:"
    cat "${SERIAL_LOG}" 2>/dev/null || true
    exit 1
fi

echo "✅ QEMU running (PID ${QEMU_PROCESS})"

# ─────────────────────────────────────────────────────────────
# Start noVNC
# ─────────────────────────────────────────────────────────────

NOVNC_ROOT="/usr/share/novnc"

if [[ ! -d "${NOVNC_ROOT}" ]]; then
    echo "❌ noVNC web directory not found:"
    echo "   ${NOVNC_ROOT}"
    exit 1
fi

echo
echo "🌐 Starting noVNC..."

websockify \
    --web "${NOVNC_ROOT}" \
    0.0.0.0:6080 \
    127.0.0.1:5900 \
    > "${NOVNC_LOG}" 2>&1 &

NOVNC_PROCESS=$!
printf '%s\n' "${NOVNC_PROCESS}" > "${NOVNC_PID}"

sleep 1

if ! kill -0 "${NOVNC_PROCESS}" 2>/dev/null; then
    echo "❌ noVNC failed to start."
    echo
    cat "${NOVNC_LOG}" 2>/dev/null || true
    exit 1
fi

# ─────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────

echo
echo "══════════════════════════════════════════"
echo "✨ SmilyAI OS VM is running"
echo "══════════════════════════════════════════"
echo
echo "Open the Codespaces forwarded port:"
echo
echo "   6080"
echo
echo "Then use:"
echo
echo "   /vnc.html?autoconnect=1&resize=scale"
echo
echo "Local form:"
echo
echo "   http://localhost:6080/vnc.html?autoconnect=1&resize=scale"
echo
echo "QEMU PID: ${QEMU_PROCESS}"
echo
echo "Logs:"
echo "   Serial: ${SERIAL_LOG}"
echo "   noVNC:  ${NOVNC_LOG}"
echo
echo "To stop:"
echo
echo "   bash scripts/stop-cloud-vm.sh"
echo
