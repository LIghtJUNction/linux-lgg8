# 本地验证记录

日期：2026-10-29。当前实验源码已完成本机从源码到 `boot.img` 的流程。
**撤回自动 RPMh 读回后的新 Image 已做真机控制；全套新 DTB 与默认参数尚未通过，未刷入分区。**

下方首轮制品对应源码提交 `af449a8872c64be85703982ac3843160e0cf7afb`。
后续 regulator 读回回退、增量制品和真机控制另列在文末，首轮哈希不代表当前 Image。

## 已完成的检查

| 检查 | 结果 | 证据范围 |
| --- | --- | --- |
| 完整内核与板 DTB 构建 | 通过 | `./lgg8/build.sh kernel`，ARM64 / LLVM，版本 `7.3.0-lgg8` |
| 本地测试 | 46 项通过，0 跳过，约 1.708 秒 | 25 项封装、11 项板树、10 项 initramfs；包含负例 |
| 静态 init 构建与 CPIO | 通过 | AArch64 静态 ELF、GNU cpio 可解析；普通进程下返回 91 |
| QEMU virt 实际启动 | 通过，约 46.688 秒退出 | 同一 Image/CPIO 进入 PID 1，出现入口和截止日志，最终 SysRq 复位 |
| boot 镜像 verify | PASSED | v0/4096、gzip CRC、2 个 stock DTB、内存与文件布局、可信 manifest 哈希 |
| 容量 | 11,853,824 / 100,663,296 字节 | 镜像约 11.30 MiB，目标分区实测 96 MiB；读取未写分区 |
| 脚本与面板代码检查 | 通过 | ShellCheck；面板 checkpatch 无错误/警告；新增面板 binding 通过 dt-doc-validate |

QEMU 使用 `virt,gic-version=3`、Cortex-A76、512 MiB、单 CPU 与 TCG，
使用 QEMU 自动产生的虚拟设备树。它验证通用启动与诊断 PID 1，
**没有模拟 LG G8 的 RPMh、USB PHY、DSI 屏幕或 ABL/shim 交接**。
入口保护测试与完整 PID 1 启动是两项不同检查。

验证器依赖可信 manifest 固定的 shim 哈希；它重新解析镜像中的组件，
但不重新编译 shim，也不证明每条汇编指令的语义。板树测试验证静态依赖，
不能证明真实电压、时钟和总线状态。

## 工具版本

- Clang / LLD 23.1.4
- AArch64 GCC 16.2.0
- DTC 1.8.1
- QEMU 11.1.2
- Python 3.14.8；zlib 1.3.1.zlib-ng

`SOURCE_DATE_EPOCH=1792365298`，构建用户名/主机名固定，默认 `LOCALVERSION` 为空。
配置内自动生成的编译器字段已更新到本次工具版本，当前配置文件与实际 `.config` 一致。
其他工具链会更新相关自动字段；跨工具版本的字节一致性未经验证。

## 制品指纹

这些文件位于被 Git 忽略的 `out/lgg8/`，没有上传设备模板或二进制镜像。
下表中的板 DTB 是编译产物；boot 内部 `linux.dtb` 另加入了命令行和 initrd 地址。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `lgg8/configs/lgg8.config` | 200301 | `41dbae047ff67689ab25f9975dd089e3bd3e15f2f31c70ce961316b6d7090ca9` |
| `out/lgg8/kernel/.config` | 200301 | `41dbae047ff67689ab25f9975dd089e3bd3e15f2f31c70ce961316b6d7090ca9` |
| `out/lgg8/kernel/arch/arm64/boot/Image` | 26745344 | `49bfec85c27570dff4cd5ebeb7c7c493d70ccf61159775681d9b09a3e62fb4b5` |
| `out/lgg8/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb` | 95674 | `cbe75ff81bb1a7fcb40ccc66880ea25d12a28dd1c77556d6254514a4e97ffbbd` |
| `out/lgg8/initramfs/initramfs.cpio` | 599040 | `9f491f36789c714a50631d785f46de7d4dd2868a41bbae939343187be5f6decb` |
| `out/lgg8/boot/boot.img` | 11853824 | `443229ebe4d35000246ac260a7bbf6af4bddfe46ddf97d4eb762790fa079bc5f` |
| `out/lgg8/boot/linux.dtb` | 96025 | `8e7a54084269db46ec4ed2d2974872cafe9abfa073682ca86f780990da9ca384` |
| `out/lgg8/boot/manifest.json` | 6109 | `04d6a590f37f11355d24dbc4c0bd69ccfcb8cfda8110cebae3e26d754898b198` |

## 内存布局

- 内核目标地址：`0xaa000000`
- initramfs 起点：`0xaba00000`
- initramfs 终点（不含）：`0xaba92400`
- DTB 起点：`0xabc00000`
- 载荷终点（不含）：`0xabc17720`

所有载荷落在板树声明的真实 RAM 范围，且与其固定保留区、memreserve 表无重叠。
这仍以板树本身正确为前提，不构成实时硬件内存探测。

本地完整日志保存在 `out/lgg8/validation/`，包含 `build.log`、`tests.log`、
`qemu.log`、`verify.json` 和 `result.json`。临时打包试验输出已清理，
保留一套增量内核构建目录、最终镜像和私有模板，便于下一轮迭代。

## 本轮未完成的硬件条件

首轮制品的完整组合，以及正常显示、USB 枚举/shell、触控、桌面及持久刷入均未验证。
旧 C109 约 52 秒回收且未出现预期七秒信号的结果，不能升级为本镜像启动通过。
后续 Image 控制已取得原生用户态时序证据；具体范围和当前停点见 [STATUS.md](STATUS.md)。

## 撤回自动 RPMh 读回后的增量与真机控制（2026-10-29）

源码提交 `c0cfe9a` 单独恢复 regulator 缓存策略，没有固定 XO 旁路或全局
`rpmh_read()` 错误注入。复用同一构建缓存，以 `JOBS=1` 增量构建成功；
46 项测试在 1.250 秒内通过，日志保存在忽略目录
`out/lgg8/validation/readback-revert-tests.log`。

| 产物 | SHA-256 |
| --- | --- |
| Image | `3f2487cb0710d38fbb3856318ed32cc3529bd33478572104ffd34a545eea2bca` |
| resolved .config | `41dbae047ff67689ab25f9975dd089e3bd3e15f2f31c70ce961316b6d7090ca9` |
| 全套源码默认诊断 boot.img | `b0f785295be3b5d7a733c52519dfe4a119715a482a97c0e864cff3f7697712af` |

新默认 boot.img 为 11,853,824 字节，位于 `out/lgg8/boot-readback-revert`，
独立 verify 为 PASSED。它包含本树 DTB、默认 45 秒诊断 init 和无 initcall
blacklist 的默认参数；该完整组合尚未真机验收。本次不重复通用 QEMU 测试来
替代具体板子的电源、USB 或显示证据。

C119 从已测旧候选只替换成上面的新 Image，保留旧 DTB 与七秒原生控制。
USB 空窗为 29.433 秒，Android 完整回收，两槽 boot 哈希不变。
它为源码内核执行到原生用户态控制提供设备证据；新 DTB、默认 init/参数与
Linux gadget、显示、桌面需分别验收，详见 [STATUS.md](STATUS.md)。

## RAM 桌面用户态与全套离线封装

`lgg8/rootfs/` 使用 Alpine 3.24.3 固定输入、74 个已验证签名 APK 的所选文件，
保留 Weston 14.0.2、pixman、desktop-shell、终端、seatd/eudev 及所需字体与数据。
171 个保留 ELF 的依赖和 15 项关键运行文件通过实际检查；没有伪造完整 APK 安装闭包。

| 产物 | 字节数 | SHA-256 |
| --- | ---: | --- |
| 桌面 CPIO | 50051584 | `e8593c38b5e2e24aeccf294b2530c8524c69b3bf3ba2d4d0145fdec414a6bb27` |
| 桌面 boot.img | 29712384 | `e32f2299646bd15126ba01d44d1c77ab4689e5efe16ea53948e85e74b155ae55` |

同一维护内核 `3f2487cb…` 和该 CPIO 在 QEMU 系统模拟中实际运行约 22.07 秒，
退出码 0。PID 1、Wayland socket、桌面壳、终端 shell、两条同 surface 的
buffer/damage/commit/frame callback 链及 guest/Weston 的 printk 镜像均通过。
这不是手机显示测试，也没有生成截图。

桌面 boot.img 使用本仓 DTB 和默认无 blacklist 的 DRM 参数；离线 build/verify
通过，原始 RAM 载荷末端为 `0xaea17720`，通过 bank 与保留区检查。
本机另通过新增 shell 的 ShellCheck、supervisor 的 `-Wall -Wextra -Werror`
语法检查及 Python AST 解析。真机完整组合结果仍须单独记录，不能由本节推导。
