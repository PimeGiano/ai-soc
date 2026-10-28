#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
verilator --cc --exe --build --assert -Wall -j 2 --top-module fuse_requant --Mdir "$AI_SOC_ROOT/build/converter" \
 rtl/{requant,fuse_requant}.sv "$AI_SOC_ROOT/tb/converter.cpp" > build/build_converter.log 2>&1 || { cat build/build_converter.log;exit 1; }
build/converter/Vfuse_requant | tee results/converter.log
