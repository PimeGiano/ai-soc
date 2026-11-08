# 目标检测实际结果

本文件由scripts/summarize.py生成，数值来自实际测试日志。

## 验证

- pool.log: PASS
- cache.log: PASS
- converter.log: PASS
- accel_delay0.log: PASS
- accel_delay3.log: PASS
- accel_delay15.log: PASS
- stress_delay0.log: PASS
- stress_delay15.log: PASS
- ablation_serial.log: PASS
- ablation_no_prefetch.log: PASS
- smoke_ordinary.log: PASS
- smoke_fused.log: PASS
- smoke_cpu.log: PASS
- smoke_pool_packed.log: PASS
- smoke_pool_tail.log: PASS
- smoke_pool_cpu.log: PASS
- smoke_copy_identity.log: PASS
- smoke_copy_scaled.log: PASS
- smoke_copy_unaligned.log: PASS
- smoke_slice_word.log: PASS
- smoke_slice_tail.log: PASS

普通/融合RTL覆盖151组有效任务及7组非法任务，另验证对齐拒绝、busy拒绝、W1C、随机等待和任务中复位重跑（含后台预取）。另有6组容量/行旋转/融合跨源压力测试、串行取数/关闭预取消融，以及独立指令缓存冲突/失效/等待/复位测试。输入转换器2048样本含背压/复位；真实CPU小图包含普通卷积、融合和纯CPU基线。完整模型每层由CPU哈希和测试平台逐字节双重检查。

## 融合子图：M物化 / F融合

| 模型 | M周期 | F周期 | 周期减少 | M数据总线字节 | F数据总线字节 | 流量减少 |
|---|---:|---:|---:|---:|---:|---:|
| yolov3-tiny | 8,546,396 | 8,011,888 | 6.25% | 4,631,520 | 4,343,268 | 6.22% |
| yolov4-tiny | 8,546,396 | 8,011,888 | 6.25% | 4,631,520 | 4,343,268 | 6.22% |

流量为CPU_DATA+DMA实际完成总线字节，不含取指；原始ROI日志另外给出CPU_IFETCH。包含CPU软件物化、配置、轮询和驱动，排除事后检查/打印。既包含去物化也包含输入尺度转换卸载的综合收益；未用这些数值单独宣称融合映射的纯收益。

## 整网周期

| 模型 | M周期 | F周期 | 周期减少 |
|---|---:|---:|---:|
| yolov3-tiny | 43,187,759 | 42,653,251 | 1.24% |
| yolov4-tiny | 66,329,313 | 65,794,805 | 0.81% |

整网含CPU非卷积算子、驱动和轮询，不含主机图像前处理、镜像装载、检查/打印和单独测量的CPU解码NMS。解码/NMS见ROI65533。不能将以上周期换算成实际FPS。B0纯CPU路径仅运行小图验收，尚未测完整模型CPU周期。

## 独立COCO精度（主机）

| 模型 | 浮点AP | INT8 AP | 下降百分点 | INT8 AP50 |
|---|---:|---:|---:|---:|
| yolov3-tiny | 3.80 | 3.33 | 0.47 | 7.21 |
| yolov4-tiny | 11.56 | 10.15 | 1.41 | 20.73 |

160输入；100张train2017校准、500张val2017评价，ID不重叠；官方COCOeval。AP为0..100百分数。完整RTL演示使用单独的demo-only量化配置，不能把500张主机评价写为500张RTL验证。

## 资源与未达目标

已完成Yosys层次/进程/存储收集/结构检查；保留RAM，实际scratch40KiB，X/W双slot、每slot四路bank，后台预取与计算重叠；CPU指令缓存数据/标签/有效位另计1248B。synthesis.json为RTL级算子统计，不是门级面积/时序。

性能研究目标为子图数据流量减少30%、周期减少15%；是否达标见summary.json各模型comparison中的布尔字段，不能将功能通过写为所有性能达标。CPU物化路径也使用精确查表优化，因此当前M/F差异不可套用旧版百分比。完整B0仅做小图，未测完整模型CPU周期。

## 等尺度隔离实验（合成子图）

| 场景 | M周期 | F周期 | 周期减少 | 数据流量减少 |
|---|---:|---:|---:|---:|
| equal | 357,129 | 172,233 | 51.77% | 23.68% |
| unequal | 441,815 | 172,233 | 61.02% | 33.31% |

固定5×5×7低路、10×10×19高路、3×3卷积17输出通道、相同权重/分块。equal使用两路m=1/s=0，排除输入尺度差异；unequal采用3/4与5/8。两种场景均真实CPU/RTL逐字节对拍，不将合成子图的收益当作完整模型收益。
