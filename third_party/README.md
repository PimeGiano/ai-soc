# PicoRV32

本项目复用PicoRV32的CPU RTL，来源为 [YosysHQ/picorv32](https://github.com/YosysHQ/picorv32)。固定提交记录在 [REVISION](REVISION)，原版权及ISC许可见 [COPYING](COPYING)，RTL为 [picorv32.v](picorv32.v)。

检测SoC使用RV32IM、快速乘法/除法、计数器，无中断与压缩指令；接入方式见rtl/det/det_soc_top.sv。对固定版本第三方代码的Verilator告警适配在sim/vendor.vlt，自研代码采用严格lint。

检测模型cfg、权重与演示图片的来源和内容哈希见data/det/sources.json；权重按需下载，数据不属于自研CPU或加速器逻辑。
