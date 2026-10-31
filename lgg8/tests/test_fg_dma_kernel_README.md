# 实际内核草案源码的离线故障注入

在仓库根运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python lgg8/tests/test_fg_dma_kernel_run.py
```

需要 Linux 用户态 C 编译器、pthread、ASan/UBSan 和 Python 3。不需要内核构建、
设备、网络或权限提升。编译器临时目录显式设在本目录下的
`test_fg_dma_kernel_build_*` 专用目录；退出时删除本次目录，不使用 `/tmp`。

`test_fg_dma_kernel_source.c` 直接 `#include` 当前
`drivers/power/supply/qcom_fg_dma_experimental.c`，没有复制或改写事务逻辑，
没有重定义 `static`。实际 `.c` 仍包含实际 `.h`。
runner 在构建目录生成 Linux API 转接头，并由
`test_fg_dma_kernel_shim.h` 提供内存 regmap、pthread mutex、虚拟时钟和延迟。
Linux errno 使用主机 UAPI 定义。测试前后校验实际 `.c/.h` 的 SHA-256。

执行顺序和覆盖：

1. **首先测公开入口硬阻塞**：填满伪造审核字段和成功回调，必须仍返回
   `-EOPNOTSUPP`。断言回调、mutex、总线 API、格式查询和延迟均未调用，
   不发布温度；空 result 返回 `-EINVAL`。此行为不依赖证据真实性判断。
2. **仅在离线测试编译单元内调用 static draft**：空参数、逐项缺证据、未知版本、
   到期证据、缺回调、已占用锁、map 格式、各阶段动态拒绝；确认拒绝不释放别人的锁。
3. 源码 preflight 的每项错误和每次读失败：subtype、V2 PEEK、分区模式、DMA 状态、
   busy、C220 `0x04`、遗留 grant。未请求时禁止擅自释放或写寄存器。
4. 两次请求分别在写未生效/已生效后报错；grant 读失败、50 次超时、最后一次授权、
   轮询中证据到期；数据读失败和部分缓冲区已写但返回错误。
5. 两次释放和两次读回的全部 16 种报错组合，分别组合主体错误与请求/释放写是否
   生效；核对完整有序错误链（最多五项），首错不被覆盖，四步清理均独立尝试。
   另测无报错但释放写未生效，由读回发现请求位仍在。
6. 所有请求后失败隔离，下一次 draft 调用零总线访问；即使清理字段读回成功也
   不解除隔离。任何失败都清空温度和有效标志，后期动态检查也能阻止发布。
7. 成功路径的精确总线顺序、位保留、四次动态验证，以及全部 1024 个 10-bit
   温度编码（含高位忽略及负数向零截断）。所有总线替身均断言本线程持锁。

普通优化构建和 ASan/UBSan 构建分别运行全部用例；sanitizer 检出错误即失败。
测试代码编译必须带 `TEST_FG_DMA_KERNEL_OFFLINE`，没有内核模块、导出符号、
probe、Kconfig/Makefile/DT 接线或硬件后端。公开入口没有任何绕过机制。

## 边界

这是**实际事务源码在 API 替身下的控制流测试**，不是内核运行时测试，也不声称
执行了 Linux regmap/cache/SPMI 实现。mutex 使用 pthread，锁拒绝测试为确定性的
已持锁场景，不是并发压力测试。时间是虚拟时间，不能证明真实调度或总线超时上限。
regmap 的短读处理、缓存、全字节读改写副作用、外部总线主机竞争、PMIC 算法、ADC
恢复、实际样本有效性和硬件安全均未验证。测试审核字段明确是假数据，不能用于
解除硬件阻塞；公开入口应继续保持硬性禁用。通过测试不是启用许可。
