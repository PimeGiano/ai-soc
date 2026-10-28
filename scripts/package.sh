#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
python3 "$AI_SOC_ROOT/scripts/manifest.py"
archive="$(dirname "$AI_SOC_ROOT")/ai-soc-submission.tar.gz"
tar --exclude='ai-soc/build' --exclude='ai-soc/tools/root' --exclude='ai-soc/tools/packages' \
 --exclude='ai-soc/data/*.gz' --exclude='ai-soc/data/det/*.weights' --exclude='ai-soc/data/det/coco' --exclude='ai-soc/tools/python' --exclude='ai-soc/.git' --exclude='ai-soc/.venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='core' \
 -czf "$archive" -C "$(dirname "$AI_SOC_ROOT")" "$(basename "$AI_SOC_ROOT")"
printf 'Submission: %s\n' "$archive"
