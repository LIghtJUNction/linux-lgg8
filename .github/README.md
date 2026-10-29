# LG G8 ThinQ — 主线 Linux 内核

面向 **LM-G820 / alphalm_lao_com / SM8150** 的独立内核源码项目，基于官方 Linux **v7.3**。
包含板级设备树、实验性 SW43410 显示驱动、可复现构建入口和 Android v0 `boot.img` 打包工具。

**当前仍处于硬件适配阶段：正常显示、USB shell、触控及桌面尚未通过真机验证。**
默认镜像使用约 45 秒后复位的诊断用户态；它不是可日常使用的手机系统。

- [中文入口与当前范围](../README.lgg8.md)
- [构建内核、设备树和 boot.img](../lgg8/docs/BUILD.md)
- [临时启动、人工刷入与恢复](../lgg8/docs/BOOT-AND-RECOVERY.md)
- [本地验证结果](../lgg8/docs/LOCAL-VALIDATION.md)
- [硬件状态与未解决问题](../lgg8/docs/STATUS.md)
- [源码来源、许可与上游维护](../lgg8/docs/PROVENANCE.md)

开发分支：`lgg8/mainline`。原厂模板、备份和编译产物留在本地，不进入 Git。
本机快速检查入口：`./lgg8/build.sh test`；只改设备树时：`./lgg8/build.sh dtb`。
