export AI_SOC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ai_soc_chip_env="${AI_CHIP_ENV:-$HOME/ai-chip-tools/env.sh}"
if [[ -f "$ai_soc_chip_env" ]]; then
    source "$ai_soc_chip_env"
fi
export PATH="$AI_SOC_ROOT/tools/root/usr/bin:$PATH"
export LD_LIBRARY_PATH="$AI_SOC_ROOT/tools/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
