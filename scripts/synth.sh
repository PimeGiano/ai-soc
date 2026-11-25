#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

cd "$AI_SOC_ROOT"

mkdir -p build/synth results
# Preserve inferred SRAM cells for the structural check.
accel_rtl=(rtl/det_accelerator/*.sv)
yosys -Q -T -p "read_verilog -sv -Irtl/det_accelerator ${accel_rtl[*]}; hierarchy -check -top det_accelerator; proc; opt; memory_dff; memory_share; memory_collect; opt_clean; check; write_json build/synth/netlist.json; stat -json" >build/synth/accelerator.log 2>&1
python3 - <<'PY'
from pathlib import Path
import json

p = Path("build/synth/accelerator.log").read_text()
modules = json.loads(Path("build/synth/netlist.json").read_text())["modules"]
engines = modules["det_accelerator"]["cells"]
assert engines["pool_engine"]["type"] == "pool_accelerator"
conv = modules[engines["conv_engine"]["type"]]["cells"]
datapath = conv["datapath"]["type"]
tile_buffer = modules[conv["tile_buffer"]["type"]]["cells"]
scratch = {}
for module, prefix, copies in [(datapath, "", 1), ("banked_scratch", "banked/", 4)]:
	for name, cell in modules[module]["cells"].items():
		if cell["type"] != "$mem_v2":
			continue
		if module == datapath and name not in {"psum", "obuf"}:
			continue
		params = cell["parameters"]
		entry = {key: int(params[key], 2) for key in ["WIDTH", "SIZE", "RD_PORTS", "WR_PORTS"]}
		assert entry["RD_PORTS"] == 1, (name, "unexpected replicated read ports")
		assert entry["WR_PORTS"] == 1, (name, "write ports were not consolidated")
		entry["instances"] = copies
		scratch[prefix + name] = entry
assert len(scratch) == 6
instances = sum(cell["type"] == "banked_scratch" for cell in tile_buffer.values())
assert instances == 4
assert sum(m["WIDTH"] * m["SIZE"] // 8 * m["instances"] for m in scratch.values()) == 40960
data, _ = json.JSONDecoder().raw_decode(p[p.rfind("\n{") + 1 :])
Path("results/synthesis.json").write_text(
	json.dumps(
		{
			"stage": "RTL process lowering and memory collection; not gate-level area or timing",
			"statistics": data,
			"implemented_scratch_bytes": 40960,
			"scratch_memories": scratch,
			"prefetch_read_cache_data_bytes": 16,
			"prefetch_read_cache_tag_valid_bits": 116,
			"reserved_budget_bytes": 40960,
		},
		indent=2,
	)
	+ "\n"
)
print(
	"Synthesis structural check PASS; actual scratch SRAM 40KiB; ping-pong X/W with four single-read/single-write banks per slot"
)
PY

yosys -Q -T -p 'read_verilog -sv rtl/instruction_cache.sv; hierarchy -check -top instruction_cache; proc; opt; memory_dff; memory_share; memory_collect; opt_clean; check; write_json build/synth/cache_netlist.json; stat -json' >build/synth/cache.log 2>&1
python3 - <<'PY_CACHE'
import json
from pathlib import Path
net = json.loads(Path("build/synth/cache_netlist.json").read_text())
memories = {}
for name, cell in net["modules"]["instruction_cache"]["cells"].items():
	if cell["type"] == "$mem_v2":
		p = cell["parameters"]
		memories[name] = {key: int(p[key], 2) for key in ["WIDTH", "SIZE", "RD_PORTS", "WR_PORTS"]}
		assert memories[name]["RD_PORTS"] == memories[name]["WR_PORTS"] == 1
assert sum(m["WIDTH"] * m["SIZE"] for m in memories.values()) == (1024 + 192) * 8
Path("results/cache_synthesis.json").write_text(json.dumps({
	"stage": "RTL structural memory check; not FPGA placement/timing",
	"memories": memories, "data_bytes": 1024, "tag_bytes": 192, "valid_bytes": 32,
	"total_storage_bytes": 1248}, indent=2) + "\n")
print("Instruction cache structure PASS: 1024B data + 192B tags + 32B valid bits")
PY_CACHE

yosys -Q -T -p 'read_verilog -sv -Irtl/det_accelerator rtl/det_accelerator/pool_accelerator.sv; hierarchy -check -top pool_accelerator; proc; opt; check; stat -json' >build/synth/pool.log 2>&1
python3 - <<'PY_POOL'
import json
from pathlib import Path
text = Path("build/synth/pool.log").read_text()
statistics, _ = json.JSONDecoder().raw_decode(text[text.rfind("\n{") + 1:])
assert statistics["modules"]["\\pool_accelerator"]["num_memory_bits"] == 0
Path("results/pool_synthesis.json").write_text(json.dumps({
	"stage": "RTL process/structural check; no FPGA placement/timing",
	"scratch_bytes": 0, "statistics": statistics}, indent=2) + "\n")
print("Pool engine structural check PASS; no additional scratch RAM")
PY_POOL
