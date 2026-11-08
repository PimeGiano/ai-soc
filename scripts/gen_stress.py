"""Capacity, bank-conflict and fused-prefetch tests beyond the fixed benchmark."""

from pathlib import Path
import runpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
namespace = runpy.run_path(str(ROOT / "scripts/gen_vectors.py"))
case = namespace["case"]
g = case.__globals__
g["OUT"] = ROOT / "build/stress"
g["OUT"].mkdir(exist_ok=True)
g["image"] = namespace["Image"]()
g["jobs"] = []
rng = np.random.default_rng(20261108)


def add(x, co, k, stride, tile, fusion=None):
	weights = rng.integers(-128, 128, (co, k, k, x.shape[2]), dtype=np.int16).astype(np.int8)
	q = np.tile(np.array([0, 1, 12, 1, 12]), (co, 1))

	def set_tile(d):
		d[18:22] = tile

	case(x, weights, q, stride, (k // 2,) * 4, fusion, change=set_tile)


for shape, co, k, stride, tile in [
	((16, 16, 33), 19, 3, 1, [16, 16, 16, 4]),
	((16, 16, 17), 4, 1, 1, [16, 16, 16, 4]),
	((17, 17, 33), 17, 3, 2, [8, 8, 16, 16]),
	((31, 31, 17), 5, 3, 2, [13, 8, 16, 4]),
]:
	x = rng.integers(-128, 128, shape, dtype=np.int16).astype(np.int8)
	add(x, co, k, stride, tile)
for order in [0, 1]:
	lo = rng.integers(-128, 128, (7, 5, 17), dtype=np.int16).astype(np.int8)
	hi = rng.integers(-128, 128, (14, 10, 19), dtype=np.int16).astype(np.int8)
	x = namespace["materialize"](lo, hi, 3, 2, 5, 3, order)
	add(x, 17, 3, 1, [8, 5, 16, 16], (lo, hi, 3, 2, 5, 3, order))
g["image"].write(g["OUT"] / "vectors.mem")
(g["OUT"] / "jobs.txt").write_text(
	"".join(f"{a} {b} {c} {path} {err}\n" for a, b, c, path, err in g["jobs"])
)
print("Generated", len(g["jobs"]), "capacity/fused-prefetch stress cases")
