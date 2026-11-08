# 当前实现与复现

初次学习请先读[从零学习指南](learning-guide.md)，再用本文核对实际模块与边界。

当前主线是实际可运行的目标检测 SoC，不再只是设计提案。硬件不识别模型名称；同一份 RTL 接受普通卷积或双源融合描述符。旧GEMM/MNIST和设计过程归档已删除，当前文档只描述检测实现。

## 1. 实际模块

| 文件 | 已实现职责 |
|---|---|
| rtl/det_soc_top.sv | 真实PicoRV32、双主仲裁、检测MMIO、主设备身份/取指标志输出 |
| rtl/det_accelerator.sv | 描述符校验、分块、双源坐标映射、低路2×散写、单项读缓存、X/W/P/O存储、DMA、输出字节选通、性能计数 |
| rtl/fuse_requant.sv | I9独立弹性输入转换器，背压稳定、两分支参数、半值远离零舍入与饱和 |
| rtl/banked_scratch.sv | 四个独立2KiB bank，单读/字节使能写端口 |
| rtl/tile_prefetch.sv | 后台X/W通道块预取，融合虚拟源与整数转换 |
| rtl/pool_accelerator.sv | 2×2 NHWC四通道最大池化、边界/尾部保护、独立DMA |
| rtl/instruction_cache.sv | 1KiB直接映射指令缓存、冲突替换、CPU写失效 |
| rtl/conv_core.sv | 16个INT8乘法器的4×4输出驻留广播MAC阵列，串行恢复/导出INT32部分和 |
| rtl/requant.sv | 64位乘移与明确舍入/饱和，输入和输出转换复用此算术定义 |
| firmware/ | 裸机驱动、图解释器、CPU物化/池化/切片、CPU卷积基线、解码与class-aware NMS |
| scripts/model.py | 两种Darknet tiny配置/权重导入、BN折叠、浮点参考、letterbox和可视化 |
| scripts/reference.py | 独立NumPy INT64卷积和定点参考，不使用RTL分块循环 |
| scripts/export_model.py | 量化、融合识别、两种内存执行图、描述符、逐层参考与哈希 |
| tb/ | C++原生总线BFM、真实CPU系统内存、随机等待、分类ROI计数、全层逐字节比较 |

表中路径均相对项目根目录。A/B/C/D是接手职责，不表示已经有四名成员完成贡献。

## 2. 相对设计方案的具体实现选择

- 计算核心采用4×4广播MAC，每步计算一个K位置；不是旧GEMM核心的10拍错拍流水。四路分bank在无冲突时每拍形成完整向量，同时计算上一组，每个微块K循环仅K+1拍；容量限制下的紧凑布局若冲突则回退4拍取数，不将理论峰值当整网吞吐。
- 实际X/W各两组8KiB、P/O各4KiB，共40KiB。每组X/W分为四个2KiB bank，每个bank一个读口和一个字节选通写口。双缓冲自动启用，旧FLAGS.bit1仍保留并拒绝。
- 第一通道块由前台装载器填充；计算当前块时后台预取下一通道块的X/W（包含融合输入转换）。仅在预取完成后交换slot。输出排空仍独立执行；跨空间/输出通道块仍可能重读。
- 部分和RAM和微块状态由det_accelerator统一管理，conv_core只暴露clear/restore/step/index/result。没有额外套用尚未实现的I5流式微命令端口。
- 每组输出通道缓存4通道×5字量化参数（80B寄存器），跨空间微块复用，输入转换一个样本在途，token固定0；不分配64B FIFO，该数是原设计的上限。
- X/W/O改为32位打包存储，容量不变。普通输入和权重在主存/片上同时对齐且有效通道足够时整字装载，否则按字节处理；融合转换继续逐项散写。X清零每拍一个字。输出在源/目标均对齐且至少剩4通道时整字写回，否则按byte lane写入；每次完成后才推进，尾字节不破坏邻居。
- graph解释器使用主机导出的静态拓扑和地址，不是通用ONNX运行时。YOLOv4-tiny骨干内部route/concat保留CPU执行，只融合两模型检测颈部的上采样/拼接/卷积路径。

公开CSR和描述符见 interfaces.md；框图表示当前四路分bank、双slot预取和CPU指令缓存实现。

## 3. 模型、结果和测量边界

模型固定为仓库保存的cfg及公开预训练weights，其SHA256和来源由data/sources.json记录；不以网络上的master变化替换当前配置。输入160×160、batch1、INT8零点0、按输出通道权重量化；BN在导出时折叠。

默认run_model使用dog.jpg生成演示量化参数，manifest明确标记calibration_demo_only=true，不能将该演示称为独立精度实验。正式精度实验由evaluate.py使用不重叠的100张COCO train2017校准和500张val2017评价，用官方COCOeval，另存calibration.json与metrics.json。主机500张评价不等于500张RTL仿真。

CPU图内验证使用每层FNV哈希，系统测试平台另逐字节比较全部卷积输出与NumPy二进制参考。检查与打印在测量区外。CPU的浮点解码通过软件浮点库执行，exp使用范围约简与8阶展开；与独立NumPy解码框逐项比较，容差3e-4。候选框最大512、输出最多100，最高类别选择、按类别贪心NMS、稳定同分顺序。演示阈值0.25，正式AP评估阈值0.001，二者分别记录。

ROI按CPU_DATA、CPU_IFETCH、DMA分别记录读写事务与实际总线字节。模式0测融合子图，模式1测整网；因ROI不允许嵌套，两种测量需分别运行。解码/NMS使用独立ROI=65533。预处理在主机进行，不包含在CPU周期中；没有摄像头或实际FPS/功耗证据。

COCOeval和图片resize均属于独立参考实现；尚未声称与原Darknet resize位级相同，因此浮点/INT8比较使用项目内同样的前处理，不引用原论文416输入准确率。

## 4. 综合边界

scripts/synth.sh通过Yosys层次检查、进程转换、存储端口与结构检查，保留memory cell，输出results/synthesis.json。统计处于RTL级，不是完成门级映射的面积；动态地址/整数除法和64位缩放的代价需要后续工艺映射测量。没有时序收敛，不将仿真10ns时钟当作100MHz能力。

## 性能优化与复现

16个MAC通过四路分bank与行旋转实现常见卷积每拍step，后台tile_prefetch利用第二组X/W重叠取数/计算。instruction_cache缓存64KiB程序区中的热点指令；CPU写程序区时失效对应行。2×2池化由独立硬件执行，CPU基线及其他kernel保留地址优化的软件实现，上采样/拼接通过精确INT8转换表避免逐字节64位乘移。阶段、bank供数与预取计数见[接口](interfaces.md)，测试和边界见[性能记录](performance.md)。

末尾Cin块会跳过TIC中的补零归约项，输出通道微块也只遍历有效co_count；K+1中的K应使用该块实际有效通道数乘kernel面积，不能把旧版COMPUTE_CYCLES不变当作当前验收条件。数值对拍与实际MAC计数分别验证。

CPU切片和尺度转换复制已按32位打包；恒等转换仍对-128饱和到-127，普通memcpy则保持全部字节不变。新增真实CPU小图独立验证这两种语义及对齐/尾部。
