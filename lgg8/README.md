# LG G8 源码构建与启动封装

本目录把 LG G8 的配置、诊断用户态和打包入口放在完整内核源码树里维护，不再依赖旧集成仓库中的历史 `Image` 或构建目录。源码、设备树和配置可以独立审查；私有模板提供 bootloader 封装所需的已知输入。

## 当前能做什么

| 层次 | 产物或操作 | 通过后能说明什么 |
| --- | --- | --- |
| 源码构建 | ARM64 `Image`、板级 DTB、静态诊断 initramfs | 当前源码能生成对应文件；新内核尚未通过真机验证 |
| 离线打包/校验 | `boot.img` 与 manifest | 格式、输入哈希、布局和分区容量符合工具检查范围 |
| RAM 临时启动 | 人工 `fastboot boot` | 仅在取得可归属到本镜像的真机证据后，确认实际运行到的阶段 |
| 持久刷入 | 人工写入明确的 `boot_b` | 需要另外验证刷后冷启动、回读哈希和恢复；目前未通过 |

“可直接刷入格式”指输出是 Android boot image，而不是裸 `Image`、DTB 或 cpio。它不等于“已证实可安全持久运行”。当前默认用户态仅用于诊断，不是 Android、发行版安装器或桌面系统。

## 目录与产物

| 路径 | 用途 |
| --- | --- |
| `arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dts` | LG G8 板级设备树源码 |
| `lgg8/configs/lgg8.config` | 完整内核配置，不是追加到任意 defconfig 的短片段 |
| `lgg8/boot/cmdline.txt` | 候选内核命令行；修改后重新打包并验证 |
| `lgg8/boot/shim-mmu-off.S` | 启动交接 shim 源码，具体布局由打包工具维护 |
| `lgg8/initramfs/` | 原生诊断 PID 1 及最小 initramfs 输入 |
| `lgg8/build.sh` | `kernel`、`dtb`、`initramfs`、`boot`、`test`、`verify` 入口 |
| `lgg8/tools/bootimg.py` | `prepare-template`、`build`、`verify` 离线工具 |
| `lgg8/tests/` | 打包工具离线回归测试 |
| `out/lgg8/` | 默认独立输出目录，避免污染源码树 |
| `private/template/` | 本机经哈希确认的封装模板，不提交 |
| `out/lgg8/boot/` | 默认打包目录：`boot.img`、`manifest.json`、修补后的 `linux.dtb`，不提交 |

在仓库根目录执行：

```sh
cd linux-lgg8
./lgg8/build.sh kernel
./lgg8/build.sh initramfs
```

内核默认采用 `ARCH=arm64 LLVM=1`、并行任务数 2。显式输出目录的形式为 `./lgg8/build.sh kernel out/lgg8`；内存紧张时用 `JOBS=1`。原生 init 使用 `aarch64-linux-gnu-gcc` 静态编译，不能用主机 x86 ELF 代替。只修改板级设备树时，可用 `./lgg8/build.sh dtb` 单独构建 DTB，随后重新打包并验证。

打包前必须按 [BUILD.md](docs/BUILD.md) 准备已验证的 v0 模板，并取得准确的目标分区字节数：

```sh
TEMPLATE_DIR="$PWD/private/template" PARTITION_SIZE='<BOOT_B_BYTES>' \
  ./lgg8/build.sh boot out/lgg8
```

`<BOOT_B_BYTES>` 必须替换成实测的十进制字节数。此命令只构建文件；默认产物为 `out/lgg8/boot/boot.img` 和 `manifest.json`。可用 `INITRAMFS`、`CMDLINE_FILE`、`BOOT_OUTPUT` 覆盖输入或打包输出目录。设备启动和刷入由 [人工操作文档](docs/BOOT-AND-RECOVERY.md) 单独约束。

## 源码维护边界

基线为官方 `v7.3` / `c03c1a14507dfaf8b856c2608f9ac216021fc222`。本轮维护板级 DTS 与实验性面板/DSC 改动，USB1 明确采用 USB2 配置以避免引用被禁用的 USB3 PHY；`sm8150.dtsi` 的 SHA-256 为 `82887c779c9425ca23e49a81fe3ff8d8c7eec4d073edb305e6a9270371f3b7bc`，与旧实验输入对应文件精确一致。完整来源与迁入文件指纹见 [PROVENANCE.md](docs/PROVENANCE.md)。

新树刻意不移入旧实验的 `late_initcall_limit`、强制 restart、BCM 投票 bypass、async/initmem bypass 和 DWC3 runtime-PM 补丁。上游 `dwc3_gadget_pullup()` 中 `pm_runtime_get_sync()` 返回 0 时，成功恢复后的连接由 runtime resume 回调处理；返回正数表示设备原本已活跃，随后继续本函数的连接流程。不能把 `if (!ret)` 直接称为已证明的 bug，更不能把删除它称为已验证修复。

默认 bootargs 不含 `initcall_blacklist`。这仍是诊断配置，并不意味着已经完成电源管理、并发 CPU、显示或正常桌面的验证。上游更新应在单独 upstream 分支跟踪，再审查合入 LG 开发分支，见 [源码更新步骤](docs/BUILD.md#更新上游而不覆盖-lg-改动)。

## 默认诊断用户态

原生 PID 1 每约 5 秒列出 UDC、DRM、graphics 状态，默认约 45 秒后请求复位，另有约 50 秒后备路径；不配置 USB gadget，也没有默认 shell。它不挂载手机上的 Android、userdata 或其他持久分区；临时内容位于 RAM 中的 initramfs/devtmpfs，proc/sysfs 提供内核视图。无持久分区挂载不等于整个内核绝不访问硬件。

45 秒是用户态诊断策略，不是从 `fastboot boot` 开始计时的硬件复位保证。早期内核挂起、PID 1 未运行、复位路径失效都可能使该策略无法执行。当前 USB/shell、显示、触控与桌面仍未通过，不能依赖候选提供恢复入口。

完整内核、DTB、boot.img 离线核验和 46 项本地测试已通过；QEMU virt 已运行同一内核及诊断 PID 1 并按期复位。新内核尚未通过真机验证。具体记录见 [LOCAL-VALIDATION.md](docs/LOCAL-VALIDATION.md)，C108/C109 及功能状态见 [STATUS.md](docs/STATUS.md)。
