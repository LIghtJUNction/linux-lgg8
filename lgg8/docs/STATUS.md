# 当前状态与证据边界

更新：2026-10-30。本页分别记录源码、本地验证和手机功能的进展。

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
| 封装与本地测试 | **46 项通过，最终 verify 通过** | 使用本仓新 Image/DTB/CPIO，11,853,824 字节 boot.img，未上机 |
| 默认诊断 PID 1 | **QEMU virt 实际运行通过** | 同一内核进入 PID 1 并按期复位；非 PID 1 返回 91 保护也通过；不代表手机通过 |
| 原生 initramfs | **GNU cpio 解析通过** | 说明归档可解析，不证明真机能启动 |
| 本仓新内核真机启动 | **完整默认参数已运行** | C160 与 C162–169 使用 GPIO 保护、启用 TLMM、默认无 blacklist；每轮均回收 Android 且 A/B boot 哈希不变 |
| RAM 桌面用户态 | **QEMU headless 通过；手机终端已派生且 Weston 存活** | C167 阶段 8、C169 WPROC=1；用户报告全屏花屏，仍无可用桌面验收 |
| Linux USB 枚举和 shell | **未通过；检测到 1 个 UDC** | C168 回传的 UDC 数量为 1，但主机未见 Linux `18d1:4ee7`，尚不能用 ACM shell |
| 显示与触控 | **显示链已启动，画面错误；触控未验收** | C165/166 分别检测到 2 个 connected connector、fb0 存在；这些状态不证明正确 scanout |
| 桌面/Omarchy | **未通过** | 不能由源码编译或通用 QEMU 推导 |
| 当前 Android 与软件 fastboot 修复 | 历史真机通过 | 依赖当前已安装 Android 启动镜像；覆盖后不可假设保留 |
| 新主线 boot 持久刷入与恢复 | **未验证** | 目前仅给有前置条件的人工流程 |
| ABL 改写 | 本轮未请求 | 不作为当前恢复或适配步骤 |
| EDL 9008 恢复 | **未验证** | 不能作为必然可用的兜底 |

源码来源与文件指纹见 [PROVENANCE.md](PROVENANCE.md)；本地命令、制品哈希及检查结果见 [LOCAL-VALIDATION.md](LOCAL-VALIDATION.md)。当前源码已完成本机验证，后续真机结果需另行更新。

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

完整源码编译、46 项本地测试、QEMU PID 1 执行和最终 boot.img verify 已完成，具体指纹见 [LOCAL-VALIDATION.md](LOCAL-VALIDATION.md)。后续真机实验按 [BOOT-AND-RECOVERY.md](BOOT-AND-RECOVERY.md) 匹配手机、核对 b 槽和恢复条件，再做单次 RAM boot；未通过前不升级为持久刷入结论。

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

C172 回收后捕获到 70,388 字节 `console-ramoops-0`，归档传输与源哈希匹配；文本本身严重损坏。仍能辨认到 DSI repeated-TPG pre-enable 信息，以及 DPU frame-done/vblank timeout 的片段。前者说明 bridge/host enable 路径走到调度图案的位置，不等于确认周期工作项发出帧；后者也不能在损坏日志中确定时间因果。用户对 C172 屏幕是否出现棋盘格的观察尚待记录。显示修复和 DSI/DSC 根因都未验收。
