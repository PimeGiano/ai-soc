#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
python3 scripts/gen_stress.py
for delay in 0 15; do
	build/accel/Vdet_accelerator build/stress/vectors.mem build/stress/jobs.txt "$delay" \
		>"results/stress_delay${delay}.log"
done
printf 'Capacity/bank-layout/fused-prefetch stress PASS\n'
