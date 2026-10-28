#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
mkdir -p build
verilator --cc --exe --build --assert -Wall -j 2 -Irtl --top-module det_soc_top --Mdir "$AI_SOC_ROOT/build/soc" \
 sim/vendor.vlt third_party/picorv32.v rtl/*.sv "$AI_SOC_ROOT/tb/soc.cpp" \
 -CFLAGS "-O3 -I$AI_SOC_ROOT/tb" > build/build_soc.log 2>&1 || { cat build/build_soc.log;exit 1; }

python3 - <<'PY_BUILD'
import hashlib,json
from pathlib import Path
files=sorted(Path('rtl').glob('*.sv'))+[Path('rtl/spec.vh'),Path('third_party/picorv32.v')]
h=hashlib.sha256()
for p in files:h.update(str(p).encode());h.update(p.read_bytes())
Path('results/build.json').write_text(json.dumps({'rtl_sha256':h.hexdigest(),'files':[str(p) for p in files]},indent=2)+'\n')
PY_BUILD
