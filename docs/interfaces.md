# 已实现融合检测接口 v2.1

本文件描述实际RTL，取代原v0.2草案的内部端口设想。所有地址/字段的唯一机器可读来源是 [registers.json](../spec/registers.json)，由scripts/gen_spec.py生成C/SV常量。实际实现差异和复现边界见 [implementation.md](implementation.md)。

## 分工与接口总表

| 接手角色 | 实际文件/职责 | 接口 |
|---|---|---|
| A 系统 | det_soc_top.sv、native_arbiter.sv、tb/soc.cpp；CPU、地址译码、存储、分类ROI、集成与综合 | I1 CPU，I2译码，I3共享存储 |
| B 调度/融合 | det_accelerator.sv 实例化两引擎；det_conv_scheduler.sv 调度卷积及融合搬运 | I2/I3/I4，I5核心控制，I8主/子描述符，I9请求侧 |
| C 计算/数值 | conv_core.sv、fuse_requant.sv、requant.sv；16MAC、部分和恢复、输入/输出定点转换 | I5/I6，I7量化算术，I9转换侧 |
| D 模型/软件 | scripts/及firmware/；图、量化、内存、软件算子、解码/NMS、独立参考 | I8描述符/图格式，逐层/精度数据 |

A/B/C/D为未来成员分工，真实贡献应另外登记。B负责P RAM控制，C负责core累加器恢复；相对草案的所有权调整反映真实模块边界。

## 1. 全局与I1/I2/I3

clk单时钟，rst同步高有效。valid发送方不等ready才发，背压时所有载荷稳定。原生总线在valid&&ready上升沿完成，读数据同拍有效；最多一个在途；选定主设备锁定到完成，双主竞争轮询。复位清控制/转换有效，取消任务，不清RAM；已有部分输出保留，任务必须重跑。CPU在START到完成期间不得改描述符、源、权重或参数，也不得访问输出。

| 信号 | 位宽 | 方向 |
|---|---:|---|
| mem_valid / dma_valid / reg_valid | 1 | 主→从 |
| addr | 32 | 主→从，字节地址，传输字地址对齐 |
| wdata | 32 | 主→从 |
| wstrb | 4 | 主→从，0读，非0按字节写 |
| ready | 1 | 从→主，当前事务完成 |
| rdata | 32 | 从→主，读完成拍有效 |

I1是CPU→仲裁器，另有mem_instr；I2译码到0x10000100；I3为DMA→仲裁器→内存。det_soc_top额外输出mem_dma/mem_instr，仅在完成事务采样以识别来源。

| 地址 | 用途 |
|---|---|
| 0x00000000～0x0000ffff | 64KiB代码/只读常量，包括.srodata，固件镜像必须加载 |
| 0x01000000～0x01007fff | 固件全局/候选框工作区 |
| 0x01008000 | 64字节图头 |
| 0x01010000起 | 模型静态分配区，末端必须低于0x04f00000 |
| 0x04f00000～0x04ffffff | 栈保留区，栈顶0x05000000 |
| 0x10000100～0x100001ff | 检测加速器CSR |
| 0x20000000 / 0x20000004 / 0x20000008 | 仿真打印 / 退出码 / ROI标记 |

新DMA只允许0x01000000～0x04ffffff。旧GEMM地址不再映射。输出不得与任何读区重叠；所有长度/区间加法扩位检查。RTL检查数据区范围，固件/栈的细分所有权由静态分配器保证。

## 2. I2：CSR（相对0x10000100）

| 偏移 | 名称 | 语义 |
|---|---|---|
| 0x00 | CTRL | 写1启动，其余写拒绝 |
| 0x04 | STATUS | bit0 BUSY，bit1 DONE、bit2 ERROR、bit3 REJECT为sticky/W1C |
| 0x08 | DESC_ADDR | 空闲可写，16字节对齐 |
| 0x0c | ERROR_CODE | 2配置/容量，3对齐，4范围/输出重叠，5量化/累加溢出，6状态错误 |
| 0x10/14 | JOB_CYCLES_LO/HI | 64位BUSY周期 |
| 0x18/1c | COMPUTE_CYCLES_LO/HI | 64位MAC使能周期 |
| 0x20/24 | READ_WORDS_LO/HI | DMA完成读字数，包含描述符/参数 |
| 0x28/2c | WRITE_BYTES_LO/HI | DMA完成写字节数 |
| 0x30/34 | DMA_WAIT_LO/HI | valid未ready周期 |
| 0x3c | VERSION | 0x00020100（保留原接口；以下计数器为向后兼容扩展） |
| 0x40/44 | LOAD_CYCLES_LO/HI | X清零、源加载/转换/散写、权重加载 |
| 0x48/4c | GATHER_CYCLES_LO/HI | X/W并行取数及最后MAC排空 |
| 0x50/54 | PARTIAL_CYCLES_LO/HI | P读取、恢复、保存 |
| 0x58/5c | PARAM_CYCLES_LO/HI | 参数校验及微块量化参数读取 |
| 0x60/64 | OUTPUT_CYCLES_LO/HI | RESULT及DMA写回 |
| 0x68/6c | CONTROL_CYCLES_LO/HI | 其他控制与描述符阶段 |
| 0x70/74 | FAST_GATHER_LO/HI | 四路并行取数拍数 |
| 0x78/7c | SERIAL_GATHER_LO/HI | bank冲突时逐lane取数拍数 |
| 0x80/84 | PREFETCH_ACTIVE_LO/HI | 后台预取忙周期 |
| 0x88/8c | PREFETCH_MAC_LO/HI | 后台忙与core_step同时发生的周期 |
| 0x90/94 | PREFETCH_WAIT_LO/HI | IC_NEXT等待下一块就绪的周期 |


busy期间写配置/START及时应答、忽略且置REJECT；STATUS清状态仍可用。部分字/非对齐写拒绝；保留读0。空闲START锁存地址、清状态/计数，描述符地址非法不读总线；其他非法配置可能读取描述符/参数，但禁止输入/权重和输出访问。最终输出写完成后才DONE。忙时64位计数可能撕裂，正式读数在完成后进行。驱动有20亿cycle超时，仿真有独立watchdog。

## 3. I8：主描述符与融合子描述符

主描述符128B，32个little-endian uint32，字段顺序与spec.json一致。

| 字偏移 | 字段 | 约束 |
|---|---|---|
| 0..3 | SRC,WEIGHT,DST,QPARAM | 基址4字节对齐，融合时SRC=0 |
| 4..7 | H,W,CIN,COUT | H/W=1..160，通道=1..1024 |
| 8..11 | KH,KW,SH,SW | 方核1/3，等步长1/2，groups1、dilation1 |
| 12..15 | PT,PB,PL,PR | 四边padding各0/1 |
| 16..17 | HOUT,WOUT | floor((输入+两边padding−kernel)/stride)+1，正值且匹配 |
| 18..21 | TH,TW,TIC,TOC | 空间1..16，通道4/8/16，满足8KiB X/W和4KiB P/O容量 |
| 22 | ACT | 0 linear、1 ReLU、2 leaky |
| 23 | FLAGS | bit0复用必须1，bit2融合可选；bit1保持旧保留位语义、置1报错；当前双slot自动启用；其他0 |
| 24 | FUSE_ADDR | 融合时指向16字节对齐64B子描述符，普通模式0 |
| 25..31 | RESERVED | 0 |

激活连续NHWC INT8，权重连续OHWI INT8。参数每输出通道5个字：signed32 bias、m_pos、s_pos、m_neg、s_neg。m≤0x7fffffff，s≤62；linear两组相同，ReLU负乘数0，leaky导出器将斜率包含在负支比例。64位乘移，半值远离零，饱和[-127,127]。输出bias前后都不在每个Cin块重复量化。最后bias加法检查INT32范围。

融合子描述符16字：

| 字偏移 | 字段 | 含义 |
|---|---|---|
| 0..3 | SRC0,H0,W0,C0 | 低分辨率源 |
| 4..7 | SRC1,H1,W1,C1 | 高分辨率源 |
| 8..9 | R0,R1 | 必须2/1 |
| 10..13 | M0,S0,M1,S1 | 两路输入转共同尺度，约束同上 |
| 14 | ORDER | 0低后高，1高后低 |
| 15 | RESERVED | 0 |

要求H0*2=H1=主H、W0*2=W1=主W、C0+C1=主CIN、各源通道>0。padding先判越界返回0；再按ORDER选通道源，低路坐标floor(y/2),floor(x/2)，高路恒等。一次Tic跨源边界时分别填充，共享同一个X bank；低路转换后散写到当前块交集内最多2×2位置。无完整虚拟张量主存地址，源/子描述符区间均受范围和重叠保护。

## 4. I4/I5/I6/I7：实际内部边界

I4在det_accelerator内部：X/W各两组8KiB，每组由四个512×32位bank组成，独立单读/字节选通写口。活动slot供计算，非活动slot由tile_prefetch填充；后台请求与前台读请求共享原生DMA，等待期间锁定请求方。只有下一通道块X/W全部就绪才交换slot。P为1024×INT32，O为1024×32位，合计40KiB。融合首块走源优先散写，后台块走虚拟输入坐标映射与同一定点转换，两者数值一致。

| conv_core端口（I5/I6） | 位宽 | 语义 |
|---|---:|---|
| clear | 1 | 首个Cin块开始微块时清16个累加器 |
| restore,index,restore_data | 1/4/32 | 计算前按index串行恢复，restore时不step |
| step,a_vector,b_vector | 1/32/32 | 每vector4个INT8，广播到4×4；step执行一个K位置 |
| index,result | 4/32 | 按index读出累加器，控制器串行保存P或量化 |

微块含4个空间位置×4个输出通道。P索引为`(m0+r)*TOC+n0+c`，只保存有效位置；后续Cin块先读P再restore，首块clear，最后块加bias并量化到O。输出排空逐字节，wstrb只选目标lane，全部ready后才任务完成。I7是requant模块的value signed32、multiplier31、shift6输入及signed8结果，为组合算术接口，不是草案中的流式输出总线。

## 5. I9：已实现输入转换器

| 端口 | 位宽 | 语义 |
|---|---:|---|
| cfg_valid/ready,m0,m1,s0,s1 | 1/1/31/31/6/6 | 输出为空时配置两支参数 |
| in_valid/ready,src_id,in_data,in_token | 1/1/1/8/16 | 输入样本；signed8，tag透明传递 |
| out_valid/ready,out_data,out_token | 1/1/8/16 | 转换结果，阻塞时保持 |

一项弹性输出寄存器，复位丢弃在途输出并使配置无效。控制器一次仅发一个样本，token固定0；收到转换结果并完成全部散写后才推进源坐标。输入/输出转换是独立物理模块，无共享乘法器仲裁假设。单位测试覆盖2048个极值/移位/负值样本和随机背压、复位。

## 6. 固件图与系统ROI

图头 16 字位于 0x01008000，依次包含 magic=0x44455431、nops、ops_addr、mode（2 为纯 CPU 卷积）、nheads、heads_addr、boxes_addr、profile，其余为 0。24 字操作记录包含来源/目标、形状、参数、描述符、预期哈希/字节数、层号和 ROI 边界。type1 是卷积，2 是池化，3 是转换拼接，4 是通道切片，5 是上采样，6 是按分支复用池化引擎的融合拼接池化。

type6 通过 src0/src1 指向两路已有张量，用 H/W/C0/C1 描述它们的共同空间形状与各自通道数，用 M0/S0、M1/S1 将两路转换到共同输出尺度。固件提交两次池化，使用相同 stride 和目标像素步幅 C0+C1，写入基址分别为 DST 和 DST+C0。完成两个任务后，下游读取完整的 NHWC 池化输出。

16字检测头记录布局见export_model.py；输出为count uint32后接最多100个24字节Box（5个float32坐标/score，uint32类别）。CPU解码与NumPy按3e-4容差比较，NaN不接受。

ROI 写 0x20000008，bit31 表示开始或结束，低 16 位是 ID，ROI 之间不嵌套。标记事务从计数中排除。交易按 CPU_DATA、CPU_IFETCH 和 DMA 分类，完成读计 4 字节，写计 popcount(wstrb)。profile=0 使用图中的融合卷积子图标记，profile=1 用 65534 测量整网，profile=2 用 4096 加操作索引逐算子测量。解码和 NMS 单独用 65533，哈希检查与打印在 ROI 外。

阶段计数器在START/复位清零，BUSY时每拍恰好增加一组，完成后六组之和等于JOB_CYCLES。READ_DISPATCH/READ_BUS归入read_return对应的阶段，包含总线等待。COMPUTE_CYCLES单独统计实际core_step；因MAC与GATHER重叠，不能再与六组相加。WRITE_BYTES仍统计有效字节数，整字写一次增加4。

后台预取与前台阶段重叠，因此六组阶段计数仍按前台状态互斥归类，后台剩余时间在IC_NEXT记CONTROL；不能把PREFETCH_ACTIVE再与六组相加。READ_WORDS/DMA_WAIT计入前台与后台实际总线活动。FAST+SERIAL+排空拍数等于GATHER_CYCLES。

指令缓存只覆盖地址0x00000000～0x0000ffff中的取指读取，256个32位数据字、6位标签、有效位；普通数据读取与MMIO始终旁路。CPU对程序区的完成写入会失效对应行，复位清有效位。加速器DMA已被范围校验限制在数据区。

## 2×2池化引擎

基址0x10000200，由spec/registers.json生成POOL_BASE和POOL_REG_*；与卷积CSR窗口独立。两引擎同属 `det_accelerator`。池化原生DMA作为第三个主设备接入外层仲裁，等待期间锁定请求。ROI将卷积与池化完成事务一起记为DMA。

| 偏移 | 名称 | 含义 |
|---|---|---|
| 0x00 / 0x04 | SRC / DST | 对齐的NHWC INT8输入/输出地址 |
| 0x08 / 0x0c / 0x10 | H / W / C | 1..160、1..160、1..1024 |
| 0x14 | STRIDE | 1或2；kernel固定2×2 |
| 0x18 | START | 写 1 启动连续 NHWC 池化，写 2 启动跨步幅写回与重定标，校验失败不发 DMA |
| 0x1c | STATUS | bit0忙、bit1完成、bit2错误；下次START清状态 |
| 0x20 / 0x24 | CYCLES_LO/HI | 完成后读取64位忙周期 |
| 0x28 | DST_PITCH | START=2 的目标像素步幅，单位字节，C..1024 |
| 0x2c / 0x30 | Q_MULT / Q_SHIFT | START=2 的非负 31 位乘数与 0..62 右移位数 |
| 0x34 | CAPABILITIES | 只读，bit0 表示支持 START=2 |

源和目标基址须字对齐，位于数据区且区间互不重叠。START=2 校验的输出区间包含跨步幅空隙，跨度为 `(Hout×Wout−1)×DST_PITCH+C`。输出写只选本分支的 C 个字节。C 和输出步幅均为 4 的倍数时使用四通道打包，否则逐字节访问。输出高宽为 floor((H−1)/stride)+1 和 floor((W−1)/stride)+1。

普通任务以 −127 为比较初值。带非恒等重定标的任务以 −128 为初值，仅对有效样本取最大值，再用与卷积一致的舍入和饱和规则重定标。每个输出窗口至少有一个有效样本，重定标结果不低于 −127，等价于先重定标有效输入再做 −127 填充池化。START=1 忽略扩展配置。

firmware的type2操作在mode!=2、kernel=2时调用det_pool；mode=2或其他kernel保留CPU实现，因此B0仍是CPU卷积/池化基线。未将池化与卷积融合为同一个流式流水。
