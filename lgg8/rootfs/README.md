# RAM 桌面根文件系统

这是 Alpine 3.24.3 / AArch64 的文件级精简桌面：Weston 14.0.2、DRM + pixman、desktop-shell、终端、seatd、eudev 和 Liberation Mono。另保留小型 headless 后端供 QEMU 系统测试。**本地 headless 用户态已通过；LG G8 的 DRM、面板、触控和桌面仍未验收。**

源文件仅在本目录，默认生成物位于 `out/lgg8/desktop`。可用 `LGG8_DESKTOP_OUT=/absolute/path` 指定独立输出目录；构建缓存可通过该目录的 `cache` 符号链接复用。构建器没有设备、Git、主机软件安装或主机挂载操作。它不修改内核、DTS、通用 bootpacker 或 `build.sh`。

## 构建与验证

从仓库根目录运行，需要现有 Python 3、`aarch64-linux-gnu-gcc`、QEMU system AArch64；打包另外使用通用 bootpacker 已有的 LLVM 工具。GNU 工具链必须带 AArch64 静态 libc/libgcc，生成静态 ET_EXEC；不能替换成主机 gcc。实际工具版本记录在 provenance.json，改变工具链后需重建并重新验证，不能沿用参考产物哈希。

本次实际使用 GNU AArch64 GCC **16.2.0**、QEMU **11.1.2**。当前 package lock 固定的 Image 为 `2962224f…8463d6`，由仓库根目录的 `JOBS=2 ./lgg8/build.sh diag-pstore` 构建；构建凭据记录于 `out/lgg8/kernel/build-provenance.json`。根文件系统构建器只核对锁定的 Image，不会自行编译内核。旧基准 `3f2487…a2bca` 仅对应下文历史交付。CLI 只调整打包参数或锁文件的本地路径元数据时，若 CPIO 哈希未变，可重新核验已有日志，无需重跑 guest。

```sh
# 使用现有、已核验的 ARM mini 归档，不重复下载。
python3 lgg8/rootfs/build.py build --base /absolute/path/to/alpine-minirootfs-aarch64.tar.gz

# 同一根、静态 PID1、固定 Image 的真实系统模拟；不是 qemu-user。
python3 lgg8/rootfs/build.py qemu

# 仅重新核验已有日志，不再次启动模拟器。
python3 lgg8/rootfs/build.py qemu-check

# 离线构造 Android v0 boot.img，并调用通用 bootpacker verify。
# 容量必须是另行确认的实测值；这里没有默认容量或设备查询。
TEMPLATE_DIR=/absolute/path/to/verified-template \
PARTITION_SIZE=CONFIRMED_PARTITION_BYTES \
python3 lgg8/rootfs/build.py pack

# 同样可以显式传 --template 和 --partition-size。
python3 lgg8/rootfs/build.py pack \
  --template /absolute/path/to/verified-template \
  --partition-size CONFIRMED_PARTITION_BYTES

# 绑定同一最终 CPIO、日志、boot.img、源文件和签名输入。
python3 lgg8/rootfs/build.py receipt
```

一次性 pmsg 通路检查可在启动参数追加 `lgg8.pmsg_probe=1`，并用
`lgg8.pmsg_tag=C196` 给本轮打标。PID 1 只创建共享回执并派生专用 worker；
worker 尝试向 `/dev/pmsg0` 写入带 `LGG8_USER_PMSG_PROBE` 标记的短记录。
即使 pmsg 的 open 或 write 卡住，桌面监督和 USB beacon 仍继续运行。beacon
启动时冻结当时的 open/write 状态、真实 errno 或短写字节数，并写入 USB
iSerial；`lgg8.pmsg_probe` 未启用时，原 iSerial 保持 `LGG8-RAM`。旧的
`/run/usb-beacon-snapshot` 格式不变。Android 回收后若 pstore 导出该标记，
可证明 Linux 用户态到 ramoops pmsg 的通路可读，但不能证明 DPU 驱动自己的
诊断 worker 已执行。

2026-10-31 pmsg 回执版本已用 `diag-pstore` 配置重建内核，并通过离线包格式核验和 AArch64 QEMU headless 桌面验收：Image SHA-256 `2962224f1fda3031af28c01b05f3b0a9e15101cb266fccafb38ce5c6848463d6`，DTB SHA-256 `88207ff2e9b28cca8d0b98dc4e5ca64552c7023930d51b207a5546ebe71d4ef2`，CPIO SHA-256 `c97389e44938bcb9fe3e0c8059604d10096cba8eeabf72601a2eb39f80e5c2f7`，默认 probe 关闭的 RAM-only `boot.img` SHA-256 `1488331400a54a35edb69f367061a3b7d4017190c160ed5a60ccfb0e00d75faa`。x86_64 `dummy_hcd` 测试覆盖禁用、open 错误/挂起、write 错误/挂起/成功和短写七种状态，主机均能读取冻结后的 iSerial 回执。随后 C196 在 bootargs 开启 pmsg probe，RAM-only `fastboot boot` 成功；Android 完整回收，slot `_b`、boot_completed、boot ID 轮转核验通过，boot_a/boot_b 哈希不变，全程无分区写入。USB 1-2 于 +16.238 秒断开、Android USB 于 +137.164 秒返回、ADB 于 +137.452 秒恢复。C196 启动前后 pstore 均经完整性核验为空，且主机在 USB 断开窗口没有观察到 Linux `18d1:4ee7` gadget 枚举，因此不能读到 iSerial 中的 open/write 回执，也不能判定探针停在何处；屏幕结果未记录。C196 镜像 SHA-256 `527934b7c5e050d26567f72c40c3cfb63fe106c62ccfb639b98c7f49ff00844f`，产物、运行器及证据位于 `out/lgg8-c196-pmsg-beacon-receipt-20261031/`。AArch64 QEMU 和虚拟 USB 结果不代表实机显示正常或 gadget 已枚举。

可用本机内核和 `dummy_hcd` 快速跑真实 `supervisor.c` PID 1 的隔离测试；它
使用临时 initramfs，不接触手机或物理 USB 口：

```sh
python3 lgg8/rootfs/test_pmsg_beacon_qemu.py --mode disabled
python3 lgg8/rootfs/test_pmsg_beacon_qemu.py --mode open-error
python3 lgg8/rootfs/test_pmsg_beacon_qemu.py --mode hang-open
python3 lgg8/rootfs/test_pmsg_beacon_qemu.py --mode hang-write
python3 lgg8/rootfs/test_pmsg_beacon_qemu.py --mode write-ok
python3 lgg8/rootfs/test_pmsg_beacon_qemu.py --mode write-error
python3 lgg8/rootfs/test_pmsg_beacon_qemu.py --mode short-write
```

这些测试验证虚拟主机实际读到的 gadget iSerial、pmsg 探针挂起时 PID 1 仍
能绑定并枚举，以及复位监督进程仍存活；它们不代替 LG G8 的 pmsg 成功读回
或真机 USB 物理枚举验收。

`--base` 只读取调用者明确指定的本地归档并校验 SHA-256；指定路径不存在就停止，不猜测私人目录。不传它时，向专用 cache 获取锁定的官方 ARM mini，已有缓存则核验后复用。公开锁文件不包含本地用户路径。`build` 每次重新生成唯一工作根，并重新核验缓存 APK 的 SHA-256、签名、名称、版本和 aarch64/noarch 架构；没有包安装事务。`--record-lock` 仅用于首次经过签名验证后补入缺失的包 SHA-256，已有 SHA 不会被静默替换。当前锁文件已完整，不需要此选项。

`pack` 只接受明确的 `--template` / `TEMPLATE_DIR` 和 `--partition-size` / `PARTITION_SIZE`，没有旧实验 manifest 依赖、默认容量、当前 slot 猜测或设备查询；模板应已由通用 bootpacker 的 prepare-template 从固定 SHA 的已核验 v0 输入准备好。它使用实际 Image、板级 DTB、最终 CPIO 和独立手机命令行，不会把 QEMU headless 参数带入手机镜像。没有私有模板和已确认容量时，可独立完成 rootfs、静态检查与 QEMU，但不打包手机 boot.img。

QEMU 命令固定为 `virt,gic-version=3`、`cortex-a76`、单 CPU、768 MiB、`-nographic -nic none -no-reboot`；仅使用虚拟串口，不访问主机 DRM/Wayland 设备。启动前读取 MemAvailable，低于 2 GiB 写入 `PENDING_MEMORY` 并以状态 3 退出。guest 的显式测试参数为：

```text
console=ttyAMA0 rdinit=/init loglevel=7 panic=1
lgg8.desktop_backend=headless lgg8.desktop_timeout=20
```

guest 20 秒结束，QEMU 进程另有 45 秒主机等待上限。测试检查 PID1、socket、desktop-shell 加载及 helper 启动、终端实际执行 shell、同一 surface 的非空 buffer → damage → commit → 对应 frame callback 完成，以及 guest/Weston 日志实际进入 printk。解析器按具体协议对象 ID 关联事件，不用单纯的 commit 字符串存在判断，也不把 kmsg 的重复镜像当作另一条协议流。

## 二进制来源与裁剪

- ARM mini 原包 SHA-256：`4d3f80afaebd447c5591a63a73bde380a149fe8b2d85488cafabb2ff97551f50`，大小 4029999 字节。本地已有该文件，本次未重复下载。
- 主机验证工具来自已锁定的 Alpine 3.24.3 x86_64 mini 归档。用其自己的 musl loader/库启动 apk，避免依赖主机包管理器或先运行未经验证的 apk.static。这个验证工具树与 ARM 工作根分离。
- 74 个 APK 均来自 v3.24/main 或 community。`package-lock.json` 给出逐包 URL、版本、实际 SHA-256、仓库校验标识、签名结果和 aports commit 元数据。
- 使用 apk 的 `verify` 和 `extract --no-chown`，不执行 add、不执行 APK 脚本/trigger、不忽略签名，也不假造已安装包数据库。`verify/extract` 本身不执行安装脚本；apk 3.0.8 这两个子命令不接受安装阶段的 `--no-scripts` 参数。
- 仅保留 DRM/headless 后端、desktop-shell、核心 helper、终端及小型 debug 工具。去除 GL、PipeWire、remoting、其他 shell/backend/client 模块。没有 LLVM、GStreamer 或 Mesa DRI/Gallium 驱动。
- `mesa-gbm` 的小型 `libgbm.so` 仍然保留，因为 DRM 后端真实链接它；保留文件的全部 DT_NEEDED 都必须可解析。不能因为渲染器选择 pixman 就忽略真实 ELF 依赖。
- 字体、fontconfig、xkb、libinput 的输入规则、eudev daemon 和 shell 图标/数据均有实际文件审计。首轮 UI 是英文；未加入完整中文字形。

所有已保留 ELF 的架构、PT_INTERP、DT_NEEDED、RPATH/RUNPATH 与依赖目标均检查；目标也必须属于已审计的 AArch64 ELF 集合。dlopen/plugin 的选择另见 [来源与运行约束](PROVENANCE.md)。DRM 路径仍需真机验证，不能由 headless 测试推导。

## PID1、日志与手机默认路径

`supervisor.c` 以现有 GNU AArch64 编译器生成静态 ET_EXEC：`-static -fno-pie -no-pie -Wl,--build-id=none`。非 PID1 立即返回 91；没有使用 qemu-user 执行特权挂载逻辑。

PID1 在任何挂载、console/kmsg 打开等 I/O 前 fork 独立的 90 秒单调时钟复位进程。随后只建立 proc、sysfs、devtmpfs、devpts 和 RAM `/run`，启动 guest `/bin/sh` 脚本并回收子进程。复位先写 SysRq-b，再尝试 reboot 作为后备；这个用户态计时器不保证能处理任意内核硬卡死。没有 Android 分区访问、块分区挂载、网络取包或主机终端访问。默认不配置 gadget；下面的 USB 状态 beacon 需要明确开启。

手机默认始终是 `drm`，不自动转入 headless。脚本启动真实 `/sbin/udevd`，仅触发 DRM/input 子系统；存储、网络和模块加载相关规则不进入该根。随后启动 seatd，检查其进程和 `/run/seatd.sock`，约 3 秒内未就绪则记录明确错误并停止启动 Weston。seatd 0.9.3 的 socket 路径是编译期设置，不能传不存在的 `-s` 参数。

`SEATD_VTBOUND=0` 是这个嵌入式原型的明确配置，不绑定 VT；不代表完成会话切换或权限模型验收。连接器和对应 card 从实际 `/sys/class/drm/card*-*/status` 的 connected 状态选择；使用该真实 card 和 connector 的 preferred mode，不猜测 card0/DSI-1。`require-input=false` 允许先验显示，不能据此声称输入已工作。

RAM 日志有 `desktop-events.log`、`weston.log`、`client.log`、`seatd.log`、`udev.log`。PID1 同时转发到 console 和 kmsg；每次 kmsg 写入含路径前缀及换行不超过 960 字节，fd 为非阻塞，超长文本分段。console 自身的写入不等于 printk，因此两条路径必须保留。kmsg 限流、EAGAIN、内核状态及 ramoops/Android 的保留行为都可能丢日志；**没有保证完整日志或跨重启保留**。QEMU 使用 loglevel=7，使 INFO 镜像也可在串口中核验。

## 可选 USB 状态 beacon（默认关闭）

仅当命令行明确包含 `lgg8.usb_beacon=1` 时启用；重复该键时最后一个值决定，其他值均关闭。guardian90 已建立、桌面脚本已 fork 后，主循环在 PID1 启动约 8 秒时只派生一次 beacon 工作进程。它有 3 秒 alarm、有限目录扫描和短读取；无 UDC、多 UDC 或任一步失败就有限记录日志并结束，不阻塞桌面主循环、不重试或修改已有 gadget。若 UDC 写入卡在不可中断内核路径，alarm 不保证能中止，仍依靠独立 90 秒 guardian 和平台复位路径。

仅对 `/sys/class/udc` 中唯一的实际控制器创建 configfs ACM：VID:PID 为 `18d1:4ee7`，默认保留原 iSerial；启用 pmsg 探针时 serial 携带冻结回执，最多写一次 UDC 绑定。没有 ACM shell，不打开 `/dev/ttyGS0`，不导出网络或存储，不访问持久分区。configfs 状态和阶段文件都只在 RAM。真实 USB 绑定和主机看到描述符仍须真机证明。

产品字符串示例：

```text
LGG8-RAM DRM=1 CON=1 FB0=1 SEATSOCK=1 WPROC=1 ST=8
```

- `DRM`：`/sys/class/drm/cardN` 的卡数量；`CON`：该目录中 connector 的 status 恰为 connected 的数量。目录读取出错或扫描超限时两项均为 -1；单个 status 读取失败时 CON 为 -1。每次 readdir 前清零 errno，区分正常目录结束与读取错误；UDC 目录读取出错直接结束尝试，绝不使用部分列表绑定。
- `FB0`：`/sys/class/graphics/fb0` 是否存在，不打开 framebuffer，也不代表 scanout 正常。
- `SEATSOCK`：`/run/seatd.sock` 是否是 socket，不代表协议握手成功。
- `WPROC`：脚本记录的 Weston PID 当前仍为名叫 weston 的非僵尸活进程。**进程存在不等于 socket、帧提交、可见显示或桌面成功。**
- `ST`：`/run/desktop-stage` 的采样值：1 脚本入口，2 配置已写，3 进入 udev 阶段，4 等待 seatd，5 seatd socket 就绪，6 Weston 已派生，7 Wayland socket 就绪，8 终端已派生。90/91 为 seatd 退出/超时，92/93 为 Weston 提前退出/socket 超时，94 为终端退出；缺失或无法读取为 -1。阶段只说明脚本到达位置，不代替帧证据。

`lgg8.desktop_timeout=20` 现可用于显式 DRM 诊断及 headless 测试，默认仍为 0（仅 guardian90）。DRM 超时会记录 `LGG8_DESKTOP_TIMEOUT`；headless 另保留已有 QEMU 超时标记。没有因 DRM 失败而转用 headless 的路径。

可选复位时长回传：同时设置 `lgg8.usb_beacon=1 lgg8.desktop_timeout=20 lgg8.ram_field=字段`，字段仅支持 `DRM|CON|FB0|SEATSOCK|WPROC|ST|UDC|CAL0|CAL15`，默认关闭。beacon 将完整产品快照写入 RAM `/run/usb-beacon-snapshot`，初始 `UDC=-1`；完成有界 UDC 枚举后，先原子替换文件中的 UDC 数量，再尝试 configfs。枚举出错保留 -1，不把部分结果当完整数量。可设置 `lgg8.usb_beacon_delay=12` 将采样从默认约 8 秒延后至约 12 秒，仍使用 3 秒工作进程 alarm。

PID1 约 16 秒只读取一次该快照：字段值 0..15 对应启动后 `20+2*值` 秒的主复位截止；读取/解析失败、负数或越界统一用码 16，即 52 秒。ST 的 1..8 保持原值，90..94 映射为 9..13，其余 ST 为未知码 16。CAL0/CAL15 固定为 20/50 秒，不依赖快照是否可用，供硬件校准使用，不能推测 USB 空窗基线。主截止比较包含纳秒部分；独立 guardian90 保持不变。数值只代表当次状态快照，不证明出帧。

v3 CPIO `5065ed41…d05b59` 已通过默认桌面和延迟 12 秒采样的真实 QEMU 测试。使用固定 96 MiB 容量及私有、SHA 固定的 boot 模板，C162–169 均完成完整 boot.img 打包、通用 verify 和 RAM-only 手机测试；候选镜像和私有 runner 保存在主实验仓的 `out/`，不提交本仓。C162/C163 校准的 USB 空窗差为 29.823 秒；C165–169 的回传分别显示 2 个 connected connector、fb0 存在、ST 阶段 8（终端已派生，靠近解码容差边缘）、1 个 UDC、以及 Weston 在约 12 秒采样时仍存活。C162 用户报告全屏花屏，所有轮次都未观察到 Linux `18d1:4ee7`；C164 DRM 样本超出编码范围。Android 均完整回收，两槽 boot 哈希不变。以上状态不代表正常显示、桌面交互或 gadget 已枚举；逐轮数据见 [设备状态](../docs/STATUS.md#c162c169ram-桌面阶段回传与真实设备状态)。

## 首次冻结交付（历史基准，不是新 beacon CPIO）

| 项目 | 结果 |
| --- | --- |
| 固定 Image SHA-256 | `3f2487cb0710d38fbb3856318ed32cc3529bd33478572104ffd34a545eea2bca`，未修改 |
| APK 签名/身份 | 74/74 通过；APK 总计 18236506 字节 |
| ELF 与运行数据 | 171 个 ELF、15 项关键 daemon/plugin/font/xkb/rule 文件通过 |
| 未压缩 CPIO | 50051584 字节，约 47.73 MiB，小于 64 MiB |
| CPIO SHA-256 | `e8593c38b5e2e24aeccf294b2530c8524c69b3bf3ba2d4d0145fdec414a6bb27` |
| QEMU | 最终同根测试通过，约 22.1 秒，退出码 0；包含实际 kmsg 镜像和完整同 surface 帧链 |
| boot.img | 29712384 字节，通用 bootpacker build/verify 通过 |
| boot.img SHA-256 | `e32f2299646bd15126ba01d44d1c77ab4689e5efe16ea53948e85e74b155ae55` |
| 原始载荷末端 | `0xaea17720`，通过全部 bank/保留区检查，低于 `0xb0000000` |
| 手机显示/触控/桌面 | **未通过**：C133 整体 RAM 实验在计划的 90 秒前回收，视觉结果待反馈 |

设备侧 C123–C130 约 31 秒复位的控制结果，不构成本桌面根的 DRM、终端或触控验收。
C133 首次实际 RAM 启动本节同一 `e32f2299…` 镜像，USB 空窗为 37.090 秒，
Android 完整返回，两槽 boot 哈希不变；pstore 为空，未观察到 Linux USB，
没有取得九十秒用户态时序或手机桌面证据。这是多组件整体集成验收，不能与先前
单变量控制混为同一因果实验。真实设备仍需分别确认 DRM connector/mode、scanout、
终端可见、输入和恢复路径；屏幕反馈尚待收集。

实际交付路径：

```text
out/lgg8/desktop/root/                      唯一 ARM 工作根
out/lgg8/desktop/initramfs.cpio             未压缩 newc，静态入口
out/lgg8/desktop/boot/{boot.img,manifest.json,linux.dtb}
out/lgg8/desktop/archive-verification.json  每个 APK 的签名结果
out/lgg8/desktop/file-origins.json          每文件来源、权限、链接和 SHA-256
out/lgg8/desktop/elf-audit.json             实际 ELF 闭包和关键数据检查
out/lgg8/desktop/qemu.log                   最终真实系统模拟原始日志
out/lgg8/desktop/qemu-report.json           对象 ID/帧链/printk 证据
out/lgg8/desktop/boot-verification.json     通用打包器验证结果
out/lgg8/desktop/provenance.json            源文件、输入和交付哈希
```

newc 内路径/符号链接不含 `..`，合法的相对链接已规范化为根内绝对链接；普通 hardlink 数据独立存储，nlink=1。仅在 CPIO 元数据中添加必要字符设备，不在主机创建或打开设备节点。整个 CPIO 在 boot 外层 gzip 解压后的原始 RAM 占用仍约 47.73 MiB，不能拿 boot.img 的压缩大小代替内存预算。

保留一个包缓存和小型 x86_64 验证工具树以便复现，没有重复 ARM 归档或逐包展开目录。初版日志解析的 `@/#` 错误已按既有日志复核修正；加入 kmsg 转发后做了最终实际 QEMU 测试，没有把旧 CPIO 的结果挪给新文件。日志里的缺省鼠标 cursor theme 提示尚未补齐；首轮不声称指针外观验收。现有包未提供可直接使用的截图客户端，本次不另建截图框架，也未生成 PNG。
