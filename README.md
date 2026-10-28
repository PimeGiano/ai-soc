# 多尺度特征融合与卷积协同加速 SoC

真实PicoRV32运行裸机C，通过可配置INT8卷积加速器执行YOLOv3-tiny / YOLOv4-tiny。核心设计将“2×最近邻上采样 → 通道拼接 → 卷积”改成双源取数、输入尺度转换与片上散写，省去完整上采样和拼接张量的主存物化。硬件按描述符运行，同一RTL用于两个模型。

## 运行

```bash
git clone https://github.com/PimeGiano/ai-soc.git
cd ai-soc
```

full会分别测子图和整网，包含多次完整仿真，需要数分钟到数十分钟；quick不下载模型。首次full若缺权重，按data/det/sources.json下载并校验。accuracy首次下载官方标注及600张图片，需要网络。新机器先按下述步骤安装依赖。脚本从任意目录可执行。

Ubuntu / Debian依赖示例：

```bash
sudo apt-get update
sudo apt-get install -y git verilator yosys g++ make gcc-riscv64-unknown-elf binutils-riscv64-unknown-elf python3-venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-detection.txt
bash scripts/run_all.sh quick
```

需要Verilator 5.x、支持RV32IM/ilp32的裸机工具链及其libgcc。Python依赖必须在运行脚本时的`python3`环境中可用。项目不依赖开发者本机的tools目录；工具可从PATH使用，也可通过AI_CHIP_ENV指定工具环境文件。仓库不包含预训练权重、COCO图像、工具链或build产物，full/accuracy会按需获取资源。

运行模式：

```bash
bash scripts/run_all.sh quick      # RTL单元、真实CPU小图、异常/等待/复位、结构综合
bash scripts/run_all.sh full       # 两模型M/F完整CPU+RTL推理，逐层比较、解码NMS、性能对照
bash scripts/run_all.sh accuracy   # 100张独立校准+500张COCO评价，官方COCOeval，主机执行
```

单独运行：

```bash
bash scripts/det/run_model.sh yolov3-tiny F 0 0  # 模型、M/F/B0、额外等待上限、整网ROI开关
bash scripts/det/run_model.sh yolov4-tiny M 0 1
```

B0是已实现的纯CPU卷积路径，完整模型仿真很慢；quick验证小图CPU基线，默认full重点对照相同阵列的M/F。

## 证据与设计入口

- [实际结果汇总](results/det/summary.md)：测试、精度、融合子图/整网周期和访存。
- [当前实现及边界](docs/detection/implementation.md)：模块、存储、数值、模型和综合口径。
- [架构框图](docs/detection/architecture.svg) · [DOT](docs/detection/architecture.dot) · [Mermaid](docs/detection/architecture.mmd)。
- [已实现分工接口表](docs/detection/interfaces.md) · [团队接手分工](docs/team-map.md)。
- [总体设计与目标](docs/detection/README.md) · [四人八周计划](docs/detection/schedule.md)。

M为CPU上采样/尺度转换/拼接物化后硬件卷积，F为双源融合取数后同一硬件卷积，输出逐元素相同。ROI区分CPU数据、取指与DMA，包含配置、软件算子与轮询；逐层验证与打印在计时外。解码/NMS在真实CPU上执行并与独立NumPy参考比较。

演示为160×160、batch1；默认dog.jpg量化标记demo-only，独立COCO精度实验另用100张train校准/500张val评价。主机精度与RTL集成样本范围明确区分。图像预处理在主机执行，无摄像头、FPGA、实际FPS或功耗测量。资源报告为保留memory cell的RTL结构统计，不是门级面积/时序。

## 项目结构

新增主线在rtl/det、firmware/det、tb/det、scripts/det、spec/det、data/det、results/det。spec生成C/SV常量。实际单bank scratch SRAM为24KiB，预算40KiB，第二bank尚未实现，相关配置明确拒绝。

旧GEMM/MNIST代码、报告、数据和设计归档已删除。当前源码、框图、接口与脚本统一围绕目标检测主线。

协作方式见[贡献说明](CONTRIBUTING.md)：public允许公开clone；直接push需要写权限，其他贡献者通过fork和PR参与。

四人八周是后续团队投入和学习/验证计划，不是声称四名成员已完成贡献；实际工作记录需由成员填写。
