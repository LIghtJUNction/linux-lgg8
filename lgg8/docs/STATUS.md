# 当前状态与证据边界

更新：2026-10-31。本页分别记录源码、本地验证和手机功能的进展。

## 本仓源码基线

- 仓库：`linux-lgg8`，独立维护完整内核源码、LG 板级设备树与构建工具。
- 官方上游：`v7.3`，提交 `c03c1a14507dfaf8b856c2608f9ac216021fc222`。
- 板级输出目标：`sm8150-lg-alphalm.dtb`；完整配置：`lgg8/configs/lgg8.config`。
- 本轮内核改动包括板级 DTS（含 USB2 PHY 依赖修正、受保护 GPIO 区间和无客户端的 I2C7 禁用）、实验性面板/DSC，以及下文单列的 regulator 自动读回回退。未把旧诊断绕过作为修复移入。`sm8150.dtsi` SHA-256 为 `82887c779c9425ca23e49a81fe3ff8d8c7eec4d073edb305e6a9270371f3b7bc`，与旧实验输入对应文件精确一致。
- 默认内核走干净 init 路径，命令行无 initcall blacklist。没有 `late_initcall_limit`、强制 restart、BCM bypass、async/initmem bypass 或 DWC3 runtime-PM 旧补丁。

上游 `dwc3_gadget_pullup()` 的 `pm_runtime_get_sync()` 返回 0 表示成功恢复，连接交由 resume 回调处理；正值表示原本已活跃。旧说法“`if (!ret)` 就是 bug”没有成立证据，本仓不以该说法引入补丁。

旧记录的“QSCRATCH 二次偏移”也不适用于当前节点：`qcom,dwc3` 绑定
`dwc3-qcom-legacy.c`，直接映射 wrapper 的 `0x0a6f8800`。
加 `0xf8800` 的代码属于 `qcom,snps-dwc3` 的另一套布局，不能据此移动 legacy reg。

## 验收状态

| 项目 | 当前结论 | 范围 |
| --- | --- | --- |
| 官方基线与独立完整源码仓库 | 已建立 | 标签/提交明确，LG 代码独立维护 |
| 本仓源码内核编译 | **通过** | 完整 ARM64 Image 与板 DTB；版本 `7.3.0-lgg8` |
| 封装与本地测试 | **62 项通过，最终 verify 通过** | 当前回归覆盖打包来源收据与输入哈希拒绝路径；硬件验收仍独立 |
| 默认诊断 PID 1 | **QEMU virt 实际运行通过** | 同一内核进入 PID 1 并按期复位；非 PID 1 返回 91 保护也通过；不代表手机通过 |
| 原生 initramfs | **GNU cpio 解析通过** | 说明归档可解析，不证明真机能启动 |
| 本仓新内核真机启动 | **完整默认参数已运行** | C160 与 C162–169 使用 GPIO 保护、启用 TLMM、默认无 blacklist；每轮均回收 Android 且 A/B boot 哈希不变 |
| RAM 桌面用户态 | **C208-R3 用户观察到蓝底终端与极简桌面；同次 ACM 通过** | 显示＋ACM 里程碑 M1 通过；屏幕证据为用户观察，无录像 |
| Linux USB 枚举和 shell | **RAM-only 路径通过** | C206 空 client 与 C208 有效 log client 均通过 `18d1:4ee7` ACM shell；C207 的 log client 未编译，C203 默认 fbdev 未到达 ACM |
| SMB5 充电状态与 USB ADC | **C212 RAM-only 真机读取成功** | `present=1`、`online=1`；USB 输入 4.876 V，电流检测 ADC 64.489 mV（按 PM8150B buck 标定约 322 mA USB 输入）；不是电池充电电流，也未启用充电 |
| FG 原始温度字节 | **C221 RAM-only 真机读到 `0x1f`** | Android 同地址近期也为 `0x1f`；尚未验证 Linux 下持续更新或可用于温度保护 |
| 电池侧 ADC 遥测 | **C213 RAM-only 真机读回** | VBAT 4.421559 V；原厂 30k/100k/400k 电池热敏上拉电压均读回，按 1.875 V 参考换算阻值约 47–49 kΩ；仍未接温度保护或充电控制 |
| ramoops/pstore 真机证据 | **C192 首次导出 console-ramoops；内容损坏，pmsg 未确认** | 早期与回收后同一 32878 字节记录；C191 为空；C192 用户态标记及 DPU pmsg 仍未观察到 |
| 显示与触控 | **C210 RAM-only 真机：桌面触控有效（用户确认）；显示花屏状态另行追踪** | C210 X/Y 轴注册修复；自动回 Android，boot_a/boot_b 哈希不变；ACM 内核日志因主机 tty 权限未取到 |
| Weston RAM 桌面 | **同次显示＋ACM 通过** | C208-R3；见下方记录与独立审查文档 |
| Omarchy | **未通过** | Weston 极简桌面不等于 Omarchy；不能由源码编译或通用 QEMU 推导 |
| 当前 Android 与软件 fastboot 修复 | 历史真机通过 | 依赖当前已安装 Android 启动镜像；覆盖后不可假设保留 |
| 新主线 boot 持久刷入与恢复 | **未验证** | 目前仅给有前置条件的人工流程 |
| ABL 改写 | 本轮未请求 | 不作为当前恢复或适配步骤 |
| EDL 9008 恢复 | **未验证** | 不能作为必然可用的兜底 |

源码来源与文件指纹见 [PROVENANCE.md](PROVENANCE.md)；本地命令、制品哈希及检查结果见 [LOCAL-VALIDATION.md](LOCAL-VALIDATION.md)。当前源码已完成本机验证，后续真机结果需另行更新。

## C187–C190：pstore writer 诊断静态门已通过

四轮 RAM-only 测试均回收 Android；C187–C189 的 boot SHA 分别为
`8e0cabd2…`、`85ca12e0…`、`d892c3cc…`，C190 为
`d07408e631bb9570a3e787a9c2d2801f98668b359d232aff0953fc37cf050926`。
C190 的主机观测到 Android USB 返回约 148 秒后完成回收，总计约 159 秒；这是主机时钟，不是 Linux uptime。slot `_b`、boot_a/boot_b 哈希不变。启动前、早期及回收后 pstore 快照均为空；recovery `last_kmsg` 不是可归属的候选 Linux 日志，C190 没有屏幕观察、Linux USB gadget 或 shell 证据。

C190 实际 DTB 的 ramoops 区为 `0xb0000000–0xb0280000`，console 子区为 256 KiB。打包内核 SHA-256 `eccd43a30dd2559b7f1b4a27ceb2188ae77bbef541c618ffab2e7890a2b69db0` 与保留 ARM64 Image 完全相同；同目录 `vmlinux`/System.map 含 worker、ramoops probe/write 和 `pstore_write_console_and_seal()`。反汇编确认：容量字段在注册前由 ramoops console zone 初始化；backend `.write()` 返回 0 才 seal；可达失败路径释放锁并返回原始错误。**离线静态通过**，不证明真机执行过 worker 或写入成功，也不证明复位后 RAM 保持。

## C191：独立 ramoops pmsg 诊断路径已编译

针对 C190 暴露的证据盲区，诊断构建现在把驱动注册/探测与 KMS 状态写入独立 ramoops pmsg 区；只有 encoder 事件写入并 seal console 快照。pmsg 记录含事件名、启动时间、计数、尝试次数、上次 errno 和 CRC；helper 对后端未注册、区域容量不足及非 ramoops 后端显式返回错误。驱动注册及 KMS 工作项对后端尚未就绪做有限重试。诊断功能要求 `PSTORE_PMSG=y`，默认配置仍关闭。

2026-10-30 本地构建 C191 默认配置和 `diag-pstore` 配置均完整链接成功。默认 Image SHA-256 为 `9435665265c4157098f809005a5d757509344a4bfbdc1b6a088401ee3123daf2`，诊断 Image 为 `bde85639312b653e5f135adb2de84ac0f2e9497e9a7262336845115a5ea1029f`，两者 DTB SHA 均为 `88207ff2e9b28cca8d0b98dc4e5ca64552c7023930d51b207a5546ebe71d4ef2`。修复默认配置下一个未使用变量警告后，两种配置复编无警告；62 项本地测试通过，`git diff --check`、构建脚本语法和 bootimg CLI 检查通过。

C191 已打包并完成一次 RAM-only 真机实验，boot.img SHA-256 为 `16e24f7d2c8b9cf91284ec0f0487b6c9a62628cbb321184119090ae79bcb3047`。物理口 1-2 于 +15.828 秒断开，Android `1004:631f` 于 +145.965 秒返回，ADB 于 +146.311 秒上线；`fastboot boot` 返回 0。启动前后型号/设备/slot `_b` 和 `boot_completed=1` 一致，boot ID 轮转，boot_a=`a8266516…`、boot_b=`fec418e5…` 哈希保持不变；fastboot 实测 boot_b 容量 100663296 字节。pstore 启动前、早期回收及回收后清单均验证为空。

Android 4.14.348 配置含 `CONFIG_PSTORE_PMSG=y`，启动日志确认 ramoops 注册且映射 `0x280000@0xb0000000`，与本候选 DTB 的保留区相同。尽管如此，没有任何 C191 pmsg 记录，因此只能判定“内核诊断记录未被观察到”，不能判断 DPU worker 是否执行、pmsg 写接口是否被调用或 RAM 内容为何未导出。屏幕反馈仍待用户观察。设备命令和原始快照保存在 `out/lgg8-c191/run/`。

为区分用户态到 pmsg 区的可读性与 DPU worker 执行，C192 在同一诊断内核、同一桌面根上增加一个默认关闭的 `/dev/pmsg0` 一次性写入标记，仍只做 RAM-only 启动。若 Android 导出该唯一标记，可确认 pmsg 区通路；没有标记仍不能单独定位原因。

C192 已通过 RAM-only 真机启动。boot.img SHA-256 为 `f1f5f5019a5c88bfc52eca4be3f6b02d896ad06e2cac01e0d078f3c8860056d9`，使用干净提交 `037f27450bf973efa398acae70f8a0dac6c9e303` 构建，pmsg 探针桌面 CPIO SHA-256 为 `4e0770c33cfa8632c7adf54fcaced78b7692cb556f8280e72c276e0aaebdc66e`。fastboot 命令返回 0；物理口 1-2 于 +16.036 秒消失，Android USB +143.165 秒返回，ADB +143.446 秒上线。设备身份、slot `_b`、`boot_completed=1` 和 boot ID 轮转均通过，boot_a/boot_b 哈希不变，容量实测 100663296 字节。

C192 启动前 pstore 为空；早期及回收后均得到哈希相同的 `console-ramoops-0`（32878 字节，SHA-256 `f60337bb8efd32644191dd9c0e194511fa324616d6dc0b5a7941c48b3c5ca2b6`），快照范围和 tar 内容交叉校验通过。**新确认的里程碑是 ramoops console 内容能跨候选启动并由 Android 导出。** 该内容有大量乱码，不能作为可读诊断日志；没有 `pmsg-ramoops-0`，也没有找到用户态探针标记，因此 `/dev/pmsg0` 探针是否执行成功、DPU worker 是否运行仍未确认。C192 原始记录位于 `out/lgg8-c192/run-02/`。

## C108 / C109 留下了什么证据

目标手机是 LM-G820 / `alphalm_lao_com` / SM8150，历史系统报告 LM-G820UM，使用 slot b。新文档只使用序列号占位符，所有设备命令明确 `adb -s` 或 `fastboot -s`。

| 历史候选 | 观察 | 可以得出的结论 |
| --- | --- | --- |
| C108 | 花屏；USB 消失到 Android 返回仍约 52 秒 | 显示未通过；没有据此确认 fb0、完整 DRM 扫描输出或桌面 |
| C109 | 最小 PID 1 七秒复位对照未缩短约 52 秒 USB 空窗 | 预期时序信号未出现；不能证明七秒分支执行，也不能直接定位早期停点 |

上述实验后 Android 恢复、`boot_b` 保持不变，是 RAM 实验的回收证据；不代表主线新镜像已刷入。Android 运行正常与 Linux 功能未通过可以同时成立。新仓使用干净上游 init 路径，旧候选的绕过补丁、Image 偏移和时序不能直接套用。

此前 C105–107 的约 52 秒回收周期也未随着预期用户态分支缩短。C100 曾有七秒量级的时序差异，但它建立在旧 async/initmem 诊断绕过上，不得用它替代 C109 或本仓干净路径的验收。

## 损坏 pstore 与 RPMh 线索

C105–108 的损坏 pstore 尾部取证没有建立真实 panic。材料存在环形缓冲区旋转的可能，以及疑似位从 1 变 0 的损坏；日志重排或文本修复不是原始无损记录。

RPMh `VOLTAGE` / `ENABLE` 的 `-110` 在部分损坏片段中只能模糊辨认；C105 的 `ret=-110` 文本可精确辨认。即使该返回码真实存在，也只是一条错误线索，尚未建立它与用户可见现象、停点或复位之间的因果关系。**根因未确定。** 不能据此宣布 RPMh、面板或 DWC3 是唯一原因，也不能从缺失的 panic 尾部反推没有崩溃。

历史 root 二进制导出还发生过 LF→CRLF 转换，后续已纠正；相关 OEM wrapper、特殊 FDT 字节序等旧推断已撤回。新导出必须核对传输探针、完整长度及设备/主机哈希，不能再次把传输损坏当成 bootloader 格式特征。

## 默认用户态和下一步验收

默认原生 init 仅做诊断：在 RAM 临时文件系统及内核视图中工作，每约 5 秒记录 UDC、DRM 和 graphics 列表，约 45 秒请求复位，另设约 50 秒后备路径。不挂载手机持久分区，不配置 USB gadget，也没有默认 shell。可通过打包器的外部 cpio 输入构建其他经审查的用户态；外部输入的行为和验收必须单独说明。

自动复位依赖执行到相应代码与平台复位路径可用，不能保证早期挂起恢复，更不能替代独立下载/恢复入口。当前新内核的目标首先是建立可归属的启动证据，再分别验证 USB、显示、触控及用户态；没有现成桌面承诺。

完整源码编译、62 项本地测试、QEMU PID 1 执行和最终 boot.img verify 已完成，具体指纹见 [LOCAL-VALIDATION.md](LOCAL-VALIDATION.md)。后续真机实验按 [BOOT-AND-RECOVERY.md](BOOT-AND-RECOVERY.md) 匹配手机、核对 b 槽和恢复条件，再做单次 RAM boot；未通过前不升级为持久刷入结论。

## 历史实验的适用范围

C108/C109 与 pstore 取证来自旧集成实验，保留为排查参考；新源码、构建和候选需各自记录验证结果。旧通用 QEMU Linux/USB、CPU 模拟和 Android 软件 fastboot 补丁各有独立范围，均不构成 LG G8 主线桌面验收。

## C110–C114：缩小真机初始化停点

这些对照沿用旧实验 Image（SHA-256
`45f5d41e1dd14de1ac3400cef722162fe728afbf4de520a1e4e73f931350b988`），
不是本仓首版构建 Image。以下文件偏移只对该指纹有效，不可用于其他构建。

| 候选 | 变量／检查位置 | USB 空窗，秒 | boot.img SHA-256 |
| --- | --- | ---: | --- |
| C110 | XO 路由对照 | 150.747 | `bc16070e4fa27bc5e5d0e734fd4556112e099d7a10c78465d49b2a08dce68504` |
| C111 | 初始化末尾，异步等待之前 | 150.968 | `53415ec365536e59c2a12eadad83c52047440d5896343be15414639ca0374381` |
| C112 | kernel_init 主体入口 | 25.229 | `109682bd9473c7426e12f91390267ed5c66d20e47984df18152133e55f0b7043` |
| C113 | kernel_init_freeable 调用之前 | 25.025 | `5e004d58d768fbfc17d27f9ff1cf8d900b48ed57873978b497b7cb25312bd9a7` |
| C114 | do_basic_setup 返回之后 | 150.511 | `cfebe1dace297e145eca3864df3af4e4103ef1df8b5b95e7e2f6769d85d4bc06` |

C110 保留 C109 的七秒用户态复位程序，只把 GCC 与 USB2 PHY 的 XO 引用
改为原有 38.4 MHz 输入的二分频声明。它改变了回收时间，没有取得用户态执行证据。

C111–C114 各自从 C110 派生，只在不同位置放入相同的 72 字节不返回探针：
按架构计数器等待三秒，再调用 PSCI 复位。C112/C113 出现一致的短复位信号，
C111/C114 没有。这是检查点可达性的差分时序证据，支持把范围缩到
`kernel_init_freeable()` 内、`do_basic_setup()` 返回前，仍不能证明用户态 exec。
负向探针还须考虑探针自身或复位路径未执行等限制，不能只凭时序宣布具体驱动死锁。

全部实验只用 RAM 临时启动，Android 均完整返回，两槽 boot 哈希保持一致。
C114 读回 157,817 字节 console pstore：设备端前后 SHA 与主机 tar 成员 SHA 相同，
确认这次传输完整；内容本身仍有大量 NUL 和位损坏，没有把猜测修复的文本当作原始日志。

当前电源路径候选与上游新增的
[RPMh 状态读回变更](https://github.com/torvalds/linux/commit/09d99ff7fc3c802c9b31ded9ffdf992d966a0835)
有关：部分受损日志可辨认 VOLTAGE/ENABLE 读取超时，发送前等待 TCS 槽位的路径
没有有限超时。尚未证明是读回支持、IRQ、协议或其他条件造成；正在准备拒绝新增读取、
保留原有写入路径的单变量诊断，不把它发布为已验证修复。

## C115/C116：RPMh 读取对照与原生 PID 1 延迟证据

C115 从 C110 只改 `rpmh_read()` 入口 12 字节，立即返回人为注入的
`-EOPNOTSUPP`；不发送读取、不写返回数据，其他写 API、DTB 和 C109 用户态完全不变。
所有三处调用者检查错误，原有 DT 电压约束初始化写入策略仍可执行。
USB 空窗从 150.747 秒缩为 **29.428 秒**；没有把注入的错误码当作硬件报告。

C116 再只把两份相同原生 ELF 的正常 `sleep(7)` 参数改成 `sleep(17)`，
45 秒后备和完整内核不变。原 7 秒源码重建与原 ELF 逐字节一致；17 秒 ELF 各只改
同一条 MOV 参数指令，独立验证覆盖整个镜像和 CPIO。USB 空窗为 **39.838 秒**，
比 C115 增加 **10.410 秒**，与指定增加十秒吻合。
这是实际执行原生 PID 1 用户态延迟分支的强差分证据；尚无完整的设备端 PID 1
日志或 Linux USB 描述符读回。两轮 pstore 均为空。

两轮 Android 完整回收，两槽 boot 哈希不变。这确认了初始化阻塞与新增读取路径的关联，
没有确定底层是固件能力、协议、IRQ 还是其他原因；该诊断不是正式修复。
下一步验证 Linux gadget 枚举，再检查 DRM、framebuffer 和可见显示。
本仓首版干净内核与这些旧 Image 诊断仍分开验收。

- C115 boot.img SHA-256：`0e0e1d5c732299b9a7ff14190a78c46ed0d2d40461d5cf1f9b84fb5152f62327`
- C116 boot.img SHA-256：`acaeaf4130559ec4eacfe9619dbb46fdd8633ef8b03ffc76aa054ad69eadc30e`

## C118 与源码读回回退

C118 保留 C115 的内核和七秒用户态，只恢复完整 C109 DTB，撤去 C110 的 XO
分频旁路与两处引用改写。USB 空窗 **29.441 秒**，与 C115 只差 **0.013 秒**。
Android 完整回收，两槽 boot 哈希不变。这支持在当前拒绝读取的旧 Image 对照中，
原有 RPMh XO 路径同样可用；因此暂不把时钟旁路移入板级源码。

本树已撤回
[09d99ff7](https://github.com/torvalds/linux/commit/09d99ff7fc3c802c9b31ded9ffdf992d966a0835)
增加的 regulator 自动状态读回，恢复此前的缓存 getter/probe 策略。
公共 `rpmh_read()`、RSC 和写 API 保留；这不是 C115 的全局 API 错误注入。
缓存策略会影响后续 DT 约束投票，不能保证硬件写入序列完全相同。
这是供 LG G8 bring-up 验证的 feature revert，会影响该驱动支持的全部 PMIC，
不是已经定位的最小底层修复。

该源码增量编译和 46 项本地测试已通过，新 Image SHA-256：
`3f2487cb0710d38fbb3856318ed32cc3529bd33478572104ffd34a545eea2bca`。
C119 已对该 Image 执行独立真机控制，见下一节；新 DTB 和默认启动路径仍待验收。

## C117/C119：USB 仍缺证据，维护源码已走到用户态控制

C117 在旧 Image 上换入独立计时的原生 gadget 探针：等待 UDC 最多十秒，
尝试绑定 ACM，并计划通过 USB product 字符串报告 PID 1 与 UDC/DRM/FB 状态。
它按三十秒主计时回收，USB 空窗 **52.650 秒**，没有看到 Linux gadget 或描述符。
pstore 为空，尚无法区分 UDC 缺失、绑定失败和物理连接未建立。没有打开主机 ACM。

C119 只把 C115 的内核区替换为维护源码编译的 Image
`3f2487cb0710d38fbb3856318ed32cc3529bd33478572104ffd34a545eea2bca`，
旧 DTB、七秒原生用户态、shim 和 bootargs 全部保留。USB 空窗 **29.433 秒**，
与 C115 只差 0.005 秒；Android 完整回收，两槽 boot 哈希不变。
这是源码 feature revert 后内核实际走到原生用户态控制的阶段验收，
并非全套新 DTB、默认启动参数、正常 USB 或桌面已经通过。

C117 boot.img SHA-256：`1b363fcfc998cd5415fbd0a470ff8b2bc31f786ee7c9481d839ac7750f7f6f24`。
C119 boot.img SHA-256：`945926193872c32e173688e63b2f63960fca35d2895bf83a00be8afa3a5edf29`。

## C120–C126：延期探测开启后出现提前回收

源码审计发现旧 DTB 的 DWC3 同时引用启用的 USB2 PHY 和禁用的 USB3 PHY。
PHY provider 尚未注册时，直接 PHY 查找可返回 `-EPROBE_DEFER`，
`fw_devlink=permissive` 不会绕过该查找。本仓 USB2 板树已移除 USB3 引用，
限制 high-speed，并声明 wrapper 的 UTMI-as-PIPE 路径；这仍需真机枚举验证。

另一处独立限制来自旧命令行：它屏蔽 `deferred_probe_initcall`。
`drivers/base/dd.c` 仅在该 initcall 中开启重试开关并刷新延期工作，
所以此前进入用户态不代表延期设备已重试。下表所有空窗均从 fastboot 断开计至 Android USB 返回。

| 候选 | 单个功能变量 | USB 空窗，秒 | 结果 |
| --- | --- | ---: | --- |
| C120 | 让 mainline dmesg 区对齐 Android console reader 的 RAM 日志配置 | 52.662 | 无 Linux USB，pstore 为空；保留日志的假设未获支持 |
| C122 | 从 C120 改为仅引用 USB2 PHY 的配置 | 52.852 | 三十秒回收模式保持；仍无 Linux USB |
| C123 | 从 blacklist 移除 `deferred_probe_initcall` | 30.830 | 提前回收，不再符合三十秒用户态控制 |
| C124 | 在 C123 上换为本仓 Image `3f2487cb…` | 30.846 | 相同提前回收 |
| C125 | 在 C124 上换入 C116 完全相同的十七秒最小用户态 | 31.031 | 提前回收不依赖用户态 gadget 配置 |
| C126 | 在 C124 上只改 `panic=10` 为 `panic=120` | 30.834 | 没有增加预期的一百一十秒，普通 panic 等待未被证实 |

C121 仅离线组装，未做真机启动，不计为设备实验。
C120 与 C122–126 均未观察到 Linux USB，pstore 均为空，Android 完整回收，
两槽 boot 哈希不变。不能从空日志断言没有 panic，也不能把提前复位确定为某个驱动。
硬件复位、panic 被 watchdog 截断、显式重启等原因尚待区分。

下一步用同一个十七秒控制分别关闭 USB 和 MDSS 子树，以及恢复原 XO 引用，
定位开启延期重试后出现异常的依赖链。独立 Weston/pixman RAM 根文件系统已完成本地
headless 会话验证，见 [构建说明](../rootfs/README.md)；手机桌面仍未通过。

| 候选 | boot.img SHA-256 |
| --- | --- |
| C120 | `d1830d1d0a49406780180393605bda44323ccfad2f52431c0e38a374bdca7fa6` |
| C122 | `31dbc5dc8aca53f26ab3bc0916ff3dbfa169f0bc051c4bd4e3940ce5e4ce2056` |
| C123 | `82a9f89c4f9808a889dd43ccfbbf53e18e21f1aa86285ec1d137d46330830e32` |
| C124 | `097c34fd9587fdc11eae185bf40528f73f189379796814988f3625d9c2d854b2` |
| C125 | `9d9ee8636619c565aa01391ae1c9f23b2d039d10ff4a429639872d9746211631` |
| C126 | `ac21023cf86d2de3d54e0165a0381439eaadca50c67e9cde62ab04bf4eb7acfc` |

## C127–C132：首轮延期工作边界

C127–130 分别在同一个 C125 十七秒控制上改变一个条件。
仅关闭 USB、仅关闭 MDSS、恢复原 RPMh XO 引用，均没有恢复预期用户态时序。
这不排除多个独立故障，也不能把父节点禁用等同于禁用所有独立 PHY。

| 候选 | 变量 | USB 空窗，秒 |
| --- | --- | ---: |
| C127 | USB1 wrapper 父节点 disabled | 30.841 |
| C128 | MDSS 父节点 disabled | 30.847 |
| C129 | 两处 XO 引用恢复原值，保留未引用分频节点 | 30.666 |
| C130 | console-size 从 0 改为 256 KiB，日志区仍在 `0xb0000000` | 30.857 |
| C131 | `deferred_probe_initcall` 入口三秒终止检查点 | 25.627 |
| C132 | 首个 `flush_work` 返回后同类三秒终止检查点 | 31.062 |

C130 的内存分配变为无 dmesg 区、256 KiB 流式 console；源码确认零 dump count
合法，Android PRZ 头部 ABI 也一致，但实际 pstore 仍为空。后续不继续猜测日志地址。
DT 可用状态、reserved-memory 专门创建路径、配置及 initcall 顺序均未发现静态阻断；
这仍不能证明 `ramoops_probe()` 或 `pstore_register()` 在本轮运行成功。

C131/C132 仅各自替换固定 Image 的 72 字节终止检查点，CPIO、DTB、命令行和 shim
均与 C125 相同。C131 出现短复位信号，支持已到达延期探测入口；C132 未出现该信号，
支持下一步检查首轮延期工作及其 flush 等待期间。不能据此宣布具体 probe 崩溃，
也要保留检查点有效性和并行工作调度的限制。两处补丁均按实际 vmlinux、System.map
和 raw Image 对照；C132 额外保留运行时 LSE alternatives 会改写的位置。

六轮 Android 完整回收，两槽 boot 哈希保持不变，pstore 为空；均为 RAM 实验。
上述终止式二进制诊断没有进入本仓正常源码。

## C133：首次全套维护源码桌面镜像 RAM 实验

C133 使用已经离线校验和 QEMU 验证的完整桌面 boot.img
`e32f2299646bd15126ba01d44d1c77ab4689e5efe16ea53948e85e74b155ae55`：
本仓 Image、板 DTB、shim、无 blacklist 的默认参数和 90 秒后备复位的 Weston 根。
这是一轮整体集成验收，不是相对 C125 的单变量因果对照。

fastboot boot 接受镜像，USB 空窗 **37.090 秒**后 Android 完整返回，两槽 boot 哈希不变；
没有 Linux USB，pstore 为空。未出现预期的九十秒用户态时序，
没有取得手机桌面启动或正常显示证据，屏幕观察反馈尚待收集。
这轮结果不能把同一根在 QEMU headless 中的通过升级为手机 DRM 验收。

## C142–C159：延期设备身份与 GPIO 保护后的 PID 1 差分

维护源码 Image 仍为 `3f2487cb…a2bca`；身份时序诊断使用独立 Image
`3e652ca6…f047d`，不能混同。C142 关闭新身份诊断时，USB 空窗 **31.029 秒**，
仍提前复位。C143–146 的 1/3/5/7 秒校准通过；C147–151 的五段 FNV 时序
将 1098 条候选收敛到 `platform:3100000.pinctrl`。C152/C153 的完整 eq
两次均给出一秒匹配，C154 错名 `pinctrlx` 给出七秒拒绝。同诊断 Image 的
C155 未观察到 `after:2` 预期信号，空窗 **30.827 秒**。这些证据定位了设备身份
和延期重试调用边界，不是驱动内具体故障指令的证明。

仅关闭 TLMM 的 C156/C157，十七/七秒用户态空窗分别为 **39.847 / 39.245 秒**，
没有出现预期十秒差分，**不能算作 PID 1 执行通过**。

实际 Android runtime FDT 的 `/soc/pinctrl@03000000` 带有
`lge,access-denied-gpios = <92 93 94 95 98 99 100 101>`；主线原来的
`gpio-reserved-ranges` 只有 `<126 4>`。随后在维护源码 Image 上进行单变量对照：

| 候选 | 变量与条件 | USB 空窗，秒 |
| --- | --- | ---: |
| C158 | 从 C125 只把该 TLMM 属性改为 `<92 4>, <98 4>, <126 4>`，TLMM 保持启用；原冻结十七秒 CPIO | 40.238 |
| C159 | 从 C158 只换入原冻结七秒 CPIO | 30.028 |

两轮相差 **10.210 秒**，符合用户态延迟相差十秒，构成原生 PID 1 实际执行的
强差分证据。此时 `deferred_probe_initcall` 已启用，但仍屏蔽
`of_platform_sync_state_init,sync_state_resume_initcall`；**不能据此宣布默认无
blacklist 路径通过**。上述 RAM 实验的 Android 回收、安全检查和 `boot_a/boot_b`
哈希保持均通过，没有取得真实 Linux USB 或手机 GUI 验收。

本仓板级 DTS 已加入这八个 GPIO 的保护，并禁用没有子设备、却请求受保护 GPIO98/99 的 I2C7 控制器；DTB 重编与 46 项本地测试通过。便携式 GPIO 合同检查器及其 14 项正反例测试也已通过。
采用该更新的完整桌面镜像已完成离线核验，真实桌面测试尚未完成；仍需分别验收完整
启动参数、Linux USB、DRM 可见输出、触控及手机桌面，不能沿用 QEMU headless
或上述最小 PID 1 控制的结论。

C160 随后对修正后的完整维护源码桌面镜像执行 RAM 启动：默认参数没有
initcall blacklist，桌面 CPIO 与已通过 QEMU 的版本相同。镜像 SHA-256 为
`21e42adf58dce4401049ca3ab733ebb77def09dbaf360f5c789b860f3664e03f`。
USB 空窗为 **119.340 秒**，与九十秒用户态后备复位的时序吻合；Android
完整返回，两槽 boot 哈希未变。pstore 仍为空，屏幕反馈待收集，不能把该时序
直接称为正常手机桌面通过。此桌面根不配置 USB gadget，该轮未枚举 Linux USB
也不能据此判断 UDC 不存在。

## C162–C169：RAM 桌面阶段回传与真实设备状态

后续候选均为同一维护源码 Image `3f2487cb…a2bca`、同一 GPIO 保护 DTB、同一
v3 桌面 CPIO `5065ed41…d05b59`；唯一变化是 `lgg8.ram_field` 值。每轮均先核对
冻结清单、Android 型号/slot/boot 完成状态和两槽镜像哈希，再执行 RAM-only
`fastboot boot`。Android 均完整回收，`boot_a`、`boot_b` 均未变化；未写任何分区。

CAL0/CAL15 的 USB 断开至 Android 返回分别为 **49.898 秒**与 **79.721 秒**，
差 **29.823 秒**，符合预设的 30 秒校准差，故使用同一设备/CPIO 的 CAL0 作为
状态码差分基线。结果如下：

| 候选 | 回传字段 | USB 空窗 | 解码/观察 |
| --- | --- | ---: | --- |
| C162 | CAL0 | 49.898 s | 固定 20 秒主截止基线；用户观察为全屏花屏 |
| C163 | CAL15 | 79.721 s | 与 CAL0 相差 29.823 s；校准通过 |
| C164 | DRM | 160.507 s | 超出协议可解码范围；记为异常复位时序，不能推断 DRM 数值 |
| C165 | CON | 53.907 s | 相对基线 +4.009 s，解码为 2 个 connected connector |
| C166 | FB0 | 51.697 s | 相对基线 +1.799 s，解码为 fb0 节点存在 |
| C167 | ST | 65.361 s | 按差分及既定容差解码为阶段 8，即终端进程已派生；结果靠近容差边缘，宜复测 |
| C168 | UDC | 51.673 s | 相对基线 +1.775 s，解码为 1 个 UDC |
| C169 | WPROC | 51.887 s | 相对基线 +1.989 s，解码为 Weston 在约 12 秒快照时仍存活 |

主机在 C162–169 都没有观察到 Linux `18d1:4ee7`。因此 UDC 已注册，但 gadget
是否成功绑定/拉起 D+ 尚未确认。connector 数量、fb0、阶段 8、Weston 存活和屏幕花屏共同说明
显示栈已明显越过“没有设备/没有用户态”的阶段，**不等于正确画面、可交互桌面或
USB shell 已经可用**。C164 的异常时序和 C167 边缘容差均保留，不能从其结果过度外推。


## C170–C172：DSI 路由与面板测试图案诊断

C170 只把 Weston 目标输出固定为 DSI、关闭其他已连接输出；用户仍观察到全屏花屏。RAM-only 启动后 Android 于 135.449 秒首次回到 USB，完整恢复且两槽 boot 哈希未变。Android runtime 也显示 DSI-1 connected、DP-1 disconnected、Virtual-1 connected，因此“Weston 选错物理输出”没有得到支持。

C171 增加 `lgg8_dsi_tpg=1`，在面板初始化后请求 DSI host command-mode 测试图案一帧。用户仍报告全屏花屏。Android 于 175.922 秒回到 ADB，`boot_completed=1`，slot `_b`，两槽哈希不变。该轮没有可用的 Linux pstore 日志，不能确认测试图案工作项是否执行，也不能据此定位 DSI/DSC/面板故障。

C172 保持 C171 的 DTB、CPIO、bootargs 和其余启动输入，只把图案触发改为 DSI bridge 活跃时每 16 ms 重发，并在关闭 host 前同步取消。内核 SHA-256 为 `0beab1bc…b9ddb223`，boot.img SHA-256 为 `2a2df706…3f03d7ce`。RAM-only `fastboot boot` 被接受；USB 于 15.907 秒断开、178.907 秒恢复为 Android，ADB 于 179.390 秒上线。`boot_completed=1`、slot `_b`、boot ID 轮转，`boot_a` 与 `boot_b` 哈希均不变；没有分区写入或 ttyACM 输入。USB 状态变化中未出现 Linux gadget `18d1:4ee7`。

C172 回收后捕获到 70,388 字节 `console-ramoops-0`，归档传输与源哈希匹配；文本本身严重损坏。仍能辨认到 DSI repeated-TPG pre-enable 信息，以及 DPU frame-done/vblank timeout 的片段。前者说明 bridge/host enable 路径走到调度图案的位置，不等于确认周期工作项发出帧；后者也不能在损坏日志中确定时间因果。用户确认 C172 仍为全屏花屏，重复 TPG 没有带来可见改善。显示修复和 DSI/DSC 根因都未验收。

### 面板时钟与 PHY 时序实验

从 Android runtime device tree 只读取得 SW43410 MP DSC timing：1440×3120@60 Hz、水平 porch 168/4/88、垂直 porch 9/1/10，DSC 8 bpc/8 bpp、SCR 1、两片 720×60、每包两片；与主线面板模式和主要 DSC 参数一致。原厂 `qcom,mdss-dsi-panel-clockrate` 属性长度为 4 字节，值为 920,145,600 Hz。Qualcomm 解析器在 u64 读取溢出时回退读 u32；下游时钟代码随后用 `clk_rate / 8` 设置 byte clock（[解析器](https://android.googlesource.com/kernel/msm/%2B/ccc65019619064cafef389aeb100606292186753/drivers/video/fbdev/msm/mdss_dsi_panel.c)、[时钟设置](https://android.googlesource.com/kernel/msm/%2B/d92068af0333a7e8d93dd7102aadc5e0a0b7f853/drivers/video/msm/mdss/msm_mdss_io_8974.c)），因此 920,145,600 Hz 是原厂面板配置的 lane bit rate。按当前主线 DSI host 源码的压缩时钟算法（压缩活动宽度 480、水平总宽 740，再按 RGB888/4 lanes 换算），请求 bit clock 为 836,496,000 Hz，低约 9.1%。主线面板驱动现向 DSI host 提供原厂 lane rate，host 仅在该值非零时用其计算 byte clock；其余设备保持原算法。

同一原厂 MP timing 还给出 14 字节 PHY timing `001d070723220707050204001817`。Candidate 173 只改变 lane rate 为 920,145,600 Hz；用户后来澄清没有看到 Linux 阶段画面，因此显示结果未知。Android USB 于 136.291 秒返回，ADB 于 136.482 秒上线，总运行 146.783 秒，比 C172 快约 42.3 秒；Android 完整启动、slot `_b`，两槽 boot 哈希不变。pstore 为空，未提供 Linux 阶段日志。**lane rate 修正缩短了回收时间，但无法据此判断显示是否改善。**

源码对照进一步确认，SM8150 使用 `qcom,dsi-phy-7nm-8150`，主线 7 nm PHY 将 D-PHY 的 14 个值写入 timing control 0–13 寄存器；高通下游的 v4 PHY 接口也接受长度恰为 14 的面板 timing 数组并按顺序写入这 14 个寄存器（[下游 PHY 接口](https://android.googlesource.com/kernel/msm/%2B/51cfd1adbc3cdaab6c4cbfc32b675a5322f0bd57/drivers/gpu/drm/msm/dsi-staging/dsi_phy_hw_v4_0.c)、[主线 SM8150 PHY](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/gpu/drm/msm/dsi/phy/dsi_phy_7nm.c)）。这把原厂数组与主线寄存器顺序直接对应起来。

按 920,145,600 Hz 请求重算，主线当前寄存器数组为 `00 1f 08 09 24 22 08 08 05 02 04 00 1d 18`；原厂为 `00 1d 07 07 23 22 07 07 05 02 04 00 18 17`。两者差异集中在 HS/clock timing 和 clock pre/post；主线算法仍有“需与下游核对”的 TODO。

Candidate 174 保留 C173 全部输入，只增加原厂 14 项 PHY timing override。用户观察到全屏花屏；USB 于 176.799 秒返回 Android，ADB 于 177.227 秒上线，总运行 187.381 秒。`boot_completed=1`，slot `_b`，boot ID 轮转，两槽 boot 哈希不变；无分区写入或 ttyACM 输入。pstore 为空，Android recovery `last_kmsg` 损坏，无法从日志确认 override 是否执行；当前只能结论为该轮可见画面仍花屏。

随后对 Android MP profile 节点只读核对：`qcom,mdss-dsi-panel-type` 为 `dsi_cmd_mode`，且 `lge,update-pps-in-lp-mode` 布尔属性存在（0 字节）。Candidate 175 将该属性解释为初始 PPS 也应在 LP 发送，只改变 PPS 状态，其他输入沿用 C174；当时这只是待验证假设。后来核对到同一原厂 MP DTSI 明确设置 `qcom,mdss-dsi-pps-command-state = "dsi_hs_mode"`，因此初始 PPS 应按 HS 配置；该 LGE 布尔属性对其他更新路径的确切作用仍未确认。C175 镜像 SHA-256 为 `1018afcfdeb2d835f10342d810ce3d55a48b5bb104b655d97c3fa86ef2624ab5`，离线验证通过；RAM-only 真机启动被接受，USB 于 16.093 秒断开、136.405 秒返回 Android，ADB 于 136.784 秒上线。`boot_completed=1`、slot `_b`、boot ID 轮转，两槽哈希不变；没有分区写入或 ttyACM 输入。pstore 为空；C175 屏幕观察仍待用户确认，因此暂不判断 LP PPS 是否改善画面。

### 原厂 TE 路由核对与 Candidate 176

LineageOS LG 下游的整机 DTS 将 panel TE 接到 `TLMM GPIO8`，选择 panel TE source 0；对应 pinctrl 把 GPIO8 复用为 `mdp_vsync`、2 mA 并下拉（[整机 DSI 路由](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/lineage-22.2/arch/arm64/boot/dts/qcom/sm8150-sde-display-lge.dtsi)、[GPIO8 pinctrl](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/lineage-22.2/arch/arm64/boot/dts/lge/sm8150-alpha/sm8150-alpha_common/sm8150-alpha_common-pinctrl.dtsi)）。同一 SW43410 MP 面板配置启用 TE pin 检查，并明确将初始 PPS command state 配置为 HS（[原厂 MP panel profile](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/lineage-22.2/arch/arm64/boot/dts/lge/sm8150_common/settings_panel/dsi-panel-sw43410-mp-dsc-qhd-cmd.dtsi)）。原 `lge,update-pps-in-lp-mode` 属性的确切作用仍未从驱动实现确认，不能据属性名覆盖该 profile 的初始 PPS HS 设置。

主线 LG 板树原先没有给 DSI0 配置 GPIO8 的 `mdp_vsync` pinctrl；未显式填写 `qcom,te-source` 时，主线 DPU 选择默认 `mdp_vsync_p`。Candidate 176 基于 C174 的 HS PPS 行为，只新增原厂 GPIO8 TE pad 复用。内核与 DTB 编译、DTB pinctrl 引用检查、boot.img 离线 verify 均通过；镜像 SHA-256 为 `4bc8ab082cb6b14ee1088b2863d34c6a00cb7321463e22ef895326ffb18fe0b3`。它复用了 C175 的桌面 CPIO、命令行和 boot envelope，CPIO 哈希保持 `345d8001…e30b4e`。

真机 RAM-only `fastboot boot` 被接受；USB 于 +15.869 秒断开、+136.259 秒恢复为 Android，ADB +136.537 秒上线。用户观察到全屏花屏。`boot_completed=1`、slot `_b`、boot ID 轮转，`boot_a` 与 `boot_b` 哈希均与运行前一致；未写分区、未打开 ttyACM 或发送终端输入。pstore 文件为空。结论：**GPIO8→mdp_vsync 复用本身不足以修复花屏**；本轮没有验证 GPIO 上是否实际出现 TE 波形，也没有确定 DSI/DSC/DPU 根因。下一步应核对原厂 TE / DSI 命令及 scanout 状态证据，而不是把此结果写成面板已修复。完整运行记录见 `android-mainline-port/out/candidate-m3-dpu-te-gpio8-20261030-176/` 和相邻 `run-candidate-m3-dpu-te-gpio8-20261030-176-attempt1/`。

### Candidate 177：将初始 PPS 移到完整 on-command 序列之后

下游 `mdss_dsi_panel_on()` 先发送完整 `on_cmds`，随后单独发送 DSC PPS；后续 `mdss_dsi_post_panel_on()` 才发送 `post_panel_on_cmds`（[下游 on/PPS 顺序](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/lineage-22.2/drivers/video/fbdev/msm/mdss_dsi_panel.c#L1014-L1018)、[下游 post-on 顺序](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/lineage-22.2/drivers/video/fbdev/msm/mdss_dsi_panel.c#L1031-L1050)）。原主线驱动在 35 个 on 命令中的早期 compression-mode packet 位置就发送 PPS；Candidate 177 保持 compression-mode packet 原位，只把 HS PPS 移到整组 on 命令之后、9 个 post-on 命令之前。这是与下游调用顺序一致的单变量候选。

内核与 boot.img 构建、独立离线 verify 均通过。镜像 SHA-256 为 `8528ecea3318ca59d543e2143a1412770951ff82076f4fdf8a035dfe2fce12e8`；DTB、initramfs、bootargs 和 RAM boot envelope 均与 C176 哈希相同。RAM-only `fastboot boot` 被接受；USB 1-2 于 +15.841 秒断开、+136.043 秒恢复为 Android，ADB +136.356 秒上线。`boot_completed=1`、slot `_b`、boot ID 轮转，`boot_a` 与 `boot_b` 哈希均未变化；pstore 为空，没有分区写入或 ttyACM 输入。屏幕观察仍待用户确认，因此尚不能判断 PPS 时序是否改善可见画面。候选与完整运行材料见 `android-mainline-port/out/candidate-m3-panel-pps-after-on-commands-20261030-177/` 和相邻 `run-candidate-m3-panel-pps-after-on-commands-20261030-177-attempt1/`。

### Candidate 178：关闭 DSI 测试图案，直接观察桌面

C177 的启动参数仍启用 `lgg8_dsi_tpg=1`，驱动每 16 ms 重发测试图案，因而不能把显示结果归因到桌面合成器。Candidate 178 复用 C177 的内核、源 DTB、initramfs 和固定 boot 模板（各组件哈希相同），只改两个启动参数：关闭 TPG（`lgg8_dsi_tpg=0`），并把看门狗等待从 120 秒缩为 45 秒。boot.img 为 29,720,576 字节，SHA-256 `8f0fc9f981f06073e2d91c9f1dac9732660af9e02b8cda4b777b9605f2227888`；独立离线 verify 通过。

RAM-only `fastboot boot` 被接受。物理 USB 1-2 于 +15.858 秒断开，Android USB 于 +97.770 秒返回，ADB +98.152 秒上线；总运行 108.062 秒。`boot_completed=1`、slot `_b`、boot ID 轮转，`boot_a` 与 `boot_b` 哈希均未变化。用户报告屏幕“花屏5”（原始回复；覆盖范围未说明）。这证明关闭测试图案后屏幕仍花，测试图案不是唯一原因；不能算作 Weston 桌面可见验收。

本轮首次保存到 85,348 字节的 ramoops console，运行器校验了归档与源文件哈希一致。日志中可辨认出 DPU command-mode `failed wait_for_idle`（`ret=-110`）和多次 `frame done timeout`，末尾可见 watchdog 调用栈。原始日志有明显字符损坏，因此这些内容是 DPU/帧完成路径的诊断线索，不足以单独证明 TE、时钟、DSI 或 DPU 中哪一项是根因。等待参数确实缩短了 Linux 观察窗口，但从 USB 断开到 Android USB 返回仍约 98 秒。没有分区写入、ttyACM 打开或终端输入。候选和运行记录见 `android-mainline-port/out/candidate-m3-desktop-direct-20261030-178/` 与相邻 `run-candidate-m3-desktop-direct-20261030-178-attempt1/`。

### Candidate 179：初始 PPS 在 LP 模式发送

C178 的 PPS 在 HS 模式发送。Candidate 179 仅改变初始 128 字节 PPS 传输期间的临时 DSI mode flag：保存原 flags、仅为该消息设置 LPM，传输后恢复；ON → PPS → POST_ON 顺序不变，其余内核配置、DTB、initramfs、bootargs 与 C178 相同。内核对象编译及 ARM64 Image 链接通过，boot.img 离线核验通过。镜像 SHA-256 为 `9c78487c104c6b96f1960559f017e53b18dbee853dbeb7ab15effbb42aed2244`，内核 SHA-256 为 `654b97e3649eba16ab0f2bd12b447c9dc33b97c330cd7b196bb68bbd1ad5c833`。

源码核对确认临时 LPM flag 会被 MIPI DSI helper 转成 `MIPI_DSI_MSG_USE_LPM` 并传至 MSM host；这验证了软件选择的消息模式，不证明面板电气链路已接受 PPS。静态检查还确认最终 DTB 的活动 DSI/panel endpoint 双向连接、GPIO8 配置为 `mdp_vsync`，以及 PPS 的保存/恢复路径。运行时 DPU/PP/CTL 分配、PP_DONE 硬件状态、TE 波形和面板收到的实际数据仍未证实。

RAM-only `fastboot boot` 被接受。USB 1-2 于 +15.834 秒断开、+97.930 秒恢复 Android，ADB 于 +98.239 秒上线，总运行 108.431 秒；与 C178 时序基本相同。用户观察为“花屏5”（覆盖范围未说明），未取得可读画面，LP PPS 没有显示出可见修复。两次 pstore 快照均为空，因此本轮没有新增 PP_DONE 或 DPU timeout 运行证据。`boot_completed=1`、型号/设备/slot 保持 `LM-G820` / `alphalm_lao_com` / `_b`，`boot_a` 与 `boot_b` 哈希不变；无分区写入、ttyACM 打开或终端输入。完整候选及运行证据保存在相邻 `android-mainline-port/out/candidate-m3-desktop-direct-20261030-179/` 与 `run-candidate-m3-desktop-direct-20261030-179-attempt2/`。

### Candidate 180：持久 DPU/DSI 跟踪与 ramoops 读回

C179 的屏幕反馈后来被用户更正为“没来得及看/没看到，不确定”；早先的“花屏5”保留为先前回答，不能视作 C179 的可靠显示结论。

Candidate 180 启用 `FTRACE`、`FUNCTION_TRACER`、`DYNAMIC_FTRACE` 与 `PSTORE_FTRACE`，并只筛选 12 个已在最终 `System.map` 中核实存在的 DPU/DSI 函数。boot.img SHA-256 为 `0d0ceeff378e3adb61b5e284e52554d8423a42173806eabe9b73bb64dbb89c9f`；镜像 31,076,352 字节，离线校验通过，低于实测 100,663,296 字节 boot 容量。

RAM-only `fastboot boot` 被接受；USB 1-2 于 +16.230 秒断开、+100.135 秒以 Android `1004:631f` 返回。ADB +100.221 秒上线，`boot_completed=1`；设备身份和 slot `_b` 保持，boot ID 轮转，`boot_a`/`boot_b` SHA 均未变化，boot_b 仍为既有基线。无分区写入、ttyACM 打开或输入。当前没有可靠的 C180 屏幕观察。

复位后读回 85,284 字节 `console-ramoops-0`；设备端前后 SHA 与归档成员 SHA 均为 `1605297c84b342738dc110e2152cfde87c53702a342f3739e026689cde90064b`，确认字节传输稳定。日志字符有损坏，但可辨认多次 `frame done timeout` 与 `failed wait_for_idle`，支持 DPU command-mode 帧完成仍超时的诊断；它不能区分 TE、DPU 中断、DSI 传输或面板接受状态。

本次未出现 `ftrace-ramoops-*`。源码路径审计发现启动参数布尔值 `record_ftrace=true` 与“回调已注册”状态共用同一变量，初始化的 `pstore_set_ftrace_enabled(true)` 因相等判断提前返回，跳过注册。已在工作树把参数请求与回调状态分开；Candidate 180 不包含该修复，因此不能据它判断过滤函数没有执行。Candidate 181 将验证该修复及持久轨迹读回。C180 镜像、完整运行采集、pstore 原始归档和符号表保存在 `android-mainline-port/out/candidate-m3-desktop-ftrace-20261030-180/` 与 `out/run-candidate-m3-desktop-ftrace-20261030-180-attempt1/`。


### Candidate 181：验证 pstore 读取边界

Candidate 181 仅在 C180 跟踪内核中加入 `record_ftrace` 请求值与实际回调注册状态分离修复。RAM-only 启动被接受；USB 1-2 于 +16.233 秒断开、+100.121 秒以 Android `1004:631f` 返回，ADB +100.384 秒上线。`boot_completed=1`，身份、slot `_b` 与两槽 boot 哈希均核验通过，无分区写入。读回 85,388 字节 console，前后与归档哈希一致；仍没有 ftrace 文件。

只读检查确认返回 Android 使用 Linux `4.14.348-openela-perf+`；`/proc/config.gz` 有 `CONFIG_PSTORE_CONSOLE=y`、`CONFIG_PSTORE_RAM=y`，没有 `CONFIG_PSTORE_FTRACE`；设备未提供 `/dev/mem`。因此 Android 端的 pstore 导出器不能展示 Candidate 181 的 ftrace 区，文件缺失不构成回调修复失败的证据。C181 镜像与运行记录保存在 `android-mainline-port/out/candidate-m3-desktop-ftrace-20261030-181/` 与对应 `run-candidate-m3-desktop-ftrace-20261030-181-attempt1/`。

### Candidate 182：首次量化 TE/read-pointer 与 PP_DONE 中断

为绕过 Android 4.14 不支持 ftrace 区导出的限制，诊断配置下在 DPU command-mode 编入四个 IRQ 累计计数器；仅在第一次 PP_DONE 超时时向 ramoops console 输出 PP_DONE、TE/read-pointer、CTL_START 与 underrun 数量。普通配置不包含这些计数器。boot.img SHA-256 为 `646b9484fdd35a78098b51bbf1e968b369353d07a81483ec10fd6ee1f461dbf8`，大小 31,076,352 字节，离线验证通过。

RAM-only 启动被接受；USB 1-2 于 +16.231 秒断开、+100.116 秒返回 Android，ADB +100.394 秒上线。`boot_completed=1`、身份/slot `_b` 与 boot_a/boot_b 哈希核验通过，无分区写入。稳定读回 86,948 字节 console，SHA-256 `7c2fae52919ca2d1b242a230e48c841b0b0af6395a91c67a9aa8bc663ac4ba93`。字符有损坏，但首次超时约 +6.2 秒处的新增计数行可对齐为：`pp_done=0 te_rdptr=2 ctl_start=0 underrun=0`。这表示 DPU 的 TE/read-pointer 回调路径至少运行两次，同时没有观察到 PP_DONE、CTL_START 或 underrun 回调；它把问题缩小到命令模式 kickoff/CTL 启动与完成中断路径，尚不能说明为何这些中断没有到达。该行不是对外部 TE 电气波形或面板接收数据的直接测量。

C182 当前没有可靠屏幕观察。原始 console、哈希、候选与完整被动采集保存在 `android-mainline-port/out/candidate-m3-desktop-dpu-irqs-20261030-182/` 和 `out/run-candidate-m3-desktop-dpu-irqs-20261030-182-attempt1/`。

### Candidate 183：软件 kickoff 与 CTL 状态采集

C182 首超时计数显示 TE/read-pointer 回调出现两次，但 CTL_START/PP_DONE 为零。Candidate 183 继续在 `CONFIG_FTRACE` 诊断构建中记录软件 flush/start 调用数、pending-flush 位、CTL busy 与待处理计数，并沿用四类 IRQ 计数。boot.img SHA-256 为 `629fd2f889383ba7108dbe45f7a280e905c312a298be41f438ebc448a3207df0`，离线验证通过。

RAM-only 启动被接受；USB 1-2 于 +16.231 秒断开、+100.116 秒返回 Android，ADB +100.374 秒上线。`boot_completed=1`，两槽 boot 哈希未变。稳定读回 87,055 字节 console，SHA-256 `a6158ff6151043d1eda12f1ac5605f60009a52f145b8de4b27b8dc7a498d1150`。字符损坏严重，本轮无法可靠恢复新增软件调用数/CTL 状态字段；所以没有据此把故障归到 CTL 写入侧或硬件响应侧。原始记录、脱敏回收摘要和候选保存在 `android-mainline-port/out/candidate-m3-desktop-dpu-state-20261030-183/` 与 `out/run-candidate-m3-desktop-dpu-state-20261030-183-attempt1/`。

### Candidate 184：合并短日志的 kickoff/IRQ 诊断

Candidate 184 只把 C183 的两条诊断输出合并为一条 `DPU_DIAG`，缩短 pstore 行长；boot.img SHA-256 `95904f00c382bb92f5e2cc368c642786b59adbdb81bac2ba49b96922a073d6bc`，大小 31,076,352 字节，桌面 initramfs SHA-256 `345d8001e7cbba1a29ba71adb9de33fa4ae0f3b8cb1dd408b4fb226c59e30b4e`。离线 boot.img 校验通过。

RAM-only 测试于 +16.232 秒观察到 USB 1-2 断开，+104.120 秒返回 Android；`boot_completed=1`、设备 `LM-G820 / alphalm_lao_com`、slot `_b`、boot ID 轮转，boot_a/b 哈希均保持不变，boot_b 基线 `fec418e5…` 匹配。未写分区，未打开 ttyACM 或发送输入。Android 的 `console-ramoops-0` 在本轮前后相同，31,613 字节，SHA-256 `405025287678331468463de46b0eb50fe8a459660dd72c4208e0099786fa4230`；没有读到 `DPU_DIAG`，所以 C184 没有补上软件 kickoff/CTL 侧证据。屏幕观察缺失。候选及原始 pstore 证据位于 `android-mainline-port/out/candidate-m3-desktop-dpu-state-20261030-184/`，运行记录位于 `out/run-candidate-m3-desktop-dpu-state-20261030-184-attempt2/`。

### C194：ramoops writer 顺序对齐候选（2026-10-31，真机回收完成）

只读设备证据与固定参考源码交叉核验后，Android reader 的 ramoops 区域高置信布局为 `console (0xb0000000, 256 KiB) → ftrace (0xb0040000, 256 KiB) → pmsg (0xb0080000, 2 MiB)`。参考源码为 `LineageOS/android_kernel_lge_sm8150@f43e8f17061239356b05abc00a4dbbbf3b56eac8`，Makefile 标记 `4.14.348-openela`；它与设备型号/DT 属性吻合，但未证明就是手机精确构建提交。独立 `0xb02c0000–0xb02dffff` 的 128 KiB 区域匹配 LG bootloader-log 驱动地址公式，不属于 ramoops 子区；当前 `/soc/bootlog` 平台设备存在但没有 driver 绑定链接。

C194 只交换主线 `fs/pstore/ram.c` 中 pmsg 与 ftrace 的初始化顺序，使 writer 区域匹配该 reader；bootargs、initramfs、DTB、有效配置、模板与工具链均与 C193 相同。构建成功，boot.img SHA-256 `d67482f2a96638c1246f4639cdcd526afdd73e4884f51e22ea4d87c1e0d211d8`，30,818,304 字节；离线 manifest 校验 `PASSED`。RAM-only `fastboot boot` 返回 0，USB 1-2 于 +16.235 秒断开，Android `1004:631f` 于 +137.159 秒返回、ADB 于 +137.442 秒恢复；总计 148.280 秒。设备恢复 `LM-G820` / `alphalm_lao_com`、slot `_b`、`boot_completed=1`，boot ID 轮转；`boot_a` 与 `boot_b` SHA 前后相同。全程无分区写入。

C193/C194 DTB 只显式保留 2.5 MiB ramoops 窗口；Android 原 FDT 的 3 MiB 外层 reservation 多出的 512 KiB 未映射为相应保留节点。源码确认 C194 三个子区仍止于 `0xb0280000`，重排不会扩大访问范围；尾部差异作为继承限制记录，空 pstore 结果的排除能力会受其限制。

启动前、早期 Android 回连及后续 pstore 快照都通过完整性核验为空。C194 bootargs 未包含 `lgg8.pmsg_probe=1`，故没有执行用户态探针；本轮不能据此验证 pmsg writer/reader 布局，也没有新的 DPU 记录。pstore 区仍有 ramoops attach 保留区尾部 512 KiB 未在候选 DTB 显式保留的继承限制。屏幕反馈等待用户确认。

候选包与复核材料位于 `out/lgg8-c194-pstore-layout-20261031/`；本轮安全回收证据在 `run-01/`。首轮构建对象已清理，保留 boot.img、manifest、vmlinux、System.map、有效配置、源码差分及运行器。

### C195：用户态 pmsg 往返探针（2026-10-31，真机回收完成）

C195 复用 C194 完全相同的 kernel Image、initramfs 和源码差分，只在 bootargs 追加 `lgg8.pmsg_probe=1`。独立 DTS 语义比较显示，除 `/chosen/bootargs` 外 DTB 属性相同；kernel SHA-256 `2962224f1fda3031af28c01b05f3b0a9e15101cb266fccafb38ce5c6848463d`，initramfs SHA-256 `4e0770c33cfa8632c7adf54fcaced78b7692cb556f8280e72c276e0aaebdc66e`。

C195 boot.img SHA-256 `ce1d56eab8fbc0e5922838d0df859c4047d28520aac2efd44eaa6c9bbe915357`，大小 30,818,304 字节；离线独立校验通过。有效配置确认 DPU 诊断、pstore RAM、console、pmsg、FTRACE 均启用；`FUNCTION_TRACER` 未启用。RAM-only `fastboot boot` 返回 0；Fastboot 于 +0.001 秒出现、+16.230 秒断开，Android `1004:631f` 于 +178.587 秒返回、ADB 于 +178.946 秒恢复；全轮 187.966 秒。设备恢复 `LM-G820` / `alphalm_lao_com`、slot `_b`、`boot_completed=1`，boot ID 轮转，`boot_a` 与 `boot_b` SHA 前后相同；未写分区。

启动前、早期 Android 回连及稍后快照均经完整性核验为空，未发现 `LGG8_USER_PMSG_PROBE` 或 DPU 记录；Android `/data/misc/pstore` 路径也不存在。此结果不能区分用户态 pmsg 写入失败与 Android 导出/reader 路径问题。复用 CPIO 的 marker 内含旧字面标签 `candidate=C192`，不能把它当作 C195 身份；若出现记录，应以启动前空基线和已固定的 C195 镜像身份归因。屏幕观察未记录。证据：`out/lgg8-c195-pmsg-probe-20261031/run-01/`。

### C196：pmsg 探针启用、USB beacon 未启用（2026-10-31，真机安全回收）

C196 boot.img SHA-256 `527934b7c5e050d26567f72c40c3cfb63fe106c62ccfb639b98c7f49ff00844f`；RAM-only `fastboot boot` 返回 0。物理 USB 1-2 于 +16.238 秒断开，Android USB 于 +137.164 秒返回，ADB 于 +137.452 秒恢复。型号/设备、slot `_b`、`boot_completed=1`、boot ID 轮转及 boot_a/boot_b 不变全部核验通过；无分区写入。

启动前与回收后 pstore 均经完整校验为空，没有 pmsg marker。关键勘误：C196 的最终 manifest bootargs 含 `lgg8.pmsg_probe=1 lgg8.pmsg_tag=C196`，但缺少 `lgg8.usb_beacon=1`；`supervisor.c` 默认 `beacon=0`，只有显式传入该参数才会创建并绑定 configfs ACM gadget。因此 C196 没有尝试 gadget 创建或 UDC bind，未见 `18d1:4ee7` 是预期结果，不能据此判断 DWC3、D+ 或 gadget bind。该轮 pmsg 探针结果仍未知；没有创建或暴露 iSerial 回执。当前 ACM 路径也没有启动 `/dev/ttyGS0` shell。屏幕未观察。设备证据在 `out/lgg8-c196-pmsg-beacon-receipt-20261031/run-01/`。该轮只证明 RAM-only 集成启动与 Android 安全回收，没有推进 Linux USB 枚举或 pmsg 读回里程碑。

### C197：启用 USB beacon 后首次真机枚举成功（2026-10-31）

C197 仅在 C196 原完整 bootargs 末尾增加 `lgg8.usb_beacon=1`，复用同一 kernel、源 DTB、CPIO 和 boot 模板；boot.img SHA-256 `25e8c8df9e496fb3a947d5860baa58c1a468af0cfa36bdec731cfb3f9521d13a`，30,818,304 字节。离线 `bootimg.py verify` 通过。manifest 差异核验确认实际功能变化只有 beacon 参数；kernel、源 DTB、CPIO、模板、shim 源码及硬件地址/显示配置保持一致，封装 DTB、压缩载荷和镜像 hash 随 bootargs 变化。C197 manifest 使用现有 kernel-build receipt；C196 的 package-time provenance 没有 effective-config 指纹，二者 provenance 字段形态不同，但基础构建输入哈希相同。

RAM-only `fastboot boot` 返回 0。物理口 1-2 时序：+0.001s Fastboot `18d1:4ee0`，+16.234s 断开，+38.660s Linux Gadget `18d1:4ee7` 出现且 manufacturer/product/iSerial 可读；主机内核随后绑定 `cdc_acm` 并创建 `ttyACM0`。+119.465s 断开，+137.286s Android `1004:631f` 返回，ADB +137.590s 恢复；整轮 148.155s。iSerial 回执 `T=C196;O=OK;W=OK`（复用的 CPIO 标签仍为 C196，按本轮镜像 SHA、时序和空前置基线归属 C197），证明 PID1 的 `/dev/pmsg0` open 与完整 write 均成功。主机没有打开 ACM TTY 或发送数据，因此双向 ACM 通信和 shell 尚未验证；当前 CPIO 也没有 `/dev/ttyGS0` shell。

回收后 `LM-G820` / `alphalm_lao_com`、slot `_b`、`boot_completed=1` 核验通过，boot ID 轮转；`boot_a`、`boot_b` SHA 前后相同，无分区写入。启动前、早期 Android 回连、回收后 pstore 均通过完整目录/哈希校验且为空：pmsg write 成功已证实，但本轮 Android pstore 没读到该记录。屏幕观察未记录。运行器及证据：`out/lgg8-c197-usb-beacon-enabled-20261031/run-01/`。

此结果反证“DWC3 永远不会拉高 D+”这一强断言：在当前 USB2 peripheral 配置下，真机至少一次完成了物理连接和描述符枚举。它不定位先前候选为什么没有运行 beacon，也不证明枚举稳定或 shell 可用。

独立源码审阅还发现两个尚未修正的诊断/错误传播缺口：`dwc3_gadget_soft_connect()` 忽略 `__dwc3_gadget_start()` 返回值，`dwc3_resume_common()` 未传播 `dwc3_gadget_resume()` 返回值；以及 `phy-qcom-snps-femto-v2.c` 的 REFCLK `write_mask()` 调用把 `mask` 与 `value` 参数倒置。C197 在这些源码保持原样时仍成功枚举，因此它们不是本轮枚举的阻断条件；PHY 实际复位位值未知，后续应作为独立、可验证的维护项处理，不回填成 C196 根因，也不据此做寄存器写入。

### C198：真机 USB ACM shell 命令往返通过（2026-10-31）

C198 在 C197 基础上加入显式开关 `lgg8.usb_shell=1`：仅在 `lgg8.usb_beacon=1` 且 ACM UDC 绑定成功后，PID1 子进程才在 `/dev/ttyGS0` 启动交互式 root shell。默认关闭，独立 PID1 90 秒恢复 watchdog 保留。源码提交 `fd841233502f939bc21f80c2ca433d3d7afcc2e3` 已推送至 `origin/lgg8/mainline`。本机 `build.sh test` 62/62 通过；隔离 dummy_hcd ACM shell 往返通过；AArch64 QEMU headless Weston 同 surface frame 流程通过。boot.img SHA-256 `04857cdb56d247ad1da95cecc660095b271c3141cfd9f277ee4d4a9aaf21e02d`，CPIO SHA-256 `0e26a5bcd088b78f7f9a4fe4bbffab942c63a099ed6a8e729b920ae5149fd449`，离线 bootimg verify 通过。

真机使用 RAM-only `fastboot boot`，没有分区写入。物理口 1-2：+0.001 秒 Fastboot `18d1:4ee0`，+16.037 秒断开，+38.463 秒出现 Linux Gadget `18d1:4ee7`，iSerial 回执 `T=C198;O=OK;W=OK`；product 快照为 `DRM=1 CON=2 FB0=1 SEATSOCK=1 WPROC=1 ST=8`。+119.441 秒 gadget 断开，+137.263 秒 Android USB `1004:631f` 返回，ADB +137.553 秒上线。首次由普通权限 runner 打开 tty 被系统拒绝（`EACCES`，未发送命令）；随后先核实 tty 的 sysfs parent 正是物理端口 `1-2`、设备 ID `18d1:4ee7`，再用提权探针发送 `echo $((23*31))`，收到 `713`，证明 shell 实际执行命令并回传输出。原始权限失败记录保留在 run result，提权往返证据单独保存在 `out/lgg8-c198-usb-shell-20261031/run-02/physical-shell-roundtrip.json`。

Android 回收为 `LM-G820 / alphalm_lao_com`、slot `_b`、`boot_completed=1`，boot ID 轮转。`boot_a` 和 `boot_b` 前后哈希不变；启动前、早期回连和回收后 pstore 均核验为空。屏幕没有可用观察记录；`ST=8` 和 Weston 进程只说明桌面启动阶段到达终端派生，不能证明 scanout 或可读画面。因此 C198 新增的已验收里程碑是**真机 Linux USB Gadget 枚举并通过 ACM shell 执行/回传命令**；显示花屏、触控与 pstore 读回仍未解决。完整证据摘要见候选目录 `acceptance.json`。

#### C198-R4：ACM shell 只读显示链路采样（2026-10-31）

复用同一 C198 镜像（boot.img SHA-256 `04857cdb56d247ad1da95cecc660095b271c3141cfd9f277ee4d4a9aaf21e02d`、CPIO SHA-256 `0e26a5bcd088b78f7f9a4fe4bbffab942c63a099ed6a8e729b920ae5149fd449`），RAM-only `fastboot boot`，物理口 1-2 被动监视；没有分区写入。经核实的 Linux Gadget `18d1:4ee7`/`ttyACM0` root shell 接收并执行只读采集脚本，完整收到结束标记及退出码 0，回传 127,318 字节。debugfs 仅以只读方式挂载到 RAM 路径 `/run/lgg8-r4-debugfs`；没有读取会触发问题的 per-CRTC `status`/`state` 节点。

采样到 DSI-1 已连接、CRTC 0 active、模式 1440×3120；活动 plane 0 使用 XR24、pitch 5760、SSPP8，并分配 PP0/CTL0。两次 `core_irq` 快照中 PP_TX_DONE 计数均为 0，CTL_START 从 65 增至 74，TE/read-pointer 计数为 2，underrun 为 0。内核同时记录 `frame done timeout`；DPU 诊断快照为 `flush/start=10/10`、`pending=0x208c0`、`busy=0`、PP_DONE/TE/CTL_START/underrun=`0/2/10/0`。这把显示故障收窄到：DPU/CTL 已开始提交并收到 TE/read-pointer 活动，但没有 PP 帧完成；尚不能据此断定面板线上实际波形或画面内容。

同一启动还记录 SMMUv2 translation fault：`SID=0xc20`、`CB=10`、`IOVA=0x9e30a700`。启动日志确认 `ae00000.display-subsystem` 加入 IOMMU group 8；SM8150 MDSS 设备树使用 stream ID/mask `<0x800 0x420>`，主线 SMMU 匹配规则允许该 mask 覆盖 SID `0xc20`。因此这条 fault 已能归属显示子系统的 SMMU stream-match 范围，是 PP_DONE 缺失的强诊断线索；IOVA 是否对应本帧 framebuffer 的具体页表映射仍未确认，不能直接宣称根因已修复或已证明。

本轮安全回收通过：Android `boot_completed=1`、slot `_b`，boot ID 轮转；`boot_a`/`boot_b` SHA 与启动前一致，启动前及回收后 pstore 完整核验为空。真机屏幕没有可靠观察记录，可读显示里程碑仍未达成。原始 ACM 采样和运行结果保留在本机忽略目录 `out/lgg8-c198-usb-shell-20261031/run-04/`；后续应优先只读核对 fault IOVA 与活动 framebuffer DMA 映射，再决定是否需要单变量候选。

#### C198-R5：活动 framebuffer 与 SMMU fault IOVA 对照（2026-10-31）

继续复用同一 C198 boot.img（SHA-256 `04857cdb56d247ad1da95cecc660095b271c3141cfd9f277ee4d4a9aaf21e02d`）和 CPIO（SHA-256 `0e26a5bcd088b78f7f9a4fe4bbffab942c63a099ed6a8e729b920ae5149fd449`），RAM-only `fastboot boot`。root ACM collector 核实 tty 的 sysfs 父级为物理口 1-2、VID:PID `18d1:4ee7`，只读挂载 debugfs 到 `/run/lgg8-r5-debugfs`，读取 `framebuffer` 与 MSM DRM 的 `gem` 节点；命令结束标记、shell prompt 和 GEM/VMA 表头均收到。完整运行约 149.2 秒后 Android 恢复，`boot_completed=1`、slot `_b`、boot ID 轮转、两分区哈希不变；启动前与回收后 pstore 核验为空。未写分区。

`framebuffer` 中 `framebuffer[97]` 的 `start=00102249` 与 `gem` 表中同一对象的 DRM offset 相符。结合 R4 同镜像的 active CRTC state（plane 0 指向 fb97），该对象的 KMS VMA 为 `0x01126000`，大小 17,973,248 字节，范围 `[0x01126000, 0x0224a000)`。另一个 Weston dumb BO 的映射范围为 `[0x2000, 0x01126000)`，`tx_gem` 为 `[0x1000, 0x2000)`；R5 的 GEM 快照没有任何映射覆盖 `0x9e30a700`。因此 R4 的 SMMU fault SID `0xc20` 虽落在 MDSS stream-ID mask 范围内，但该 fault 地址不是 R5 采样时这些当前 KMS GEM BO 的 IOVA。

新的待验证线索：fault IOVA `0x9e30a700` 位于设备树预留的 splash 区间 `[0x9d200000, 0x9e400000)`；若把该物理区间起点当作缓冲区基址，fault 偏移 `0x110a700` 仍在一个 17,973,248 字节 framebuffer 范围内，距其末尾 `0x19900` 字节。R5 还列出 fbdev 的 `stolenfb` 对象，但该对象在当前 GEM VMA 列表中没有映射。现有证据没有证明 `stolenfb` 的物理 backing 就是 `splash_mem`，也没有证明故障发生时该对象仍在 scanout；“旧 splash/bootloader 地址被当作 IOVA”只是需要用早期 framebuffer IOVA 日志验证的假设，不能据此改映射或宣称根因已证实。

R5 的脱敏运行与 ACM 输出保存在本机忽略目录 `out/lgg8-c198-usb-shell-20261031/run-05/`。下一步应在单变量候选中仅启用 DRM atomic-state 调试日志（核实 `DRM_UT_STATE` 位后），捕获 fbdev/早期 framebuffer prepare 时的 `FB[id] iova`，并与 `0x9e30a700` 比对；不要读取 per-CRTC 易触发问题的 `status`/`state` 节点。屏幕仍未取得可靠观察，可读显示里程碑仍未完成。

#### C199：仅启用早期 DRM IOVA 日志，离线打包完成（2026-10-31）

使用与 C198 完全相同的 kernel Image、source DTB、initramfs 和私有启动模板，只将两项日志参数追加到 C198 原始 bootargs：`drm.debug=0x40 log_buf_len=4M`。C198 对应的精确 `.config` 为 `CONFIG_LOG_BUF_SHIFT=17`（默认 128 KiB）、`CONFIG_LOG_CPU_MAX_BUF_SHIFT=12`，未启用 `CONFIG_DYNAMIC_DEBUG`。`include/drm/drm_print.h` 将 `DRM_UT_STATE` 定义为类别索引 6，过滤条件是 `__drm_debug & BIT(category)`，所以 `0x40` 只启用 state 类；`drivers/gpu/drm/msm/msm_fb.c` 的 `msm_framebuffer_prepare()` 在第 90 行用 `drm_dbg_state()` 打印 `FB[id] iova`。`kernel/printk/printk.c` 的 `log_buf_len` early parameter 接受 `4M`，用于保留早期日志到 ACM shell 可用时。没有改内核、设备树源码、initramfs、显示时序或 MMIO。

离线构建产物为 `out/lgg8-c199-drm-state-20261031-1/boot/boot.img`，SHA-256 `03bb98ad7662809d0aa1fe733294b84ae6881e76811dab586eb41c13cc15f91c`，大小 30,818,304 字节。initramfs SHA-256 仍为 `0e26a5bcd088b78f7f9a4fe4bbffab942c63a099ed6a8e729b920ae5149fd449`，kernel SHA-256 仍为 `2962224f1fda3031af28c01b05f3b0a9e15101cb266fccafb38ce5c6848463d6`，source DTB SHA-256 仍为 `88207ff2e9b28cca8d0b98dc4e5ca64552c7023930d51b207a5546ebe71d4ef2`；derived DTB 因 bootargs 更新而变为 `0bdaf3e3d276f56ead6de981c9722bf3b01217329eb3c6517b6fd7ce38130965`。`lgg8/tools/bootimg.py verify` 返回 `PASSED`；镜像只在 RAM 启动，未写任何分区。

该候选沿用 `ignore_loglevel` 与 `console=tty0`，因此 state 调试日志也可能显示在屏幕上；C199 屏幕不能作为干净的显示验收结果。

#### C199-R5：同次启动关联 framebuffer IOVA 与 SMMU fault（2026-10-31）

C199 run-01 的 ACM 探针曾把“命令回显”误判为成功，随后 SIGTERM 中断；那次没有形成有效日志或完整 Android 回收证据，结果作废。run-02 加入严格的随机标记与结束码校验后，正确报出 shell 命令失败（退出码 127，提示符同步竞争），没有误报采集成功；设备仍在 148.8 秒后回到 Android，`boot_completed=1`、slot `_b`、boot ID 轮转，`boot_a`/`boot_b` 与已知基线哈希不变，启动前/早期/回收后 pstore 快照均核验为空。

run-03 使用完全相同的 boot.img（SHA-256 `03bb98ad7662809d0aa1fe733294b84ae6881e76811dab586eb41c13cc15f91c`），只修正 ACM 提示符握手，没有改内核、DTB、initramfs 或 bootargs。提示符握手、随机首尾标记及完整 dmesg 结束码均验证通过；root shell 实际读回 147,444 字节，`/proc/cmdline` 含 `drm.debug=0x40 log_buf_len=4M`，`/sys/module/drm/parameters/debug` 为 `64`。物理口 1-2 的时序为 Fastboot `18d1:4ee0` → 断开 → Linux Gadget `18d1:4ee7`（+39.274 秒）→ 断开（+120.284 秒）→ Android `1004:631f` 返回（+137.896 秒）；总计 148.5 秒完成 postflight。Android `boot_completed=1`、slot `_b`、boot ID 从 `062bc90b-6338-4efc-8d3e-442d78bf0ce3` 轮转至 `c22f9d7b-1a7b-4390-986a-3eb7429c9f89`；`boot_a` SHA `a826651669b4e9c8e2835e315082cedb821585a683fea9afede3f23517cfe4e6`、`boot_b` SHA `fec418e5227a31927af27daf71d2225246f5adcf8dda38b5856200760b5205cd` 均保持不变。三次 pstore 采集完整且为空，没有分区写入。

关键的同次启动时序：`FB[93]` 在 0.716822 秒映射到 IOVA `0x2000`；随后 SMMUv2 SID `0xc20`/CB10 在 0.732277 秒 fault 于 `0x9d2fbf00`，并在 0.749874、0.764460 秒 fault 于 `0x9d200c00`。三个 fault 地址都落在 DTB `splash_mem` 的预留区间 `[0x9d200000, 0x9e400000)`；而此启动中日志到达的 framebuffer IOVA 是 `FB[93/97]=0x2000`、`FB[98]=0x01126000`。DPU `frame done timeout` 从 0.902303 秒开始并持续出现。由此可确认这些 fault 与这次启动及显示子系统 stream 同时相关，并且不是日志中这几个 DRM framebuffer IOVA 的同一数值；地址落在 splash carveout 仍不足以证明是哪一个硬件请求者或哪个 buffer 引发 fault，也不足以宣称 splash 是已证实根因。可读显示仍未验收。

源码顺序审计得到一条更强的待证假设：MDP5 在 `mdp5_kms.c` 中会先关闭 interface timing engine，再调用 `msm_kms_init_vm()` 附加 IOMMU；DPU 的 `dpu_kms_hw_init()` 则在初始化初期调用 `_dpu_kms_mmu_init()`/`msm_kms_init_vm()`，当前路径未见等价的“先停 bootloader display DMA”步骤。它可能使固件遗留 scanout 在新 SMMU domain 下访问 splash 区域，但日志尚未证明这些 fault 一定由遗留 scanout 触发。下一步应先只读审查 DPU 可安全停止/复位的硬件路径，再决定是否做一个 RAM-only、单变量的先停显示再附加 IOMMU 实验；不直接改 splash 映射，不读取易触发问题的 per-CRTC `status`/`state`。

Pro Round 5 独立审阅已写入并从 Drive 读回；它也指出 `stolenfb` 名称不证明其 backing 来自 splash carveout，跨启动比较 IOVA 不能证明同一映射。run-01/02/03 的原始和结构化证据保存在本机忽略目录 `out/lgg8-c199-drm-state-20261031-1/`；候选镜像的屏幕可能显示调试日志，因此这些运行不算显示验收。

### C200–C205：像素时钟根因、正常画面与早期启动卡点（2026-10-31）

C200 因误用基础 `.config`，与 C199 的有效配置不一致，设备结果不用于单变量归因。之后从 C199 boot.img 的 `IKCFG_ST` 内核配置块恢复并核对精确配置，SHA-256 为 `ada1d054a4ae9004dc167a6b88ae5b62daa908098cb65e3b3c9a070e2e9f7b9b`。C201 在该配置下加入 DSI pixel-clock 失败日志，RAM-only 启动成功进入 ACM；日志显示请求像素时钟 `139416000 Hz` 的 `clk_round_rate()` 返回 `-22`，当时 parent 与 grandparent 均约 `153357593 Hz`，对应 `920145600 Hz` HS lane rate 的六分之一。

C202 唯一硬件参数变化是把 SW43410 HS lane rate 从 `920145600` 调到 `836496000 Hz`，使 lane-rate/6 与请求像素时钟对齐。用户在 Linux 阶段确认屏幕画面正常，这是本轮显示里程碑；但物理口 1-2 在 +16.264 秒断开后，直到 +174.462 秒才以 Android `1004:631f` 返回，未观察到 Linux ACM，因此不能声称 Linux 用户态或 USB gadget 已启动。C202 镜像 SHA-256 `00a62b8d1ba5a1277c132025870c3e2b45d97c6012db33804208ebfbcf0ec9d6`。

C203 保持 C202 内核和其余输入不变，只把 `watchdog.open_timeout` 从 120 秒改为 60 秒；没有 ACM，Android 于 +114.179 秒返回。C204 保持该面板速率和启动参数，添加 `CONFIG_DETECT_HUNG_TASK=y`、30 秒检测阈值及首个 hung task panic。它仍未枚举 ACM，Android 于 +114.162 秒返回，回收后的 pstore 经完整校验为空，没有取得卡死堆栈。C204 镜像 SHA-256 `5613717b44a2747fe4466dba32de4bb00839fcd7ea25150cd24e11cac04509b7`。C205 再启用 soft-lockup 检测及 panic；同样没有 ACM，Android 于 +113.966 秒返回，完整 pstore 仍为空。C202–C205 均为 RAM-only；Android `boot_completed=1`、slot `_b`、boot_a/boot_b 哈希保持基线，未写入分区。

Linux 的可见桌面与 ACM 已在 C208-R3 同次 RAM-only 启动通过；用户观察为蓝底、终端和极简桌面，未留录像。用户报告该 Linux 阶段触控没有响应。

启动时短暂花屏仍未定位。C208-R3 的已采集日志未见显示 SMMU fault 或 `frame done timeout`，不能把 C199 的旧 fault 直接归因于该现象。源码审查发现 SW43410 的 prepare 序列会发送 `0x29` 开启显示，panel enable 路径启用亮度，但这两处均未确认首个有效画面已完成；因此过早显示旧内容或不完整画面是待验证假设。C210 因 ACM 权限问题未取得同次内核日志。

下一次需要屏幕观察时，可以在相同内核、设备树和 rootfs 下，仅将 `drm_client_lib.active=log` 改成 `drm_client_lib.active=`，记录从启动到 Weston 首帧的完整画面和时间。C206 曾证明空 client 可到达 ACM，但缺少可靠画面观察，不是此对照的结果。若花屏仍在，再对齐面板亮屏、首次 DPU kickoff/frame-done 和 Weston 首次提交；不要把固定延时或将 `0x29` 移到 enable 当成已证明的首帧同步。

已用 C208 的原始输入打包空 client 对照镜像，保存在忽略目录 `out/lgg8-c208-empty-client-contrast-20261031/boot/`，SHA-256 为 `b9b535dfb4cf5225e227f6603679dabdbec6d14048eebcd2f8d824c40c374ac6`。打包器独立 verify 通过；比较了解码后的完整 DTB、bootargs、kernel、source DTB、initramfs、shim、stock DTBs、外部 ramdisk、构建来源与加载范围，仅 bootargs 的 `log` 被移除。此镜像尚未在设备启动，不能据此判断花屏是否消失。

C208-R3 回 Android 后的只读采集确认当前 Android 运行设备树声明 `lge,sw42000`，I²C client `4-0028` 的名称为 `sw42000` 并绑定 `lge_touch`，触摸中断线名为 `lge_touch`，输入设备列表中有 `touch_dev`；运行节点地址 `0x28`、IRQ 122、reset GPIO54、vdd GPIO152、vcl GPIO59、maker_id GPIO7、坐标最大值 1439×3119、reset delay 40 ms，均与公开 alpha_lao_com 下游树匹配。Android `/proc/config.gz` 含 `CONFIG_LGE_TOUCH_LGSIC_SW42000=y`。只读记录在忽略目录 `out/lgg8-c208-drm-log-enabled/run-03/` 下的 `android-readonly.txt`、`android-dt-details.txt`、`touch-runtime-node-readonly.txt`、`touch-runtime-pinctrl-readonly.txt`；本次没有触碰触摸 sysfs、I²C 总线或 GPIO。

新分支 `lgg8/sw42000-touch` 已加入精简 SW42000 主线 I²C/input 驱动、LG G8 设备树节点及绑定文档，并启用 `CONFIG_TOUCHSCREEN_LGE_SW42000=y`。完整配置内核与板级 DTB 已编译通过；离线 C 报文解析测试覆盖坐标/压力/宽度、多点、UP 释放、零计数拒绝、非法计数、重复 ID、非触摸报文与 palm 取消并通过。驱动版本检查要求芯片 ID 10 / 协议 4，只写正常 I²C 模式、扫描模式和中断控制；没有固件升级、工厂测试、手势或调试 sysfs。`dt_binding_check`、YAML lint 与针对 LG G8 编译 DTB 的 targeted `dt-validate` 均通过。C209 发现输入轴未注册；C210 修复轴并由用户在 RAM-only Linux 桌面确认触控有效，随后自动回 Android，boot_a/boot_b 哈希保持原值。ACM 串口权限导致本次内核日志未采集。候选镜像 SHA-256 为 `befe11656fe2e6941edda75beaf0935a7602c5823a3da06f0408d0819f22cef4`。suspend/resume、手势和睡眠恢复尚未实现。

同一 Android 只读采集显示 `battery`、`dc`、`main`、`pc_port`、`usb` 等 power_supply 设备归属 `qcom,qpnp-smb5`，`bms` 归属 `qcom,fg-gen4`，运行设备树还含 Qnovo 与 SMB1355 节点；配置含 `CONFIG_QPNP_SMB5=y`、`CONFIG_QPNP_FG_GEN4=y`、`CONFIG_SMB1355_SLAVE_CHARGER=y`、`CONFIG_QPNP_QNOVO5=y` 与 `CONFIG_LGE_PM=y`。这确认了当前 Android 软件栈使用的电源路径，但不等于本仓主线支持或本轮实测充电。`qcom,battery-data` 引用和选中 profile 尚未解析。主线当前的 `CHARGER_QCOM_SMB2` 不等同于 SMB5/FG GEN4；电量计可能写 PMIC SDAM/学习状态，因此不新增猜测的 charger/FG 节点，也不做试充。

### C208-R3：同次 Weston 桌面与 ACM 通过（2026-10-31）

复用 C208 原镜像 `3ead08159f1f99d7582ad21dd3af45b69bd05fe4e1ea8a9d99ab6d4b9c767176`，只执行 RAM-only `fastboot boot`。物理口 1-2 的 Fastboot `18d1:4ee0` 断开后，Linux Gadget `18d1:4ee7` 于 +37.077 秒出现并绑定 `ttyACM0`。随机首尾标记、dmesg snapshot 和结束码全部通过；回执共 519 行、39,716 字节。用户在同一 Linux 阶段观察到蓝色背景、终端和极简桌面，用户态状态含 `WPROC=1`。

Linux USB 于 +93.935 秒断开，Android ADB 于 +114.027 秒恢复；全轮 124.51 秒。设备仍为 `LM-G820` / `alphalm_lao_com`、slot `_b`、`boot_completed=1`；boot ID 轮转，boot_a/boot_b 哈希不变且 boot_b 仍匹配已知基线。启动前、早期回连和回收后 pstore 快照均通过完整清单与源哈希校验。未写入任何分区。触控无响应属用户观察，不是对屏幕硬件的电气故障诊断。

完整运行结果位于忽略目录 `out/lgg8-c208-drm-log-enabled/run-03/`；更详尽的证据边界见 [C208 阶段审查与 M1 验收](C208-NEXT-MILESTONE-REVIEW.md)。

### C206：禁用 DRM in-kernel client 后首次稳定到达 Linux ACM shell（2026-10-31）

以 C203 为基线，仅增加启动参数 `drm_client_lib.active=`（空值；保留等号），其余内核、有效配置、initramfs、源 DTB、shim 源码、stock DTBs、模板及用户态均保持一致。因 DTB/载荷长度变化而重新生成的 shim 二进制属于打包派生物。Candidate 206 镜像 SHA-256：`695c565fe801d0b5aab107707059c3721b71ed65f8c2e09c90e7fdcbd4ee47be`。

RAM-only `fastboot boot` 首次成功在物理 USB 1-2 枚举 Linux ACM `18d1:4ee7`；ACM shell 探针通过，读取 518 行、39,712 字节内核日志。日志中的 `/proc/cmdline` 确认空值参数生效；用户态快照报告 `DRM=1 CON=2 FB0=0 SEATSOCK=1 WPROC=1 ST=8`。这证明 Linux PID 1、USB gadget 绑定及 ACM shell 均已工作。相对 C203 的受控对比强烈指向 DRM client 启动路径为此前未到达 ACM 的关键影响因素，但尚不能区分具体 client 或宣称显示输出已修复。

手机自动回到 Android：`boot_completed=1`、slot `_b`、boot ID 轮转；`boot_a`、`boot_b` SHA-256 均与测试前一致，未写入任何分区。尝试记录与原始采样保存在本机忽略目录 `out/lgg8-c206-drm-client-bypass-20261031-1/`。屏幕本轮未作可靠观察；触控和充电仍未验收。

### C207：`active=log` 被当前配置忽略，仍然到达 ACM（2026-10-31）

以 C203 为基线仅增加 `drm_client_lib.active=log`，镜像 SHA-256 为 `ec71b695cc9b0053fb0f13bd11c2cf5e33a43d2c2c87cf9f1b493734e11a1a4f`。RAM-only 启动后物理口 1-2 枚举 `18d1:4ee7`，ACM shell 通过并读取 520 行、39,836 字节；Android 自动回收，`boot_completed=1`、slot `_b`、boot ID 轮转，boot_a/boot_b 哈希不变。

核查有效配置发现 `CONFIG_DRM_CLIENT_LOG` 未启用；本轮日志明确出现 `Unknown DRM client log`。因此 C207 没有启动 log client，而是与 C206 一样没有活动 DRM client。C206（空值）和 C207（未知 log）均到达 ACM；对照默认 `fbdev` 的 C203 未到达 ACM，支持 fbdev 分支为影响因素，但 C207 不是 log client 的有效对照，不能据此声称已排除其他 DRM client。原始记录保留在 `out/lgg8-c207-drm-log-client-20261031-1/`。

源码调用链已收敛到：`msm_drm_kms_post_init()` → `drm_client_setup()` → `drm_fbdev_client_setup()` → `drm_client_register()` 同步触发 fbdev hotplug → `drm_fb_helper_initial_config()`。这给出可插入阶段标记的位置，但具体阻塞函数仍未证实。

C208 修正了 C207 的无效对照：本次有效配置启用 `CONFIG_DRM_CLIENT_LOG=y`，保持默认 client 为 `fbdev`，仅用 `drm_client_lib.active=log` 选择 log client。RAM-only 启动镜像 SHA-256 为 `3ead08159f1f99d7582ad21dd3af45b69bd05fe4e1ea8a9d99ab6d4b9c767176`；kernel SHA-256 为 `2a9d1be7f2725cd2756a99a33248a9cd6beebbbcb40949abe3d8f358765c9dcc`。ACM shell 探针通过，读取 519 行、39,716 字节；启动参数含 `active=log`，没有 `Unknown DRM client log`，并记录到 DPU framebuffer 准备活动。Android 自动回收，`boot_completed=1`、slot `_b`、boot ID 轮转，boot_a/boot_b 哈希均与启动前一致。屏幕未获可靠观察，因此此结果证明有效 log-client 配置下 Linux/ACM 路径可用，不证明可见桌面正常。证据保存在 `out/lgg8-c208-drm-log-enabled/run-02/`。

当前有效 Linux 版本标识为 `7.3.0-lgg8+`。C208-R3 已通过用户观察和同次 ACM 验收蓝底桌面；C210 用户确认触控有效。C212 已读到 SMB5 状态和 PM8150B USB ADC；尚未实现 Linux 充电控制或快充。

### C224：电池存在与温控寄存器只读观测候选（尚未真机测试）

在 C223 使用的配置和构建目录上增量编译当前源码，生成 RAM-only 候选 `out/lgg8-c224-fg-presence-observe-20261031/boot/boot.img`，SHA-256 为 `c535c66a42eaf836c0267b4c29913962b23824e8a8df3b788c14aadee3b7f4cf`。`bootimg.py verify` 通过；与 C223 比较，源 DTB、initramfs、模板、stock DTBs、bootargs、装载约束及打包 gzip 时间戳一致；内核自身的构建标识和时间不同。内核更新包含 FG `PRESENT`、SMB5 软 JEITA 原始字节，以及 C223 之后其他已提交变更（包括 TCPM 恢复变更）；因此这不是单变量内核对照。vmlinux 包含对应 FG 回调和四个属性符号。

本候选尚未启动，不能证明状态读取、桌面、触控、Android 回收或硬件保护在此镜像上通过。`PRESENT` 仅报告电池缺失位；软阈值字节不是温度或停充证明。构建前 C223 的 Image 和 provenance 保存在候选目录内以保留比较基线；打包临时目录已移除。

此后源码增加了电池电压、电流读取前后的缺失位检查：支持 RRADC 的节点遇到缺失位返回 `-ENODEV`，状态读取失败则传递错误；原有两资源节点保持兼容。离线实际源码测试覆盖前后缺失、读取失败及旧节点，严格编译和 ASan/UBSan 均通过，ARM64 驱动对象也编译通过。检查不是原子快照，也不能证明采样新鲜度；C224 镜像构建于此修改之前，不包含该修改，未进行真机验证。

USB ACM 观测需要连接供电的 USB 线；不写充电控制寄存器不等于电池确定没有充电。C223 曾读到充电使能命令为 `0x01`、USB suspend 命令为 `0x00`，这也不足以推断实际电池电流。当前没有已验证的供电隔离或停充反馈，C224 保持未启动；未来若执行快照，不能称其为已证明停充的测试。现有 C223 runner 锁定旧镜像且监听和采集串行，不能直接用于本候选；还需独立监听、限定属性回执和采集失败后的完整 Android 回收验证。

C224 本地运行器草案的独立审查复现了两处误报：数值载荷被截短但标记和退出码完整时可能仍判成功；USB 监视在最后样本之后发生长时间空窗时可能仍判监控通过。草案正在修复，在重新验证之前不能用于真机；17 项早期离线测试通过并不能覆盖这两种反例。

另发现监视子进程冻结时，`multiprocessing.Event.set()` 本身可能阻塞，停止流程也必须有界。对与 C224 镜像内逐字节一致的 ARM64 BusyBox（SHA-256 `97d52efa149563c8d886e3670e2496d4140d3c54138017afd3a105e0397fae2e`），已用 QEMU 用户态分别执行 `wc -c`、`sha256sum`、`od -An -v -tx1`，空、文本、二进制三组输入均与 Python 核对一致，不存在的文件使 `sha256sum` 返回非零。此项只验证独立 applet，尚未验证完整生成脚本，也不证明真实设备上的监控、回收或停充。

后续对本地草案（runner SHA-256 `037cce02548772d0a977101f201822ab861480d4d0aabb63d9e893343b2db968`）用 QEMU 及该 BusyBox 跑通生成脚本的成功读取和文件不存在回执；仅改本机 BusyBox 包装器和暂存目录，未执行真机。另复现监视尾部反例：末次读取开始到停止为 1.8 秒，但以读取结束计尾部为 0.9 秒，草案仍返回采样通过。该草案仍不得用于真机；还需核对采样日志内容与不可读端口状态是否影响整体结果。

现有 gadget 的 `MaxPower=120` 是 USB 用电声明，不是已接入 SMB5 的硬件限流；普通 USB 端口的标称能力也不是实际电流的精确物理上限。DWC3 有软件 VBUS override，但这既不能证明断开 VBUS 后仍可正常传输，也不能证明电池不会充电。尚无经过验证的保留 USB 数据同时保证停充的接法；外部限流若经验证，限制的也是 USB 输入，不单独证明电池侧停充。

独立复审确认 FG、SMB5 和 TCPM 对象在本轮重编，Image 与 vmlinux 各节及内嵌配置一致。构建收据记录的是打包前现有产物和源码状态，不能证明整个构建期间每个旧对象的来源，未完成独立干净重建；本候选不宣称严格可复现。复审发现共享构建目录中的收据仍是 C223，已核对 Image、DTB 和配置哈希后更新为 C224 收据；原收据保存在上述基线目录。

### C211：PM8150B SMB5 只读状态首轮真机通过（2026-10-31）

C211 镜像 SHA-256 为 `1b94dbbbd338fb168cd5384c15d621d44aed6cf585136c061c6cdaa63933ebc5`，独立离线 verify 通过。只读 SMB5 驱动内建于内核；通用 PM8150B 节点默认关闭，alphalm 板级节点启用。预检在物理 USB 1-2 的 `18d1:4ee0` bootloader fastboot 中得到 `product=msmnile`、`unlocked=yes`、`current-slot=b`、boot_a/boot_b 均为 100663296 字节；此旧 bootloader 不支持 `is-userspace` 查询。RAM-only `fastboot boot` 后同一物理口枚举 Linux `18d1:4ee7` ACM shell。

归属于 C211 命令的 shell 回执确认 `/sys/class/power_supply/pm8150b-smb5-status/{present,online}` 分别为 `1`、`1`，证明 SMB5 USB 插入和 USB 输入路径状态寄存器在此机可读。没有读到输入/电池电压电流或 PD/QC 协议，也没有写任何充电寄存器。Android 随后自动恢复，型号/设备匹配、`boot_completed=1`、slot `_b`、boot ID 轮转；两槽 boot 哈希和 100663296 字节容量均与启动前一致。完整采集保存在忽略目录 `out/lgg8-c211-smb5-ro-20261031/run-01/`。本轮不证明正在给电池充电，更不证明达到原厂或最大充电速度；TCPM sink 设置错误处理仍未连接 SMB5 的硬件输入控制。

### C212：PM8150B USB 电压与电流感测 ADC RAM-only 读回（2026-10-31）

C212 仅在 PM8150B ADC 节点增加 LG 原厂设备树使用的 `ADC5_USB_IN_I` 与 `ADC5_USB_IN_V_16` 通道及相应分压系数。DTB-only 编译通过；boot SHA-256 为 `09637e7fea4b3c948b25afb4b5ca2c416e6a0730a4eba978d835153ce02f7a4e`，独立离线 verify 通过。运行仍是物理 USB 1-2 上的 RAM-only `fastboot boot`，未发出任何分区写入命令。

Linux ACM 实测读到 SMB5 `present=1`、`online=1`，USB 输入电压 `4875776 µV`，USB 输入电流检测端 `64489 µV`。LG 下游 SMB5 对 PM8150B buck 模式的换算系数是 `0.2 V/A`，对应约 `322445 µA` 的 USB 输入电流；该值不是电池侧电流。测试时主机端供电，Android 基线显示 USB 上限 500 mA、手机电池已满，因此它验证的是 ADC 和输入电流测量路径，不能作为充电速率或快充成功证据。主机 ACM 已保存完测量读数，但没有收到末尾结束标记，故该子探针标为部分采集；主机监视确认同一物理口回到 Android，`boot_completed=1`、slot `_b`、boot ID 轮转，boot_a/boot_b 哈希不变，pstore 前后均为空。证据在 `out/lgg8-c212-usb-adc-20261031/run-01/`。

C212 证明了 USB 输入模拟量可读。下一项仍需补齐电池侧电流/温度、充电状态、故障和终止保护，然后才有条件把输入限制与 Type-C/PD 协商接起来。不得把 322 mA 主机供电读数当成电池充电电流，也不得据此调高限流。

### C213：电池电压与三档热敏 ADC RAM-only 读回（2026-10-31）

C213 在主线 ADC5 中加入电池热敏 30 kΩ、100 kΩ、400 kΩ 上拉通道的电压测量映射，并在 alphalm 的 PM8150B ADC 节点加入这三路与 `VBAT_SNS`。三路分别读到 `1160553 µV`、`606682 µV`、`198399 µV`，VBAT 读到 `4421559 µV`。若假设 NTC 激励电压等于 ADC 的 1.875 V 参考、且电路为简单分压，按标称上拉阻值反算分别约 `48.73 kΩ`、`47.83 kΩ`、`47.33 kΩ`。实际激励、电路路径和标定尚待核实；三路数值接近并不能独立证明电压缩放或温度曲线正确。原厂 FG Gen4 把热敏系数写入 PMIC SRAM，本轮没有启动该驱动，也没有把推算阻值冒充温度或交给充电控制。

同次 ACM 还读到 SMB5 `present=1`、`online=1`、USB 输入 `4891344 µV` 和电流感测 `79801 µV`，按原厂 buck 标定约为 `399005 µA` USB 输入电流。测试接的是主机 USB，Android 返回后报告电池满电；该读数不代表电池充电电流、PD/QC 合约或快充速率。ACM 收到全部目标测量值，但结束标记缺失，因此记作部分采集。设备约 123.8 秒后自动回 Android，`boot_completed=1`、slot `_b`、boot ID 轮转、boot_a/boot_b 哈希未变；测试前 pstore 为空，恢复后捕获到 console ramoops，但尚未验证其内容是 C213 崩溃记录。镜像 SHA-256 为 `c7ef8a33234ff230b43b075a3ca36990ef6bd73fe422f7c9ad53c070ec7e0c2e`，离线 verify 通过；证据在 `out/lgg8-c213-battery-sense-20261031/`。

C213 将可核验的电池侧测量扩展到 VBAT 与 NTC，但 Linux 仍没有电池温度、充电电流/状态、故障处理或充电控制。达到原厂快充前还要复现原厂 NTC 映射并取得电池侧电流和故障遥测，然后才可评估 SMB5/TCPM 控制。

### C214：电量计直接寄存器读回（2026-10-31）

C214 启用 PM8150B 电池信息只读观测器，镜像 SHA-256 为 `060312bd06add06c0ad63f51f49b7ee0d4aa437876374e6439cdd8831bf98714`，离线镜像校验通过。物理 USB 1-2 上 RAM-only `fastboot boot` 后 Linux ACM 成功枚举，带完整结束标记的采集读到电池电压 `4419910 µV`、电池电流 `-976 µA`。驱动核对主值和副本后返回读数；读取成功尚不能证明采样持续更新、校准或电流方向正确，也不证明充电或快充功能。测试接主机 USB，电池此前已满。

Android 自动回收且 `boot_completed=1`、boot ID 轮转，boot_a/boot_b 哈希均不变；全程没有分区写入。前后均有 pstore 文件，未经独立归因，不以其作为本次崩溃或无崩溃证据。运行与原始采集在 `out/lgg8-c214-fg-observer-20261031/run-01/`。温度映射、故障保护、充电控制和 PD/QC 均尚未验收。

### C215：SMB5 原始状态首次读回（2026-10-31）

C215 在 SMB5 只读驱动中加入四个原始状态属性；内核构建和镜像离线 verify 通过，镜像 SHA-256 `09c7a67939f3494648a64622e573eacb528c8d258fd9c9f6c7298b161fdbb44f`。物理口 1-2 上 RAM-only 启动，Linux ACM 带结束标记读到 `charger_status=0x45`、`battery_status=0x28`、`temperature_status=0x00`、`batif_realtime_status=0x00`。状态是各自读取时刻的原始字节，不是原子快照或故障历史；零状态位不能证明保护已启用或动作有效。

Android 已回收，`boot_completed=1`、boot ID 轮转、boot_a/boot_b 哈希均不变，没有分区写入。测试前 pstore 有文件，恢复后为空，不能据此归因本次复位。原始采集与完整运行记录在 `out/lgg8-c215-smb5-status-20261031/run-01/`。下一步仍需只读核对实际限值、保护配置与电池温度，并验证充电保护动作。

### C216：SMB5 配置字节只读采集（2026-10-31）

RAM-only 启动的 C216 镜像 SHA-256 为 `95da10e346cb2095992975675bc7453c835e6e53f9e83a273d8594ec4ee4700f`，独立离线 verify 和 ACM 完整采集通过。读取 `fcc=0x34`、`fv=0x53`、`usb_icl=0x1e`、`jeita=0x00`、`watchdog=0x00`、`watchdog_timeout=0x0c`、`thermal_source=0x00`。按照原厂 PM8150B 参数表，前三个原始配置对应 FCC 2.6 A、FV 4.43 V、USB ICL 1.5 A；这是寄存器配置，不是实际电流或协商合同，也不代表允许使用这些值。

JEITA、watchdog 和热源配置字节为零，需要结合硬件修订、继承状态及其他保护机制进一步核对；本次只读不能证明各保护可用，不能据此启动主动充电。Android 自动回收，`boot_completed=1`、boot ID 轮转、两槽 boot 哈希不变，前后 pstore 均为空；没有分区写入。证据在 `out/lgg8-c216-smb5-config-20261031/run-01/`。

对照下游寄存器位定义，C216 的 JEITA `0x00` 包括 hard-limit 位及四个软补偿位均为零；watchdog `0x00` 包括插入时使能及 bark 中断使能位均为零。`watchdog_timeout=0x0c` 的 bite-disable-charging 位同样为零。这些是单次配置位读回，不足以推断 PMIC 的全部自主保护或其他固件机制。下游 SMB5 初始化只主动清 JEITA 的四个软补偿位，硬限制位必须单独评估。已加入安全计时器 enable 和 duration 的只读属性，尚未在真机读取。

### C217：充电安全计时器配置读回（2026-10-31）

RAM-only C217 的镜像 SHA-256 为 `11b02ebf21698a671630bd6fd3d9dd51b46a5a24cc0d874d8923a46be3ccc112`，离线 verify 与 ACM 完整采集通过。安全计时器使能字节为 `0x03`，按 LG 下游定义预充与快充计时器位均为 1；时长编码 `0x01` 在下游定义中对应 384 分钟。这仅证明读取时寄存器配置，未验证计时器运行或到期后的实际动作，不能抵消 C216 发现的其他保护配置未知问题。

Android 自动回收，`boot_completed=1`、boot ID 轮转、boot_a/boot_b 哈希均不变，没有分区写入；前置 pstore 为空，后置有文件，尚未验证其内容与复位的关系。证据位于 `out/lgg8-c217-safety-timer-20261031/run-01/`。

### C218：终止与重充配置只读采集（2026-10-31）

RAM-only C218 镜像 SHA-256 `ac8e59778d9cb3120af08b5b67fe0734ef6b1f1051b5f498e12738fbe0606092`；离线 verify 通过，Linux ACM 完整读回 11 个配置字节：重充模式 `0x2c`，终止上阈值 `0xfe88`，下阈值 `0x00a3`，重充采样 `0x0b`，终止采样 `0x0a`，重充 SOC `0xf2`，重充电压 `0x544a`，终止来源配置 `0x04`。字节为分别读取，不保证原子性；尚未验证阈值换算、重充或终止动作，不得据此开启充电控制。

Android 自动回收，`boot_completed=1`、boot ID 轮转、boot_a/boot_b 哈希均不变，没有分区写入。前后均有 pstore 文件，未将其归因本次复位。证据在 `out/lgg8-c218-termination-20261031/run-01/`。

C218 离线解码：原厂 `RECHG_MASK=0x06` 与 VBAT 选择位 `0x04`，故 `recharge_mode_config=0x2c` 的模式位为 VBAT。原厂 PM8150B 终止阈值编码使用有符号大端 16 位、量程 10000 mA、除数 32767；按该编码反算，`0xfe88` 为约 −114.75 mA，`0x00a3` 为约 +49.75 mA。`0x544a` 按原厂 VBAT-to-raw 公式反算约 4199.88 mV。`term_samples_config=0x0a` 的 bit0 为 0，按源码定义选择同步转换；`term_source_config=0x04` 的模拟终止选择 bit3 为 0。这些是独立读取的配置位及公式反算，并非实测电流、阈值校准或终止/重充动作的证明。参考固定版本 [SMB5 初始化](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-smb5.c#L2737) 和 [编码常量](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/smb5-lib.h#L104)。

C218 同镜像第二次 RAM-only 启动进行了 10 组约 1 秒间隔的电量计观测：电压 `4398426–4439197 µV`，电流 `−166992–80566 µA`，结束标记完整。数值发生变化，但电压与电流分别读取，无法证明同时性、校准或电流符号正确。回 Android 后 `dumpsys battery` 当时报告电压 4238 mV、温度 36.2°C、满电；与 Linux 期间电压存在约 160–201 mV 的差距，采样时间不同，不能直接判定原因或将 Linux 数据用于充电控制，需追查 FG 状态、数据新鲜度与同步对照。Android 回收成功、boot ID 轮转、两槽 boot 哈希不变；前后 pstore 均有文件，未作复位原因归因。证据在 `out/lgg8-c218-fg-series-20261031/run-01/`。

### C219：燃料计状态和电流符号的只读采集（2026-10-31）

C219 镜像 SHA-256 `54593097d8ff5251be312fbea5b6dd8184d0f6791f5e4afe019c69374baa744d`，独立镜像核验通过，物理口 1-2 经 RAM-only fastboot 启动并枚举 Linux ACM。带结束标记的单次读取：FG 温度状态 `0x00`、电池存在状态 `0x00`、电压 `4422351 µV`、新接口电流 `+488 µA`、USB 输入暂停命令 `0x00`。原厂头文件命名的温度可用位此刻未置位；状态位对本机的实际语义、温度新鲜度与保护仍未验证。电流接近零且无独立方向参照，不能验收符号或精度；USB 命令值也不能证明实际输入电流或停充。

Android 自动回收，`boot_completed=1`，slot `_b`，boot ID 轮转，boot_a 和 boot_b 的前后 SHA-256 均不变。pstore 前后均有文件，未作复位原因归因。测试未执行充电控制或分区写入，PMIC 的既有硬件充电状态不能由此推断。原始记录在 `out/lgg8-c219-fg-status-20261031/run-01/`。

回收后的 Android 启动日志中，`fg_gen4_probe` 打印温度 `345`（34.5°C）、电压 `4423816 µV`、电池 ID `91682 Ω`。固定版本下游源码在该日志前直接调用 `fg_gen4_get_battery_temp()`，这是 Android 启动时的底层 FG 温度，而不是后续 LG 补偿值；实际运行内核与该源码尚未做二进制匹配。随后只读 `bms/temp` 和 `battery/temp` 为 `358`（35.8°C），采样时刻不同，不可作为校准差值。此记录也不能证明 Linux 阶段该温度有效或可用位的 Gen4 语义。参考 [原厂 probe 日志路径](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-fg-gen4.c#L6390)。

同一 Android 启动中，使用原厂 FG debugfs 接口读取 SRAM word 328 两字节，返回 `8b 00`；按下游 Gen4 有符号 10 位公式得到 `347`（34.7°C）。紧接着 `bms/temp` 与 `battery/temp` 均为 `351`（35.1°C），两次采样并非原子操作。debugfs 地址与长度原为 `0x00000000`、`0`，读取后已恢复并复核；该读取通过原厂驱动申请并释放 DMA 仲裁，涉及 PMIC 访问控制寄存器操作，不写温度 SRAM。它验证 Android 下的受控读取路径和一个室温附近样本，但不能证明 Linux DMA 初始化、样本新鲜度、全温区精度或充电保护。

后续同一 Android 启动内再读 5 次，间隔约 1 秒；5 次 SRAM 均为 `8b 00`，相邻读取的两个 Android 属性均为 `351`。前后 debugfs 地址和计数恢复为 `0x00000000`、`0`，系统仍为 `boot_completed=1`。稳定结果支持重复读取的一致性，但不能证明原始温度持续更新，亦不能据此将 0.4°C 差距解释为固定补偿。采样记录：`out/lgg8-c219-fg-status-20261031/android-sram-temperature-series.txt`。

同一 Android 启动的 regmap 定点只读核对：设备树将 `spmi0-02` 关联至 `pm8150b@2`；`0x0105=0x20` 与 `0x0103=0x02` 分别对应 PM8150B subtype 和下游 V2 rev4，`0x4105=0x11` 为 battery-info subtype。`0x4106=0x00`、`0x4107=0x00` 与 C219 Linux 读数一致；因此即使 Android 原厂驱动此前读到合理温度，头文件命名的 bit 0 仍为零，不能将该位当作本机温度有效性的已验证判据。Android 瞬时配置 `0x41ee=0xac`、`0x4340=0x02`、`0x4350=0x00`、`0x4370=0x00`、`0x4371=0x02`、`0x4310=0x00`；这些是逐项读数而非原子快照，也不证明 Linux 接管后的寄存器状态。debugfs 地址/计数复原，原始结果保存在 `out/lgg8-c219-fg-status-20261031/android-fg-registers-reference.txt`。

设备自然冷却后的 Android 配对样本（Unix 时间 `1793436459`）：FG SRAM word 328 在 ADC 采样前后均为 `81 00`，按下游换算为 `322`（32.2°C）；期间三档 BAT_THERM 电压依次为 `1163473`、`607720`、`201124 µV`，Android BMS 与 battery 均为 `330`（33.0°C）。若沿用未验证的 1.875 V 激励和简单分压假设，三路反算约 `49.06`、`47.95`、`48.06 kΩ`。这些读取并非原子采样，ADC 转换会触发原厂驱动配置写；FG SRAM 读取使用原厂 DMA 仲裁，不写温度数据。debugfs 地址和长度已恢复，Android 正常。单组数据不能建立温度曲线、验证激励电压或授权充电。

### C220：Linux 内 FG DMA 控制状态对照（2026-10-31）

只读观测器增加独立 memory-interface 设备树资源及寄存器属性；C220 镜像 SHA-256 `d62fa81210058a8b532b42db8a2978c7155f4174d120647587bb9696258c4691`，独立核验通过，物理 1-2 RAM-only 启动并完成带结束标记的 ACM 采集。Linux 逐项读取 `0x41ee=0x00`、`0x4310=0x00`、`0x4340=0x04`、`0x4350=0x00`、`0x4370=0x00`、`0x4371=0x02`。与此前 Android 样本相比，DMA 地址模式值均为 `0x02`，访问请求字段及 DMA 错误状态均为零；PEEK 配置为 `0x00` 对 `0xac`，仲裁配置为 `0x04` 对 `0x02`。这是不同时刻、不同启动的非原子快照，不能证明底层算法或数据新鲜度，也不证明可以安全操作 DMA。Linux 电压 `4421375 µV`、电流 `−133300 µA`，方向仍无同步独立校验。

Android 自动回收，`boot_completed=1`、slot `_b`、boot ID 轮转，boot_a 和 boot_b 前后哈希一致。测试没有发起 DMA 请求、充电控制或分区写入；测试前 pstore 含文件、回收后为空，未据此归因重启原因。原始回执：`out/lgg8-c220-fg-dma-status-20261031/run-01/`。

随后在同一 Android 启动、主机 USB 连接且电池显示满电时，使用原厂 regmap debugfs 逐项读取 SMB5 配置：FCC `0x14`、FV `0x53`、USB ICL `0x0a`、JEITA `0x00`、安全计时器 `0x03/0x02`、watchdog `0x42/0x7b`、热源配置 `0x80`；原始文件为 `out/lgg8-c220-fg-dma-status-20261031/android-smb5-config-reference.txt`。按下游量化公式，FCC 配置约 1.0 A，USB ICL 配置约 0.5 A，均非实际测得电流。相较不同启动、不同时间的 C216 Linux 样本，Android watchdog 配置 `0x42` 与 Linux `0x00` 不同；前者按头文件命名设置 bark 中断和插入时启用位，热源配置 `0x80` 对 Linux 的 `0x00` 也不同。这些是非同步单次配置快照，不能证明看门狗实际运行、故障停充或整机保护有效，也不能直接归因于系统切换。debugfs 地址和计数在读取后恢复；没有向充电器配置寄存器写入。

固定版本 LG 下游 `smb5_init_hw()` 明确将 watchdog 配置中的 bark 中断和插入时启用位置 1、AFP 触发位置 0，与 Android 观测到的 `0x42` 相关位一致；其温控初始化在未选择三种硬件温控时选择软件 ICL 调节位，与 `0x80` 一种可能来源一致。这是源码和配置值之间的对应，未验证此机运行二进制完全一致、各分支实际执行情况或这些机制的故障动作；不能据此推导 Linux 样本为何不同。参考 [watchdog 初始化](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-smb5.c#L3144) 和 [热源初始化](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-smb5.c#L2828)。

上述 C214–C218 电流均为当时镜像输出，沿用 LG BMS 原始符号。后续源码已按 Linux 电池 `current_now` 接口反转符号，新源码通过对象编译，但尚未在真机验证方向；不能把历史数值误认为新源码的输出。

C218 电压差异跟进：同一 Android 启动后稍晚只读 `dumpsys battery` 首次为 4438 mV，随后 15:52:48–15:52:53（UTC+8）连续五次均为 4427 mV，温度 36.0°C。此前恢复后紧接着的 4238 mV 与后续 Android 数值本身也不一致，不能简单归因于 Linux 换算。原厂 `fg_get_battery_voltage()` 的字节序和 `raw × 122070 / 1000` 换算与当前观测器一致；真正原因以及重启期间采样更新/缓存状态仍未确定。Android 与 Linux 不同时采样，数值接近不能作为校准验收。

进一步在同一供电条件的 Android 中使用 root 只读五组 BMS 与 battery 单项属性（15:53:44–15:53:49 UTC+8）：两处电压均为 4438953–4439441 µV；BMS 电流为 −141113 至 −150878 µA，而 battery 属性为对应相反数。Android 原厂下游 `battery/VOLTAGE_NOW` 转发 BMS，`battery/CURRENT_NOW` 转发后取反；这一运行结果与源码一致，也与此前 Linux 观测器稳态读数接近。Android 与 Linux 采样不同时，且电源/负载可能变化；这支持路径与符号对应关系，但不构成独立校准、同步对照或充电保护验收。原始五次结果保存在 `out/lgg8-c218-fg-series-20261031/android-current-voltage-followup.json`。

Android 温度参考：15:54:41–15:54:46（UTC+8）连续五组只读 BMS 与 battery 温度均为 354（35.4°C），BMS `resistance_id=91695` Ω，BMS 电压与电流仍有波动。原厂 LG `POWER_SUPPLY_PROP_TEMP` 可能返回补偿值或 fake 值，采样未独立确认 fake 状态和补偿参数；该基线不是 FG 原始温度，也无法确定全温区映射或保护阈值。`resistance_id` 接近 Tocad profile 的标称 91 kΩ，但不足以证明 profile 选择及 fallback 情况。原始记录保存在 `out/lgg8-c218-fg-series-20261031/android-temperature-followup.json`。

Android 当前只读 profile 跟进：BMS 报告 `battery_type=LGE_BLT41_Tocad_3500mAh`、`resistance_id=91695` Ω、`debug_battery=0` 和 `voltage_max_design=4430000` µV；当前内核日志多次记录找到该 91 kΩ profile，并报告原有 profile 相同、未重载。本次筛选未见默认 profile 的日志，但不能据日志缺失证明未发生 fallback，亦不能独立证明实体电芯身份。`debug_battery=0` 不证明 LG fake temperature 被关闭；温度依然只能作为可能经过补偿的参考。证据在 `out/lgg8-c218-fg-series-20261031/android-profile-evidence.txt` 和 `android-profile-attributes.txt`。

Android 原始温度路径检查：当前 BMS 节点及 `qpnp_fg_gen4` 模块参数中没有发现明确命名的原始电池温度只读属性；现有内核日志的温控相关行仅显示保护模块初始化和状态变化，未找到当前 raw temp。原厂代码说明 BMS 温度可能为 FG 温度加 LG 插值与电流补偿，并可能使用 fake 值。未读取 SRAM 或更改调试参数，现有数据仍不足以反推出完整 NTC 温度曲线；日志筛选证据在 `out/lgg8-c218-fg-series-20261031/android-battemp-log.txt`。
