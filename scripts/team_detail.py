"""RTL-based hierarchical schematics. Bundles list widths per field, never sums."""

from team_schematic import Diagram

REQ = "1/32/32/4"
RESP = "1/32"
CSR = "1/8/32/4"


def connect(d, a, b, via=()):
	d.wire(a, b, via)


def system_detail():
	d = Diagram("SoC总图（含外部端口）", 4400, 2900)
	d.outer(
		[("clk", 1, "in"), ("rst", 1, "in"), ("mem_ready", 1, "in"), ("mem_rdata", 32, "in")],
		[
			("trap", 1, "out"),
			("mem_valid", 1, "out"),
			("mem_addr", 32, "out"),
			("mem_wdata", 32, "out"),
			("mem_wstrb", 4, "out"),
			("mem_dma", 1, "out"),
			("mem_instr", 1, "out"),
		],
	)
	d.box(
		"cpu",
		"CPU + I-cache",
		"A",
		850,
		350,
		450,
		650,
		[("clk", 1, "in"), ("rst", 1, "in"), ("cbr / cbd", RESP, "in")],
		[("cbv / ca / cw / cs", REQ, "out"), ("ci", 1, "out"), ("trap", 1, "out")],
	)
	d.box(
		"bus",
		"两级仲裁 / 地址译码",
		"A（顶层逻辑分组）",
		2300,
		350,
		460,
		1000,
		[
			("cbv / ca / cw / cs", REQ, "in"),
			("cbr / cbd", RESP, "out"),
			("conv DMA req", REQ, "in"),
			("conv DMA resp", RESP, "out"),
			("conv CSR req", CSR, "out"),
			("conv CSR resp", RESP, "in"),
			("pool DMA req", REQ, "in"),
			("pool DMA resp", RESP, "out"),
			("pool CSR req", CSR, "out"),
			("pool CSR resp", RESP, "in"),
		],
		[
			("mem_valid", 1, "out"),
			("mem_addr", 32, "out"),
			("mem_wdata", 32, "out"),
			("mem_wstrb", 4, "out"),
			("mem_ready", 1, "in"),
			("mem_rdata", 32, "in"),
			("dr / pool_dr", "1/1", "out"),
			("reg_select / pool_select", "1/1", "out"),
		],
	)
	d.box(
		"conv",
		"det_accelerator",
		"B / C",
		850,
		1750,
		450,
		600,
		[("CSR req", CSR, "in"), ("CSR resp", RESP, "out")],
		[("DMA req", REQ, "out"), ("DMA resp", RESP, "in")],
	)
	d.box(
		"pool",
		"pool_accelerator",
		"D",
		2300,
		1750,
		460,
		600,
		[("CSR req", CSR, "in"), ("CSR resp", RESP, "out")],
		[("DMA req", REQ, "out"), ("DMA resp", RESP, "in")],
	)
	d.box(
		"tags",
		"访问统计标记",
		"顶层组合逻辑",
		3300,
		1850,
		430,
		400,
		[("ci", 1, "in"), ("dr / pool_dr", "1/1", "in"), ("reg_select / pool_select", "1/1", "in")],
		[("mem_dma", 1, "out"), ("mem_instr", 1, "out")],
	)
	for p in ["clk", "rst"]:
		connect(d, ("boundary", p), ("cpu", p))
	connect(d, ("cpu", "cbv / ca / cw / cs"), ("bus", "cbv / ca / cw / cs"))
	connect(d, ("bus", "cbr / cbd"), ("cpu", "cbr / cbd"))
	connect(
		d,
		("cpu", "trap"),
		("boundary", "trap"),
		[(1500, 837.5), (1500, 170), (3950, 170), (3950, d.pins[("boundary", "trap")][1])],
	)
	connect(
		d, ("cpu", "ci"), ("tags", "ci"), [(1550, 675), (1550, 1550), (3100, 1550), (3100, 1950)]
	)
	for p in ["mem_valid", "mem_addr", "mem_wdata", "mem_wstrb"]:
		connect(d, ("bus", p), ("boundary", p))
	for i, p in enumerate(["mem_ready", "mem_rdata"]):
		y = 150 + 40 * i
		connect(
			d,
			("boundary", p),
			("bus", p),
			[
				(550, d.pins[("boundary", p)][1]),
				(550, y),
				(3050 + i * 60, y),
				(3050 + i * 60, d.pins[("bus", p)][1]),
			],
		)
	connect(d, ("bus", "dr / pool_dr"), ("tags", "dr / pool_dr"), [(3020, 1225), (3020, 2050)])
	connect(d, ("bus", "reg_select / pool_select"), ("tags", "reg_select / pool_select"))
	for p in ["mem_dma", "mem_instr"]:
		connect(d, ("tags", p), ("boundary", p))
	for key in ["conv", "pool"]:
		for a, b in [("DMA req", f"{key} DMA req"), ("CSR resp", f"{key} CSR resp")]:
			connect(d, (key, a), ("bus", b))
		for a, b in [(f"{key} DMA resp", "DMA resp"), (f"{key} CSR req", "CSR req")]:
			connect(d, ("bus", a), (key, b))
	d.notes = [
		(350, 65, "det_soc_top：边界外接主存模型 / 主存控制器", 34),
		(
			650,
			2450,
			"请求束：valid(1), addr(32), wdata(32), wstrb(4)；应答束：ready(1), rdata(32)。",
			23,
		),
		(650, 2500, "CSR请求地址为8位。全局clk/rst接全部时序块；CPU resetn = !rst。", 23),
		(
			650,
			2550,
			"仲裁器无instr端口；ci仅到I-cache及右下角统计逻辑。译码选择也送统计逻辑。",
			23,
		),
		(
			650,
			2600,
			"mem_dma / mem_instr仅在mem_valid && mem_ready时用于分类；主存不属于本RTL顶层。",
			23,
		),
		(
			650,
			2650,
			"主存接口是一个共享32位native端口；图中束线表示多根独立信号，不是新RTL端口。",
			23,
		),
	]
	return d


def cpu_cache():
	d = Diagram("CPU与I-cache（按文件）", 3000, 1700)
	d.outer(
		[("clk", 1, "in"), ("rst", 1, "in"), ("cbr", 1, "in"), ("cbd", 32, "in")],
		[
			("trap", 1, "out"),
			("cbv", 1, "out"),
			("ci", 1, "out"),
			("ca", 32, "out"),
			("cw", 32, "out"),
			("cs", 4, "out"),
		],
	)
	d.box(
		"cpu",
		"picorv32.v",
		"",
		750,
		300,
		350,
		950,
		[("clk", 1, "in"), ("resetn = !rst", 1, "in"), ("mem_ready", 1, "in"), ("mem_rdata", 32, "in")],
		[
			("mem_valid", 1, "out"),
			("mem_instr", 1, "out"),
			("mem_addr", 32, "out"),
			("mem_wstrb", 4, "out"),
			("mem_wdata", 32, "out"),
			("trap", 1, "out"),
		],
	)
	d.box(
		"cache",
		"instruction_cache.sv",
		"",
		1850,
		300,
		400,
		950,
		[
			("cpu_valid", 1, "in"),
			("cpu_instr", 1, "in"),
			("cpu_addr", 32, "in"),
			("cpu_wstrb", 4, "in"),
			("cpu_ready", 1, "out"),
			("cpu_rdata", 32, "out"),
		],
		[
			("clk", 1, "in"),
			("rst", 1, "in"),
			("bus_valid", 1, "out"),
			("bus_ready", 1, "in"),
			("bus_rdata", 32, "in"),
		],
	)
	for p in ["clk", "rst"]:
		connect(d, ("boundary", p), ("cache", p))
	connect(d, ("boundary", "clk"), ("cpu", "clk"))
	d.wire(("boundary", "rst"), ("cpu", "resetn = !rst"), label="!")
	for a, b in [
		("mem_valid", "cpu_valid"),
		("mem_instr", "cpu_instr"),
		("mem_addr", "cpu_addr"),
		("mem_wstrb", "cpu_wstrb"),
	]:
		connect(d, ("cpu", a), ("cache", b))
	for a, b in [("cpu_ready", "mem_ready"), ("cpu_rdata", "mem_rdata")]:
		connect(d, ("cache", a), ("cpu", b))
	for a, b in [("cbr", "bus_ready"), ("cbd", "bus_rdata")]:
		connect(d, ("boundary", a), ("cache", b))
	connect(d, ("cache", "bus_valid"), ("boundary", "cbv"))
	for a, b in [
		("trap", "trap"),
		("mem_instr", "ci"),
		("mem_addr", "ca"),
		("mem_wdata", "cw"),
		("mem_wstrb", "cs"),
	]:
		connect(d, ("cpu", a), ("boundary", b))
	d.notes = [(350, 65, "CPU + I-cache", 30)]
	# Name the inversion directly on the pin, since it is wiring in the parent file.
	return d


def accelerator():
	d = Diagram("卷积加速器内部（按文件）", 3700, 2250)
	left = [
		("clk", 1, "in"),
		("rst", 1, "in"),
		("reg_valid", 1, "in"),
		("reg_addr", 8, "in"),
		("reg_wdata", 32, "in"),
		("reg_wstrb", 4, "in"),
		("reg_ready", 1, "out"),
		("reg_rdata", 32, "out"),
	]
	right = [
		("dma_valid", 1, "out"),
		("dma_addr", 32, "out"),
		("dma_wdata", 32, "out"),
		("dma_wstrb", 4, "out"),
		("dma_ready", 1, "in"),
		("dma_rdata", 32, "in"),
	]
	d.outer(left, right)
	d.box(
		"parent",
		"det_accelerator.sv",
		"",
		780,
		350,
		440,
		1350,
		left + right,
		[
			("prefetch cfg/start/consume", "32/31/6/1", "out"),
			("prefetch busy/done", "1/1", "in"),
			("prefetch read req", "1/32", "in"),
			("prefetch read resp", "1/32", "out"),
			("prefetch write", "1/1/13/32/4", "in"),
			("X/W write", "1/2/9/32/4", "out"),
			("X/W read_addr", "36/36", "out"),
			("X/W read_data", "128/128", "in"),
			("core control/A/B", "1/1/4/32/1/32/32", "out"),
			("core result", 32, "in"),
			("input_q cfg/sample", "31/6/1/8/16", "out"),
			("input_q handshake/data", "1/1/1/8", "in"),
			("output_q inputs", "32/31/6", "out"),
			("output_q result", 8, "in"),
		],
	)
	d.box(
		"pf",
		"tile_prefetch.sv",
		"",
		1800,
		250,
		380,
		400,
		[
			("cfg/start/consume", "32/31/6/1", "in"),
			("busy/done", "1/1", "out"),
			("read req", "1/32", "out"),
			("read resp", "1/32", "in"),
			("write", "1/1/13/32/4", "out"),
		],
		[("input_quant inputs", "32/31/6", "out"), ("input_quant result", 8, "in")],
	)
	d.box(
		"banks",
		"banked_scratch.sv",
		"",
		1800,
		850,
		380,
		360,
		[("write ×4", "1/2/9/32/4", "in"), ("read_addr X/W", "36/36", "in")],
		[("read_data X/W", "128/128", "out")],
	)
	d.box(
		"core",
		"conv_core.sv",
		"",
		2700,
		850,
		360,
		360,
		[("clear/restore/index/data/step/A/B", "1/1/4/32/1/32/32", "in")],
		[("result", 32, "out")],
	)
	d.box(
		"fq",
		"fuse_requant.sv",
		"",
		1800,
		1450,
		380,
		360,
		[("cfg/sample", "31/6/1/8/16", "in"), ("handshake/data", "1/1/1/8", "out")],
		[("q inputs", "32/31/6", "out"), ("q result", 8, "in")],
	)
	d.box(
		"q",
		"requant.sv",
		"",
		2700,
		1450,
		360,
		450,
		[
			("output_q inputs", "32/31/6", "in"),
			("input_q.q inputs", "32/31/6", "in"),
			("prefetch.input_quant inputs", "32/31/6", "in"),
		],
		[
			("output_q result", 8, "out"),
			("input_q.q result", 8, "out"),
			("prefetch.input_quant result", 8, "out"),
		],
	)
	for p, _, direction in left + right:
		connect(d, ("boundary", p), ("parent", p)) if direction == "in" else connect(
			d, ("parent", p), ("boundary", p)
		)
	for a, b in [
		("prefetch cfg/start/consume", "cfg/start/consume"),
		("prefetch read resp", "read resp"),
	]:
		connect(d, ("parent", a), ("pf", b))
	for a, b in [
		("busy/done", "prefetch busy/done"),
		("read req", "prefetch read req"),
		("write", "prefetch write"),
	]:
		connect(d, ("pf", a), ("parent", b))
	for a, b in [("X/W write", "write ×4"), ("X/W read_addr", "read_addr X/W")]:
		connect(d, ("parent", a), ("banks", b))
	connect(d, ("banks", "read_data X/W"), ("parent", "X/W read_data"))
	connect(d, ("parent", "core control/A/B"), ("core", "clear/restore/index/data/step/A/B"))
	connect(d, ("core", "result"), ("parent", "core result"))
	connect(d, ("parent", "input_q cfg/sample"), ("fq", "cfg/sample"))
	connect(d, ("fq", "handshake/data"), ("parent", "input_q handshake/data"))
	connect(d, ("parent", "output_q inputs"), ("q", "output_q inputs"))
	connect(d, ("q", "output_q result"), ("parent", "output_q result"))
	for key, prefix in [("fq", "input_q.q"), ("pf", "prefetch.input_quant")]:
		name = "q" if key == "fq" else "input_quant"
		connect(d, (key, f"{name} inputs"), ("q", f"{prefix} inputs"))
		connect(d, ("q", f"{prefix} result"), (key, f"{name} result"))
	d.notes = [(350, 65, "det_accelerator.sv", 30)]
	return d


def route(d):
	"""Orthogonal obstacle routing; boxes remain simple and edges never cross them."""
	import heapq

	xs = {320, d.width - 320}
	ys = {150, d.height - 180}
	for _, _, _, x, y, w, h, _, _ in d.boxes:
		xs.update([x - 100, x - 65, x + w + 65, x + w + 100])
		ys.update([y - 85, y - 45, y + h + 45, y + h + 85])
	for x, y, *_ in d.pins.values():
		xs.add(x)
		ys.add(y)
	xs = sorted(xs)
	ys = sorted(ys)
	obstacles = [(b[3] - 20, b[4] - 20, b[3] + b[5] + 20, b[4] + b[6] + 20) for b in d.boxes]
	used = {}

	def clear(a, b):
		for x0, y0, x1, y1 in obstacles:
			if (
				a[0] == b[0]
				and x0 < a[0] < x1
				and max(min(a[1], b[1]), y0) < min(max(a[1], b[1]), y1)
			):
				return False
			if (
				a[1] == b[1]
				and y0 < a[1] < y1
				and max(min(a[0], b[0]), x0) < min(max(a[0], b[0]), x1)
			):
				return False
		return True

	new = []
	for _, src, dst, label in d.edges:
		a = d.pins[src][:2]
		b = d.pins[dst][:2]
		start = (xs.index(a[0]), ys.index(a[1]), 0)
		queue = [(0, 0, start)]
		cost = {start: 0}
		prev = {}
		end = None
		while queue:
			_, g, state = heapq.heappop(queue)
			if g != cost.get(state):
				continue
			x, y, axis = state
			if (xs[x], ys[y]) == b:
				end = state
				break
			for nx, ny, na in [(x - 1, y, 1), (x + 1, y, 1), (x, y - 1, 2), (x, y + 1, 2)]:
				if not (0 <= nx < len(xs) and 0 <= ny < len(ys)):
					continue
				p, q = (xs[x], ys[y]), (xs[nx], ys[ny])
				if not clear(p, q):
					continue
				# Leave/enter every pin horizontally, and keep tracks off the part boundary.
				if p == a and na != 1:
					continue
				if q == b and na != 1:
					continue
				if na == 2 and p[0] in (320, d.width - 320):
					continue
				edge = tuple(sorted((p, q)))
				ng = (
					g
					+ abs(p[0] - q[0])
					+ abs(p[1] - q[1])
					+ (100 if axis and axis != na else 0)
					+ used.get(edge, 0) * 180
				)
				ns = (nx, ny, na)
				if ng < cost.get(ns, float("inf")):
					cost[ns] = ng
					prev[ns] = state
					heapq.heappush(queue, (ng + abs(q[0] - b[0]) + abs(q[1] - b[1]), ng, ns))
		if end is None:
			raise RuntimeError(f"Cannot route {src} -> {dst}")
		points = []
		while True:
			points.append((xs[end[0]], ys[end[1]]))
			if end == start:
				break
			end = prev[end]
		points.reverse()
		for p, q in zip(points, points[1:]):
			edge = tuple(sorted((p, q)))
			used[edge] = used.get(edge, 0) + 1
		compact = []
		for p in points:
			if len(compact) >= 2 and (
				(compact[-2][0] == compact[-1][0] == p[0])
				or (compact[-2][1] == compact[-1][1] == p[1])
			):
				compact[-1] = p
			else:
				compact.append(p)
		new.append((compact, src, dst, label))
	d.edges = new
	return d
