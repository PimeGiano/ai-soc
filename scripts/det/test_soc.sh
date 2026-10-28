#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../env.sh"
cd "$AI_SOC_ROOT"
python3 scripts/det/gen_smoke.py
for label in ordinary fused cpu; do
 build/det/soc/Vdet_soc_top "build/det/smoke_${label}.mem" build/det/firmware.bin "build/det/smoke_${label}.checks" "build/det/smoke_${label}.boxes" 3 | tee "results/det/smoke_${label}.log"
done
