#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
mkdir -p build results
python3 scripts/gen_spec.py
verilator --cc --exe --build --assert -Wall -j 2 -Irtl --top-module pool_accelerator \
	--Mdir "$AI_SOC_ROOT/build/pool" rtl/pool_accelerator.sv "$AI_SOC_ROOT/tb/pool.cpp" \
	-CFLAGS "-O3 -I$AI_SOC_ROOT/tb" >build/build_pool.log 2>&1 || {
	cat build/build_pool.log
	exit 1
}
build/pool/Vpool_accelerator | tee results/pool.log
