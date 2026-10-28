# 检测项目分工、实际文件与接口

主线：**多尺度特征融合与卷积协同加速SoC**。同一RTL运行YOLOv3-tiny / YOLOv4-tiny，研究上采样/拼接中间张量消除。表中A/B/C/D为接手角色，不是四名成员已经完成的贡献记录。

| 角色 | 实际文件（相对项目根目录） | 核心任务与接口 | 接手验收 |
|---|---|---|---|
| A 系统/验证 | rtl/det/det_soc_top.sv、rtl/native_arbiter.sv、tb/det/soc.cpp、scripts/det/build_soc.sh、synth.sh | I1/I2/I3；真实CPU、64MiB仿真主存、字节写、CPU/DMA分类ROI、系统集成/综合 | 快速真实CPU回归、长等待、两模型完整推理 |
| B 融合/调度 | rtl/det/det_accelerator.sv、spec/det/registers.json、tb/det/accelerator.cpp | I2/I3/I4/I5/I8/I9请求；双源坐标、ORDER、跨源通道块、复制散写、X/W/P/O调度、DMA | 随机卷积/融合、容量/范围拒绝、尾字节、读写量与M/F对照 |
| C 计算/数值 | rtl/det/conv_core.sv、requant.sv、fuse_requant.sv、tb/det/converter.cpp | I5/I6/I7/I9转换；广播4×4MAC、部分和恢复、输入/输出64位定点舍入/饱和 | 跨Cin块恢复、极值、2048个转换样本、背压与复位 |
| D 模型/软件 | scripts/det/model.py、reference.py、export_model.py、evaluate.py；firmware/det/ | I8；融合识别、双执行图、BN折叠/量化、CPU软件算子、独立参考、解码/NMS/COCOeval | 同RTL两模型、逐层对拍、CPU框比对、独立100校准/500评价 |

- [当前实际实现](detection/implementation.md)
- [设计框图](detection/architecture.svg) · [DOT源](detection/architecture.dot)
- [已实现接口及字段](detection/interfaces.md)
- [四人八周计划与贡献登记模板](detection/schedule.md)
- [实际测量结果](../results/det/summary.md)

P RAM调度实际由B模块管理，C核心提供串行restore/result；输入尺度转换是C独立模块，B控制源样本与散写。主线采用单bank，双bank作为扩展项，不能写为已完成。所有分工按真实测试和贡献填写，不能把自动生成内容当作四人既有成果。
