# 框图、取指与共享主存接口说明

配套三页框图记录了重构前的模块层级。当前层级和接口以本文第 2 节及源码为准。三页都包含对应部分的外部输入输出。黑色箭头是引脚方向，红线是连接；束线中的斜线分隔各字段位宽，不代表一个打包RTL信号。交叉无连接点不表示相连，同名全局时钟/复位按说明连接。

- [SoC总图](team-system.svg)：边界是 `det_soc_top`，主存位于边界外。
- [CPU与I-cache](team-cpu-cache.svg)：顶层CPU与缓存的组合部分，不是一个新增RTL模块。
- [卷积加速器内部](team-accelerator.svg)：展示重构前的卷积模块和数据通路。
- [可编辑三页源文件](team-interfaces.drawio)：用diagrams.net打开。模块的引脚、标签作为子对象，红线连接引脚锚点；移动模块时连接端点随之移动，折线路径仍可手工整理。

旧的 `team-datapath.svg/png/dot` 保留为新版卷积加速器图的兼容副本。图形由 `python3 scripts/team_schematic.py` 生成；Excel及图一起更新用 `python3 scripts/export_team_workbook.py`。手工编辑drawio后应另存，重新运行导出会覆盖生成文件。

## 1. cpu_instr究竟到哪里

原图将CPU的 `ci` 画到仲裁器输入，这是接线错误，现已修正。`native_arbiter` 没有任何 `instr` 端口。

`ci` 是PicoRV32的 `mem_instr` 输出，表示CPU当前请求是取指。它在顶层有两个用途：

1. `instruction_cache.cpu_instr(ci)`：与地址、写选通一起判断请求能否命中取指缓存。
2. `assign mem_instr = ci && !mem_dma`：生成顶层的外部访问统计标记。它不参与仲裁或选路。

所以 **ci这根属性线没有进入arb；取指请求在未命中时仍会通过arb访问主存**。取指属性与取指请求要分开理解。

缓存使用以下组合关系（`rtl/instruction_cache.sv`）：

```systemverilog
bus_valid = cpu_valid && !hit && !rst;
cpu_ready = !rst && (hit || bus_ready);
cpu_rdata = hit ? words[index] : bus_rdata;
```

- 命中：缓存直接给CPU返回指令并完成握手，`cbv=0`，不发起这一次外部读。
- 未命中：`cbv=cv`，请求到总线，收到返回数据后交给CPU并填入缓存。
- CPU数据读写、MMIO、不可缓存的取指：绕过缓存存储，经同一个总线出口访问。
- 地址 `ca`、写数据 `cw`、写选通 `cs` 直接接仲裁器；I-cache没有这些信号的独立bus输出，也没有CPU写数据输入。它通过 `cbv` 门控访问，通过 `cr/cd` 选择应答。

缓存容量为256个32位字，共1KiB数据；只缓存64KiB程序窗口内、对齐的指令读取。CPU写程序窗口会使对应缓存行失效。每次miss只填一个32位字，没有突发cache-line refill。

`ENABLE_ICACHE=0` 时直接 `cbv=cv, cr=cbr, cd=cbd`。CPU/缓存图按默认启用配置绘制。

### CPU＋缓存组合的对外接口

| 方向（相对组合） | 名称 | 位宽 | 连接位置 |
|---|---|---:|---|
| 输入 | clk、rst | 各1 | 全局时钟复位；CPU的resetn=!rst |
| 输入 | cbr、cbd | 1、32 | arb.c_ready、arb.c_rdata |
| 输出 | cbv | 1 | arb.c_valid |
| 输出 | ca、cw、cs | 32、32、4 | arb.c_addr、c_wdata、c_wstrb |
| 输出 | ci | 1 | 顶层统计标记逻辑，**不是arb** |
| 输出 | trap | 1 | 顶层trap输出 |

## 2. 内部图按文件组织

[det_accelerator.sv](../rtl/det_accelerator/det_accelerator.sv) 实例化卷积调度器和池化引擎。卷积调度器通过组合控制信号调用下表模块。

| 模块 | 职责 |
|---|---|
| det_conv_descriptor | 主/融合描述符的地址、参数和容量检查 |
| det_conv_counters | 计数和卷积 CSR 读回 |
| det_conv_tile_buffer | X/W 两槽的物理地址、bank 冲突检测及操作数收集 |
| det_conv_datapath | 部分和与输出 SRAM、4×4 MAC 和输出定点转换 |
| tile_prefetch | 后台下一 Cin 块取数 |
| fuse_requant | 前台融合输入转换及握手 |

前台和后台均把逻辑索引交给 `det_conv_tile_buffer`，由它生成 bank（2 位）和字地址（9 位）。前台读写活动槽，后台写非活动槽。每组 X/W 的四个 bank 合计 36 位读地址和 128 位读数据，收集后形成两个各 32 位的操作数向量。

P 使用 10 位地址和 32 位部分和。O 在 RESULT 阶段写选定字节，WRITE_OUT 阶段给调度器提供 32 位字，由调度器根据地址与剩余通道数产生外部字节选通。

融合输入请求的字段是：cfg_valid(1)、m0/m1(各31)、s0/s1(各6)、in_valid(1)、src_id(1)、in_data(8)、in_token(16，固定0)、out_ready(1)。应答是cfg_ready/in_ready/out_valid（各1）、out_data(8)；out_token(16)未接使用者。

预取配置字段是：start/consume/fused（各1）；src/weight/src0/src1/width0/width1/channels0/channels1/order（各32）；multiplier0/1（各31）、shift0/1（各6）；height/width/cin/cout/kh/kw/tic/toc/next_ic/oc/xh/xw/ytop/xtop（各32）。busy/done为各1位；读请求read_valid/read_addr为1/32，返回read_ready/read_data为1/32；写侧x_write/w_write/write_index/write_data/write_strobe为1/1/13/32/4。

### det_accelerator的全部外部端口

| 方向 | 名称 | 位宽 | 含义 |
|---|---|---:|---|
| 输入 | clk、rst | 各1 | 时钟、复位 |
| 输入 | reg_valid、reg_addr、reg_wdata、reg_wstrb | 1、8、32、4 | CSR请求 |
| 输出 | reg_ready、reg_rdata | 1、32 | CSR应答 |
| 输出 | dma_valid、dma_addr、dma_wdata、dma_wstrb | 1、32、32、4 | 主动访问主存的请求 |
| 输入 | dma_ready、dma_rdata | 1、32 | 卷积主存应答 |
| 输入 | pool_reg_valid | 1 | 池化 CSR 请求有效，共用 reg_addr、reg_wdata、reg_wstrb |
| 输出 | pool_reg_ready、pool_reg_rdata | 1、32 | 池化 CSR 应答 |
| 输出 | pool_dma_valid、pool_dma_addr、pool_dma_wdata、pool_dma_wstrb | 1、32、32、4 | 池化主存请求 |
| 输入 | pool_dma_ready、pool_dma_rdata | 1、32 | 池化主存应答 |

SoC 保留两个引擎各自的 CSR 地址窗口和 DMA 仲裁端点。

## 3. SoC总图所有外部输入输出

相对 `det_soc_top`，共11个命名端口：4个输入、7个输出。没有外部CSR端口，CPU在SoC内部发起CSR访问。

| 方向 | 信号 | 位宽 | 用途 |
|---|---|---:|---|
| 输入 | clk | 1 | 时钟 |
| 输入 | rst | 1 | 高有效同步复位 |
| 输入 | mem_ready | 1 | 本次外部请求已完成 |
| 输入 | mem_rdata | 32 | 外部读返回数据 |
| 输出 | trap | 1 | CPU陷阱标记 |
| 输出 | mem_valid | 1 | 外部请求有效 |
| 输出 | mem_addr | 32 | 字节地址 |
| 输出 | mem_wdata | 32 | 写数据 |
| 输出 | mem_wstrb | 4 | 每个bit控制一个字节写入；0000表示读 |
| 输出 | mem_dma | 1 | 外部完成访问是否来自卷积/池化DMA的统计标记 |
| 输出 | mem_instr | 1 | 外部完成访问是否为CPU取指的统计标记 |

`mem_dma/mem_instr` 不是一套独立地址/数据通路，也不是仲裁输入。当前实现中 `mem_dma` 由ready完成信号推导，因此**只在mem_valid && mem_ready时解释这两个分类值**，不能用它们在等待周期预测当前owner。

## 4. 主存的线怎么接、在哪里实现

### 请求方向

```text
CPU → I-cache门控后的请求 → arb.c ─────┐
                                     ├→ arb.s → 地址译码 → pool_arbiter.c ─┐
卷积det_accelerator.dma_* → arb.d ─────┘                                   ├→ mem_* → 外部主存
池化pool_accelerator.dma_* ─────────────────────────────→ pool_arbiter.d ─┘
```

地址译码拦截 `0x100001xx` 给卷积CSR，拦截 `0x100002xx` 给池化CSR；只有其他地址的请求进入外层仲裁器c侧。外层还接池化DMA的d侧。两个native_arbiter实例最终把三个主设备复用到一组外部线。

- `rtl/det_soc_top.sv`：实例arb连接CPU与卷积DMA；reg_select/pool_select做地址译码；实例pool_arbiter的s_*直接接顶层mem_*。
- `rtl/native_arbiter.sv`：selected控制地址、写数据、strobe多路选择；两个请求同时等待时交替选择；请求未完成则locked保持owner。**不是把多个输出直接并接。**

### 应答方向

`mem_rdata` 被送回内部读数据路径，`sr` 按地址选择卷积CSR的rr、池化CSR的pool_rr或外部external_ready；`sd` 同样选择rd、pool_rd或mem_rdata。arb再把ready只给被选中的请求方：

```systemverilog
c_ready = s_valid && !selected && s_ready;
d_ready = s_valid && selected && s_ready;
c_rdata = s_rdata;
d_rdata = s_rdata;
```

读数据可广播给多个接收端，但只有获得ready且自身valid的端点消费。池化的dma_rdata直接接mem_rdata，其dma_ready仍由外层仲裁器门控；并不代表它能抢读其他设备的应答。顶层中 `unused_pool_crdata/drdata` 是外层重复的读数据输出，因为代码直接使用同一个mem_rdata而不再接这些别名。

### 协议与主存模型

这是一次一笔在途请求的native valid/ready协议：valid持续有效，地址/写数据/strobe在等待期间稳定，**valid && ready表示这笔操作完成**。读时wstrb=0000；写时bit0对应wdata[7:0]，bit3对应wdata[31:24]。所有操作共享32位数据线，读和写没有独立并行通道。

当前RTL里没有DDR控制器、AXI总线或实际主存RAM实例。主存由仿真环境提供：

| 文件 | 代码位置/内容 |
|---|---|
| `tb/soc.cpp` | tick中检测t.mem_valid，插入随机等待，检查addr/wdata/wstrb稳定；完成时驱动t.mem_ready及t.mem_rdata，写入调用mem.write |
| `tb/memory.hpp` | Memory::code为64KiB、data为64MiB；at做地址映射，read按小端组合4字节，write按4位strobe逐字节更新 |

程序窗口为 `[0x00000000,0x00010000)`，数据窗口为 `[0x01000000,0x05000000)`。`0x20000000/04/08`由testbench处理打印、退出和ROI统计标记，不能误画成主存RAM容量的一部分。实际接FPGA/芯片时，需要在mem_*外侧加主存控制器/协议适配及对应的物理存储。

## 5. 还有哪些部分没有继续展开

不能说只有CPU/I-cache和卷积内部没展开。当前交付按“模块接口和主要内部数据流”层级绘制，还有这些更低层细节：

- 总图“两级仲裁/地址译码”仍是逻辑合并块，内部两个native_arbiter实例和返回mux可在后续单独展开；实际接线已在上文解释。
- pool_accelerator的CSR与DMA接口已有，内部池化扫描、比较器、尾部字节及状态机没有独立展开图。
- tile_prefetch内部的地址映射、四字读缓存和requant没有逐项展开。
- banked_scratch内部四bank、conv_core内部16个MAC、fuse_requant内的单项弹性缓冲/算术，也没有绘到每个寄存器。
- CPU图展开到PicoRV32与I-cache模块接口；PicoRV32内部译码/执行/乘除法、I-cache内部tag比较与有效位也没有另画。

这些不影响当前模块接口图表达；若要逐模块讲解实现，则可针对上述部分继续补图，不能称当前图已经覆盖所有电路细节。
