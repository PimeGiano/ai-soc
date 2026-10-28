#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
cd "$AI_SOC_ROOT"
mode="${1:-full}"
mkdir -p build results
case "$mode" in
 accuracy)
  python3 scripts/download_coco.py
  for model in yolov3-tiny yolov4-tiny; do OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 -u scripts/evaluate.py --model "$model" | tee "results/${model}_accuracy.log"; done
  python3 scripts/summarize.py;exit 0 ;;
 quick|full) ;;
 *) echo 'usage: run_all.sh [quick|full|accuracy]' >&2;exit 2 ;;
esac
python3 scripts/gen_spec.py
bash scripts/test_converter.sh
bash scripts/test_accel.sh
bash scripts/build_firmware.sh
bash scripts/build_soc.sh
bash scripts/test_soc.sh
bash scripts/test_probe.sh
bash scripts/synth.sh
if [[ "$mode" == full ]]; then
 python3 scripts/fetch_models.py
 for model in yolov3-tiny yolov4-tiny; do
  for variant in M F; do
   OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 scripts/export_model.py --model "$model" --mode "$variant"
   folder="build/${model}_${variant}";result="results/${model}_${variant}"
   for whole in 0 1; do
    label=subgraph;[[ "$whole" == 1 ]] && label=whole
    build/soc/Vdet_soc_top "$folder/model.mem" build/firmware.bin "$folder/checks.txt" "$result/boxes_${label}.bin" 0 "$whole" | tee "$result/${label}.log"
   done
   cp "$result/boxes_subgraph.bin" "$result/boxes.bin"
   python3 scripts/check_boxes.py "$result"
  done
 done
fi
python3 scripts/summarize.py
printf 'DETECTION %s PASS\n' "$mode"
