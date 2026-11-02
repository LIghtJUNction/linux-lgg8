# OmaMobile 共享用户空间接入

更新：2026-11-02。目标为共享 Arch Linux ARM 根系统和 Hyprland。
当前通过的是共享 initramfs 的 RAM 启动、串口和 USB SSH，尚非完整系统验收。

## M1 真机结果

`run-20261102-124755-8d103d24` 完整结果 `PASS`：

- PID 1 为 `/bin/sh /init`，运行的是 OmaMobile 的共享脚本；内容哈希核对通过。
- ACM 收到带长度、SHA-256 和命令返回码的完整帧。
- 同一物理 USB 口的 NCM 网卡放入临时独立网络命名空间；两次新建 SSH 连接均成功，
  第二次严格核对第一轮保存的服务器密钥，不复用连接。
- 空 UFS 写入列表、`/run` tmpfs 和存活的 RAM guardian 均通过检查。
- 未发送手动重启命令；USB gadget 存在约 89.6 秒后退出，自动返回 Android。
  完整 USB 采样和两槽 boot 哈希核对通过，恢复槽仍为 B。临时网络命名空间已清理。
- 输入清单有 `LG SW42000 Touchscreen`。本轮没有实际触摸或屏幕观察；
  约 1.3 秒时的 DRM modes 查询为空，不能算显示验收。

源码入口：`lgg8/tests/run_omamobile_ram_only.py`。默认只核对制品，实际运行需
`--execute-ram-only --serial <device>`。重用已固定哈希的 C234/C210 Android 身份、
锁、独立 USB 监控、300 秒恢复截止与前后哈希流程。未改写这些旧入口。

| 制品 | SHA-256 |
| --- | --- |
| 内存启动镜像 | `3e6544cfe2bac4bb6b8d7135ee06005335c9fa73df2fcbe4d7c10118577d7937` |
| 启动 manifest | `d84b9c105172e512378000a19e6008e059463f1dde2fc8cff94920a9fdaf2f1c` |
| 共享 `/init` | `52957d7fc9902178b515bf65665062d0a7111d548bbc5298407277dd5e28d79c` |
| 静态 PIE BusyBox | `999cb969d09093a71716cfc747bb53cdada3f332c05eb5046c56e0f66a4d6d22` |

私有制品在相邻 OmaMobile 仓库的 `out/alphalm/m1-compatible/private/boot`。
运行记录及客户端临时密钥在 `out/alphalm/m1/private`，均不提交。
内核、配置和 BT 修正 DTB 复用之前已验收的构建；本阶段未重编或改写共享 Image。
命令行仅将 `watchdog.open_timeout=60` 改成 `120`，给共享脚本的 90 秒 timer 留出时间，
仍保留有限的内核 watchdog 后备。该参数的含义来自 `drivers/watchdog/watchdog_dev.c`。

## 封装边界与反例

先前的错误前提是标准 Alpine initramfs 可以原样通过旧封装器：实际有静态 PIE
BusyBox 和 26 个合法的前导 `..` 符号链接，旧检查只接受静态 ET_EXEC 且拒绝所有 `..`。
`bootimg.py` 现在识别没有解释器或外部库依赖的静态 PIE，旧 ET_EXEC manifest 不变。
独立 `tools/omamobile_initramfs.py` 只将留在归档根内的前导父路径改成等价绝对路径，
保留 newc 文件数据及其余元数据，再运行原先的严格归档检查。越界、路径中间的 `..`、
穿过符号链接的归档路径及常规硬链接仍拒绝。输出是单流 CRC32 XZ；
输入 LZ4 哈希、展开上限、共享脚本、显式公钥、空写入列表和编译 DTB 的 compatible 均核对。

第一轮 `run-20261102-123159-bd6d0232` 没有 USB，完整恢复和监控通过，但功能结果失败。
原因定位到描述符写成 `lg,alphalm`，而实际 DTB 是 `lge,alphalm`，匹配保护会阻止继续。
这轮及其 `73a05c07...` 镜像保留为反例。修正描述符后才取得上面的成功结果；
适配工具新增必填 `--dtb`，直接以编译结果核对 marker，不再仅依赖相互一致的模拟字符串。

本地 63 项封装、静态 PIE、归档、USB 绑定、串口帧、SSH 隔离及清理测试通过，无跳过；
旧 QRTR 生产镜像仍通过更新后封装器的 verify。OmaMobile 全套本地检查通过，
其中根系统 smoke 因尚无根系统镜像按项目规则跳过。

## 下一阶段

先准备 LG 设备包和实际共享根系统的只读 RAM 启动方案，再验收 Arch、Hyprland、
实际显示与触摸。内核当前未启用 SCSI，本轮没有暴露 UFS，因此这不证明真实 UFS
枚举后的只读保护，更不提供安装能力。镜像、刷写、分区变更与持久启动仍不能据 M1 放行。
刷新率继续使用现有 1440×3120@60 Hz，切换档位尚未适配。
