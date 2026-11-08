"""Small real-CPU checks: hardware ordinary/fused jobs plus CPU baseline."""

from pathlib import Path
import struct, json
from memory import Image

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "build"
parts = []
with (out / "vectors.mem").open("rb") as f:
	for _ in range(struct.unpack("<I", f.read(4))[0]):
		a, n = struct.unpack("<II", f.read(8))
		parts.append((a, f.read(n)))
lookup = dict(parts)
jobs = (out / "jobs.txt").read_text().splitlines()
for label, index, mode in [("ordinary", 0, 0), ("fused", 100, 0), ("cpu", 0, 2)]:
	da, dst, n, ref, _ = jobs[index].split()
	da, dst, n = int(da), int(dst), int(n)
	d = struct.unpack("<32I", lookup[da])
	data = Path(ref).read_bytes()
	h = 2166136261
	for v in data:
		h = ((h ^ v) * 16777619) & 0xFFFFFFFF
	image = Image()
	image.parts = parts.copy()
	image.next = max(a + len(b) for a, b in parts) + 16
	op = [1, d[0], 0, dst, d[16], d[17], d[7], 0, 1, 0, 1, 0, 1, 0, da, h, n, 0, 0, 0, 0, 0, 0, 0]
	oa = image.words(op)
	ba = image.put(bytes(2404))
	head = [0x44455431, 1, oa, mode, 0, 0, ba, 1] + [0] * 8
	image.parts.append((0x01008000, struct.pack("<16I", *head)))
	image.write(out / f"smoke_{label}.mem")
	(out / f"smoke_{label}.checks").write_text(f"{dst} {n} {ref}\n")

# Real-CPU checks for the separately addressed pool engine and B0 fallback.
import numpy as np
from model import maxpool

rng = np.random.default_rng(20261108)
for label, shape, stride, mode in [
	("pool_packed", (6, 8, 16), 2, 0),
	("pool_tail", (5, 7, 7), 1, 0),
	("pool_cpu", (5, 7, 7), 1, 2),
]:
	x = rng.integers(-127, 128, shape, dtype=np.int16).astype(np.int8)
	y = maxpool(x, 2, stride)
	image = Image()
	src = image.put(x.tobytes())
	dst = image.put(bytes(y.size + 4))
	ref = out / f"smoke_{label}.bin"
	ref.write_bytes(y.tobytes())
	hash_value = 2166136261
	for value in y.tobytes():
		hash_value = ((hash_value ^ value) * 16777619) & 0xFFFFFFFF
	op = [
		2,
		src,
		0,
		dst,
		*shape,
		0,
		1,
		0,
		1,
		0,
		1,
		0,
		0,
		hash_value,
		y.size,
		0,
		2,
		stride,
		0,
		0,
		0,
		0,
	]
	assert len(op) == 24
	oa = image.words(op)
	ba = image.put(bytes(2404))
	head = [0x44455431, 1, oa, mode, 0, 0, ba, 1] + [0] * 8
	image.parts.append((0x01008000, struct.pack("<16I", *head)))
	image.write(out / f"smoke_{label}.mem")
	(out / f"smoke_{label}.checks").write_text(f"{dst} {y.size} {ref}\n")

from reference import materialize as integer_materialize

for label, c0, c1, prefix, scales, order in [
	("copy_identity", 16, 16, 0, (1 << 30, 30, 1, 0), 0),
	("copy_scaled", 16, 16, 0, (3, 2, 5, 3), 1),
	("copy_unaligned", 17, 19, 1, (1, 0, 5, 3), 1),
]:
	lo = (np.arange(2 * 2 * c0, dtype=np.int16) - 128).astype(np.int8).reshape(2, 2, c0)
	hi = (np.arange(4 * 4 * c1, dtype=np.int16) - 128).astype(np.int8).reshape(4, 4, c1)
	y = integer_materialize(lo, hi, *scales, order)
	image = Image()
	a = image.put(bytes(prefix) + lo.tobytes()) + prefix
	b = image.put(bytes(prefix) + hi.tobytes()) + prefix
	dst = image.put(bytes(y.size + 4))
	ref = out / f"smoke_{label}.bin"
	ref.write_bytes(y.tobytes())
	hash_value = 2166136261
	for value in y.tobytes():
		hash_value = ((hash_value ^ value) * 16777619) & 0xFFFFFFFF
	op = [3, a, b, dst, 4, 4, c0, c1, 2, order, *scales, 0, hash_value, y.size, 0, 0, 0, 0, 0, 0, 0]
	assert len(op) == 24
	oa = image.words(op)
	ba = image.put(bytes(2404))
	head = [0x44455431, 1, oa, 0, 0, 0, ba, 1] + [0] * 8
	image.parts.append((0x01008000, struct.pack("<16I", *head)))
	image.write(out / f"smoke_{label}.mem")
	(out / f"smoke_{label}.checks").write_text(f"{dst} {y.size} {ref}\n")
for label, channels, count, start in [("slice_word", 16, 8, 8), ("slice_tail", 17, 7, 3)]:
	x = (np.arange(3 * 5 * channels, dtype=np.int16) - 128).astype(np.int8).reshape(3, 5, channels)
	x[:, :, start] = -128
	y = x[:, :, start : start + count].copy()
	image = Image()
	a = image.put(x.tobytes())
	dst = image.put(bytes(y.size + 4))
	ref = out / f"smoke_{label}.bin"
	ref.write_bytes(y.tobytes())
	hash_value = 2166136261
	for value in y.tobytes():
		hash_value = ((hash_value ^ value) * 16777619) & 0xFFFFFFFF
	op = [
		4,
		a,
		0,
		dst,
		3,
		5,
		channels,
		count,
		start,
		0,
		1,
		0,
		1,
		0,
		0,
		hash_value,
		y.size,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
	]
	oa = image.words(op)
	ba = image.put(bytes(2404))
	head = [0x44455431, 1, oa, 0, 0, 0, ba, 1] + [0] * 8
	image.parts.append((0x01008000, struct.pack("<16I", *head)))
	image.write(out / f"smoke_{label}.mem")
	(out / f"smoke_{label}.checks").write_text(f"{dst} {y.size} {ref}\n")
