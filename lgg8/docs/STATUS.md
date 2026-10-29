# 当前状态与证据边界

更新：2026-10-29。本页分别记录源码、本地验证和手机功能的进展。

## 本仓源码基线

- 仓库：`linux-lgg8`，独立维护完整内核源码、LG 板级设备树与构建工具。
- 官方上游：`v7.3`，提交 `c03c1a14507dfaf8b856c2608f9ac216021fc222`。
- 板级输出目标：`sm8150-lg-alphalm.dtb`；完整配置：`lgg8/configs/lgg8.config`。
- 本轮内核改动范围为板级 DTS（含 USB2 PHY 依赖修正）与实验性面板/DSC，未把旧诊断绕过作为修复移入。`sm8150.dtsi` SHA-256 为 `82887c779c9425ca23e49a81fe3ff8d8c7eec4d073edb305e6a9270371f3b7bc`，与旧实验输入对应文件精确一致。
- 默认内核走干净 init 路径，命令行无 initcall blacklist。没有 `late_initcall_limit`、强制 restart、BCM bypass、async/initmem bypass 或 DWC3 runtime-PM 旧补丁。

上游 `dwc3_gadget_pullup()` 的 `pm_runtime_get_sync()` 返回 0 表示成功恢复，连接交由 resume 回调处理；正值表示原本已活跃。旧说法“`if (!ret)` 就是 bug”没有成立证据，本仓不以该说法引入补丁。

## 验收状态

| 项目 | 当前结论 | 范围 |
| --- | --- | --- |
| 官方基线与独立完整源码仓库 | 已建立 | 标签/提交明确，LG 代码独立维护 |
| 本仓源码内核编译 | **通过** | 完整 ARM64 Image 与板 DTB；版本 `7.3.0-lgg8` |
| 封装与本地测试 | **46 项通过，最终 verify 通过** | 使用本仓新 Image/DTB/CPIO，11,853,824 字节 boot.img，未上机 |
| 默认诊断 PID 1 | **QEMU virt 实际运行通过** | 同一内核进入 PID 1 并按期复位；非 PID 1 返回 91 保护也通过；不代表手机通过 |
| 原生 initramfs | **GNU cpio 解析通过** | 说明归档可解析，不证明真机能启动 |
| 本仓新内核真机启动 | **阶段通过** | C119 新 Image + 旧 DTB 的七秒用户态控制；新 DTB 与默认无 blacklist 路径仍待验收 |
| Linux USB 枚举和 shell | **未通过** | 默认 init 也不配置 gadget 或提供 shell |
| 正常显示与触控 | **未通过** | 面板/DSC 原型及花屏不是可用显示证明 |
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
