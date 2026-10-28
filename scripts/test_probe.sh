#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
python3 scripts/gen_probe.py
for label in equal unequal; do
 for mode in M F; do
  folder="build/probe_${label}_${mode}"
  build/soc/Vdet_soc_top "$folder/model.mem" build/firmware.bin "$folder/checks.txt" "$folder/boxes.bin" 0 > "results/probe_${label}_${mode}.log"
 done
done
python3 - <<'PY'
import json
from pathlib import Path
out={}
for label in ['equal','unequal']:
 row={}
 for mode in ['M','F']:
  text=Path(f'results/probe_{label}_{mode}.log').read_text();assert 'DETECTION SOC PASS' in text
  row[mode]=next(r for line in text.splitlines() if line.startswith('ROI ') for r in [json.loads(line[4:])] if r['id']==7)
 out[label]=row
Path('results/probe.json').write_text(json.dumps(out,indent=2)+'\n')
print('Controlled equal/unequal-scale M/F probes PASS')
PY
