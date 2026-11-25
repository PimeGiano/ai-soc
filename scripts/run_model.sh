#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

cd "$AI_SOC_ROOT"

model="${1:-yolov3-tiny}"
mode="${2:-F}"
delay="${3:-0}"
profile="${4:-0}"
case "$profile" in
	0) label=subgraph ;;
	1) label=whole ;;
	2) label=profile ;;
	*) printf 'Profile must be 0 (subgraph), 1 (whole), or 2 (per-layer)\n' >&2; exit 2 ;;
esac
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
python3 scripts/export_model.py --model "$model" --mode "$mode" "${@:5}"
bash scripts/build_firmware.sh
bash scripts/build_soc.sh
folder="build/${model}_${mode}"
result="results/${model}_${mode}"
build/soc/Vdet_soc_top "$folder/model.mem" build/firmware.bin "$folder/checks.txt" "$result/boxes.bin" "$delay" "$profile" | tee "$result/${label}.log"
python3 scripts/check_boxes.py "$result"
