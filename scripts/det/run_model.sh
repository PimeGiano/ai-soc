#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../env.sh"
cd "$AI_SOC_ROOT"
model="${1:-yolov3-tiny}";mode="${2:-F}";delay="${3:-0}";whole="${4:-0}"
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
python3 scripts/det/export_model.py --model "$model" --mode "$mode"
bash scripts/det/build_firmware.sh
bash scripts/det/build_soc.sh
folder="build/det/${model}_${mode}";result="results/det/${model}_${mode}"
label=subgraph;[[ "$whole" == 1 ]] && label=whole
build/det/soc/Vdet_soc_top "$folder/model.mem" build/det/firmware.bin "$folder/checks.txt" "$result/boxes.bin" "$delay" "$whole" | tee "$result/${label}.log"
python3 scripts/det/check_boxes.py "$result"
