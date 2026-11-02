# LG G8：连接驱动与新内核验收

更新：2026-11-02。新内核的八核执行、DMS 版本和 UIM 卡状态查询已有真机证据。
蓝牙原厂固件加载、控制器上电/版本/关闭与八核执行已完整通过。
Wi-Fi 实验已到 WLFW、MSA、板数据及 firmware ready，但启动不稳定，网卡注册与连接尚未通过。

## 制品与模块来源

`lgg8/configs/connectivity.config` 在已验证配置上增加 Bluetooth HCI UART/QCA、
RFCOMM/BNEP 和 ath10k SNOC。隔离源码在 `out/lgg8-connectivity-20261102/source`，
基线 `487beacbf6586214125939888b94e6231a91a672`；完整编译 Image、板 DTB 和 544 个模块。
构建退出状态 0；模块安装后剥离调试符号。

Image SHA-256 为 `2d9adff067ca028d8b17b2e9488d11e8b4d30f8faf5042793f31bf801634d78a`，
有效配置 SHA-256 为 `fde137bc83bec3c386ac26136445e1c2f3fea78b6aad4ec76e3f32c42d6fbd16`。
配置和构建收据在 `kernel/`，原始命令与后续完成收据在输出目录根部。
固定环境包含 `SOURCE_DATE_EPOCH=1792365298` 及实际使用的
`KBUILD_BUILD_TIMESTAMP='2026-10-18 23:14:58 UTC'`；复现时保留这两个原值。

蓝牙测试只放入同一完整构建的 6 个依赖模块；组合无线/基带归档放入 20 个依赖模块。
`depmod -e -F System.map` 均没有未解析符号。没有从旧 Image 按相同内核版本号借用模块。
测试归档不增加设备 alias 自动加载项，驱动由测试步骤显式加载。

## 新内核上的基带回归

`private/run-20261102-073147-c8d6edc8` 使用新 Image、匹配模块、已验证的原板 DTB、
原厂固件与私有 EFS shadow，完整自动结果 `PASS`：再次取得 DMS 固件版本和一个状态为
2（卡错误）的 UIM 条目，成功关闭基带、回收 Android、保持两槽 boot 哈希。
这一步把 [MODEM.md](MODEM.md) 的控制验收迁移到新内核，实际插卡及入网仍待测。

| 制品 | SHA-256 |
| --- | --- |
| `private/radio-baseline-boot/boot.img`，66,629,632 字节 | `643f38db45124a072ecca767397fdd536a9a2a3192e0466df7cff24da8806ec7` |
| 对应 `manifest.json` | `1d51c002dda5b4f7a9491c27f15f59310b4654dcc8df159abf300b06b0c00a78` |

该制品和 XZ 输入含私有 EFS，目录 0700、文件 0600，不能提交或发布。
默认核对入口为 `python3 -B lgg8/tests/run_uim_connectivity_ram_only.py`。

## 蓝牙：引脚、唤醒中断与协议型号

原厂运行时 FDT 的只读副本已在 Backups 中校验。UART13 位于 `0xc8c000`，
GPIO43/44/45/46 分别承担 CTS/RTS/TX/RX。原板树没有 `pinctrl-0`，只声明了 sleep。
现在补上工作状态，按原厂 active 配置设置 2 mA、CTS/RX 无偏置、RTS 下拉、TX 上拉。

仅补 `pinctrl-0` 后两轮均没有 ACM，约 110 秒后返回 Android，pstore 为空；
不能据此认定 kernel panic。只移除 GPIO46 的 RX wake IRQ 后，ACM 和八核执行恢复，
保留同一跨页的 payload 末端。代码路径显示 GPIO IRQ 申请会强制 RX 为 GPIO 输入，
且补上 default 也首次启用了原来未解析的 sleep 状态。
**当前不声明蓝牙能从系统休眠唤醒，须补做这一条电源管理链路。**

初次声明为 WCN3991 时，驱动等待 Command Complete，而芯片实际返回 Vendor Event
`0xff`、EDL 类型 `0x02`。受限的临时 RX/TX 日志确认发出的版本命令正确，
2400 和 115200 波特率均按请求设置，四根引脚实际处于 qup13 模式。
回复解码为产品 `0x0a`、SoC `0x40010224`、ROM `0x1001`。
WCN3998 分支使用该事件格式，其固件版本计算得到 `0x21`，与原厂
`crbtfw21.tlv` 和 `crnv21.bin` 相符；因此板树修正为 `qcom,wcn3998-bt`。
最终控制器验收使用原始模块，临时字节日志补丁已从隔离源码反向撤销。

| 运行 | 结果 |
| --- | --- |
| `run-20261102-062458-d7da5e5c`、`run-20261102-065119-2f06ba6e` | 原板树：USB 与八核通过，QCA 版本无响应，MGMT 控制器数 0。 |
| `run-20261102-064004-b6055ddb`、`run-20261102-064613-07d367e9` | 只补 active 引脚，仍保留 GPIO46 wake IRQ：没有 ACM，自动回收 Android。 |
| `run-20261102-070954-6bd6626d`、`run-20261102-071746-accfb3a4` | 去掉 RX wake IRQ：USB/八核恢复；等待 6 秒及 20 秒均未完成旧型号的版本查询。 |
| `run-20261102-073609-45b55148` | 临时日志证实 Vendor Event 回复与型号分支不符，完整测试仍为 `FAILED`。 |
| `run-20261102-074910-1f0a4a27` | WCN3998 与原始模块：控制器及八核 capture 为 `PASS`，Android 回收成功；USB 拔除时一条 `ENODEV` 不可读样本，完整实验保留 `FAILED`。 |
| `run-20261102-075439-f6090ae9` | 同一 WCN3998 制品复测：固件加载、唯一控制器上电/版本/关闭、八核执行、完整 USB 采样、Android 回收与两槽 boot 哈希均通过，完整结果 `PASS`。 |

成功响应为 `BT_CONTROLLER_COUNT 1`、`BT_VERSION 9`、`BT_MANUFACTURER 29`、
`BT_POWERED 1`、`BT_POWERED_OFF 1`。内核两次记录从本地加载 `qca/crbtfw21.tlv`、
`qca/crnv21.bin` 并完成 UART setup。首次加载约 1.3 秒；20 秒观察窗口后探针上电时
再次完成相同加载流程。开机脉冲后有一次 `00 00` 导致的 reassembly 提示，随后收到完整版本响应。

| 蓝牙成功制品 | SHA-256 |
| --- | --- |
| `bt-wcn3998-boot/boot.img`，30,969,856 字节 | `ca1bfb12f4ba2ec3f5ae0cd0a8adde2fb3948ecb351a247a6469c800260f5b34` |
| 对应 `manifest.json` | `3d8714f76710cf8bcb526ca9ae8ff475cd4b944e30891d0eddeaa09f1884f8c9` |

本地针对打包、CPU、基带、私有副本、RMTFS 与蓝牙协议的 73 项测试全部通过，无跳过。

默认入口 `python3 -B lgg8/tests/run_bluetooth_ram_only.py` 仅核对本地制品。
显式执行沿用 `--execute-ram-only --serial SERIAL`、固定 C234 传输、90 秒 guardian、
Android 回收和两槽 boot 哈希核对。控制器验收须同时满足唯一控制器、上电、读取版本和
确认关闭，不能从存在 `hci0` 或几行 UART 日志推导通过。探针不输出地址与名称。
板树原有占位蓝牙地址仍待改为工厂地址来源；配对与实际数据传输尚未验收。

## 后续硬件入口

Wi-Fi 的 ath10k SNOC 模块及依赖已编译，默认板级 Wi-Fi 仍 disabled，
实验配置在 `lgg8/experiments/wifi/wifi-override.dtsi`。
原厂 ICNSS 的供电为 L1A 0.752 V、L7A 1.8 V、L2C 1.304 V、L11C 3.104–3.312 V；
板数据有多个 `bdwlan.*`，必须取得固件报告的 board ID 后选择对应数据。
后续 TFTP 对照已在部分启动中发现 WLFW 服务 69。读取到芯片 `0x30224`、
family `0x4001`、board `0xff`、SoC `0x40060000`；固件版本 `0x300e00b4`，
构建标识 `WLAN.HL.3.0.c4-00180-QCAHLSWMTPLZ-1`。
原厂日志确认选用 bdwlan.bin，校验后原样提供给主线 board.bin，BDF/cal 与 firmware ready 已出现。
加入上游 60 字节能力描述及签名 regdb 后，A/B/A 确认 QRTR HELLO 与服务 64 公告竞态。
公告重试补丁的首轮真机测试通过：同一处 `-EAGAIN` 后补公告成功，PD 查询、
WLAN 请求、WLFW 69、ath10k API 5、PHY 1 与网卡 1 均出现，完整运行 `PASS`。
无 QRTR/PD 临时日志的同一修复已独立回归通过。热点连接、扫描、实际数据及长期稳定性未验收；
当前 ath10k 还报告工厂 MAC 无效并使用随机地址，地址来源仍需适配。
regdb 的签名接受也不能仅从文件已打包推断。完整对照、指纹和边界见 [TFTP.md](TFTP.md)。

## 最终用户空间与显示模式

用户指定后续运行 OmaMobile（Arch Linux ARM、Hyprland、Omarchy），
源码在同级 `omarchy-mobile`。已开始独立的 alphalm 设备接入分支，
尚未启动该项目的共享 rootfs，也没有持久安装。

SW43410 驱动当前只有 1440×3120、60 Hz 固定模式：
`320280000 / (1700 × 3140) = 60`。本轮原厂 Android 的 supportedModes
也只有约 60 Hz，alternativeRefreshRates 为空。该查询没有切换显示模式。
真实 scanout 帧率、动态切换和降刷新率省电未验收；不能承诺 90/120 Hz。

## 音频库存

音频库存已确认 I²C `0x890000` 下有 ES9218（地址 `0x48`）与 NXP TFA98xx（`0x34`），
并有 Qualcomm SLIMbus 音频 codec 节点。库存不是声卡或播放验收；ES9218 驱动、
功放具体型号、DSP 固件与路由仍需适配。
