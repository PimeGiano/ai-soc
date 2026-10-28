#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AI_SOC_ROOT"
model="${1:-yolov3-tiny}";mode="${2:-F}";delay="${3:-0}";whole="${4:-0}"
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
python3 scripts/export_model.py --model "$model" --mode "$mode"
bash scripts/build_firmware.sh
bash scripts/build_soc.sh
folder="build/${model}_${mode}";result="results/${model}_${mode}"
label=subgraph;[[ "$whole" == 1 ]] && label=whole
build/soc/Vdet_soc_top "$folder/model.mem" build/firmware.bin "$folder/checks.txt" "$result/boxes.bin" "$delay" "$whole" | tee "$result/${label}.log"
python3 scripts/check_boxes.py "$result"
