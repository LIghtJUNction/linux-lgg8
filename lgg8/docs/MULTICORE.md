# LG G8 八核 RAM 启动验证

2026-11-02：八个 CPU 均已在主线真机上上线并执行代码。
改动为启动参数 `maxcpus=1` → `maxcpus=8`；未修改内核二进制或驱动。
`lgg8/boot/cmdline.txt` 已采用八核。本轮候选其余诊断参数，包括
`cpuidle.off=1`，保留原值；后续 [CPU 空闲验证](CPU-IDLE.md) 又推进了默认值。
默认诊断用户态与本轮桌面候选的其他参数不同，不能视为同一镜像。

## 真机证据

成功目录：`out/lgg8-multicore-20261102/run-20261102-032534-347f9fbe/`。

- `multicore-result.json`：`success=true`、`capture=PASS`、
  `eight_cpu_execution_verified=true`、`android_return_verified=true`、
  `monitor_verified=true`。
- `multicore-capture.json`：七份带长度与 SHA-256 校验的命令回执全部通过。
  online、present、possible 均为 `0-7`；`cpuinfo` 和中断表也包含八个 CPU。
- `multicore-transfer.json`：原生探针经逐批确认上传到已验证为 tmpfs 的 `/run`，
  手机校验其 SHA-256 后执行。探针依次调用 `sched_setaffinity()` 和 `getcpu()`，
  输出严格匹配 `CPU0_OK` 至 `CPU7_OK` 八行，退出码 0。
- Android 启动标识已改变，`boot_a` / `boot_b` 与启动前哈希一致。
  未刷分区、切槽或写入充电控制寄存器。

这是短时调度验证，不是八核并发压力测试、性能测试、CPU 空闲省电验证或
充电安全验收。诊断日志仅保存末尾 8192 字节，不支持“全量日志无错误”的结论。

## 制品身份与复现

候选：`out/lgg8-multicore-20261102/boot/boot.img`，30,224,384 字节。

| 输入或输出 | SHA-256 |
| --- | --- |
| boot.img | `c46540fcba4d6c37ab3ddd579e480a9e1e76c6add15233fa0ceb133a53959cad` |
| manifest.json | `396c9e088cbf62645b6e684780c8d4af14ddb20b08ea223d9539a473c4e61b7f` |
| 原生探针 | `2fb29cb5db468cc4688fd231746fb12cc683487a078662563ad8bcd5f4aac4b8` |
| Image | `1d600d62f6c6c88204d32f0414fc87d0e453f316bf9d13f5404a7c8c86cb2b7d` |
| initramfs | `3742801e7706db9da80b56a072411e926f5292d9d9463a4b3466c41e32330e75` |

`single-variable-verify.json` 记录：与已验收的 PM reconnect 镜像相比，
解压后载荷仅一字节不同，即 `maxcpus` 的 `1` → `8`；内核、源 DTB、
initramfs、shim、外部 ramdisk 及 stock DTB 均相同。封装 verify 通过。
这些候选和运行收据保存在本机 `out/`，不随 Git 克隆提供；执行脚本会拒绝
缺失或哈希不符的制品，不会自动替换成最新构建。

构建无 libc 依赖的 ARM64 探针：

```sh
aarch64-linux-gnu-gcc -nostdlib -static -Os -Wall -Wextra -Werror \
  -fno-stack-protector -fno-builtin -Wl,--build-id=none \
  -Wl,-z,max-page-size=4096 \
  -o out/lgg8-multicore-20261102/cpu-probe lgg8/tests/multicore_probe.c
python3 -B -m unittest discover -s lgg8/tests -p 'test_multicore_capture.py' -v
python3 -B lgg8/tests/run_multicore_ram_only.py
# 明确选择已授权、已解锁且可从 Android 软件重启至 fastboot 的手机：
python3 -B lgg8/tests/run_multicore_ram_only.py --execute-ram-only --serial DEVICE_SERIAL
```

不加执行参数只核对制品。真机执行复用既有 USB 绑定、锁、截止时间、
Android 回收和分区哈希检查。探针另经 qemu-user 执行；同一 initramfs 中的
ARM64 BusyBox applet 与探针也经 qemu-user 验证回执，外层使用主机 shell。
该离线结果不替代真机记录。
本机新增采样测试及既有运行器、USB 适配、回收、上传回归共 22 项通过。

## 修正过的采样问题

前三次同一八核镜像的采样未获完整 PASS，均已正常回 Android：

1. `run-20261102-031449-4eb9d51e`：帧前缀不符合既有解析器契约。
2. `run-20261102-031746-0df48db9`：已读到八核，但目标 BusyBox 没有
   `taskset`，且全量 dmesg 超出解析器上限；改用原生探针。
3. `run-20261102-032229-682e5c7c`：八核执行及其余 CPU 回执通过，
   但 `dmesg -s 8192` 仍输出超限日志，因此整轮结果为失败。

最终使用 `set -o pipefail; dmesg | tail -c 8192`，限制输出并保留读取错误；
未放宽既有帧解析器。新增测试覆盖大日志、上游读取失败、逐核输出缺失、
校验失败、USB 绑定丢失以及诊断失败后保留已完成回执。

## 同日的电源与唤醒复测

- C234：`out/lgg8-c234-integration-20261101/run-20261102-030142-ed635222/`，
  64 项只读采样通过。
- freeze：`out/lgg8-pm-reconnect-20261101/system-freeze-20261102-030639-97f5bff4/`，
  内核有 s2idle entry/exit 和后续触摸；用户明确确认短按音量上后屏幕才恢复，
  随后按提示触摸。自动证据仍不宣称测得实际休眠时长、唤醒 IRQ 或功耗。
- 更早的 `system-freeze-20261102-030340-920fe244` 因桌面通知缺少会话
  D-Bus 地址，在请求 freeze 前退出；成功轮为通知进程提供了用户会话地址。
