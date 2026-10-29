# 构建与离线验证

以下命令从仓库根目录执行。设备相关步骤集中在 [BOOT-AND-RECOVERY.md](BOOT-AND-RECOVERY.md)；本页的编译、打包和测试不需要连接手机。

## 依赖

宿主为 Linux。内核使用 LLVM 工具链交叉编译 ARM64；原生诊断 init 另用 GNU ARM64 编译器静态链接。打包工具需要 Python 3、设备树工具及 LLVM 汇编/链接工具。以下是常见依赖包名；发行版镜像的可用版本以本机包管理器为准。

| 用途 | Arch Linux 常见包 | Debian/Ubuntu 常见包 |
| --- | --- | --- |
| Git、make、宿主编译环境 | `git base-devel` | `git build-essential` |
| LLVM 编译/链接/objcopy | `clang llvm lld` | `clang llvm lld` |
| 内核配置与生成依赖 | `bc bison flex openssl libelf ncurses` | `bc bison flex libssl-dev libelf-dev libncurses-dev` |
| Python、DTB、cpio、压缩 | `python dtc cpio gzip` | `python3 device-tree-compiler cpio gzip` |
| GNU ARM64 静态 init | `aarch64-linux-gnu-gcc`、配套 `aarch64-linux-gnu-glibc` | `gcc-aarch64-linux-gnu libc6-dev-arm64-cross` |
| 可选真机工具 | `android-tools` | `adb fastboot` |

如果配置启用 BTF，还需要提供 `pahole` 的包（Arch 通常为 `pahole`，Debian/Ubuntu 通常为 `dwarves`）。不需要为了离线构建安装桌面系统、Android SDK 全套或刷机 GUI。

```sh
command -v git make clang ld.lld llvm-objcopy python3 dtc fdtget cpio gzip
command -v aarch64-linux-gnu-gcc aarch64-linux-gnu-readelf
```

命令存在不证明静态 libc 齐全；`initramfs` 构建和 ELF 检查才验证实际链接结果。

## 空间与内存

完整源码、`.git`、对象文件和打包中间文件可能累计超过 100 MB。执行构建、复制模板、导出分区或新增源码工作树之前，先用全局 `space-first` 技能检查实际写入目录。人工操作至少检查：

```sh
df -h . /home/lightjunction/Backups
free -h
# 只检查存在的相关目录；工具缺失时用窄范围 du -sh 替代，不自动安装。
test ! -d out || timeout 20s ionice -c 3 dust -d 1 out
test ! -d out || timeout 20s prefixlens out --summary
test ! -d private || timeout 20s ionice -c 3 dust -d 1 private
test ! -d private || timeout 20s prefixlens private --summary
```

超时不等于目录为空。根据目标配置、现有构建目录及并存候选预留数 GB 至数十 GB，不能把 100 MB 触发阈值当作容量预算。默认 `JOBS=2` 是保守并发起点，不是内存足够的保证；内存/交换空间紧张时改用 `JOBS=1`，避免与其他大型编译并行。不要使用无上限的 `-j$(nproc)` 来覆盖脚本默认值。

复用一个 `out/lgg8` 做增量构建；只有确实需要对照时才保留第二套对象目录。清理时逐项确认属于本次任务、未被运行中的构建引用，保留最终镜像、对应 manifest、有效模板、未提交源码及唯一恢复备份。不为整理输出而执行 `git clean -fdx`。系统回收站内的文件仍占用磁盘，移入回收站不能算作已释放空间。

## 获取源码

需要完整源码文件即可构建，不必下载全部 Linux 历史：

```sh
git clone --depth=1 --branch lgg8/mainline \
  https://github.com/LIghtJUNction/linux-lgg8.git
cd linux-lgg8
git fetch --depth=1 origin tag v7.3
git remote add upstream https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git
```

上述 `clone` 用于新目录。已有本地项目只检查 `git remote -v`，不要重复添加或覆盖 remote。
浅克隆适合构建；准备合并上游更新时，须先确认共同祖先可见，并按需加深对应历史。
历史下载同样先做空间检查，不默认获取全部上游标签。

## 确认源码身份

```sh
git rev-parse v7.3^{commit}
git rev-parse HEAD
git status --short
git diff --stat
```

官方基线应为 `c03c1a14507dfaf8b856c2608f9ac216021fc222`。开发提交增加后，HEAD 可以不同；需同时记录基线、实际 HEAD 和工作区差异，不能仅记录标签。未跟踪的 LG 文件也属于构建输入，不能遗漏。

`lgg8/configs/lgg8.config` 是完整配置。使用脚本复制/更新到输出目录，不另行套用不相关 defconfig。配置经 `olddefconfig` 处理后，实际生效配置是输出目录的 `kernel/.config`；应记录它与输入配置的差异。

## 编译内核、板级 DTB 与原生 init

```sh
./lgg8/build.sh kernel out/lgg8
./lgg8/build.sh initramfs out/lgg8
```

只修改设备树时，用单独的 DTB 目标缩短迭代，不重编 Image：

```sh
./lgg8/build.sh dtb
# 显式指定与 Image 相同的输出目录：
./lgg8/build.sh dtb out/lgg8
```

输出仍为 `out/lgg8/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb`。修改后重新执行 `boot` 和 `verify`，避免把新 DTB 与旧镜像混淆。

省略最后一个参数时同样使用 `out/lgg8`。低内存环境可执行：

```sh
JOBS=1 ./lgg8/build.sh kernel out/lgg8
```

预期关键产物：

```text
out/lgg8/kernel/.config
out/lgg8/kernel/arch/arm64/boot/Image
out/lgg8/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb
out/lgg8/initramfs/initramfs.cpio
```

内核脚本使用 `ARCH=arm64 LLVM=1`，默认任务数 2，可由 `JOBS` 覆盖。
默认构建时间固定为官方 v7.3 提交时间，构建者/主机名固定，
`LOCALVERSION` 默认显式为空以避免 Git dirty 状态改变版本字符串；
可通过 `SOURCE_DATE_EPOCH` 和 `LOCALVERSION` 明确覆盖，覆盖后记录这些输入。`initramfs` 使用 `aarch64-linux-gnu-gcc` 编译仓内原生 init 并静态链接，不能用宿主 `/bin/sh` 代替。原生 PID 1 的默认约 45 秒复位、RAM 临时文件和日志/设备检查属于诊断行为，不提供桌面验收，也不保证早期挂起后的恢复。

脚本的可用空间下限分别为：`kernel` 至少 4 GiB，`dtb` 至少 256 MiB。这是启动检查的下限，不是完整构建的空间保证；输出目录必须专用，非空且缺少 `.lgg8-build` 标记时会拒绝使用。不要为了绕过保护给未知目录随意补标记。

最小产物检查：

```sh
test -s out/lgg8/kernel/arch/arm64/boot/Image
test -s out/lgg8/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb
fdtget out/lgg8/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb / compatible
cpio -it < out/lgg8/initramfs/initramfs.cpio
sha256sum lgg8/configs/lgg8.config out/lgg8/kernel/.config \
  out/lgg8/kernel/arch/arm64/boot/Image \
  out/lgg8/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb \
  out/lgg8/initramfs/initramfs.cpio lgg8/boot/cmdline.txt
```

CPIO 列表应包含可执行 `/init`。检查原生 init 构建产物：

```sh
aarch64-linux-gnu-readelf -h out/lgg8/initramfs/init
aarch64-linux-gnu-readelf -l out/lgg8/initramfs/init
```

前者应确认 Machine 为 AArch64，后者应确认无动态解释器 `INTERP`。仅检查 cpio 中“有 init”不足以证明它能作为 PID 1 执行。

## 可选：在本机运行真正的诊断 PID 1

安装提供 `qemu-system-aarch64` 的包后，可用同一 Image 和 CPIO 跑一次虚拟 ARM64 启动：

```sh
timeout 90s qemu-system-aarch64 \
  -M virt,gic-version=3 -cpu cortex-a76 -smp 1 -m 512M \
  -nodefaults -display none -serial stdio -monitor none -nic none -no-reboot \
  -kernel out/lgg8/kernel/arch/arm64/boot/Image \
  -initrd out/lgg8/initramfs/initramfs.cpio \
  -append 'console=ttyAMA0 rdinit=/init panic=5 loglevel=6' \
  > out/lgg8/qemu-console.log 2>&1
rg 'LGG8-SOURCE-INIT: (PID1 entry|diagnostic deadline reached)' \
  out/lgg8/qemu-console.log
```

应同时看到 PID 1 入口与约 45 秒后的截止日志，并正常退出；仅有 QEMU 退出码不够。
这使用虚拟板和 QEMU 自动生成的设备树，验证通用启动和原生 init 的执行流程，
不模拟手机的 ABL/shim、RPMh、USB PHY 或屏幕。该检查约需一分钟，
日常修改先运行秒级的 `test` 和单独的 `dtb` 构建。

## 为什么必须准备经验证的 v0 模板

本项目封装路径采用 **Android boot header v0、4096 字节页、gzip 压缩 shim 及其载荷，并追加已知 stock DTB 段**。shim 是一段启动交接代码，负责把主线 `Image`、initramfs 和 Linux 板级 DTB 交给内核；stock DTB 段用于现有 bootloader 兼容封装，不能替代新编译的 Linux 板级 DTB。

概念布局如下，偏移、地址和对齐以工具实际解析/验证为准：

```text
Android boot v0 / page_size=4096
  kernel 区：gzip(shim + 主线 Image + initramfs + Linux DTB + 对齐填充)
            + 已核对的 stock DTB 段
  其他 header/ramdisk/填充字段：按已验证模板及工具约束处理
```

这不是“把 DTB 直接拼到 Image 后就能刷”。板级 DTB、boot header、bootloader 看到的 stock DTB 和内核最终收到的 FDT 各有职责。ARM64 入口、地址重叠、保留内存、initrd 边界与传入寄存器仍需各自验证。

模板必须来自本机已经明确来源、校对 SHA-256 的 **v0 候选封装**。真实 OEM/Android 分区备份可能是 v2，可能带完整分区填充或 AVB 元数据；它是恢复材料，不天然适合 `prepare-template`。不能把文件名含 `stock`、来自同机或 `unpack` 成功当作模板兼容证明。

旧实验曾出现 root 二进制导出的 LF→CRLF 转换；后来已纠正。不得据坏导出推断 OEM 加密、特殊 wrapper 或损坏 FDT，也不要对新文件盲目做 CRLF 替换。先验证传输，再核对设备端哈希、完整长度、gzip CRC 和 DTB 结构。格式检查通过也不构成 OEM 签名认证。

准备模板从本地镜像读取输入，并写入新的输出目录。先创建父目录 `private`，**不要预先创建 `private/template`**；工具要求输出目录不存在，不覆盖已有模板。

```sh
mkdir -p private
python3 lgg8/tools/bootimg.py prepare-template \
  --from-boot '/absolute/path/to/verified-v0-candidate/boot.img' \
  --sha256 '<EXACT_SOURCE_BOOT_SHA256>' \
  --output private/template
```

SHA 必须来自独立可信记录，不能仅对随手拿到的未知文件算一次哈希就称为来源已验证。输入不符合 v0/4K/shim/stock DTB 约束、来源哈希不匹配或输出冲突时，应修正输入，不绕过检查。模板与原始镜像保留在本地，不提交设备私有输入。

## 打包 boot.img

`PARTITION_SIZE` 是经过人工核对的 **boot_b 实际字节数**，不是剩余磁盘空间、fastboot 最大下载尺寸或沿用旧手机的常量。获取方法见 [设备预检](BOOT-AND-RECOVERY.md#匹配设备并确认-b-槽)。历史分区容量不能替代本次核对。

脚本入口（默认输出 `out/lgg8/boot/{boot.img,manifest.json,linux.dtb}`）：

```sh
TEMPLATE_DIR="$PWD/private/template" PARTITION_SIZE='<BOOT_B_BYTES>' \
  ./lgg8/build.sh boot out/lgg8
```

脚本还支持 `INITRAMFS`（外部 cpio）、`CMDLINE_FILE`（命令行文件）、`BOOT_OUTPUT`（打包目录）覆盖；不设置时使用本仓默认输入。`boot` 只打包已有产物，不代替 `kernel`/`initramfs` 编译，脚本不执行手机命令。

外部 `INITRAMFS` / `--initramfs` 输入有以下格式要求：

- 必须是**未压缩的 newc CPIO**（`070701`），不支持直接传入 gzip、xz、zstd 压缩归档、拼接的多个归档或任意发行版完整 initrd。
- 默认入口 `/init`（或命令行 `rdinit=` 指定的入口）必须可执行，并最终解析到归档内的静态小端 AArch64 ELF；脚本入口的解释器也必须在归档内，最终使用静态 AArch64 解释器。动态 ELF/动态解释器不受支持。
- 普通文件不支持 hardlink，必须以独立文件内容存储，链接计数为 1。不能用硬链接别名替代经过检查的 init 或解释器。

封装检查只确认这些结构条件；自定义 init 的挂载、设备访问、日志和复位行为由其自身实现，不能沿用默认诊断 init 的行为说明。

直接调用打包工具，便于显式核对所有输入（这里演示独立命名的输出目录）：

```sh
python3 lgg8/tools/bootimg.py build \
  --kernel out/lgg8/kernel/arch/arm64/boot/Image \
  --dtb out/lgg8/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb \
  --initramfs out/lgg8/initramfs/initramfs.cpio \
  --template private/template \
  --cmdline-file lgg8/boot/cmdline.txt \
  --partition-size '<BOOT_B_BYTES>' \
  --output out/boot-TIMESTAMP
```

将 `TIMESTAMP` 替换为本次唯一标识，避免覆盖其他候选。记录工具实际打印的镜像和 manifest 路径。默认命令行不含 `initcall_blacklist`，不得为复用旧候选而悄悄加回它。分区容量检查只防止镜像越界，不证明 bootloader 接受、签名有效或设备可启动。

## 离线测试与产物验证

仓内回归测试入口（只运行本地测试，不访问手机）：

```sh
PYTHONDONTWRITEBYTECODE=1 ./lgg8/build.sh test
```

等价的直接入口：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s lgg8/tests -p 'test_*.py' -v
```

必须看到实际发现并运行的测试数量；`Ran 0 tests` 不算通过。测试应覆盖正确输入及错误 SHA、格式/页尺寸、模板损坏、镜像篡改、manifest 不一致、分区容量不足等拒绝路径；截至 2026-10-29，46 项本地测试已通过；修改工具或输入约束后应重新运行。

默认脚本产物使用：

```sh
./lgg8/build.sh verify out/lgg8
sha256sum out/lgg8/boot/boot.img
```

若打包时设置 `BOOT_OUTPUT`，验证时也必须设置为同一个目录。对前面直接调用工具生成的独立目录执行：

```sh
python3 lgg8/tools/bootimg.py verify \
  --image out/boot-TIMESTAMP/boot.img \
  --manifest out/boot-TIMESTAMP/manifest.json
sha256sum out/boot-TIMESTAMP/boot.img
```

当前 manifest 文件名为 `manifest.json`；路径应与该次输出目录一致。镜像与 manifest 必须来自同一次构建，不能拿旧报告验证新文件。manifest 本身也是可信输入：若镜像和它一起被替换，仅两者相互匹配不能证明来源。核对 header v0、页尺寸 4096、gzip 完整性、stock DTB 保留、Linux DTB/initrd 布局、输入/输出哈希和分区上限；未实现的检查不能以人工期望冒充工具已验证。

验收记录至少包括上游基线、实际 HEAD/dirty 差异、有效配置 SHA、Image/DTB/initramfs/cmdline SHA、模板来源 SHA、目标分区容量、镜像 SHA、测试数量与退出码、最终 verify 输出。测试和 verify 均通过后只能标记 **离线通过，真机未验收**。当前完整内核/DTB 构建、46 项本地测试、boot.img 打包与最终 verify 均已通过；同一内核和 CPIO 已在 QEMU virt 中进入 PID 1 并按期复位。详见 [LOCAL-VALIDATION.md](LOCAL-VALIDATION.md)。源码基线及迁入文件来源见 [PROVENANCE.md](PROVENANCE.md)。

## 更新上游而不覆盖 LG 改动

官方版本通过指定标签跟踪；板级 DTS、面板/DSC、配置及本目录工具保留在 `lgg8/mainline`。升级时从 LG 分支创建独立维护分支，审查合入后再更新主开发分支。合入前确认没有无关 dirty 工作；存在时先协调或使用单独工作树，不 reset/clean 现有树。

核对远端 URL、工作区和目标标签后，按需执行：

```sh
git remote -v
git status --short
# upstream 应指向官方 Linux 来源；名称或 URL 不符时先核实。
NEW_TAG='vNEXT'  # 替换为本次选定的实际官方标签。
git fetch --no-tags upstream "refs/tags/$NEW_TAG:refs/tags/$NEW_TAG"
git show --no-patch --format=fuller "$NEW_TAG^{commit}"
# 核对标签来源与提交，并审查升级范围后，在独立维护分支合入。
git switch -c "lgg8/update-$NEW_TAG" lgg8/mainline
git merge --no-commit --no-ff "$NEW_TAG^{commit}"
```

这里只获取选定标签及其所需对象，不使用全量 `--tags` 获取。独立维护分支的名称应未被使用，核对标签后再合并。不要把 `git reset --hard upstream/...` 当作升级步骤，也不要用旧树整个覆盖新基线。遇到冲突逐项审查保留内存、DTS 绑定、面板/DSC 和配置变化；合并内容未确定时不要编译并宣称升级成功。

上游变更后重新生成配置、编译、运行离线测试并重新打包。旧模板可以重新检查兼容性，但旧 Image 偏移、旧二进制绕过及旧验收结果不能继承。更新后将实际版本、文件哈希及本地检查结果记入 [LOCAL-VALIDATION.md](LOCAL-VALIDATION.md)。
