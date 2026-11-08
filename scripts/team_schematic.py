"""Pin-on-box schematics: native SVG, PNG and editable diagrams.net pages."""

from pathlib import Path
import math
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/python"))
from PIL import Image, ImageDraw, ImageFont


class Diagram:
	def __init__(self, name, width, height):
		self.name, self.width, self.height = name, width, height
		self.boxes, self.edges, self.notes = [], [], []
		self.pins = {}

	def box(self, key, title, owner, x, y, w, h, left, right):
		self.boxes.append((key, title, owner, x, y, w, h, left, right))
		for side, pins in [("left", left), ("right", right)]:
			for i, (pin, bits, direction) in enumerate(pins):
				py = y + (i + 1) * h / (len(pins) + 1)
				px = x - 60 if side == "left" else x + w + 60
				self.pins[(key, pin)] = (px, py, side, bits, direction)

	def wire(self, source, target, via=(), label=""):
		a, b = self.pins[source], self.pins[target]
		self.edges.append(([a[:2], *via, b[:2]], source, target, label))


def system():
	d = Diagram("系统接口框图", 3300, 1800)
	d.box(
		"cpu",
		"CPU / 指令缓存",
		"A",
		400,
		210,
		370,
		460,
		[("clk", 1, "in"), ("rst", 1, "in"), ("cbr", 1, "in"), ("cbd", 32, "in")],
		[
			("cbv", 1, "out"),
			("ci", 1, "out"),
			("ca", 32, "out"),
			("cw", 32, "out"),
			("cs", 4, "out"),
		],
	)
	d.box(
		"bus",
		"仲裁 / 地址译码",
		"A",
		1450,
		190,
		400,
		600,
		[
			("CPU: valid", 1, "in"),
			("CPU: instr", 1, "in"),
			("CPU: addr", 32, "in"),
			("CPU: wdata", 32, "in"),
			("CPU: wstrb", 4, "in"),
			("CPU: ready", 1, "out"),
			("CPU: rdata", 32, "out"),
			("卷积 DMA 请求", "1 / 32 / 32 / 4", "in"),
			("卷积 DMA 应答", "1 / 32", "out"),
			("卷积 CSR 请求", "1 / 8 / 32 / 4", "out"),
			("卷积 CSR 应答", "1 / 32", "in"),
		],
		[
			("mem_valid", 1, "out"),
			("mem_addr", 32, "out"),
			("mem_wdata", 32, "out"),
			("mem_wstrb", 4, "out"),
			("mem_ready", 1, "in"),
			("mem_rdata", 32, "in"),
			("池化 DMA 请求", "1 / 32 / 32 / 4", "in"),
			("池化 DMA 应答", "1 / 32", "out"),
			("池化 CSR 请求", "1 / 8 / 32 / 4", "out"),
			("池化 CSR 应答", "1 / 32", "in"),
		],
	)
	d.box(
		"mem",
		"主存 / 系统 Testbench",
		"A / D",
		2580,
		200,
		400,
		570,
		[
			("mem_valid", 1, "in"),
			("mem_addr", 32, "in"),
			("mem_wdata", 32, "in"),
			("mem_wstrb", 4, "in"),
			("mem_ready", 1, "out"),
			("mem_rdata", 32, "out"),
		],
		[],
	)
	d.box(
		"conv",
		"det_accelerator",
		"B / C",
		400,
		1120,
		390,
		510,
		[
			("clk", 1, "in"),
			("rst", 1, "in"),
			("CSR 请求", "1 / 8 / 32 / 4", "in"),
			("CSR 应答", "1 / 32", "out"),
		],
		[("DMA 请求", "1 / 32 / 32 / 4", "out"), ("DMA 应答", "1 / 32", "in")],
	)
	d.box(
		"pool",
		"pool_accelerator",
		"D",
		2580,
		1120,
		390,
		510,
		[("CSR 请求", "1 / 8 / 32 / 4", "in"), ("CSR 应答", "1 / 32", "out")],
		[
			("clk", 1, "in"),
			("rst", 1, "in"),
			("DMA 请求", "1 / 32 / 32 / 4", "out"),
			("DMA 应答", "1 / 32", "in"),
		],
	)
	for p in ["mem_valid", "mem_addr", "mem_wdata", "mem_wstrb"]:
		d.wire(("bus", p), ("mem", p))
	for p in ["mem_ready", "mem_rdata"]:
		d.wire(("mem", p), ("bus", p))
	# Bundles are deliberately named as interfaces, with individual field widths.
	# They are not invented packed RTL signals; the lower modules list each pin.
	for a, b in [
		("cbv", "CPU: valid"),
		("ci", "CPU: instr"),
		("ca", "CPU: addr"),
		("cw", "CPU: wdata"),
		("cs", "CPU: wstrb"),
	]:
		d.wire(("cpu", a), ("bus", b))
	d.wire(
		("bus", "CPU: ready"),
		("cpu", "cbr"),
		[(1120, 490), (1120, 740), (220, 740), (220, d.pins[("cpu", "cbr")][1])],
	)
	d.wire(
		("bus", "CPU: rdata"),
		("cpu", "cbd"),
		[(1190, 540), (1190, 810), (160, 810), (160, d.pins[("cpu", "cbd")][1])],
	)
	d.wire(("conv", "DMA 请求"), ("bus", "卷积 DMA 请求"), [(1000, 1193), (1000, 523)])
	d.wire(("bus", "卷积 DMA 应答"), ("conv", "DMA 应答"), [(1180, 590), (1180, 1484)])
	d.wire(
		("bus", "卷积 CSR 请求"),
		("conv", "CSR 请求"),
		[(1220, 657), (1220, 950), (160, 950), (160, 1290)],
	)
	d.wire(
		("conv", "CSR 应答"),
		("bus", "卷积 CSR 应答"),
		[(230, 1517), (230, 1020), (1320, 1020), (1320, 723)],
	)
	d.wire(
		("pool", "DMA 请求"),
		("bus", "池化 DMA 请求"),
		[(3140, 1290), (3140, 880), (2050, 880), (2050, 572)],
	)
	d.wire(
		("bus", "池化 DMA 应答"),
		("pool", "DMA 应答"),
		[(2110, 626), (2110, 1000), (3200, 1000), (3200, 1517)],
	)
	d.wire(("bus", "池化 CSR 请求"), ("pool", "CSR 请求"), [(2200, 681), (2200, 1193)])
	d.wire(("pool", "CSR 应答"), ("bus", "池化 CSR 应答"), [(2300, 1484), (2300, 735)])
	d.notes = [
		(110, 70, "AI-SOC  系统接口框图", 36),
		(1480, 1020, "CSR请求：reg_valid(1)、reg_addr(8)", 20),
		(1480, 1060, "reg_wdata(32)、reg_wstrb(4)", 20),
		(1480, 1120, "CSR应答：reg_ready(1)、reg_rdata(32)", 20),
		(1480, 1200, "DMA请求：dma_valid(1)、dma_addr(32)", 20),
		(1480, 1240, "dma_wdata(32)、dma_wstrb(4)", 20),
		(1480, 1300, "DMA应答：dma_ready(1)、dma_rdata(32)", 20),
		(1480, 1390, "总线为逻辑分组，束线位宽分别标注。", 20),
		(1480, 1440, "同名clk/rst为全局网；resetn=!rst。", 20),
		(1480, 1490, "D池化/固件联调，C协审数值。", 20),
		(
			110,
			1740,
			"A 系统/缓存/总线  ·  B 控制/存储/预取  ·  C MAC/定点  ·  D 池化/固件/模型联调",
			24,
		),
	]

	return d


def datapath():
	d = Diagram("卷积与池化接口框图", 3400, 2150)
	d.box(
		"ctrl",
		"控制 / 地址生成",
		"B",
		480,
		780,
		380,
		900,
		[
			("clk", 1, "in"),
			("rst", 1, "in"),
			("reg_valid", 1, "in"),
			("reg_addr", 8, "in"),
			("reg_wdata", 32, "in"),
			("reg_wstrb", 4, "in"),
			("reg_ready", 1, "out"),
			("reg_rdata", 32, "out"),
			("dma_valid", 1, "out"),
			("dma_addr", 32, "out"),
			("dma_wdata", 32, "out"),
			("dma_wstrb", 4, "out"),
			("dma_ready", 1, "in"),
			("dma_rdata", 32, "in"),
			("fq_data", 8, "in"),
			("prefetch_done", 1, "in"),
			("prefetch_busy", 1, "in"),
		],
		[
			("x_read_addr", 36, "out"),
			("x_read_data", 128, "in"),
			("core_clear", 1, "out"),
			("P_RESTORE", 1, "out"),
			("ri[3:0]", 4, "out"),
			("psum_rd", 32, "out"),
			("core_step", 1, "out"),
			("avec", 32, "out"),
			("bvec", 32, "out"),
			("core_result", 32, "in"),
			("biased[31:0]", 32, "out"),
			("qmult", 31, "out"),
			("qshift", 6, "out"),
			("qresult", 8, "in"),
		],
	)
	d.box(
		"core",
		"conv_core",
		"C",
		1450,
		850,
		370,
		660,
		[
			("clk", 1, "in"),
			("rst", 1, "in"),
			("clear", 1, "in"),
			("restore", 1, "in"),
			("index", 4, "in"),
			("restore_data", 32, "in"),
			("step", 1, "in"),
			("a_vector", 32, "in"),
			("b_vector", 32, "in"),
		],
		[("result", 32, "out")],
	)
	d.box(
		"q",
		"requant",
		"C",
		2450,
		880,
		340,
		320,
		[("value", 32, "in"), ("multiplier", 31, "in"), ("shift", 6, "in")],
		[("result", 8, "out")],
	)
	d.box(
		"bank",
		"banked_scratch ×4",
		"B",
		1450,
		170,
		370,
		440,
		[
			("clk", 1, "in"),
			("write_valid", 1, "in"),
			("write_bank", 2, "in"),
			("write_addr", 9, "in"),
			("write_data", 32, "in"),
			("write_strobe", 4, "in"),
			("read_addr", 36, "in"),
		],
		[("read_data", 128, "out")],
	)
	d.box(
		"pf",
		"tile_prefetch",
		"B",
		2450,
		170,
		370,
		440,
		[
			("clk", 1, "in"),
			("rst", 1, "in"),
			("start", 1, "in"),
			("consume", 1, "in"),
			("read_ready", 1, "in"),
			("read_data", 32, "in"),
		],
		[
			("busy", 1, "out"),
			("done", 1, "out"),
			("read_valid", 1, "out"),
			("read_addr", 32, "out"),
			("x_write / w_write", "1 / 1", "out"),
			("write_index", 13, "out"),
			("write_data", 32, "out"),
			("write_strobe", 4, "out"),
		],
	)
	d.box(
		"fq",
		"fuse_requant",
		"C",
		480,
		170,
		370,
		440,
		[
			("clk", 1, "in"),
			("rst", 1, "in"),
			("cfg_valid", 1, "in"),
			("in_valid", 1, "in"),
			("src_id", 1, "in"),
			("in_data", 8, "in"),
			("out_ready", 1, "in"),
		],
		[
			("cfg_ready", 1, "out"),
			("in_ready", 1, "out"),
			("out_valid", 1, "out"),
			("out_data", 8, "out"),
		],
	)
	d.box(
		"pool",
		"pool_accelerator",
		"D",
		2450,
		1450,
		370,
		480,
		[
			("clk", 1, "in"),
			("rst", 1, "in"),
			("reg_valid", 1, "in"),
			("reg_addr", 8, "in"),
			("reg_wdata", 32, "in"),
			("reg_wstrb", 4, "in"),
		],
		[
			("reg_ready", 1, "out"),
			("reg_rdata", 32, "out"),
			("dma_valid", 1, "out"),
			("dma_addr", 32, "out"),
			("dma_wdata", 32, "out"),
			("dma_wstrb", 4, "out"),
			("dma_ready", 1, "in"),
			("dma_rdata", 32, "in"),
		],
	)
	for a, b in [
		("core_clear", "clear"),
		("P_RESTORE", "restore"),
		("ri[3:0]", "index"),
		("psum_rd", "restore_data"),
		("core_step", "step"),
		("avec", "a_vector"),
		("bvec", "b_vector"),
	]:
		d.wire(("ctrl", a), ("core", b))
	d.wire(
		("core", "result"),
		("ctrl", "core_result"),
		[(2030, 1180), (2030, 1570), (1190, 1570), (1190, 1380)],
	)
	for i, (a, b) in enumerate(
		[("biased[31:0]", "value"), ("qmult", "multiplier"), ("qshift", "shift")]
	):
		cx, cy, tx = 1150 + i * 70, 700 + i * 40, 2150 + i * 70
		d.wire(
			("ctrl", a),
			("q", b),
			[(cx, d.pins[("ctrl", a)][1]), (cx, cy), (tx, cy), (tx, d.pins[("q", b)][1])],
		)
	d.wire(
		("q", "result"),
		("ctrl", "qresult"),
		[(3020, 1040), (3020, 1270), (2270, 1270), (2270, 1660), (1300, 1660), (1300, 1620)],
	)
	d.wire(("ctrl", "x_read_addr"), ("bank", "read_addr"), [(1000, 840), (1000, 555)])
	d.wire(
		("bank", "read_data"),
		("ctrl", "x_read_data"),
		[(2040, 390), (2040, 650), (1080, 650), (1080, 900)],
	)
	d.wire(
		("fq", "out_data"),
		("ctrl", "fq_data"),
		[(950, 522), (950, 660), (150, 660), (150, d.pins[("ctrl", "fq_data")][1])],
	)
	d.wire(
		("pf", "busy"),
		("ctrl", "prefetch_busy"),
		[
			(3200, d.pins[("pf", "busy")][1]),
			(3200, 680),
			(200, 680),
			(200, d.pins[("ctrl", "prefetch_busy")][1]),
		],
	)
	d.wire(
		("pf", "done"),
		("ctrl", "prefetch_done"),
		[
			(3260, d.pins[("pf", "done")][1]),
			(3260, 720),
			(260, 720),
			(260, d.pins[("ctrl", "prefetch_done")][1]),
		],
	)
	d.notes = [
		(110, 70, "LAYER / AI-SOC  模块接口框图", 36),
		(
			100,
			1740,
			"控制/地址块为 det_accelerator 内部逻辑分组；P_RESTORE 是 state == P_RESTORE 的使能条件。",
			22,
		),
		(
			100,
			1790,
			"X/W 共四个同型存储实例，示例连 X 读接口；前台/后台写入须经过控制器的 bank/地址映射。",
			22,
		),
		(100, 1840, "池化是独立外设，仅通过 CSR / DMA 接系统总线，不将其伪接成卷积后级流水。", 22),
		(100, 1890, "图中仅标主要跨块接口；配置、token、完整握手及所有位宽见 Excel 端口表。", 22),
		(
			100,
			1940,
			"红线为主要连接，交叉无圆点表示不相连；同名 clk/rst、CSR/DMA 接系统页网络。",
			22,
		),
		(
			100,
			2090,
			"A 系统/缓存/总线  ·  B 控制/存储/预取  ·  C MAC/定点  ·  D 池化/固件/模型联调",
			24,
		),
	]
	return d


def font(size):
	for path in [
		Path("/mnt/c/Windows/Fonts/msyh.ttc"),
		Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
	]:
		if path.exists():
			return ImageFont.truetype(str(path), size)
	raise RuntimeError("生成PNG需要微软雅黑或Noto Sans CJK中文字体；Excel和已生成PNG可直接查看")


def render(d, destination, stem, mxroot):
	parts = [
		f'<svg xmlns="http://www.w3.org/2000/svg" width="{d.width}" height="{d.height}" viewBox="0 0 {d.width} {d.height}">',
		'<defs><marker id="pinArrow" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="none" stroke="black" stroke-width="1"/></marker><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="none" stroke="#d32f2f" stroke-width="1.5"/></marker></defs>',
		'<rect width="100%" height="100%" fill="white"/>',
		f'<rect x="75" y="100" width="{d.width - 150}" height="{d.height - 230}" fill="none" stroke="black" stroke-width="2"/>',
	]
	im = Image.new("RGB", (d.width, d.height), "white")
	draw = ImageDraw.Draw(im)
	draw.rectangle((75, 100, d.width - 75, d.height - 130), outline="black", width=2)
	page = ET.SubElement(mxroot, "diagram", name=d.name, id=stem)
	model = ET.SubElement(
		page,
		"mxGraphModel",
		dx=str(d.width),
		dy=str(d.height),
		grid="1",
		gridSize="10",
		page="1",
		pageScale="1",
		pageWidth=str(d.width),
		pageHeight=str(d.height),
	)
	root = ET.SubElement(model, "root")
	ET.SubElement(root, "mxCell", id="0")
	ET.SubElement(root, "mxCell", id="1", parent="0")
	serial = 0

	def text(x, y, s, size=22, anchor="start", bold=False):
		nonlocal serial
		parts.append(
			f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Microsoft YaHei,Noto Sans CJK SC,sans-serif" font-size="{size}">{escape(str(s))}</text>'
		)
		bbox = draw.textbbox((0, 0), str(s), font=font(size))
		w = bbox[2] - bbox[0]
		px = x if anchor == "start" else x - w if anchor == "end" else x - w / 2
		draw.text((px, y - size), str(s), font=font(size), fill="black")
		serial += 1
		cell = ET.SubElement(
			root,
			"mxCell",
			id=f"t{serial}",
			value=str(s),
			style=f"text;html=0;align={'left' if anchor == 'start' else 'right' if anchor == 'end' else 'center'};verticalAlign=middle;whiteSpace=wrap;fontSize={size};fontFamily=Microsoft YaHei;strokeColor=none;fillColor=none;",
			vertex="1",
			parent="1",
		)
		ET.SubElement(
			cell,
			"mxGeometry",
			x=str(px),
			y=str(y - size - 3),
			width=str(max(w + 12, 30)),
			height=str(size + 12),
			**{"as": "geometry"},
		)

	for key, title, owner, x, y, w, h, left, right in d.boxes:
		parts.append(
			f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="white" stroke="black" stroke-width="2.5"/>'
		)
		draw.rectangle((x, y, x + w, y + h), outline="black", width=3)
		cell = ET.SubElement(
			root,
			"mxCell",
			id=key,
			value=f"{title}\n{owner}",
			style="rounded=0;whiteSpace=wrap;html=0;fillColor=#ffffff;strokeColor=#000000;fontSize=26;fontFamily=Microsoft YaHei;",
			vertex="1",
			parent="1",
		)
		ET.SubElement(
			cell,
			"mxGeometry",
			x=str(x),
			y=str(y),
			width=str(w),
			height=str(h),
			**{"as": "geometry"},
		)
		# The SVG/PNG box contains only module name and owner.
		for delta, s in [(-16, title), (28, owner)]:
			parts.append(
				f'<text x="{x + w / 2}" y="{y + h / 2 + delta}" text-anchor="middle" font-family="Microsoft YaHei,Noto Sans CJK SC,sans-serif" font-size="26">{escape(s)}</text>'
			)
			bb = draw.textbbox((0, 0), s, font=font(26))
			draw.text(
				(x + w / 2 - (bb[2] - bb[0]) / 2, y + h / 2 + delta - 26),
				s,
				font=font(26),
				fill="black",
			)
	for (key, pin), (px, py, side, bits, direction) in d.pins.items():
		frame_x = px + 60 if side == "left" else px - 60
		p0, p1 = ((px, py), (frame_x, py)) if direction == "in" else ((frame_x, py), (px, py))
		parts.append(
			f'<line x1="{p0[0]}" y1="{py}" x2="{p1[0]}" y2="{py}" stroke="black" stroke-width="2" marker-end="url(#pinArrow)"/>'
		)
		draw.line((p0, p1), fill="black", width=2)
		sign = 1 if p1[0] > p0[0] else -1
		draw.line(
			(p1[0] - sign * 8, py - 4, p1[0], py, p1[0] - sign * 8, py + 4), fill="black", width=2
		)
		cell = ET.SubElement(
			root,
			"mxCell",
			id=f"pin{key}{serial}",
			style="edgeStyle=none;endArrow=open;endSize=6;strokeColor=#000000;strokeWidth=2;",
			edge="1",
			parent="1",
		)
		geometry = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
		ET.SubElement(geometry, "mxPoint", x=str(p0[0]), y=str(py), **{"as": "sourcePoint"})
		ET.SubElement(geometry, "mxPoint", x=str(p1[0]), y=str(py), **{"as": "targetPoint"})
		text(
			frame_x - 10 if side == "left" else frame_x + 10,
			py - 9,
			pin,
			20,
			"end" if side == "left" else "start",
		)
		if isinstance(bits, str):
			text(
				frame_x - 10 if side == "left" else frame_x + 10,
				py + 20,
				bits,
				17,
				"end" if side == "left" else "start",
			)
		else:
			text((px + frame_x) / 2, py + 20, bits, 17, "middle")
	for index, (points, source, target, label) in enumerate(d.edges):
		coords = " ".join(f"{x},{y}" for x, y in points)
		parts.append(
			f'<polyline points="{coords}" fill="none" stroke="#d32f2f" stroke-width="2.2" marker-end="url(#arrow)"/>'
		)
		draw.line(points, fill="#d32f2f", width=2)
		x, y = points[-1]
		a, b = points[-2]
		angle = math.atan2(y - b, x - a)
		draw.polygon(
			[
				(x, y),
				(x - 12 * math.cos(angle - 0.45), y - 12 * math.sin(angle - 0.45)),
				(x - 12 * math.cos(angle + 0.45), y - 12 * math.sin(angle + 0.45)),
			],
			fill="#d32f2f",
		)
		cell = ET.SubElement(
			root,
			"mxCell",
			id=f"e{index}",
			value=label,
			style="edgeStyle=none;rounded=0;html=0;endArrow=open;endFill=0;strokeColor=#d32f2f;strokeWidth=2;",
			edge="1",
			parent="1",
		)
		geo = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
		ET.SubElement(
			geo, "mxPoint", x=str(points[0][0]), y=str(points[0][1]), **{"as": "sourcePoint"}
		)
		ET.SubElement(
			geo, "mxPoint", x=str(points[-1][0]), y=str(points[-1][1]), **{"as": "targetPoint"}
		)
		if len(points) > 2:
			array = ET.SubElement(geo, "Array", **{"as": "points"})
			for x, y in points[1:-1]:
				ET.SubElement(array, "mxPoint", x=str(x), y=str(y))
	for x, y, s, size in d.notes:
		text(x, y, s, size)
	parts.append("</svg>")
	(destination / f"{stem}.svg").write_text("\n".join(parts))
	im.save(destination / f"{stem}.png")
	# DOT is a port-level topology alternative; diagrams.net preserves this layout.
	lines = [
		"digraph Interfaces {",
		"graph [rankdir=LR];",
		'node [shape=record,fontname="Microsoft YaHei",fontsize=12];',
	]
	for key, title, owner, x, y, w, h, left, right in d.boxes:
		lp = "|".join(f"<l{i}> {p} ({b})" for i, (p, b, _) in enumerate(left)) or " "
		rp = "|".join(f"<r{i}> {p} ({b})" for i, (p, b, _) in enumerate(right)) or " "
		lines.append(f'{key} [label="{{{{{lp}}}|{title}\\n{owner}|{{{rp}}}}}"];')
	for _, source, target, label in d.edges:

		def port_id(endpoint):
			key, pin = endpoint
			box = next(b for b in d.boxes if b[0] == key)
			for prefix, ports in [("l", box[7]), ("r", box[8])]:
				for i, (p, _, _) in enumerate(ports):
					if p == pin:
						return f"{key}:{prefix}{i}"

		lines.append(f"{port_id(source)} -> {port_id(target)} [color=red];")
	lines.append("}")
	(destination / f"{stem}.dot").write_text("\n".join(lines) + "\n")


def render_diagrams(destination):
	mx = ET.Element("mxfile", host="app.diagrams.net", type="device")
	for diagram, stem in [(system(), "team-system"), (datapath(), "team-datapath")]:
		render(diagram, destination, stem, mx)
	ET.ElementTree(mx).write(
		destination / "team-interfaces.drawio", encoding="utf-8", xml_declaration=True
	)
