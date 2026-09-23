#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${HOME}/.cache/smilyai-cloud-vm"

QEMU_PID="${STATE_DIR}/qemu.pid"
NOVNC_PID="${STATE_DIR}/novnc.pid"

stop_pid() {
    local file="$1"
    local name="$2"

    if [[ ! -f "${file}" ]]; then
        return
    fi

    local pid
    pid="$(cat "${file}")"

    if kill -0 "${pid}" 2>/dev/null; then
        echo "Stopping ${name} (${pid})..."
        kill "${pid}" 2>/dev/null || true

        for _ in {1..20}; do
            if ! kill -0 "${pid}" 2>/dev/null; then
                break
            fi
            sleep 0.1
        done

        if kill -0 "${pid}" 2>/dev/null; then
            kill -9 "${pid}" 2>/dev/null || true
        fi
    fi

    rm -f "${file}"
}

stop_pid "${NOVNC_PID}" "noVNC"
stop_pid "${QEMU_PID}" "QEMU"

rm -f "${STATE_DIR}/qemu-monitor.sock"

echo "✅ SmilyAI OS cloud VM stopped."
