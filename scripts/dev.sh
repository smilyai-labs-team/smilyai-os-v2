#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export SMILYAI_SHELL_ROOT="$PROJECT_DIR/shell"
export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"
python3 -m smilyai.server --port 47811 &
HARNESS_PID=$!
python3 -m smilyai.ui_server &
UI_PID=$!
trap 'kill "$HARNESS_PID" "$UI_PID" 2>/dev/null || true' EXIT INT TERM
if [[ "${SMILYAI_NO_BROWSER:-0}" != 1 ]]; then "$PROJECT_DIR/scripts/launch-shell.sh" & fi
wait "$HARNESS_PID" "$UI_PID"
