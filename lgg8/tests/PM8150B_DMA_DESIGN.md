# PM8150B Gen4 SRAM DMA 温度事务：离线草案

此目录中的 Python 模型只操作内存字典。没有硬件后端、设备访问、内核接线、
模块加载、adb、子进程或运行时网络请求，也不创建临时文件。
`read_temperature()` 仅接受精确的 `FakeRegmap` 类型，拒绝替代后端和子类。
这是一道防误用措施，不是 Python 的安全隔离机制。

**写入安全尚未证明，保持离线。** 模拟通过只能说明这里定义的错误处理符合
测试契约，不能证明真实 PMIC 的寄存器副作用、访问权、传感器有效性或恢复安全。

## 固定源码与复核范围

复核 LineageOS `android_kernel_lge_sm8150` 提交
`d4f335e13d73c4aa2af85581a6ec11b670ee5b94`，不是移动分支。
源码在设计阶段读取，离线测试不下载、不依赖源码树。以下行号为原文件的 1-based 行号。

| 原文件及定位 | 复核结论 |
| --- | --- |
| [qpnp-fg-gen4.c:153–154、798–816、5822–5834](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-fg-gen4.c#L798) | 温度位于 word 328、offset 0，读取 2 字节；bit 9 符号扩展，乘 100 除 40 得到 0.1°C。PM8150B 选择 DMA；V1 设置 DMA workaround。 |
| [fg-memif.c:796–921](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-memif.c#L796) | V1 先等待算法不活跃；仲裁请求、DMA 请求、40–41µs 延时、Gen4 grant 轮询；释放先 DMA 后仲裁。 |
| [fg-memif.c:923–943、1015–1092、1169–1206](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-memif.c#L923) | 地址映射和直接读事务。word 300–405 对应 DMA4，温度不跨分区。 |
| [fg-reg.h:295–316、363–380](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-reg.h#L295) | PEEK、grant、请求掩码和 DMA4 地址常量。 |
| [fg-memif.c:1208–1283](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-memif.c#L1208) | Gen4 每 word 2 字节；DMA 初始化还有清错、分区寻址、初始释放、仲裁配置和 PEEK_MUX 配置写入。 |
| [fg-util.c:635–666](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-util.c#L635) | 调用层持 `sram_rw_lock`，有 awake vote；DMA 失败不会转 IMA。battery_missing 时直接返回成功，不能照搬为有效温度。 |

已读取原始字节的 SHA-256：

```text
fg-memif.c       84e7790e991d86984ce5d69c954192261f3ceb6f24f7cb855ed8bfd3036f4efc
qpnp-fg-gen4.c   58446c6df9296b27c13d10c812026e8dba34c60fda83bd875d2b99838bbbe2f0
fg-reg.h         973bfbd039ba9cdd455866acabbdc9d5469bdb989bd1332e78d787583c8e2a02
fg-util.c        6ffb5cec6f9d944cc4fb58c95ffa853dc183c3b63b00a7760d42331cc327e37e
```

## 事务与源码差异

模型将 MEM_IF base 固定为 `0x4300`、BATT_INFO base 固定为 `0x4100`。
这些是模拟配置，不是对运行设备地址、subtype 或 revision 的检测结果。
温度 DMA 地址由源码表推导为 `0x4800 + 0x20 + (328 - 300) * 2 = 0x4858`，
一次读取 `0x4858–0x4859`，明确按小端解码。符号范围为 -128°C 至 127.75°C；
0.1°C 整数转换沿用 C 向零截断，因此 -0.25°C → -2，127.75°C → 1277。
不返回 Android LG 补偿后的温度，也不把编码范围当作电池合理温度范围。

| 次序 | 模拟操作 | 对应行为 |
| --- | --- | --- |
| 1 | 锁定同一 FakeRegmap，检查前提与占用 | 新增：拒绝未知 revision、未初始化、缺电池、陈旧数据或被隔离的接口。预读两处请求字段，已占用则不写也不清理。 |
| 2 | V1：读 `0x41ef` bit 3，最多 35 次 | 下游算法活跃等待；每次仍活跃延迟 10000µs，成功后 1000µs。PEEK 配置未经模拟声明时拒绝。 |
| 3 | `update_bits(0x4340, 0x01, 0x01)` | 下游仲裁请求。写前即标记需要清理。 |
| 4 | `update_bits(0x4350, 0xa0, 0x80)` | 下游 DMA 请求，同时清除 IACS 选择位。 |
| 5 | 延迟 40µs；读 `0x4310` bit 3，最多 50 次 | 沿用下游次数和延迟下界；每次未授权延迟 10000µs。V1 成功后额外 1000µs。 |
| 6 | 读 2 字节并解码 | 读失败或短读均不发布温度。没有缓存回退。 |
| 7 | `update_bits(0x4350, 0xa0, 0)` | 清理 DMA 请求；失败后继续下一步。 |
| 8 | `update_bits(0x4340, 0x01, 0)` | 独立清理仲裁请求。 |
| 9 | 分别读回两个字段 | 新增验证；两次都尝试。只验证请求字段，不假定 grant 立即撤销。 |

下游的三个重要缺口：首次仲裁写失败直接返回；DMA 清理失败跳过仲裁清理；
request/data 原始错误可能被 release 错误覆盖。此草案有意改进这些路径，
**并非逐条复刻下游的错误行为**。一旦请求写被尝试，无论写是否报错，
两步清理和两次读回都各执行一次；未开始请求则不擅自清理。
寄存器其余位通过掩码保留。失败后不重试请求、不转 IMA、不清错、不 dump 寄存器。

`Result.errors` 按出现顺序保留所有错误。`rc` 优先返回原始请求、授权或读数错误；
主体成功时返回第一个清理/验证错误。任何错误都使 `decicelsius=None`。
`cleanup_verified=None` 表示未尝试请求，`True` 仅表示模拟清理与读回无错误。
任一清理写或读回失败，即使写实际已经生效且随后读回为零，也返回 `False`，
并将整个 FakeRegmap 隔离，后续事务在任何寄存器操作之前被拒绝。
不提供自动解除隔离或“再清一次就恢复”的接口。

所有模拟客户端共享 FakeRegmap 的锁，覆盖前提检查、请求、等待、数据与清理。
它不模拟外部总线主机；预读与锁不能排除硬件、固件或其他驱动竞争。

## 尚未证明的前提

`initialized`、`peek_configured`、`battery_present`、`sample_fresh` 都是离线测试输入，
默认拒绝，不能作为真实设备的有效性证据。模型没有执行下游初始化写序列，
也没有证明主线启动时的 DMA 分区模式、PEEK_MUX、awake vote、算法状态及访问所有权。
这里的轮询上限只限制调用次数和虚拟延迟，不限制真实总线单次阻塞时间。
完整无短读也不能证明传感器更新、样本新鲜度、校准或硬件测量正确。
失败后强制清理是否安全、是否影响其他控制器、错误是否需要更深恢复，同样未证实。

因此本草案没有新增驱动、Kconfig/Makefile、设备树或 sysfs 路径。
未来接入硬件需要单独审查上述前提及独立温度测量，不属于本次实现。

## 离线验证

在仓库根运行，禁止生成字节码缓存：

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s lgg8/tests -p 'test_pm8150b_dma.py' -v
```

测试覆盖：精确成功事务和掩码保留；全部 1024 个编码及高位忽略；两次请求各自
在写生效前/后失败；50 次授权超时和最后一次授权；授权状态读取失败；数据读失败
和短读；两个清理步骤单独/同时失败并组合主体错误；读回失败；清理不确定后隔离；
已有访问权不被清除；缺失/陈旧输入；V1 延迟、超时、PEEK 失败；拒绝硬件式后端；
前次成功不会掩盖本次失败。时间由 FakeRegmap 累计，不进行真实 sleep。
