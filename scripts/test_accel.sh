#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
mkdir -p build results
python3 scripts/gen_spec.py
python3 scripts/gen_vectors.py
verilator --cc --exe --build --assert -Wall -j 2 -Irtl --top-module det_accelerator --Mdir "$AI_SOC_ROOT/build/accel" \
 rtl/*.sv "$AI_SOC_ROOT/tb/accelerator.cpp" -CFLAGS "-O3 -I$AI_SOC_ROOT/tb" > build/build_accel.log 2>&1 || { cat build/build_accel.log;exit 1; }
for delay in 0 3; do
 build/accel/Vdet_accelerator build/vectors.mem build/jobs.txt "$delay" | tee "results/accel_delay${delay}.log"
done
