#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
python3 -m compileall -q smilyai scripts/stage-runtime.py
python3 -m unittest discover -s tests -v
bash scripts/validate-image-definitions.sh
for file in shell/*.js; do node --check "$file"; done
node --test tests/frontend.test.cjs
echo "Automated source checks passed. This is NOT a hardware or image-boot certification."
