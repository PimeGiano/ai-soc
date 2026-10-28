#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../env.sh"
cd "$AI_SOC_ROOT"
mkdir -p build/det
riscv64-unknown-elf-gcc -march=rv32im -mabi=ilp32 -O2 -g -ffreestanding -fno-builtin -nostdlib -nostartfiles \
 -Wall -Wextra -Werror -Ifirmware/det -T firmware/det/link.ld -Wl,-Map,build/det/firmware.map \
 firmware/start.S firmware/det/{driver,main,postprocess}.c -lgcc -o build/det/firmware.elf
riscv64-unknown-elf-objcopy -O binary --only-section=.text build/det/firmware.elf build/det/firmware.bin
python3 - <<'PY'
from pathlib import Path
b=Path('build/det/firmware.bin').read_bytes();assert len(b)<=65536
print('Detection firmware bytes:',len(b))
PY
