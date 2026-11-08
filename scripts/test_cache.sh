#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
mkdir -p build results
verilator --cc --exe --build --assert -Wall -j 2 -Irtl --top-module instruction_cache \
	--Mdir "$AI_SOC_ROOT/build/cache" rtl/instruction_cache.sv "$AI_SOC_ROOT/tb/cache.cpp" \
	-CFLAGS '-O3' >build/build_cache.log 2>&1 || {
	cat build/build_cache.log
	exit 1
}
build/cache/Vinstruction_cache | tee results/cache.log
