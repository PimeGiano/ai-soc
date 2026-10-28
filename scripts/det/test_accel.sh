#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../env.sh"
cd "$AI_SOC_ROOT"
mkdir -p build/det results/det
python3 scripts/det/gen_spec.py
python3 scripts/det/gen_vectors.py
verilator --cc --exe --build --assert -Wall -j 2 -Irtl/det --top-module det_accelerator --Mdir "$AI_SOC_ROOT/build/det/accel" \
 rtl/det/*.sv "$AI_SOC_ROOT/tb/det/accelerator.cpp" -CFLAGS "-O3 -I$AI_SOC_ROOT/tb/det" > build/det/build_accel.log 2>&1 || { cat build/det/build_accel.log;exit 1; }
for delay in 0 3; do
 build/det/accel/Vdet_accelerator build/det/vectors.mem build/det/jobs.txt "$delay" | tee "results/det/accel_delay${delay}.log"
done
