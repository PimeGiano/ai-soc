#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
python3 scripts/gen_smoke.py
for label in ordinary fused cpu; do
 build/soc/Vdet_soc_top "build/smoke_${label}.mem" build/firmware.bin "build/smoke_${label}.checks" "build/smoke_${label}.boxes" 3 | tee "results/smoke_${label}.log"
done
