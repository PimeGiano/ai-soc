"""Export the example's six-column module table and current SoC diagrams.

Uses standard-library OOXML writing and Pillow for pin-on-box schematics.
No workbook macros, network links or extra Python spreadsheet dependency.
"""

from pathlib import Path
import hashlib
import math
import re
import struct
import zipfile
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs"
TEMPLATE = ROOT / "分工+框图_v0_示例.xlsx"
OUTPUT = ROOT / "分工+框图_ai-soc.xlsx"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
COLORS = {"A": "DBEAFE", "B": "DCFCE7", "C": "EDE9FE", "D": "FEF3C7"}
MODULES = [
	("det_soc_top", "A", "系统顶层，含CPU/缓存/两级仲裁/卷积及池化外设"),
	("native_arbiter", "A", "两处实例：CPU/卷积仲裁，以及共享出口/池化仲裁"),
	("instruction_cache", "A", "1KiB直接映射取指缓存，程序区写失效"),
	("det_accelerator", "B", "卷积/融合主控制器、描述符、分块与DMA调度"),
	("tile_prefetch", "B", "下一Cin块X/W后台预取，含融合映射与读缓存"),
	("banked_scratch", "B", "X/W共4处实例；每实例4×2KiB独立bank"),
	("conv_core", "C", "4×4 INT8广播MAC，16个INT32累加器"),
	("fuse_requant", "C", "前台融合输入定点转换，单样本弹性握手"),
	("requant", "C", "共享算术模块类型：输出、前台/后台输入转换"),
	("pool_accelerator", "D", "独立2×2最大池化、四通道比较及DMA"),
]
OWNERS = {"A": "A（待填姓名）", "B": "B（待填姓名）", "C": "C（待填姓名）", "D": "D（待填姓名）"}
ROLES = [
	(
		"A",
		"SoC / 总线 / 缓存 / 系统验证",
		"det_soc_top、native_arbiter、instruction_cache；tb/soc.cpp、tb/cache.cpp、综合与构建脚本",
		"CPU接入、两级仲裁、地址译码、取指缓存、ROI计数、系统联调及结构综合",
		"读懂PicoRV32接入口；仲裁锁定/缓存失效正确；两模型完整推理与源/构建指纹一致",
	),
	(
		"B",
		"融合 / 调度 / 存储 / 预取",
		"det_accelerator、tile_prefetch、banked_scratch；spec/registers.json、tb/accelerator.cpp",
		"描述符校验、ORDER和双源映射、四路bank、双slot、DMA锁定、P/O控制与阶段计数",
		"0/3/15等待下158任务、6组压力与预取复位；无越界、正确slot切换；消融可复现",
	),
	(
		"C",
		"MAC / 定点 / 池化数值协审",
		"conv_core、requant、fuse_requant；tb/converter.cpp；协审tb/pool.cpp",
		"INT8×INT8→INT32、部分和恢复、64位乘移舍入、饱和；协审2×2池化数值与边界",
		"2048转换样本；100池化+5非法配置；跨Cin与-128边界逐元素一致；无额外池化RAM",
	),
	(
		"D",
		"池化硬件 / 固件 / 模型联调",
		"pool_accelerator、tb/pool.cpp；firmware/、model.py、reference.py、export_model.py、evaluate.py、gen_*.py",
		"池化硬件与驱动、模型图/量化、融合识别、CPU算子、解码NMS、COCO与独立参考联调",
		"两模型M/F逐层与CPU框一致；100校准/500评价不重叠；完整INT8转换/字复制验证",
	),
]


def ports(module):
	text = (ROOT / "rtl" / f"{module}.sv").read_text()
	start = text.index("\n\tinput wire")
	header = text[start : text.index("\n);", start)]
	result = []
	for line in header.splitlines():
		m = re.match(
			r"\s*(input|output)\s+(?:wire|reg)\s+(signed\s+)?(?:\[(\d+):(\d+)\]\s+)?(.+)", line
		)
		if not m:
			continue
		direction, signed, hi, lo, names = m.groups()
		width = int(hi) - int(lo) + 1 if hi else 1
		for name in names.rstrip(",").split(","):
			name = name.strip()
			assert re.fullmatch(r"\w+", name), (module, name)
			result.append((name, "in" if direction == "input" else "out", width, bool(signed)))
	assert result and len({p[0] for p in result}) == len(result), module
	return result


COMMON = {
	"clk": "系统时钟，上升沿更新时序状态",
	"rst": "高有效同步复位；中断在途任务并清控制/计数，RAM内容不整体清零",
	"reg_valid": "MMIO访问有效",
	"reg_addr": "MMIO窗口内字节偏移，32位配置访问须4字节对齐",
	"reg_wdata": "MMIO写数据",
	"reg_wstrb": "MMIO写字节选通；配置写要求1111，0000表示读",
	"reg_ready": "MMIO访问完成握手",
	"reg_rdata": "MMIO读回的配置、状态或计数",
	"dma_valid": "DMA请求有效；等待期间地址、数据和选通保持稳定",
	"dma_addr": "DMA对齐字地址，低两位为0",
	"dma_wdata": "DMA写数据；与wstrb选中的字节对应",
	"dma_wstrb": "DMA字节写使能；0000读、非零写",
	"dma_ready": "DMA本次事务完成，不是仅接收请求",
	"dma_rdata": "DMA完成时的32位读数据",
	"result": "定点运算结果，具体格式见模块说明",
}
SPECIFIC = {
	"det_soc_top": {
		"trap": "PicoRV32异常/非法执行指示，由系统测试平台检查",
		"mem_valid": "共享外部主存请求；不含片上MMIO与缓存命中",
		"mem_addr": "共享外部主存字地址",
		"mem_wdata": "共享外部主存写数据",
		"mem_wstrb": "共享外部主存字节选通；0表示读",
		"mem_ready": "外部主存完成应答",
		"mem_rdata": "外部主存32位读数据",
		"mem_dma": "外部完成事务来自卷积或池化DMA，用于ROI分类",
		"mem_instr": "有意义的外部完成事务中，CPU取指标志",
	},
	"instruction_cache": {
		"cpu_valid": "CPU原生请求有效",
		"cpu_instr": "CPU取指标志；仅64KiB程序区取指参与缓存",
		"cpu_addr": "CPU字节地址；标签与索引取对应地址位",
		"cpu_wstrb": "CPU写字节选通；程序区完成写使对应行失效",
		"cpu_ready": "缓存命中或下游总线完成时应答CPU",
		"cpu_rdata": "缓存命中数据或旁路总线读数据",
		"bus_valid": "未命中的请求/非取指请求向仲裁器转发",
		"bus_ready": "下游CPU侧事务完成",
		"bus_rdata": "下游CPU侧读数据",
	},
	"conv_core": {
		"clear": "同步清零16个累加器，优先于restore/step",
		"restore": "恢复index对应的一个部分和；该拍不执行step",
		"index": "16个累加器的串行恢复/读出索引0..15",
		"restore_data": "有符号INT32部分和恢复数据",
		"step": "使能一次4×4外积累加；clear/restore时不执行",
		"a_vector": "四个INT8激活打包，低字节对应第0行",
		"b_vector": "四个INT8权重打包，低字节对应第0列",
		"result": "acc[index]，有符号INT32组合读出",
	},
	"banked_scratch": {
		"write_valid": "本拍写有效；每实例仅一个写入口",
		"write_bank": "选择四个物理bank之一（0..3）",
		"write_addr": "选中bank内32位字地址0..511",
		"write_data": "写入的32位数据",
		"write_strobe": "四个字节独立写使能，保护未选中的字节",
		"read_addr": "4×9位打包，分别为四个bank的字读地址",
		"read_data": "4×32位打包，每个bank一个读口；不是一个128位任意地址读口",
	},
	"fuse_requant": {
		"cfg_valid": "空闲时提交双源乘移参数",
		"cfg_ready": "输出槽为空时允许配置",
		"m0": "低分辨率源非负31位整数乘子",
		"m1": "高分辨率源非负31位整数乘子",
		"s0": "低路右移位数，合法范围0..62",
		"s1": "高路右移位数，合法范围0..62",
		"in_valid": "输入样本与源编号有效",
		"in_ready": "本拍可接受样本；遵循valid/ready",
		"src_id": "0选低路参数，1选高路参数",
		"in_data": "有符号INT8输入样本",
		"in_token": "随样本透传的16位标签；当前前台控制器固定为0",
		"out_valid": "转换结果有效，未被接受时保持",
		"out_ready": "下游可接受转换结果",
		"out_data": "有符号INT8，半值远离零舍入并饱和至[-127,127]",
		"out_token": "与结果对应的16位标签；当前控制器未连接该输出",
	},
	"requant": {
		"value": "有符号INT32值，内部使用有符号64位乘积",
		"multiplier": "非负31位整数乘子",
		"shift": "右移位数0..62，半值远离零舍入",
		"result": "有符号INT8结果，饱和到[-127,127]",
	},
	"tile_prefetch": {
		"start": "前台开始计算当前块时启动下一Cin块预取",
		"consume": "IC_NEXT已接收完成块，清done；随后交换slot",
		"fused": "1为双源融合，0为普通NHWC输入",
		"src": "普通输入主存基址",
		"weight": "OHWI权重主存基址",
		"src0": "低分辨率源基址",
		"src1": "高分辨率源基址",
		"width0": "低路源宽度",
		"width1": "高路源宽度",
		"channels0": "低路源通道数",
		"channels1": "高路源通道数",
		"order": "0低路在前、1高路在前；由配置检查限制",
		"multiplier0": "低路输入尺度转换乘子",
		"multiplier1": "高路输入尺度转换乘子",
		"shift0": "低路尺度转换右移位数",
		"shift1": "高路尺度转换右移位数",
		"height": "虚拟高分辨率输入H",
		"width": "虚拟高分辨率输入W",
		"cin": "虚拟输入总通道数",
		"cout": "该卷积总输出通道数",
		"kh": "卷积核高度1或3",
		"kw": "卷积核宽度，与kh相同",
		"tic": "输入通道tile容量4/8/16",
		"toc": "输出通道tile容量4/8/16",
		"next_ic": "下一输入通道块的起始通道",
		"oc": "当前输出通道tile起点",
		"xh": "当前输入tile含halo的高度",
		"xw": "当前输入tile含halo的宽度",
		"ytop": "有符号输入tile顶端坐标，可为负表示padding",
		"xtop": "有符号输入tile左端坐标，可为负表示padding",
		"busy": "预取状态机忙；与前台计算可重叠",
		"done": "下一块X/W全部填充完成，等待consume",
		"read_valid": "后台原生DMA读请求有效",
		"read_addr": "后台32位对齐主存地址",
		"read_ready": "后台读事务完成，经前后台锁定仲裁得到",
		"read_data": "后台完成时32位主存读数据",
		"x_write": "本拍写非活动slot的X",
		"w_write": "本拍写非活动slot的W",
		"write_index": "逻辑tile内字节索引0..8191，由控制器转成bank/字地址",
		"write_data": "整字或重复字节打包写数据",
		"write_strobe": "本拍有效字节选通",
	},
}


def describe(module, name, signed):
	if name in SPECIFIC.get(module, {}):
		return SPECIFIC[module][name]
	if name in COMMON:
		return COMMON[name]
	if module == "native_arbiter":
		prefix, field = name.split("_", 1)
		side = {"c": "C侧主设备", "d": "D侧主设备", "s": "共享从设备侧"}[prefix]
		meaning = {
			"valid": "请求有效，竞争时轮流选择，等待期间锁定所有者",
			"addr": "32位字节地址",
			"wdata": "32位写数据",
			"wstrb": "4位字节写选通；0表示读",
			"ready": "当前事务完成",
			"rdata": "32位读数据",
		}[field]
		return f"{side}：{meaning}"
	raise ValueError((module, name, "missing explanation"))


INTERFACES = [
	(
		"J01",
		"picorv32.mem_*",
		"instruction_cache.cpu_*",
		"valid/instr/ready=1，addr/data=32，wstrb=4",
		"CPU原生完成握手；第三方CPU仅复用和配置，不改内部RTL",
		"A ↔ A",
	),
	(
		"J02",
		"instruction_cache.bus_valid；CPU ca/cw/cs",
		"arb.c_*",
		"valid/ready=1，addr/data=32，wstrb=4",
		"缓存只拦截命中取指；地址/写数据/选通直接接仲裁器",
		"A ↔ A",
	),
	(
		"J03",
		"det_accelerator.dma_*",
		"arb.d_*",
		"valid/ready=1，addr/data=32，wstrb=4",
		"卷积前台/后台共享同一个对外DMA主接口",
		"B ↔ A",
	),
	(
		"J04",
		"arb.s_*",
		"地址译码（det_soc_top内部）",
		"valid/ready=1，addr/data=32，wstrb=4",
		"CPU/卷积组合出口先译码，MMIO在片上完成",
		"A ↔ A",
	),
	(
		"J05",
		"译码0x100001xx",
		"det_accelerator.reg_*",
		"offset=8，wdata/rdata=32，wstrb=4",
		"卷积CSR、状态、描述符地址及阶段/预取计数",
		"A ↔ B",
	),
	(
		"J06",
		"译码0x100002xx",
		"pool_accelerator.reg_*",
		"offset=8，wdata/rdata=32，wstrb=4",
		"池化SRC/DST/H/W/C/STRIDE/START/STATUS",
		"A ↔ C",
	),
	(
		"J07",
		"非MMIO的arb.s_*",
		"pool_arbiter.c_*",
		"valid/ready=1，addr/data=32，wstrb=4",
		"CPU/卷积外存请求进入外层仲裁器C侧",
		"A ↔ A",
	),
	(
		"J08",
		"pool_accelerator.dma_*",
		"pool_arbiter.d_*",
		"valid/ready=1，addr/data=32，wstrb=4",
		"池化为第三主设备；未完成事务保持稳定",
		"C ↔ A",
	),
	(
		"J09",
		"pool_arbiter.s_* / det_soc_top.mem_*",
		"tb/soc.cpp主存BFM",
		"valid/ready=1，addr/data=32，wstrb=4",
		"64KiB程序+64MiB数据为仿真模型；不是真实DDR控制器",
		"A ↔ A/D",
	),
	(
		"J10",
		"det_accelerator前后台DMA选择器",
		"tile_prefetch.read_*",
		"valid/ready=1，addr/data=32",
		"后台只读；请求等待时锁定选中方直到完成",
		"B ↔ B",
	),
	(
		"J11",
		"det_accelerator / tile_prefetch",
		"slots[0/1].input_store / weight_store",
		"write:1+2+9+32+4；read:36→128",
		"共4个banked_scratch实例；每实例四个2KiB bank；非活动slot写、活动slot读",
		"B ↔ B",
	),
	(
		"J12",
		"四bank读数据→bank旋转/冲突检测",
		"conv_core.a_vector / b_vector / step",
		"32 / 32 / 1",
		"每向量4×INT8；冲突可回退；无冲突每拍完整向量，末次排空",
		"B ↔ C",
	),
	(
		"J13",
		"det_accelerator内部psum数组",
		"conv_core.restore/index/restore_data/result",
		"1 / 4 / 32 / 32",
		"P是控制器内1024×INT32数组，不存在独立psum_ram.sv端口",
		"B ↔ C",
	),
	(
		"J14",
		"前台源样本/双源参数",
		"fuse_requant",
		"样本8，src_id1，m31×2，s6×2，token16",
		"前台转换valid/ready；当前token=0，out_token未接",
		"B ↔ C",
	),
	(
		"J15",
		"fuse_requant / tile_prefetch / 输出量化选择",
		"requant.value/multiplier/shift/result",
		"32 / 31 / 6 / 8",
		"同一算术模块类型的多处实例；无clk，不可虚构ready/valid",
		"B/C ↔ C",
	),
	(
		"J16",
		"conv_core.result→bias/激活/量化",
		"det_accelerator内部obuf→DMA",
		"INT32→INT8；O=1024×32",
		"O为内部数组；对齐四字节写，尾部单字节选通",
		"C ↔ B",
	),
	(
		"J17",
		"固件det_conv / det_pool",
		"卷积CSR / 池化CSR",
		"32位MMIO，描述符地址32",
		"fence保证顺序；轮询完成并检查错误；不把START接受当DONE",
		"D ↔ A/B/C",
	),
]
SOFTWARE = [
	(
		"模型导出",
		"D",
		"cfg/weights/图片 → model.mem",
		"NHWC INT8、OHWI INT8、每通道5×INT32量化参数",
		"export_model.py → firmware/main.c",
		"相同RTL执行v3/v4；BN折叠、哈希与量化信息固定",
	),
	(
		"计算图",
		"D",
		"图头/操作表 → 解释器",
		"图头16×32位=64B；操作记录24×32位=96B",
		"0x01008000；type1卷积、2池化、3拼接、4切片、5上采样",
		"模式2保留CPU卷积/池化；其他模式用硬件支持路径",
	),
	(
		"卷积描述符",
		"B/D",
		"主描述符与融合子描述符",
		"32×32位=128B；融合16×32位=64B",
		"spec/registers.json → gen_spec.py → C/SV常量",
		"范围/重叠/保留位检查；FLAGS.bit1仍保留，双slot自动启用",
	),
	(
		"固件与启动",
		"D/A",
		"start.S/link.ld/C → firmware.bin",
		"RV32IM，程序窗口64KiB；二进制不是model.mem",
		"build_firmware.sh → picorv32",
		"栈/BSS/入口正确；当前固件和RTL指纹与测试构建匹配",
	),
	(
		"池化驱动",
		"D/C/A",
		"H/W/C/stride、src/dst → det_pool",
		"2×2、stride1/2；4×INT8或尾字节",
		"POOL_BASE=0x10000200，独立DMA",
		"100随机+5非法；真实CPU打包/尾部/B0回退；边界-127",
	),
	(
		"CPU复制/转换",
		"D",
		"INT8源 → 切片/上采样/拼接",
		"对齐32位访问；其他地址与尾部按字节处理",
		"converted_copy与memcpy语义不同",
		"恒等转换-128→-127；普通memcpy保留-128；全INT8域小图对拍",
	),
	(
		"算子独立参考",
		"D交付，B/C复核",
		"张量/参数 → INT64 NumPy期望值",
		"不采用RTL调度代码作为参考",
		"reference.py、gen_vectors.py、gen_stress.py",
		"151有效+7非法；6压力；0/3/15等待；预取中复位；每写字节范围检查",
	),
	(
		"系统验证",
		"A主责，D交叉",
		"model.mem+firmware.bin → 全层结果",
		"CPU FNV哈希 + 测试平台逐字节比较",
		"tb/soc.cpp、checks.txt、check_boxes.py",
		"两个模型M/F各测子图与整网；CPU解码/NMS与NumPy匹配",
	),
	(
		"数值单测",
		"C主责转换器、D主责池化",
		"转换器/池化随机刺激 → 结果",
		"2048转换样本、100池化、5非法配置",
		"tb/converter.cpp、tb/pool.cpp",
		"舍入、饱和、-128、反压、复位、边界与非法范围",
	),
	(
		"性能/精度",
		"D主责，A复核",
		"ROI日志/评价清单 → 报告",
		"周期/实际总线字节；100 train校准、500 val评价",
		"summarize.py、compare_performance.py、evaluate.py",
		"主机AP不冒充500图RTL；周期比不是板上FPS；M/F单独报告",
	),
]
WEEKS = [
	(
		"W1",
		"搭建CPU/总线仿真与计数环境，梳理时钟/复位",
		"核对描述符、双源ORDER、容量和接口表",
		"手算MAC/定点/池化边界，建立参考样例",
		"固定模型、权重、输入和量化；跑通导出",
		"共同冻结CSR/描述符、方向/位宽与黄金结果",
	),
	(
		"W2",
		"复验仲裁锁定与随机等待、建立构建脚本",
		"复现普通卷积前台装载/分块/P保存恢复",
		"复现conv_core/requant，完成数值单测",
		"固件启动/驱动、NumPy INT64独立参考",
		"普通卷积逐元素一致；CPU真正执行机器码",
	),
	(
		"W3",
		"接通融合路径与系统内存模型，审查范围校验",
		"实现源映射、通道边界与2×散写",
		"输入转换器弹性握手/复位/背压验证",
		"M/F计算图、CPU物化与解码/NMS",
		"同一融合子图M/F逐字节一致",
	),
	(
		"W4",
		"指令缓存、冲突替换与程序区写失效",
		"四路bank与行旋转、容量回退、DMA打包",
		"与B联调连续step/末次排空，审查补零跳过",
		"生成短行/stride2/尾通道压力用例",
		"bank容量/单端口证据、缓存单测、MAC计数通过",
	),
	(
		"W5",
		"前后台/三级主设备总线联调与ROI准确性",
		"双slot下一Cin块预取，锁定/交换/复位",
		"融合后台定点算术与部分和跨块复核",
		"建立性能基线与关闭并行取数/预取消融",
		"0/3/15等待、预取中复位、无越界与无重复写回",
	),
	(
		"W6",
		"接通池化独立CSR/DMA和系统冒烟",
		"审查预取/池化与主存竞争及尾部选通",
		"协审池化比较/边界，维护MAC与定点验证",
		"池化硬件及驱动，100随机+5非法，B0回退与字级转换",
		"池化/转换/复制边界对拍；scratch保持40KiB",
	),
	(
		"W7",
		"跑两模型完整系统仿真、结构综合与指纹核查",
		"统计阶段/冲突/预取等待，分析实际瓶颈",
		"复查所有数值和资源声明，定位异常层",
		"M/F与历史性能表，独立COCO精度评价",
		"v3/v4全层及检测框一致；精度/周期/流量口径清楚",
	),
	(
		"W8",
		"完成系统复验、交付构建/环境说明",
		"完成接口/状态机/存储布局文档与框图",
		"完成算术/池化模块说明及答辩实验",
		"完成报告、学习指南、数据来源与演示",
		"四人交叉验收、可复现归档；不虚报FPGA频率/功耗",
	),
]


def diagrams():
	from team_schematic import render_diagrams

	render_diagrams(DOC)


def col_name(n):
	text = ""
	while n:
		n, v = divmod(n - 1, 26)
		text = chr(65 + v) + text
	return text


def attr(text):
	return escape(str(text), {'"': "&quot;"})


class Sheet:
	def __init__(self, name, widths, freeze="A3"):
		self.name, self.widths, self.freeze = name, widths, freeze
		self.cells, self.heights, self.merges, self.images = {}, {}, [], []
		self.filter = None
		self.print_area = None
		self.one_page = False

	def put(self, row, col, value, style=3):
		self.cells[(row, col)] = (value, style)

	def merge(self, start, end, value, style):
		self.merges.append(f"{start}:{end}")
		m = re.fullmatch(r"([A-Z]+)(\d+)", start)
		column = 0
		for ch in m[1]:
			column = column * 26 + ord(ch) - 64
		self.put(int(m[2]), column, value, style)

	def heading(self, title, headers):
		self.merge("A1", f"{col_name(len(headers))}1", title, 1)
		self.heights[1] = 34
		self.heights[2] = 30
		for c, header in enumerate(headers, 1):
			self.put(2, c, header, 2)

	def xml(self, drawing=False):
		rows = {}
		for (r, c), (value, style) in sorted(self.cells.items()):
			if isinstance(value, (int, float)):
				cell = f'<c r="{col_name(c)}{r}" s="{style}"><v>{value}</v></c>'
			else:
				cell = f'<c r="{col_name(c)}{r}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'
			rows.setdefault(r, []).append(cell)
		for r in self.heights:
			rows.setdefault(r, [])
		body = "".join(
			f'<row r="{r}" ht="{self.heights.get(r, 30)}" customHeight="1">{"".join(cells)}</row>'
			for r, cells in sorted(rows.items())
		)
		columns = "".join(
			f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
			for i, w in enumerate(self.widths, 1)
		)
		freeze = ""
		if self.freeze:
			m = re.fullmatch(r"([A-Z]+)(\d+)", self.freeze)
			x = 0
			for ch in m[1]:
				x = x * 26 + ord(ch) - 64
			x -= 1
			y = int(m[2]) - 1
			freeze = f'<pane xSplit="{x}" ySplit="{y}" topLeftCell="{self.freeze}" activePane="{"bottomRight" if x and y else ("topRight" if x else "bottomLeft")}" state="frozen"/>'
		merges = (
			f'<mergeCells count="{len(self.merges)}">'
			+ "".join(f'<mergeCell ref="{m}"/>' for m in self.merges)
			+ "</mergeCells>"
			if self.merges
			else ""
		)
		filter_tag = f'<autoFilter ref="{self.filter}"/>' if self.filter else ""
		return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{NS}" xmlns:r="{REL}"><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr><sheetViews><sheetView showGridLines="0" zoomScale="85" workbookViewId="0">{freeze}</sheetView></sheetViews><sheetFormatPr defaultRowHeight="30"/><cols>{columns}</cols><sheetData>{body}</sheetData>{filter_tag}{merges}<pageMargins left="0.25" right="0.25" top="0.35" bottom="0.35" header="0.15" footer="0.15"/><pageSetup paperSize="8" orientation="landscape" fitToWidth="1" fitToHeight="{1 if self.one_page else 0}"/>{'<drawing r:id="rIdDrawing"/>' if drawing else ""}</worksheet>'''


def styles():
	fonts = '<font><sz val="11"/><name val="Microsoft YaHei"/></font><font><b/><sz val="18"/><color rgb="FFFFFFFF"/><name val="Microsoft YaHei"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Microsoft YaHei"/></font><font><b/><sz val="11"/><name val="Microsoft YaHei"/></font><font><sz val="10"/><color rgb="FF475569"/><name val="Microsoft YaHei"/></font><font><sz val="10"/><name val="Consolas"/></font>'
	fills = '<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
	for color in ["1E3A5F", "315C85", *COLORS.values(), "F1F5F9"]:
		fills += f'<fill><patternFill patternType="solid"><fgColor rgb="FF{color}"/><bgColor indexed="64"/></patternFill></fill>'
	defs = [
		(0, 0, 0, "left"),
		(1, 2, 0, "center"),
		(2, 3, 1, "center"),
		(0, 0, 1, "left"),
		(3, 4, 1, "center"),
		(3, 5, 1, "center"),
		(3, 6, 1, "center"),
		(3, 7, 1, "center"),
		(4, 8, 1, "left"),
		(0, 0, 1, "center"),
		(3, 8, 1, "left"),
		(5, 0, 1, "left"),
	]
	xfs = "".join(
		f'<xf numFmtId="0" fontId="{f}" fillId="{fill}" borderId="{border}" xfId="0" applyAlignment="1" applyFill="1" applyFont="1" applyBorder="1"><alignment horizontal="{align}" vertical="center" wrapText="1"/></xf>'
		for f, fill, border, align in defs
	)
	border = '<border><left style="thin"><color rgb="FFCBD5E1"/></left><right style="thin"><color rgb="FFCBD5E1"/></right><top style="thin"><color rgb="FFCBD5E1"/></top><bottom style="thin"><color rgb="FFCBD5E1"/></bottom><diagonal/></border>'
	return f'<styleSheet xmlns="{NS}"><fonts count="6">{fonts}</fonts><fills count="9">{fills}</fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>{border}</borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="12">{xfs}</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'


def image_drawing(path, col, row, width):
	data = path.read_bytes()
	assert data[:8] == b"\x89PNG\r\n\x1a\n"
	w, h = struct.unpack(">II", data[16:24])
	height = round(h * width / w)
	cx, cy = width * 9525, height * 9525
	return (
		f'''<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="{REL}"><xdr:oneCellAnchor><xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:ext cx="{cx}" cy="{cy}"/><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="1" name="{attr(path.stem)}"/><xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill><xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor></xdr:wsDr>''',
		height,
	)


def workbook(sheets):
	rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
	overrides = [
		'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
		'<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
	]
	with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as z:
		z.writestr(
			"_rels/.rels",
			f'<Relationships xmlns="{rel_ns}"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
		)
		z.writestr("xl/styles.xml", styles())
		sheet_refs, relationships, names = [], [], []
		for i, sheet in enumerate(sheets, 1):
			sheet_refs.append(f'<sheet name="{attr(sheet.name)}" sheetId="{i}" r:id="rId{i}"/>')
			relationships.append(
				f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
			)
			overrides.append(
				f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
			)
			z.writestr(f"xl/worksheets/sheet{i}.xml", sheet.xml(bool(sheet.images)))
			if sheet.images:
				assert len(sheet.images) == 1
				path, col, row, width = sheet.images[0]
				drawing, _ = image_drawing(path, col, row, width)
				z.writestr(f"xl/drawings/drawing{i}.xml", drawing)
				z.writestr(f"xl/media/image{i}.png", path.read_bytes())
				z.writestr(
					f"xl/worksheets/_rels/sheet{i}.xml.rels",
					f'<Relationships xmlns="{rel_ns}"><Relationship Id="rIdDrawing" Type="{REL}/drawing" Target="../drawings/drawing{i}.xml"/></Relationships>',
				)
				z.writestr(
					f"xl/drawings/_rels/drawing{i}.xml.rels",
					f'<Relationships xmlns="{rel_ns}"><Relationship Id="rIdImage" Type="{REL}/image" Target="../media/image{i}.png"/></Relationships>',
				)
				overrides.append(
					f'<Override PartName="/xl/drawings/drawing{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
				)
			if sheet.print_area:
				names.append(
					f'<definedName name="_xlnm.Print_Area" localSheetId="{i - 1}">\'{escape(sheet.name)}\'!{sheet.print_area}</definedName>'
				)
			names.append(
				f'<definedName name="_xlnm.Print_Titles" localSheetId="{i - 1}">\'{escape(sheet.name)}\'!$1:$2</definedName>'
			)
		z.writestr(
			"xl/workbook.xml",
			f'<workbook xmlns="{NS}" xmlns:r="{REL}"><bookViews><workbookView/></bookViews><sheets>{"".join(sheet_refs)}</sheets><definedNames>{"".join(names)}</definedNames><calcPr calcId="191029"/></workbook>',
		)
		relationships.append(
			f'<Relationship Id="rIdStyles" Type="{REL}/styles" Target="styles.xml"/>'
		)
		z.writestr(
			"xl/_rels/workbook.xml.rels",
			f'<Relationships xmlns="{rel_ns}">{"".join(relationships)}</Relationships>',
		)
		z.writestr(
			"[Content_Types].xml",
			'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
			+ "".join(overrides)
			+ "</Types>",
		)


def build():
	digest = hashlib.sha256(TEMPLATE.read_bytes()).hexdigest()
	with zipfile.ZipFile(TEMPLATE) as z:
		shared = ET.fromstring(z.read("xl/sharedStrings.xml"))
		strings = ["".join(n.itertext()) for n in shared]
		template = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
		headers = []
		for c in template.findall(f"{{{NS}}}sheetData/{{{NS}}}row[@r='2']/{{{NS}}}c"):
			headers.append(strings[int(c.find(f"{{{NS}}}v").text)])
	assert headers[:6] == ["模块名", "负责人", "端口", "端口方向", "端口宽度(bit)", "端口功能"]
	diagrams()
	main = Sheet("分模块施工图", [32, 20, 32, 12, 18, 69, 3] + [12] * 16, "C3")
	main.heading("多尺度特征融合与卷积协同加速SoC｜分模块施工图", headers[:6])
	row, count = 3, 0
	for module, owner, summary in MODULES:
		start = row
		for name, direction, width, signed in ports(module):
			main.put(row, 3, name, 11)
			main.put(row, 4, direction, 9)
			main.put(row, 5, width, 9)
			main.put(row, 6, describe(module, name, signed) + ("（signed）" if signed else ""))
			main.heights[row] = 32
			row += 1
			count += 1
		main.merge(
			f"A{start}",
			f"A{row - 1}",
			f"{module}\nrtl/{module}.sv\n{summary}",
			4 + "ABCD".index(owner),
		)
		main.merge(f"B{start}", f"B{row - 1}", OWNERS[owner], 4 + "ABCD".index(owner))
	main.merge(
		f"A{row}",
		f"F{row + 1}",
		"说明：本表完整列出10个自研RTL模块的真实端口；重复实例只列一次并标明实例数。P/O为控制器内部数组，不虚构独立模块端口。第三方PicoRV32接入口见J01。A/B/C/D为待填姓名的计划负责人。",
		8,
	)
	main.heights[row] = 34
	main.merge("H1", "V1", "模块接口框图｜框边标端口名、方向与位宽", 1)
	main.merge("H2", "V2", "A 系统/缓存/总线｜B 控制/存储/预取｜C MAC/定点｜D 池化硬件/固件联调", 8)
	main.images.append((DOC / "team-datapath.png", 7, 2, 1500))
	_, image_height = image_drawing(DOC / "team-datapath.png", 7, 2, 1500)
	right_row = math.ceil(image_height / 42) + 5
	main.merge(
		f"H{right_row}",
		f"V{right_row + 1}",
		"A 系统/缓存/仲裁｜B 融合/存储/预取｜C MAC/定点｜D 池化/固件/模型联调；四人八周共32人周。详见后续工作表。",
		8,
	)
	main.print_area = f"$A$1:$F${row + 1}"
	roles = Sheet("四人八周分工", [12, 47, 57, 57, 57, 55])
	roles.heading(
		"四人八周分工｜接手、重建与交叉复验计划（非既有贡献声明）",
		["角色", "方向", "负责文件", "主要工作", "交付/验收", "计划投入"],
	)
	for i, (owner, title, files, tasks, acceptance) in enumerate(ROLES, 3):
		for c, v in enumerate(
			[OWNERS[owner], title, files, tasks, acceptance, "8人周；负责人姓名待填"], 1
		):
			roles.put(i, c, v, 4 + "ABCD".index(owner) if c == 1 else 3)
		roles.heights[i] = 115
	roles.merge(
		"A8",
		"F8",
		"每周并行四个人，每格约一人周；以下共8周×4人=32人周。所有成员须理解本人接口，并交叉审核相邻模块。",
		8,
	)
	for c, v in enumerate(
		["周次", "A：系统/验证", "B：调度/搬运", "C：计算/数值", "D：模型/软件", "共同验收门槛"], 1
	):
		roles.put(9, c, v, 2)
	for i, values in enumerate(WEEKS, 10):
		for c, v in enumerate(values, 1):
			roles.put(i, c, v)
		roles.heights[i] = 100
	roles.print_area = "$A$1:$F$17"
	connections = Sheet("接口连接表", [12, 46, 49, 44, 81, 18])
	connections.heading(
		"模块连接与联调责任｜信号方向从源模块看；返回通道反向",
		["接口编号", "源模块/端口", "目标模块/端口", "端口宽度(bit)", "协议/功能", "双方负责人"],
	)
	for i, values in enumerate(INTERFACES, 3):
		for c, v in enumerate(values, 1):
			connections.put(i, c, v)
		connections.heights[i] = 72
	connections.filter = f"A2:F{2 + len(INTERFACES)}"
	connections.print_area = f"$A$1:$F${2 + len(INTERFACES)}"
	soft = Sheet("软件与验证接口", [27, 24, 57, 64, 64, 80])
	soft.heading(
		"D的软件交付与软硬件契约｜软件项不虚构RTL端口，用文件/格式/调用关系描述",
		["交付项", "负责人", "输入/输出", "数据格式或规模", "调用/连接对象", "验收依据"],
	)
	for i, values in enumerate(SOFTWARE, 3):
		for c, v in enumerate(values, 1):
			soft.put(i, c, v)
		soft.heights[i] = 90
	soft.print_area = f"$A$1:$F${2 + len(SOFTWARE)}"
	images = []
	for title, stem in [("系统框图", "team-system"), ("模块接口框图", "team-datapath")]:
		sheet = Sheet(title, [15] * 20, None)
		sheet.merge("A1", "T1", title + "｜框边端口名、方向与位宽；A/B/C/D为负责人", 1)
		sheet.heights[1] = 40
		sheet.images.append((DOC / f"{stem}.png", 0, 2, 2000))
		_, height = image_drawing(DOC / f"{stem}.png", 0, 2, 2000)
		last = math.ceil(height / 40) + 5
		for i in range(3, last + 1):
			sheet.heights[i] = 30
		sheet.merge(
			f"A{last}",
			f"T{last}",
			f"可缩放矢量图：docs/{stem}.svg；同版可编辑源：docs/team-interfaces.drawio；DOT另提供接口拓扑。完整端口见主表。",
			8,
		)
		sheet.print_area = f"$A$1:$T${last}"
		sheet.one_page = True
		images.append(sheet)
	notes = Sheet("填写说明", [30, 115, 28, 28, 28, 28])
	notes.heading("填写与版本说明", ["项目", "说明", "", "", "", ""])
	values = [
		(
			"使用方式",
			"主表沿用示例六列：模块名/负责人/端口/方向/位宽/功能；A/B/C/D都有实际RTL模块，其中D负责池化及软硬件联调。右侧是黑白接口框图，框内仅模块名/负责人，框边列端口与位宽；另外两张框图表可单独A3横向打印，主表打印只含A:F，避免框图把端口表压得过小。",
		),
		(
			"负责人",
			"将A/B/C/D替换成真实姓名；角色与颜色在所有工作表和框图中一致。示例中的赵甲/钱乙/孙丙/李丁不是本项目已确认成员，不沿用为真实姓名。",
		),
		(
			"方向和位宽",
			f"从各RTL模块本身观察in/out。脚本解析当前10个自研模块，共{count}个命名端口，位宽来自声明；signed在功能栏标出。",
		),
		(
			"时钟/复位",
			"自研时序模块clk上升沿、rst高有效同步；PicoRV32 resetn=!rst。requant为纯组合，无时钟或握手端口。",
		),
		(
			"实例与内部数组",
			"banked_scratch实例4处（X/W各两slot），每实例内部4个物理bank；native_arbiter两处。P/O是det_accelerator内部数组，不能照搬示例中的独立psum_ram/pooling_ram端口。",
		),
		(
			"资源口径",
			"卷积scratch 40KiB；指令缓存1248B、后台读缓存16B数据+116bit标签/有效位，以及CSR/描述符/累加器等另外统计。池化无额外scratch RAM。",
		),
		(
			"验证范围",
			"仿真主存64KiB程序+64MiB数据；结构综合未包含FPGA布局布线或真实DDR。主机500图精度评价不能写成500图RTL验证，周期比不是板上FPS。",
		),
		("参考示例", TEMPLATE.name + "；保留原文件，不覆盖。模板SHA256：" + digest),
		(
			"重新导出",
			"python3 scripts/export_team_workbook.py；调用scripts/team_schematic.py。无需额外Excel Python库；生成PNG需Pillow与中文字体（微软雅黑或Noto CJK）。Excel已嵌入PNG，直接打开即可。表中真实端口从RTL自动读取，负责人和功能说明在导出脚本中维护。",
		),
		(
			"后续扩展",
			"更大阵列、真实AXI/DDR与物理时序需要单独设计验证，不在当前框图中画成已完成模块。",
		),
	]
	for i, (key, value) in enumerate(values, 3):
		notes.put(i, 1, key, 10)
		notes.merge(f"B{i}", f"F{i}", value, 3)
		notes.heights[i] = 66
	notes.print_area = f"$A$1:$F${2 + len(values)}"
	workbook([main, roles, connections, soft, *images, notes])
	assert hashlib.sha256(TEMPLATE.read_bytes()).hexdigest() == digest
	with zipfile.ZipFile(OUTPUT) as z:
		assert z.testzip() is None
		for name in z.namelist():
			if name.endswith((".xml", ".rels")):
				ET.fromstring(z.read(name))
	print(
		f"Exported {OUTPUT.name}: {count} real RTL ports, {len(INTERFACES)} interfaces, 7 worksheets"
	)


if __name__ == "__main__":
	build()
