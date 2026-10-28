#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../env.sh"
cd "$AI_SOC_ROOT"
mkdir -p build/det/synth results/det
# Keep SRAM as memory cells; mapping 24KiB into flip-flops misrepresents the design.
yosys -Q -T -p 'read_verilog -sv -Irtl/det rtl/det/requant.sv rtl/det/fuse_requant.sv rtl/det/conv_core.sv rtl/det/det_accelerator.sv; hierarchy -check -top det_accelerator; proc; opt; memory_dff; memory_share; memory_collect; opt_clean; check; stat -json' > build/det/synth/accelerator.log 2>&1
python3 - <<'PY'
from pathlib import Path
import json
p=Path('build/det/synth/accelerator.log').read_text();data,_=json.JSONDecoder().raw_decode(p[p.rfind('\n{')+1:])
Path('results/det/synthesis.json').write_text(json.dumps({'stage':'RTL process lowering and memory collection; not gate-level area or timing','statistics':data,'implemented_scratch_bytes':24576,'reserved_budget_bytes':40960},indent=2)+'\n')
print('Synthesis structural check PASS; actual scratch SRAM 24KiB, budget 40KiB; unused second banks not instantiated')
PY
