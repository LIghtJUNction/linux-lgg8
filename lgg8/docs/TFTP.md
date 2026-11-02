# LG G8：基带文件传输与 WLAN 固件入口

更新：2026-11-02。TFTP 已收到基带真实读写请求，DMS 回归和 Android 回收通过。
写入目录是 8 MiB tmpfs，EFS 仍由 rmtfs heap shadow 提供；没有刷写操作。
Wi-Fi 的驱动与网卡验收另见 [CONNECTIVITY.md](CONNECTIVITY.md)。

## 来源与运行条件

静态 ARM64 `tqftpserv` 来自 `linux-msm/tqftpserv`
`eb4b9a04ff92d2753ededf32cc3b6ed287f6e29b`，libqrtr 为
`29e36ae164389580a0f8ea7a7fdb728140ae978d`。构建器
`lgg8/tools/build_tqftp.py` 要求两棵源码干净且提交匹配，不修改上游文件。
当前不编入可选 XZ/ZSTD 文件传输支持；归档自身的 XZ 是内核解包层，二者不同。
二进制 729,000 字节，SHA-256
`2393f096c98cc22b68982052cbb48e0cce1f797feccf59befd0c6a5ef1b154fe`。

本固定版本把 `/readwrite/` 映射到 `/var/lib/tqftpserv`。
测试在启动前检查 `firmware_class.path` 是默认空行，然后挂载
`size=8m,mode=700,nosuid,nodev,noexec` 的专用 tmpfs，核对 `/proc/mounts`。
这条前提也避免上游路径转换代码在读取固件搜索路径失败时使用未初始化缓冲区；
当前结论只适用于已检查的环境，没有把这段上游代码宣称为通用可靠实现。

只读固件由 `/sys/class/remoteproc/*/firmware` 对应的 `/lib/firmware/` 目录寻找。
本机 ASan/UBSan 与 ARM64 QEMU 均运行了实际 `translate.c`：固件可读、
对只读文件的写入返回 EBADF、内存目录可写可读、四种越界路径被拒绝。
测试仅重定向四个环境绝对路径，不重写路径处理逻辑。

## 真机对照

证据在 `out/lgg8-tqftp-20261102/private/`，运行时间为 UTC。

| 运行 | 结果 |
| --- | --- |
| `run-20261102-081910-784f0b6c` | TFTP 先于 MPSS：服务 4096 和 tmpfs 均可见，但没有读写请求；完整结果保留 `FAILED`。 |
| `run-20261102-082632-e52d1ee8` | 同一镜像只把 TFTP 移到 MPSS running 后、rmtfs 前：出现 server_check、mcfg.tmp 和 modem_pr 请求，48 个服务、DMS、停止和回收均通过，完整结果 `PASS`。 |
| `run-20261102-083555-39c64f09` | 加入 124 个原厂 modem_pr 文件：读取摘要、配置清单和对应 MCFG；同时抓到缺少 wlanmdsp.mbn 的请求。文件请求/DMS 范围 `PASS`，当时尚无 WLFW 69。 |
| `run-20261102-084357-c2ae1426` | 仅补 wlanmdsp.mbn、Wi-Fi 节点仍禁用：DMS 通过，但未观察到 WLAN 文件请求和服务 69；该目标完整结果 `FAILED`。 |
| `run-20261102-084721-3c72abd6` | 启用实验 Wi-Fi 节点并加载驱动：WLAN 文件请求、服务 69、MSA 交换及芯片能力查询通过；缺少 board.bin，PHY/网卡数为 0，完整结果 `FAILED`。 |
| `run-20261102-085923-9c8f6fa7` | 补入原厂选定的 BDF，但这轮没有 WLAN 文件请求/服务 69；DMS 和回收通过，完整结果 `FAILED`。 |
| `run-20261102-090614-5559c024` | 同一 BDF 镜像只延后 TFTP 发布 1 秒：WLAN、BDF/cal、FW ready 和运行模式切换通过；下一处缺 firmware-N.bin，网卡仍为 0，完整结果 `FAILED`。 |
| `run-20261102-091628-8d1c2f81` | 补入上游 ath10k 描述和签名 regdb，仍保留 1 秒延时；本轮更早停在服务发现，未实际验证描述文件被驱动使用，完整结果 `FAILED`。 |
| `run-20261102-095224-df32a6a6` | 只加协议元数据日志、观察 30 秒：服务 64 公告因本机 HELLO 未发出而返回 `-EAGAIN`；随后 HELLO 成功，但始终没有补公告、PD 查询和 WLAN，完整结果 `FAILED`。 |
| `run-20261102-101641-e9c07e18` | 相同输入和时序，仅加 QRTR 公告重试：先复现同一 `-EAGAIN`，约 105 ms 后成功补发，随即收到 PD 查询。WLAN 文件、WLFW 69、ath10k API 5、PHY 1 和网卡 1 均通过，完整结果 `PASS`；未测试连接热点。 |
| `run-20261102-102157-d32e4c27` | 换回原诊断镜像作 A/B/A 对照，再次丢失服务 64 公告，30 秒内无 PD 查询、无网卡，完整结果 `FAILED`。 |
| `run-20261102-104122-9c4ec18a` | 去掉 QRTR/PD 临时日志，DMS、WLFW、WLAN 请求、PHY 1、网卡 1 的采集 `PASS`；615 次 USB 采样中有一次状态不可读，整轮保留 `FAILED`，Android 回收及 boot 核对通过。 |
| `run-20261102-105321-afc4c502` | 同一无临时日志镜像复测：网卡注册、DMS、USB 采样、Android 回收及两槽 boot 核对全部通过，完整结果 `PASS`。 |

以上已完成运行均回收 Android，A/B boot 哈希保持。
USB 采样除已明确标注的 104122 轮外均通过，未放宽验收条件。
这组对照确认当前可用顺序为：准备驱动、MPSS running、TFTP 发布、rmtfs 发布、查询。
它尚不是经过长期重启和服务重连验收的常驻管理器。
请求日志只取首尾各 4096 字节；去重列表不是完整传输清单，不能仅凭请求行宣称全部数据已交付。

已用实际返回值及 A/B/A 确认本机 QRTR HELLO 与预先注册的 PD mapper 公告竞态。
服务 64 的单播公告在 `hello_sent == false` 时被 core 拒绝，返回 `-EAGAIN`；
原名字服务没有重试。固定 1 秒等待不解决这个问题。
`0:-2` 是节点 0 和控制端口 `0xfffffffe`，不是 errno -2。

`net/qrtr/ns.c` 现在只对临时的 `-EAGAIN` 保存目标并延后 100 ms 重试。
重试和节点删除使用同一个有序工作队列；BYE 删除节点即清除其待重试状态，
模块退出及初始化错误路径均禁止、取消并排空延迟任务。没有绕过 HELLO 检查，
没有替换 PD 服务的 owner/port，没有把协议诊断日志加入正式源代码。
命中竞态的修复镜像在 13.125196 s 返回 `-11`，13.230271 s 补公告返回 20，
13.230675 s 收到 PD 查询。无 QRTR/PD 临时日志版本已独立完成全流程回归。
首尾日志可能重叠，同一时间戳的重复记录不算两次独立失败。

对应入口为 `run_wifi_qrtr_diag_ram_only.py`（对照）、
`run_wifi_qrtr_retry_ram_only.py`（带元数据日志的修复）、
`run_wifi_qrtr_fixed_ram_only.py`（无临时日志的修复）。后者默认只做离线校验，
不会要求已经移除的诊断标记；仍须真实 WLAN 请求、WLFW、PHY 和网卡注册证据。

| 制品 | boot.img SHA-256 | manifest SHA-256 |
| --- | --- | --- |
| 原始 TFTP | `4e8f80d137b0a1ca71bc23588b261d9f8836e05203d7a13ec1f51c165e79e438` | `79d5ea3356d620cb3e0bbd02a31b1475ad726041d932ced8c77d911a6324f6e3` |
| MCFG | `6075912ee33d0567d56c1e08ad02eab361cd9f8a892ab89adec5921ffebd7f54` | `52d94a55d1eabc887a5ea8cf4966e2164c49115f7b07efbc8cfc74175d07a14a` |
| QRTR 修复及临时日志 | `b3b48a8f638e22c717d5d565347680a767b6c8f0efebdfad5a2907f120f24922` | `2d3bdf1df2fd416aff53ed56d952f401138f6d969ee031263196131447c6bfa1` |
| QRTR 修复、无临时日志 | `4603381794d5f3a5ee1d3e38f9d0aba5322dd411e6d712a4548ffa1e673a19c5` | `0280ccd5868054105b718c073e1411ed6eee469fda55d28e99c36ae22c563d33` |

默认入口 `run_tqftp_ram_only.py`、`run_tqftp_late_ram_only.py`、
`run_tqftp_mcfg_ram_only.py` 只核对文件。明确执行仍须传入
`--execute-ram-only --serial SERIAL`，沿用固定 C234 framing、90 秒 guardian、
Android 回收和两槽 boot 哈希核对。实际 SIM 和入网由用户留到下次。

## 私有输入与重建

额外固件只读备份到 Backups 下的 `modem-extra-firmware/`：125 个文件、
5,271,406 字节，包括 `modem_pr/` 和 `wlanmdsp.mbn`。
复制采用设备端 base64 tar，逐文件核对复制前、本地、复制后 SHA-256。
`wlanmdsp.mbn` 为 4,057,088 字节，SHA-256
`37bfcfcaee4c2500727fdcf049c7b05c22ae874e280643b8fa490032ec39259e`。
原厂没有的 `mbn_hw.dig`、`oem_sw.txt` 没有凭空生成或替换。

原厂 Android 日志明确选择 `bdwlan.bin`；它另在 `wlan-board/` 完成同样的哈希核对。
26,328 字节，SHA-256 `a006cd753899cca7745333e946ed01ddb22134acf6c539383b271902e3620172`。
它按原内容放到主线要求的 `ath10k/WCN3990/hw1.0/board.bin`，没有修改校准数据。

后续添加的 `firmware-5.bin` 只有 60 字节，是 ath10k 能力与接口描述。
本机 linux-firmware 包解压结果与
[上游固定版本文件](https://kernel.googlesource.com/pub/scm/linux/kernel/git/iwlwifi/linux-firmware/+/827c67ef8287b8ec00214c66b64528a790e3cce6/ath10k/WCN3990/hw1.0/firmware-5.bin)
逐字节一致，SHA-256 `fef6539e0127579536bc977be57a90d018b83f2931fedc3a8870fbe38d6c4127`。
实际 WLAN DSP 程序仍来自本机原厂 wlanmdsp.mbn。另加入本机
wireless-regdb 2026.09.03-1 的 regulatory.db 和 p7s；设备签名接受及驱动使用结果仍待验收。

`connectivity_initramfs.py` 校验基础归档身份及两份 verified.json，保留原始 newc
头和私有 EFS，追加固件，输出 CRC32、preset 9 的单流 XZ。解码限制 128 MiB，
展开限制 256 MiB，额外固件限制 32 MiB；输出目录须为 0700、文件创建为 0600。
基础 TFTP XZ SHA-256 为
`fb0450ee1b4671162f8e457fa8e73443b502287d3d00a1058c40941897b62a91`。

```sh
python3 -B lgg8/tools/connectivity_initramfs.py \
  --base out/lgg8-tqftp-20261102/private/initramfs.cpio.xz \
  --base-sha256 fb0450ee1b4671162f8e457fa8e73443b502287d3d00a1058c40941897b62a91 \
  --extra /home/lightjunction/Backups/linux-lgg8-20261102/modem-extra-firmware \
  --board /home/lightjunction/Backups/linux-lgg8-20261102/wlan-board \
  --host /home/lightjunction/Backups/linux-lgg8-20261102/wifi-host-firmware \
  --output out/lgg8-tqftp-20261102/private/rebuilt-wifi-initramfs.cpio.xz
```

含 EFS 的基础和输出归档、镜像、备份、完整收据均只保存在本机，不提交或发布。
本地相关 83 项测试通过，无跳过；包括原始 C 路径代码的 ASan/UBSan 与 ARM64 QEMU，
以及私有归档保留、固件身份、请求/网卡证据和实际 framing 的检查。
