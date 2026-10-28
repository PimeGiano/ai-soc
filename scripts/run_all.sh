#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
cd "$AI_SOC_ROOT"
mode="${1:-full}"
mkdir -p build/det results/det
case "$mode" in
 accuracy)
  python3 scripts/det/download_coco.py
  for model in yolov3-tiny yolov4-tiny; do OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 -u scripts/det/evaluate.py --model "$model" | tee "results/det/${model}_accuracy.log"; done
  python3 scripts/det/summarize.py;exit 0 ;;
 quick|full) ;;
 *) echo 'usage: run_all.sh [quick|full|accuracy]' >&2;exit 2 ;;
esac
python3 scripts/det/gen_spec.py
bash scripts/det/test_converter.sh
bash scripts/det/test_accel.sh
bash scripts/det/build_firmware.sh
bash scripts/det/build_soc.sh
bash scripts/det/test_soc.sh
bash scripts/det/test_probe.sh
bash scripts/det/synth.sh
if [[ "$mode" == full ]]; then
 python3 scripts/det/fetch_models.py
 for model in yolov3-tiny yolov4-tiny; do
  for variant in M F; do
   OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 scripts/det/export_model.py --model "$model" --mode "$variant"
   folder="build/det/${model}_${variant}";result="results/det/${model}_${variant}"
   for whole in 0 1; do
    label=subgraph;[[ "$whole" == 1 ]] && label=whole
    build/det/soc/Vdet_soc_top "$folder/model.mem" build/det/firmware.bin "$folder/checks.txt" "$result/boxes_${label}.bin" 0 "$whole" | tee "$result/${label}.log"
   done
   cp "$result/boxes_subgraph.bin" "$result/boxes.bin"
   python3 scripts/det/check_boxes.py "$result"
  done
 done
fi
python3 scripts/det/summarize.py
printf 'DETECTION %s PASS\n' "$mode"
