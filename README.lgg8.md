# LG G8 主线 Linux 开发入口

这是独立维护 LG G8 内核、设备树和 Android boot image 封装的完整 Linux 源码仓库。上游基线为官方标签 **v7.3**，提交 **`c03c1a14507dfaf8b856c2608f9ac216021fc222`**。根目录的上游 `README` 保持原样，LG 专用说明从这里进入。

当前目标是从本仓源码构建 `Image`、`sm8150-lg-alphalm.dtb` 和诊断 initramfs，再打包为 bootloader 可接收的 `boot.img` 文件格式。**生成镜像不代表手机已能运行主线 Linux，也不代表已经通过持久刷入验收。** Linux USB/shell、正常显示、触控与桌面均未通过。

- [项目布局、维护边界与快速构建](lgg8/README.md)
- [依赖、源码构建、模板准备和离线验证](lgg8/docs/BUILD.md)
- [RAM 临时启动、备份、人工刷入与恢复条件](lgg8/docs/BOOT-AND-RECOVERY.md)
- [当前证据、未通过项目和历史实验边界](lgg8/docs/STATUS.md)

目标设备为 **LM-G820 / alphalm_lao_com / Qualcomm SM8150**，历史验收对象使用 **b 槽**。型号相近不构成兼容性证明。所有设备命令必须明确使用 `adb -s` 或 `fastboot -s`，文档只给占位符。

新树使用干净的上游初始化路径，未移入旧实验的 `late_initcall_limit`、强制 restart、BCM bypass、async/initmem bypass 或 DWC3 runtime-PM 修改；默认 bootargs 无 initcall blacklist。面板/DSC 代码仍为实验适配。旧候选的二进制补丁偏移和真机时序不能套用到这个新内核。

源码来源见 [PROVENANCE.md](lgg8/docs/PROVENANCE.md)，具体本地检查结果见 [LOCAL-VALIDATION.md](lgg8/docs/LOCAL-VALIDATION.md)。
