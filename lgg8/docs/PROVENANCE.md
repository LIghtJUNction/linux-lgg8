# 源码来源与维护边界

本项目基于官方 Linux **v7.3**，上游提交
`c03c1a14507dfaf8b856c2608f9ac216021fc222`。
上游地址为 `https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git`。
本地 `upstream` remote 用于跟踪官方历史；`lgg8/mainline` 保存设备改动。

LG G8 文件来自已有的 `android-mainline-port` 本地实验工作区。
该工作区原有完整内核目录没有 Git 元数据，因此本项目重新从官方提交建立历史，
只迁入明确的板级、面板和打包代码。板树保留 Rostislav Lastochkin 的署名及
BSD-3-Clause 许可，驱动遵循文件头的 GPL-2.0-only，启动 shim 使用 MIT。
完整 Linux 许可见根目录 `COPYING` 和 `LICENSES/`。

## 迁入时的源码指纹

| 文件 | SHA-256 |
| --- | --- |
| `arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dts` | `7143663d8aebd90ffc078cd270622e014ab43820fa034fac3733fc3a60a8bbf7` |
| `drivers/gpu/drm/panel/panel-lg-sw43410.c` | `1aed567d888dcda7ec30e960968b63bfb25fd8cca601f96c4879451f435da203` |
| `drivers/gpu/drm/panel/panel-lg-sw43410-cmds.h` | `08fa4b54c4e9fa5ad6dc8de21be8f43a25f5f8932ad4e7c94463b0053844153e` |
| `lgg8/boot/shim-mmu-off.S` | `fc159aab0a67037b96979618d1062aae56a991f2a1e5064b81b41a682bbf1ec4` |

面板命令头保存的是寄存器命令序列，源自这台 Alpha_lao 的运行时设备树。
每组命令的数量与数据哈希写在头文件中。整个 OEM DTB 包、原厂 boot、分区备份、
手机序列号和 pstore 原始记录均不作为 Git 项目内容；打包需要用户自己提供
经过 RAM 启动验证的兼容模板，保存在已忽略的 `private/` 下。

主线 `sm8150.dtsi` 与旧实验输入的 SHA-256 相同：
`82887c779c9425ca23e49a81fe3ff8d8c7eec4d073edb305e6a9270371f3b7bc`。
这使板树依赖可以追溯，并不证明硬件能正常工作。

## 当前补丁范围

- LG G8 板树及对应 Makefile、绑定声明。USB1 明确采用 USB2 模式，
  去掉对禁用 USB3 combo PHY 的消费者引用，并设置 UTMI 作为 PIPE 时钟。
- SW43410 面板驱动、命令数据和针对 8 bpc / 8 bpp 的 DSC 1.1 SCR1 参数。
  面板复位的 10/2/10 ms 等待使用 usleep_range，避免短 msleep 被时钟节拍放大。
  SCR1 之外的现有面板仍走原有参数路径。这项显示实现尚未取得真机正常画面。
- 固定构建配置、ARM64 MMU 关闭交接 shim、诊断 initramfs、boot v0 打包与离线验证。
- 为 LG G8 bring-up 撤回上游 09d99ff7 引入的 regulator 自动状态读回，
  恢复原缓存策略。只涉及 `qcom-rpmh-regulator.c`；公共 RPMh 读写 API 和 RSC
  实现不变。该回退影响驱动的全部 PMIC，底层原因和正式窄修复仍待验证；
  不是把旧 Image 的 12 字节 API 错误注入固化进源码。

不把历史诊断代码当成主线修复：没有移入强制晚期重启、跳过 BCM 投票、
跳过异步初始化等待/释放 init 内存的代码，也没有默认禁用
`of_platform_sync_state_init`。旧实验提出的 USB runtime PM 修改没有成为
本树的补丁；`pm_runtime_get_sync()` 的返回值必须结合恢复回调理解，
源码中的 `ret == 0` 分支本身不能证明 D+ 上拉缺陷。

## 后续更新

1. 保持上游版本更新与设备修复分开提交；先在独立分支合并新的上游版本。
2. 重新生成配置并检查被删除/改名的选项，编译 Image、板 DTB 及全部本地测试。
3. 对 boot 镜像做解包、内存区间、CPIO/ELF 和容量核验。
4. 单变量 RAM 启动，记录镜像哈希与实际观察。只有成功复现的现象才能升级
   STATUS 中的真机结论；编译和打包成功不替代设备测试。

本板树保留 `qcom,dwc3` legacy wrapper：它直接映射 `0xa6f8800`。
不能把新式扁平绑定驱动的 QSCRATCH 偏移算法套在这个节点上，
因此本树没有把 wrapper 的 reg 改为 `0xa600000`。
