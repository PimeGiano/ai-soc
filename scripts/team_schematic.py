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
		self.boundary = False

	def box(self, key, title, owner, x, y, w, h, left, right):
		self.boxes.append((key, title, owner, x, y, w, h, left, right))
		for side, pins in [("left", left), ("right", right)]:
			for i, (pin, bits, direction) in enumerate(pins):
				py = y + (i + 1) * h / (len(pins) + 1)
				px = x - 60 if side.endswith("left") else x + w + 60
				self.pins[(key, pin)] = (px, py, side, bits, direction)

	def outer(self, left, right):
		"""Whole-part ports; endpoints lie on the enclosing RTL boundary."""
		self.boundary = True
		for side, ports in [("left", left), ("right", right)]:
			for i, (name, bits, direction) in enumerate(ports):
				x = 320 if side.endswith("left") else self.width - 320
				y = 210 + (i + 1) * (self.height - 570) / (len(ports) + 1)
				self.pins[("boundary", name)] = (x, y, "boundary-" + side, bits, direction)

	def wire(self, source, target, via=(), label=""):
		a, b = self.pins[source], self.pins[target]
		self.edges.append(([a[:2], *via, b[:2]], source, target, label))


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
		f'<rect x="{320 if d.boundary else 75}" y="100" width="{d.width - (640 if d.boundary else 150)}" height="{d.height - 230}" fill="none" stroke="black" stroke-width="2"/>',
	]
	im = Image.new("RGB", (d.width, d.height), "white")
	draw = ImageDraw.Draw(im)
	margin = 320 if d.boundary else 75
	draw.rectangle((margin, 100, d.width - margin, d.height - 130), outline="black", width=2)
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
	frame = ET.SubElement(
		root,
		"mxCell",
		id="boundary",
		value="",
		style="fillColor=none;strokeColor=#000000;strokeWidth=2;",
		vertex="1",
		parent="1",
	)
	ET.SubElement(
		frame,
		"mxGeometry",
		x=str(margin),
		y="100",
		width=str(d.width - 2 * margin),
		height=str(d.height - 230),
		**{"as": "geometry"},
	)
	serial = 0
	text_parent, text_offset = "1", (0, 0)

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
			parent=text_parent,
		)
		ET.SubElement(
			cell,
			"mxGeometry",
			x=str(px - text_offset[0]),
			y=str(y - size - 3 - text_offset[1]),
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
	anchors = {}
	for pin_number, ((key, pin), (px, py, side, bits, direction)) in enumerate(d.pins.items()):
		if key == "boundary":
			text_parent, text_offset = "1", (0, 0)
		else:
			box = next(b for b in d.boxes if b[0] == key)
			text_parent, text_offset = key, (box[3], box[4])
		anchor_id = f"anchor{pin_number}"
		anchors[(key, pin)] = anchor_id
		anchor = ET.SubElement(
			root,
			"mxCell",
			id=anchor_id,
			value="",
			style="shape=ellipse;opacity=0;resizable=0;",
			vertex="1",
			connectable="1",
			parent=text_parent,
		)
		ET.SubElement(
			anchor,
			"mxGeometry",
			x=str(px - text_offset[0] - 0.5),
			y=str(py - text_offset[1] - 0.5),
			width="1",
			height="1",
			**{"as": "geometry"},
		)
		is_boundary = side.startswith("boundary-")
		left_side = side.endswith("left")
		frame_x = px + (60 if left_side else -60) * (-1 if is_boundary else 1)
		p0, p1 = (
			((px, py), (frame_x, py))
			if (direction == "in") != is_boundary
			else ((frame_x, py), (px, py))
		)
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
			parent=text_parent,
		)
		geometry = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
		ET.SubElement(
			geometry,
			"mxPoint",
			x=str(p0[0] - text_offset[0]),
			y=str(py - text_offset[1]),
			**{"as": "sourcePoint"},
		)
		ET.SubElement(
			geometry,
			"mxPoint",
			x=str(p1[0] - text_offset[0]),
			y=str(py - text_offset[1]),
			**{"as": "targetPoint"},
		)
		text(
			frame_x - 10 if side.endswith("left") else frame_x + 10,
			py - 9,
			pin,
			20,
			"end" if side.endswith("left") else "start",
		)
		if isinstance(bits, str):
			text(
				frame_x - 10 if side.endswith("left") else frame_x + 10,
				py + 20,
				bits,
				17,
				"end" if side.endswith("left") else "start",
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
			source=anchors[source],
			target=anchors[target],
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
	text_parent, text_offset = "1", (0, 0)
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
	if d.boundary:
		for (key, pin), (_, _, _, bits, direction) in d.pins.items():
			if key == "boundary":
				lines.append(
					f'"external_{pin}" [shape=plaintext,label="{pin} ({bits}) {direction}"];'
				)
	for _, source, target, label in d.edges:

		def port_id(endpoint):
			key, pin = endpoint
			if key == "boundary":
				return f'"external_{pin}"'
			box = next(b for b in d.boxes if b[0] == key)
			for prefix, ports in [("l", box[7]), ("r", box[8])]:
				for i, (p, _, _) in enumerate(ports):
					if p == pin:
						return f"{key}:{prefix}{i}"

		lines.append(f"{port_id(source)} -> {port_id(target)} [color=red];")
	lines.append("}")
	(destination / f"{stem}.dot").write_text("\n".join(lines) + "\n")


def render_diagrams(destination):
	from team_detail import system_detail, cpu_cache, accelerator, route

	mx = ET.Element("mxfile", host="app.diagrams.net", type="device")
	for diagram, stem in [
		(system_detail(), "team-system"),
		(cpu_cache(), "team-cpu-cache"),
		(accelerator(), "team-accelerator"),
	]:
		render(route(diagram), destination, stem, mx)
	ET.ElementTree(mx).write(
		destination / "team-interfaces.drawio", encoding="utf-8", xml_declaration=True
	)
	# Existing workbook/document references continue to point at the current accelerator page.
	for extension in ["svg", "png", "dot"]:
		(destination / f"team-datapath.{extension}").write_bytes(
			(destination / f"team-accelerator.{extension}").read_bytes()
		)


if __name__ == "__main__":
	render_diagrams(ROOT / "docs")
