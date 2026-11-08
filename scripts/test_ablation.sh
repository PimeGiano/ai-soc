#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
python3 scripts/gen_vectors.py
for variant in serial no_prefetch; do
	prefetch=1
	gather=1
	[[ "$variant" == serial ]] && gather=0
	[[ "$variant" == no_prefetch ]] && prefetch=0
	folder="$AI_SOC_ROOT/build/accel_${variant}"
	verilator --cc --exe --build --assert -Wall -j 2 -Irtl --top-module det_accelerator \
		-GENABLE_PREFETCH="$prefetch" -GENABLE_BANKED_GATHER="$gather" --Mdir "$folder" \
		rtl/*.sv "$AI_SOC_ROOT/tb/accelerator.cpp" -CFLAGS "-O3 -I$AI_SOC_ROOT/tb" \
		>"build/build_${variant}.log" 2>&1 || {
		cat "build/build_${variant}.log"
		exit 1
	}
	"$folder/Vdet_accelerator" build/vectors.mem build/jobs.txt 0 "$prefetch" >"results/ablation_${variant}.log"
done
printf 'Accelerator ablations PASS (serial gather / no prefetch)\n'
