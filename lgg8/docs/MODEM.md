# LG G8 基带启动与下一步断点

更新：2026-11-02。**DMS 固件版本与 UIM 卡状态查询已通过真机验证。**
基带报告一个卡条目，状态 `2`（卡错误）；插卡识别、注册网络、数据、短信和通话待验收。
下面保留首轮失败记录；最新成功结果与运行入口见下节。

## 后续：rmtfs 启动顺序、版本查询和 UIM 已通过

补入上游 `linux-msm/rmtfs` 的只读 shadow 模式，使用独立私有副本提供 EFS 数据。
源提交 `b30a3eb38f9af283f18dbd3c7755653efc52c094`，libqrtr 为
`29e36ae164389580a0f8ea7a7fdb728140ae978d`。静态 ARM64 构建使用上游直接
访问 Linux `/sys/class/rmtfs` 的后端；没有 libudev 运行依赖，也没有 `/dev/mem` 回退。
构建入口为 `lgg8/tools/build_rmtfs.py`，不修改上游 checkout。

四个 EFS 分区只读复制到 `/home/lightjunction/Backups/linux-lgg8-20261102/` 下的
私有目录，共 6,422,528 字节，复制前、复制后与本地 SHA-256 相符。
测试镜像包含这些私有副本，放在 `out/lgg8-rmtfs-20261102/private/`，目录权限 0700；
**不得把该目录的镜像、归档或 EFS 数据发布或提交到 Git。**
rmtfs 使用 `-r -o /opt/lgg8-rmtfs-input`，运行中的修改留在 heap shadow，且输入归档本身也在 RAM。
本机和 ARM64 QEMU 已实际测试 shadow 修改、重新打开恢复原值、源文件内容不变。

| 运行（UTC） | 证据 |
| --- | --- |
| `run-20261102-051739-2c4e96b0` | 空目录对照：收到 `/boot/modem_fs1` 请求，文件缺失后基带 fatal；确认文件服务确实被使用。 |
| `private/run-20261102-053004-cf6eed25`、`private/run-20261102-053710-b3c37bee` | 带配置的 gzip 镜像，两次均在 ACM 前停留 fastboot，未执行基带测试，随后回收 Android。 |
| `private/run-20261102-054425-48e2ef90` | 同一 raw CPIO 换 XZ 后启动；rmtfs 先于 MPSS 发布，没有文件请求，DMS 仍缺失。 |
| `private/run-20261102-054942-39669e3f` | 只改变发布顺序，MPSS running 后启动 rmtfs；收到三个 EFS open、多次实际读写，发现 47 个服务，DMS Get Revision 成功，关闭通过。完整自动结果 `PASS`。 |
| `private/run-20261102-060355-9cbb9021` | 新探针重复 DMS 查询并执行 UIM Get Card Status，47 个服务；`UIM_CARD_COUNT 1`、`UIM_CARD 0 2`，完整自动结果 `PASS`。 |

两次成功均完整回收 Android、A/B boot 哈希保持，内核保留日志没有此前的 shutdown ack 超时。
版本响应为 `MPSS.HE.1.0.c4-00116-SM8150_GEN_PACK-1.430468.2.433546.3`，
构建时间字符串为 `Sep 02 2021 01:00:00`。
这证明版本与卡状态的控制交换；卡错误的具体原因及实际插卡工作仍需对照。

带配置 gzip 制品的压缩段为 72,986,921 字节，XZ 制品为 64,804,127 字节。
前者失败、后者成功，与 64 MiB 附近的装载限制相符，但尚未用 ABL 源码或边界实验确认限制本身。
XZ 采用内核已编入的 `CONFIG_RD_XZ=y`、CRC32 校验及 8 MiB 字典。
打包器限制单流、展开大小与解码内存，拒绝 CRC64、附加流和未编译的解码器。

| 成功制品 | boot.img SHA-256 | manifest SHA-256 |
| --- | --- | --- |
| 延后发布 rmtfs，DMS | `293eac6dd6b48ef89be032b60ec7809d4e9e72cc3f7544edd0aa9b551e3fda78` | `43d1f8c094835403c875cec538bbdf85356c6499252b283252f0efd2357cd975` |
| DMS + UIM | `4008a255e307bbb0f03e4342fe83ec26f11444355f3fd65f310b009e5fe9d5c1` | `d27589cddc760cfac2e169622f557b1f0575596b33dcdf271a386ea9d0265a07` |

当前复核入口（默认只核对本地文件，不控制手机）：

```sh
python3 -B lgg8/tests/run_uim_ram_only.py
```

明确执行时使用 `--execute-ram-only --serial SERIAL`，继续复用固定哈希的 C234 传输和
Android 回收链路。私有归档由 `modem_nv_snapshot.py` 与 `modem_nv_initramfs.py`
校验并重建；固件复制、rmtfs 构建和归档输入的收据均在本地保留。
读回卡状态不查询 IMEI、IMSI、ICCID，不进行 PIN 尝试、拨号、发短信或注册网络的控制请求。

这些成功仍复用下文列出的已验证 Image。包含蓝牙/Wi-Fi 驱动的全新内核另在
`out/lgg8-connectivity-20261102/` 构建和验收，不能混用两组模块。

## 首轮实现

- 板级 DTS 启用 `remoteproc_mpss`，指定 `qcom/lg/alphalm/modem.mdt`。
  当前 PAS 驱动的 MPSS 描述符 `auto_boot=false`，测试控制台接通后才显式启动一次。
- 从当前手机只读复制 31 个 `modem.mdt` / `modem.bNN` 文件，共 77,701,547 字节。
  设备复制前、本地复制后、设备复制后 SHA-256 一致；ELF32 Hexagon 装载范围检查通过，
  重定位跨度 160 MiB，符合本板 `0x8e000000` / `0xa000000` 保留区。
  本地 ELF 检查不代替设备 PAS 验证。
- 补入与已验证 `7.3.0-lgg8` Image 匹配的九个模块：`qrtr`、`qrtr-smd`、
  `qcom_glink_smem`、`qcom_common`、`qcom_pil_info`、`qcom_q6v5`、
  `qcom_q6v5_pas`、`qcom_sysmon`、`qcom_pd_mapper`。
  `depmod -e -F System.map` 无未解析符号；真机成功加载，不使用强制加载。
- 原生 ARM64 探针只枚举 QRTR 服务、发送 DMS Get Revision（`0x0023`）。
  没有查询 IMEI、IMSI、ICCID，没有发短信、拨号或注册网络的控制请求。
- 含固件的 raw CPIO 为 130,289,664 字节，超过原装载布局允许的范围；
  工具增加有展开大小上限的单成员 gzip initramfs 支持，要求内核配置
  `CONFIG_BLK_DEV_INITRD=y`、`CONFIG_RD_GZIP=y`。压缩后为 56,014,888 字节，
  payload 结束地址 `0xaf017fd0`，没有移动已知装载基址或碰到 `0xb0000000` ramoops。

`modem_initramfs.py` 保留基础归档的全部原始记录头，包括字符设备的 rdev，
只在 trailer 前追加模块、探针和固件。新工具已逐字节重建本次实测压缩归档。
固件传输使用设备端 base64：本机 `su` 即使在 `adb exec-out` 下也会转换 LF，
不能直接拿二进制 `cat` 的返回值作为原文件，更不能对二进制删除 CRLF。

## 真机结果

证据目录均在 `out/lgg8-modem-20261102/`，时间为 UTC。

| 运行 | 结果 |
| --- | --- |
| `run-20261102-041724-cc20a6b4` | 模块准备、MPSS start、running 均通过；发现三个 QRTR 服务；DMS 不存在。脚本 stop 的 8 秒预算过短，收据退出 137；内核随后记录 stopped。 |
| `run-20261102-042027-d4e5a8e5` | 同一镜像被 fastboot 接受，但 Android 在 ACM 采集前返回。未执行基带操作；pstore 为空，无法据此定位启动失败层。 |
| `run-20261102-042428-7dd9f349` | MPSS start 后再等 8 秒，仍为 running；服务列表相同，DMS 仍不存在。修正预算后 stop 收据通过，明确读回 offline。 |

最后一轮日志：9.514 秒开始装载 `modem.mdt`，9.924 秒报告 modem is now up；
29.679 秒有 `timeout waiting for shutdown ack`，29.736 秒报告 stopped。
因此只是确认驱动完成关闭和 offline，**没有声称基带正常应答了关机握手**。

三个服务为 `(service, instance, node, port)`：

```text
(43, 4610, 0, 1)
(66, 46081, 0, 2)
(64, 257, 1, 16385)
```

前两个来自远端节点 0；第三个是本地内核 pd-mapper 的服务。没有 service 2（DMS），
不是一个成功的 DMS 响应解析结果。延长观察只覆盖约 8 秒额外等待，不能排除更晚出现。

三轮都完整回收 Android，boot ID 变化且槽位保持 `_b`；前后 `boot_a`、`boot_b`
SHA-256 一致。只执行 `fastboot boot`，没有刷写、擦除或切换槽位。
有一轮未到 ACM，长期启动可靠性尚未通过。

## 制品与来源

本轮刻意复用已验证 Image，不把它记成当前 HEAD 的全量重新编译：

| 输入 / 制品 | SHA-256 |
| --- | --- |
| 内核 Image | `1d600d62f6c6c88204d32f0414fc87d0e453f316bf9d13f5404a7c8c86cb2b7d` |
| 修改后的源 DTB | `bdd78b0a6f47ec25be4f6e15b3bf065d6f3a716aefcb71a6681f0a8af9e46427` |
| 有效 .config | `c70d91e448d0fb2b6e9f39c2b7168080b897fa79af2198278ae0ec511f3bd368` |
| 基础 reconnect CPIO | `3742801e7706db9da80b56a072411e926f5292d9d9463a4b3466c41e32330e75` |
| modem CPIO gzip | `f36616aabfe8eec57dc10fde21d9f6270d003e1841d607f93d5169694903bdb0` |
| ARM64 控制探针 | `ea45c1ddd6e0a3847df60b176a3aaffa74e3dae17e46ab80681969d025e87055` |
| boot.img，67,338,240 字节 | `7fd6cb0cfe4ca4c11698f5545fb676055e2e8615fbf2d69d9da9a7e19214ea35` |
| manifest.json | `1b9deb33332d2be10824887c4fdf2433a76c12b7cae3df18c3aa8ae1a425c327` |

模块源码为 `9c58979846d96501a4136b17bab7226cbe625bdd`，隔离 worktree 的唯一源码改动
是本轮板 DTS；构建目录从 `out/lgg8-pm-test-20261101/kernel` 复制后执行
`modules_prepare` 和上述九个 `.ko` 目标，另单独编译板 DTB。
未覆盖旧构建目录。有效版本 `7.3.0-lgg8 SMP preempt mod_unload aarch64`。

保留的本地材料：

- `out/lgg8-modem-20261102/boot/`：实测镜像、manifest、打包 DTB。
- 同目录上层的 `modem-initramfs.cpio.gz`、`additions/`、探针、固件复制收据、模块收据、
  构建日志、`initramfs-verify.json` 与三轮采样。原始 CPIO 在确认 gzip 可精确还原后清理。
- `kernel-artifacts/`：源 DTB、有效配置和构建来源收据；临时 worktree 与模块构建副本清理，
  下次重建仍从上述源码提交和旧的已验证内核构建目录开始。
- 私有原始固件在 `/home/lightjunction/Backups/linux-lgg8-20261102/modem-firmware/`，
  两槽原始启动备份也在其父目录；不提交这些二进制。
- 保留旧的 `out/lgg8-c234-integration-20261101/run-c234-observe.py`，新 runner 依赖它的
  固定哈希和完整 Android 回收检查；没有这个本地依赖时不得绕过检查来运行。

复核与复现入口（仓库根目录执行；默认 runner 不碰手机）：

```sh
python3 -B lgg8/tests/run_modem_ram_only.py
python3 -B lgg8/tools/bootimg.py verify \
  --image out/lgg8-modem-20261102/boot/boot.img \
  --manifest out/lgg8-modem-20261102/boot/manifest.json
python3 -B lgg8/tools/modem_initramfs.py \
  --base out/lgg8-pm-reconnect-20261101/reconnect-initramfs.cpio \
  --additions out/lgg8-modem-20261102/additions \
  --firmware /home/lightjunction/Backups/linux-lgg8-20261102/modem-firmware \
  --verify-existing out/lgg8-modem-20261102/modem-initramfs.cpio.gz
```

新建归档时将 `--verify-existing` 换成不存在的 `--output` 路径；再用 `bootimg.py build`
传入已验证 Image、`kernel-artifacts/source.dtb`、gzip 归档、原有 C234-derived 模板、
本目录 `cmdline.txt`、`kernel-artifacts/effective.config`、
`kernel-artifacts/build-provenance.json` 和分区容量 100663296。新制品须重新核对 runner
的 Image/manifest 两个哈希，不得把旧实验结论直接转给新镜像。

本地相关验证：打包工具 44 项、modem 9 项、既有八核与 idle 采集 9 项，共 62 项通过。
包含真实 LLVM 封装、原生与 ARM64 QEMU 的 QMI 解析器检查、归档设备记录保留、
损坏/缺失响应拒绝和真实 framing helper 的命令/超时检查；不以这些代替手机入网验收。

## 首轮续接计划与当前剩余项

1. 先核对手机、Android 回收条件、制品指纹及以上源码状态。不要重做已通过的触摸和
   用户配合 freeze 测试；本轮没有插 SIM，用户已说明识卡测试下次再做。
2. **rmtfs 文件服务和 DMS 已按上节通过**。内核已有 `CONFIG_QCOM_RMTFS_MEM=y` 和板级
   rmtfs 保留区，但 RAM 用户态没有该 daemon。上游
   [rmtfs 服务实现](https://github.com/linux-msm/rmtfs/blob/master/rmtfs.c)
   发布 QMI service 14；[存储实现](https://github.com/linux-msm/rmtfs/blob/master/storage.c)
   处理 modem_fs1/fs2/fsg 等请求，并提供内存 shadow 模式。
   后续对照已经收到文件请求，并在修正发布顺序后取得 DMS 响应。
3. 先检查设备节点和服务请求，再设计仅使用私有备份或 RAM 副本的文件服务对照。
   首轮没有读取 NV；后续使用专用只读快照工具复制了上述四个分区。不要把固件文件复制工具
   当作这些可变数据的一致性备份工具。NV 不进入公开源码、日志或发布制品。
4. DMS 与 UIM 状态查询已通过；后续识卡、PIN、运营商注册分开验收。
   SIM 缺席不能把本轮缺失 DMS 的问题解释成识卡失败。
5. 移动数据还缺独立的 IPA 路径：当前 `drivers/net/ipa` 和绑定没有 SM8150 匹配项。
   QRTR 控制成功不代表数据网络、短信、通话已经可用。关机 ack 超时与偶发未到 ACM
   也保留为待解决项。

## 距离日常可用的主要剩余项

按功能划分为七组，不代表只剩七个小问题，也不换算成完成百分比：

| 组 | 尚未完成的主要验收 |
| --- | --- |
| 蜂窝通信 | DMS/UIM 查询已通过；SIM、注册网络、IPA 数据、短信、通话及音频路由待测 |
| Wi-Fi / 蓝牙 | 固件、稳定连接、断连恢复及共存 |
| 音频 | 扬声器、听筒、麦克风、耳机及路由 |
| GPU / 显示 | 硬件加速、花屏/启动稳定性、实际显示模式 |
| 其他外设 | 相机、定位、传感器、NFC 等逐项验证 |
| 电源与续航 | 充电控制和温度保护、真实电池变化、负载温控、实际睡眠与待机功耗 |
| 存储与完整系统 | 存储/根文件系统、日常用户态、持久启动和可靠恢复、持续使用稳定性 |

已通过的启动、USB shell、极简桌面/触摸、八核、CPU idle、电源只读采样和按键唤醒，
是这些后续工作的基础；目前仍然是 RAM 运行的适配原型。
