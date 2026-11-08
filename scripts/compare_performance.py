"""Compare fixed-suite and full-model measurements with the preserved baseline."""

from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "results"
baseline = json.loads((BASE / "performance_baseline.json").read_text())
stage1 = json.loads((BASE / "performance_stage1.json").read_text())
valid = [
	i
	for i, line in enumerate((ROOT / "build/jobs.txt").read_text().splitlines())
	if line.split()[-1] == "0"
]
report = {"baseline_commit": baseline["baseline_commit"], "accelerator": {}, "models": {}}
rows = []
pool_rows = []
before_pool = json.loads((BASE / "performance_before_pool.json").read_text())
for delay in [0, 3]:
	text = (BASE / f"accel_delay{delay}.log").read_text()
	assert "DETECTION ACCEL PASS jobs=158" in text
	current = [
		dict(zip(["case", "cycles", "compute", "reads", "writes"], map(int, m)))
		for m in re.findall(
			r"CASE (\d+) PASS cycles=(\d+) compute=(\d+) reads=(\d+) writes=(\d+)", text
		)
	]
	phases = [
		dict(zip(["load", "gather", "partial", "param", "output", "control"], map(int, m)))
		for m in re.findall(
			r"load=(\d+) gather=(\d+) partial=(\d+) param=(\d+) output=(\d+) control=(\d+)", text
		)
	]
	assert len(phases) == 158
	old = baseline["accelerator"][str(delay)]["cases"]
	assert len(current) == len(old) == 158
	for i in valid:
		assert current[i]["compute"] <= old[i]["compute"], (
			delay,
			i,
			"MAC count unexpectedly increased",
		)
		assert current[i]["writes"] == old[i]["writes"], (delay, i, "output bytes changed")
	a = sum(old[i]["cycles"] for i in valid)
	b = sum(current[i]["cycles"] for i in valid)
	report["accelerator"][str(delay)] = {
		"valid_cases": len(valid),
		"before_cycles": a,
		"after_cycles": b,
		"speedup": a / b,
		"log_sha256": hashlib.sha256(text.encode()).hexdigest(),
		"regressed_cases": [i for i in valid if current[i]["cycles"] > old[i]["cycles"]],
	}
	report["accelerator"][str(delay)]["phase_cycles"] = {
		key: sum(phases[i][key] for i in valid) for key in phases[0]
	}
	s1 = stage1["accelerator"][str(delay)]["after_cycles"]
	report["accelerator"][str(delay)]["stage1_cycles"] = s1
	report["accelerator"][str(delay)]["speedup_over_stage1"] = s1 / b
	pipeline = [
		tuple(map(int, m))
		for m in re.findall(
			r"fast=(\d+) serial=(\d+) prefetch=(\d+) overlap=(\d+) prefetch_wait=(\d+)", text
		)
	]
	assert len(pipeline) == 158
	report["accelerator"][str(delay)]["pipeline_cycles"] = dict(
		zip(
			["fast_gather", "serial_gather", "prefetch_active", "prefetch_mac", "prefetch_wait"],
			[sum(pipeline[i][j] for i in valid) for j in range(5)],
		)
	)
	rows.append(
		f"| 算子合集 delay={delay} | {a:,} | {s1:,} | {b:,} | {a / b:.3f}× | {s1 / b:.3f}× |"
	)
for name, variants in baseline["models"].items():
	report["models"][name] = {}
	for mode, labels in variants.items():
		report["models"][name][mode] = {}
		for label, old in labels.items():
			text = (BASE / f"{name}_{mode}" / f"{label}.log").read_text()
			assert "DETECTION SOC PASS" in text
			now = {
				r["id"]: r
				for line in text.splitlines()
				if line.startswith("ROI ")
				for r in [json.loads(line[4:])]
			}
			rid = (
				65534
				if label == "whole"
				else next(r["id"] for r in old if r["id"] not in [65533, 65534])
			)
			a = next(r["cycles"] for r in old if r["id"] == rid)
			b = now[rid]["cycles"]
			report["models"][name][mode][label] = {
				"before_cycles": a,
				"after_cycles": b,
				"speedup": a / b,
				"log_sha256": hashlib.sha256(text.encode()).hexdigest(),
			}
			s1 = stage1["models"][name][mode][label]["after_cycles"]
			report["models"][name][mode][label]["stage1_cycles"] = s1
			report["models"][name][mode][label]["speedup_over_stage1"] = s1 / b
			if label == "whole":
				bp = before_pool["models"][name][mode][label]["after_cycles"]
				report["models"][name][mode][label]["before_pool_cycles"] = bp
				report["models"][name][mode][label]["speedup_over_before_pool"] = bp / b
				pool_rows.append(f"| {name} {mode} | {bp:,} | {b:,} | {bp / b:.3f}× |")

			rows.append(
				f"| {name} {mode} {label} | {a:,} | {s1:,} | {b:,} | {a / b:.3f}× | {s1 / b:.3f}× |"
			)
ablation_rows = []
report["ablations"] = {}
for variant in ["serial", "no_prefetch"]:
	text = (BASE / f"ablation_{variant}.log").read_text()
	assert "DETECTION ACCEL PASS jobs=158" in text
	cases = [int(v) for v in re.findall(r"CASE \d+ PASS cycles=(\d+)", text)]
	assert len(cases) == 158
	total = sum(cases[i] for i in valid)
	full = report["accelerator"]["0"]["after_cycles"]
	report["ablations"][variant] = {
		"cycles": total,
		"enabled_cycles": full,
		"speedup": total / full,
	}
	ablation_rows.append(f"| {variant} | {total:,} | {full:,} | {total / full:.3f}× |")
(BASE / "performance.json").write_text(json.dumps(report, indent=2) + "\n")
(BASE / "performance.md").write_text(
	"# 性能优化前后对比\n\n基线提交：`"
	+ baseline["baseline_commit"]
	+ "`。相同输入、量化、分块与仿真总线条件；当前同时包含供数、预取、指令缓存、CPU算子和独立池化硬件优化，速度比是周期比，不是板上FPS。第一轮记录保存在performance_stage1.json。算子汇总仅含151组有效任务，延迟3使用相同种子的事务等待，但事务减少后随机序列与地址对应会改变。\n\n| 场景 | 原始周期 | 第一轮周期 | 当前周期 | 对原始加速 | 对第一轮加速 |\n|---|---:|---:|---:|---:|---:|\n"
	+ "\n".join(rows)
	+ "\n\n## 同源码消融（151组有效任务，delay=0）\n\n| 关闭的机制 | 关闭时周期 | 全部开启周期 | 开启带来的加速 |\n|---|---:|---:|---:|\n"
	+ "\n".join(ablation_rows)
	+ "\n\n## 接入池化硬件前后的系统版本\n\n| 场景 | 接入前周期 | 当前周期 | 加速比 |\n|---|---:|---:|---:|\n"
	+ "\n".join(pool_rows)
	+ "\n\n所有有效算子跳过补零MAC，实际计算步数不超过基线，输出字节数保持一致；每组结果逐字节匹配独立参考。完整模型逐层验证并检查CPU检测框。原始基线保存在performance_baseline.json，当前日志和比较结果附SHA256。\n"
)
print("Performance comparison:", BASE / "performance.md")
