# LG G8 CPU 空闲状态验证

2026-11-02：移除早期调试限制后，八个 CPU 的 PSCI 空闲计数均推进，
且在采样结束后全部成功执行原生探针。默认启动参数改为 `cpuidle.off=0`，
保留已验证的 `maxcpus=8`。

## 真机结果

成功目录：`out/lgg8-cpuidle-20261102/run-20261102-033855-33c1d3fd/`。

`cpuidle-result.json` 的 `success`、`android_return_verified`、
`monitor_verified` 和 `eight_cpu_idle_and_execution_verified` 均为 true。
`cpuidle-capture.json` 的八份命令回执全部通过，长度与 SHA-256 校验完整。
online / present / possible 均为 `0-7`，当前驱动为 `psci_idle`。

两次只读采样的 `/proc/uptime` 相差 1.02 秒。以下为 `state1` 计数增量；
CPU 0–3 的名称为 `cpu-sleep-0-0`，CPU 4–7 为 `cpu-sleep-1-0`。

| CPU | 进入次数增量 | 累计时间增量（微秒） |
| --- | ---: | ---: |
| 0 | 21 | 1011900 |
| 1 | 17 | 991215 |
| 2 | 9 | 984766 |
| 3 | 1 | 941512 |
| 4 | 4 | 1001146 |
| 5 | 2 | 1014755 |
| 6 | 8 | 973587 |
| 7 | 9 | 958539 |

两个采样时刻的各状态均未被用户禁用、拓扑相同、计数未倒退。
随后探针依次绑定八核并读取当前 CPU，严格返回 `CPU0_OK` 至 `CPU7_OK`，
退出码为 0。测试结束自动回 Android，启动标识更新，`boot_a`、`boot_b`
与启动前哈希一致。全程使用 `fastboot boot`，未刷分区或改变充电配置。

这里证明的是内核记录的较深核心空闲状态及返回后执行。计数器在退出状态后
累计时长，各核又不是同时采样，因此不把上表换算成精确占空比或省电比例。
未测实际功耗、整簇断电、长期并发稳定性；也未再次执行系统 freeze。

## 单变量制品

基线是已通过八核测试的镜像 `c46540fcba4d6c37ab3ddd579e480a9e1e76c6add15233fa0ceb133a53959cad`。
本轮只改 `cpuidle.off=1` → `cpuidle.off=0`，源码内核、源 DTB、initramfs、
shim、stock DTB 和外部 ramdisk 均复用；解压载荷仅一字节变化。
比较结果见候选目录的 `single-variable-verify.json`，封装 verify 通过。

| 制品 | SHA-256 |
| --- | --- |
| `out/lgg8-cpuidle-20261102/boot/boot.img` | `f800d267f21073ffce43c5c86984cbe4e2b4f91d5e37cd8653a8bac26420ea91` |
| `boot/manifest.json` | `798f492b7893e8ca3c20e6cc7bf6b0d51b0239803a7fb5604731566915ff915c` |

镜像为 30,224,384 字节；其余输入和原生探针指纹见 [MULTICORE.md](MULTICORE.md)。
候选和回执保留在本机 `out/`，不是 Git 克隆自带的文件。运行器只接受固定哈希；
未来重建须重新审查输入与哈希，不自动采用最新制品。

## 本地验证与运行

新增状态解析、退回/缺失/禁用/静止计数拒绝测试，结合既有采样、USB 绑定、
回收和分批上传测试共 25 项通过。同一目标 ARM64 BusyBox 的 ash 读取脚本也经
qemu-user 与模拟 sysfs 验证；该项的时间和计数是 fixture，不当作真机证据。
只有空闲采样命令的超时从 1 秒增至 3 秒，以容纳两次采样间的一秒等待；
全局采样期限、USB 绑定检查和 Android 回收机制保持有效。

```sh
PYTHONPATH=lgg8/tests python3 -B -m unittest \
  test_cpuidle_capture test_multicore_capture test_run_touch_ram_only \
  test_touch_capture_adapter test_touch_session test_watchdog_transfer -q
python3 -B lgg8/tests/run_cpuidle_ram_only.py
# 仅在已授权的目标手机上显式执行：
python3 -B lgg8/tests/run_cpuidle_ram_only.py --execute-ram-only --serial DEVICE_SERIAL
```

不带执行参数仅检查制品。源码默认参数现为八核加启用 CPU 空闲；默认诊断
用户态与本轮桌面镜像的其他参数不同，不能据此声称整个默认镜像已重新验收。
