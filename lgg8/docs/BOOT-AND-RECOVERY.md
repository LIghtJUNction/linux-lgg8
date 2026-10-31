# 临时启动、人工刷入与恢复

本页说明临时启动与人工刷入的步骤。历史候选已取得 RAM 启动、桌面和触控等分项真机证据，但不能转移到其他镜像；持久刷入的前置条件尚不具备。先完成 [离线验证](BUILD.md)，再按这里逐项记录真机证据。

## 四个不同的通过条件

| 阶段 | 可以确认的事实 | 不能据此确认的事实 |
| --- | --- | --- |
| 构建完成 | 生成 Image、板级 DTB、诊断 initramfs | 手机实际执行过这些文件 |
| 离线验证通过 | 工具检查范围内的格式、哈希、布局和容量正确 | USB、显示、触控、复位或桌面可用 |
| RAM 启动通过 | `fastboot boot` 后取得归属于该镜像的运行证据 | 已写入分区、冷启动通过、恢复不依赖原 Android |
| 持久刷入通过 | 指定分区回读匹配，冷启动与恢复分别验收 | 未测试的其他功能也可用 |

fastboot 返回 `OKAY` 只说明命令/传输阶段被接受。黑屏、花屏、USB 消失或稍后返回 Android 都不能独立证明 Linux 用户态运行成功。默认诊断 init 没有 USB gadget 配置和 shell，不能把“打包了 init”理解为必有可连的 USB 终端。

## 匹配设备并确认 b 槽

为同一台物理手机分别填写两个序列号占位符；不同协议下的序列号不保证相同。以下命令仅供人在对应模式中执行，不要整页批量粘贴：

```sh
ADB_SERIAL='<MATCHED_PHONE_ADB_SERIAL>'
FASTBOOT_SERIAL='<MATCHED_PHONE_FASTBOOT_SERIAL>'
```

在已安装 Android 中记录：

```sh
adb -s "$ADB_SERIAL" shell getprop ro.product.model
adb -s "$ADB_SERIAL" shell getprop ro.product.device
adb -s "$ADB_SERIAL" shell getprop ro.soc.model
adb -s "$ADB_SERIAL" shell getprop ro.boot.slot_suffix
adb -s "$ADB_SERIAL" shell getprop sys.boot_completed
adb -s "$ADB_SERIAL" shell cat /proc/sys/kernel/random/boot_id
```

目标是 LM-G820 家族、`alphalm_lao_com`、SM8150，历史实验具体对象为 LM-G820UM，槽位 `_b`。仅型号相同不足以匹配手机，还要核对人工选定的物理设备、序列号、系统身份与备份来源。新型号/新主板须另做适配，不沿用本页刷入结论。

进入真正的 bootloader fastboot 后，人工读取并保存：

```sh
fastboot -s "$FASTBOOT_SERIAL" getvar product
fastboot -s "$FASTBOOT_SERIAL" getvar is-userspace
fastboot -s "$FASTBOOT_SERIAL" getvar unlocked
fastboot -s "$FASTBOOT_SERIAL" getvar current-slot
fastboot -s "$FASTBOOT_SERIAL" getvar has-slot:boot
fastboot -s "$FASTBOOT_SERIAL" getvar partition-size:boot_a
fastboot -s "$FASTBOOT_SERIAL" getvar partition-size:boot_b
fastboot -s "$FASTBOOT_SERIAL" getvar slot-successful:b
fastboot -s "$FASTBOOT_SERIAL" getvar slot-unbootable:b
```

历史协议 product 是 `msmnile`，不应把它误认成 Android 的产品代号。要求已确认 bootloader 解锁、当前槽为 b、boot 分区有槽位且两槽容量明确；fastbootd 不能当作已验证的 bootloader 环境。若变量不支持、身份不符、槽位不是 b 或解锁状态不明，停止依赖这些条件的操作。锁定状态下不执行 RAM boot/flash，本页不提供解锁或绕过验证流程。

`getvar` 常把结果写入 stderr；保存记录时注意 `2>&1`。容量可能是十六进制，把本次 `boot_b` 的值换算成十进制字节数后填入打包工具：

```sh
python3 -c 'print(int("<EXACT_BOOT_B_SIZE_HEX>", 16))'
```

不能用 `max-download-size`、镜像大小或历史 96 MiB 代替目标分区容量。明确目标始终为 **boot_b**；`current-slot` 是人工核对条件，不用于脚本自动拼接分区，更不用于猜测“哪个槽空闲”。本流程不自动选择 inactive slot。

## 保存当前 boot_a 和 boot_b 的完整备份

备份必须来自这台手机、当前系统，分别覆盖准确的 `boot_a` 和 `boot_b`，保存到唯一备份根目录 `/home/lightjunction/Backups`。覆盖当前带软件 fastboot 修复的 Android boot 前，尤其要保留其原样副本；单纯原厂旧备份可能不包含该修复。

导出两份完整分区通常累计超过 100 MB，先按全局 `space-first` 技能检查空间、已有同项目备份及任务残留。以下示例需要当前 Android 有已验证的 root 读取能力；没有时先建立另一条已验证的备份路径，不继续刷入。

```sh
BACKUP_DIR="/home/lightjunction/Backups/linux-lgg8-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 "$BACKUP_DIR"
adb -s "$ADB_SERIAL" shell -T "su -c 'readlink -f /dev/block/by-name/boot_a'"
adb -s "$ADB_SERIAL" shell -T "su -c 'readlink -f /dev/block/by-name/boot_b'"
adb -s "$ADB_SERIAL" shell -T "su -c 'blockdev --getsize64 /dev/block/by-name/boot_a'"
adb -s "$ADB_SERIAL" shell -T "su -c 'blockdev --getsize64 /dev/block/by-name/boot_b'"
adb -s "$ADB_SERIAL" shell -T "su -c 'sha256sum /dev/block/by-name/boot_a /dev/block/by-name/boot_b'" \
  > "$BACKUP_DIR/device-before.sha256.txt"
```

确认分区链接、大小与目标匹配。先测试 root 二进制通道，不能仅凭 `exec-out` 名字认为没有换行转换：

```sh
python3 -c 'import sys; sys.stdout.buffer.write(b"A\nB\r\nC\x00D")' \
  > "$BACKUP_DIR/transport.expected.bin"
adb -s "$ADB_SERIAL" shell -T "su -c 'printf \"A\\nB\\r\\nC\\000D\"'" \
  > "$BACKUP_DIR/transport.actual.bin"
cmp "$BACKUP_DIR/transport.expected.bin" "$BACKUP_DIR/transport.actual.bin"
```

只有字节完全一致才继续；失败时检查传输和命令本身，不对分区镜像盲目替换 CRLF。逐份导出并核对退出码：

```sh
adb -s "$ADB_SERIAL" shell -T "su -c 'cat /dev/block/by-name/boot_a'" \
  > "$BACKUP_DIR/boot_a.raw.img"
adb -s "$ADB_SERIAL" shell -T "su -c 'cat /dev/block/by-name/boot_b'" \
  > "$BACKUP_DIR/boot_b.raw.img"
stat -c '%n %s' "$BACKUP_DIR/boot_a.raw.img" "$BACKUP_DIR/boot_b.raw.img"
sha256sum "$BACKUP_DIR/boot_a.raw.img" "$BACKUP_DIR/boot_b.raw.img" \
  > "$BACKUP_DIR/host.sha256.txt"
adb -s "$ADB_SERIAL" shell -T "su -c 'sha256sum /dev/block/by-name/boot_a /dev/block/by-name/boot_b'" \
  > "$BACKUP_DIR/device-after.sha256.txt"
```

逐一比较设备前后与主机 SHA-256，并核对每个文件长度恰等于对应分区容量。仅主机文件彼此一致不够；空文件或截断文件也能计算哈希。将设备身份、Android boot ID、槽位、分区链接/容量及导出命令写入备份记录。不要把 a/b 两份备份视作可互换，也不要把它们直接当作 v0 打包模板。

## 先做单次 RAM 临时启动

前提：已完成匹配、解锁状态核对、两槽备份和最终离线 verify；当前已安装 Android 可正常启动，软件 fastboot 路径及独立恢复条件已记录。

已安装 Android 的软件入口命令为：

```sh
adb -s "$ADB_SERIAL" reboot bootloader
```

随后重新执行目标 fastboot 的身份/槽位检查。不要把 ADB 命令退出成功当作进入 fastboot；确认该手机真实重新枚举并响应 getvars。临时启动使用刚刚验证、哈希未变的同一文件：

```sh
fastboot -s "$FASTBOOT_SERIAL" boot out/lgg8/boot/boot.img
```

该命令不写 boot 分区。记录镜像 SHA、开始时刻、USB 断开/重新枚举、屏幕人工观察和可读取的日志。默认 init 每约 5 秒列出 UDC、DRM、graphics 状态，约 45 秒请求复位，另有约 50 秒后备路径；这些时间从用户态执行算起，不是主机端返回时间承诺，也不是早期挂起的看门狗保证。

默认没有 gadget 配置和 shell。要验收 USB/shell，需要另外审查支持它们的内核/用户态候选，并取得该镜像特有的运行证据。桌面还需要独立的显示、输入及用户态验收，不能用 UDC 目录或花屏替代。

返回 Android 后，对同一手机复查 `sys.boot_completed`、槽位 `_b`、新 boot ID 和 **两槽分区 SHA-256**；应与备份时保持一致。Android 回来只证明回收，不自动证明主线执行到 PID 1。未取得可归属的运行证据时，结果记为“RAM 命令接受，功能未验收”，不进入持久刷入。

## 仅在条件满足后人工刷入 boot_b

**当前尚未满足本节前置条件，不应现在执行。** 必须先完成该候选的 RAM 实际运行验证，并确认写掉 Android `boot_b` 后仍能独立进入恢复环境、回读分区和恢复原像。依赖当前 Android 内核的软件 fastboot 不属于这种独立入口。

本节只适用于同一台已匹配、已解锁、明确处于 b 槽的手机，且精确备份、镜像哈希、离线验证、分区容量及恢复材料全部核对完毕。实际候选没有通过所需功能时，不因文件名是 `boot.img` 而放宽条件。

```sh
# 再读 unlocked/current-slot/product/partition-size:boot_b 并人工核对。
fastboot -s "$FASTBOOT_SERIAL" getvar unlocked
fastboot -s "$FASTBOOT_SERIAL" getvar current-slot
fastboot -s "$FASTBOOT_SERIAL" getvar product
fastboot -s "$FASTBOOT_SERIAL" getvar partition-size:boot_b
# 前置条件全部满足后，才执行这一条显式分区写入。
fastboot -s "$FASTBOOT_SERIAL" flash boot_b out/lgg8/boot/boot.img
```

这会替换 b 槽的 Android 启动镜像；**恢复原 `boot_b` 之前，b 槽 Android 可能无法启动，现有软件 fastboot 修复也可能不可用。** 不执行 `--set-active`、erase、vbmeta、ABL 或其他分区写入，不通过切槽“试一下”，也不自动刷 inactive slot。

刷后先回读、再考虑冷启动。fastboot `OKAY` 不能替代回读 SHA。只有已经实际验证支持的 fastboot fetch 或独立恢复环境可用于回读；本项目不保证 LG bootloader 支持 fetch，不保证候选有 ADB/root shell。缺少独立回读手段就是本节前置条件未完成。

如果回读得到完整 `boot_b.after.raw.img`，其长度须等于分区容量；检查与候选等长的前缀 SHA 是否一致：

```sh
python3 - out/lgg8/boot/boot.img /absolute/path/to/boot_b.after.raw.img <<'PY'
import hashlib
import pathlib
import sys
image = pathlib.Path(sys.argv[1]).read_bytes()
raw = pathlib.Path(sys.argv[2]).read_bytes()
if len(raw) < len(image):
    raise SystemExit('read-back is truncated')
expected = hashlib.sha256(image).hexdigest()
actual = hashlib.sha256(raw[:len(image)]).hexdigest()
print('candidate:', expected)
print('readback prefix:', actual)
print('full partition:', hashlib.sha256(raw).hexdigest())
if actual != expected:
    raise SystemExit('read-back does not match candidate')
PY
```

小于分区的候选与完整分区哈希通常不同；尾部不能默认全零。保存前缀匹配与完整分区哈希两项证据。之后才进行冷启动、功能验证和恢复演练，分别记录结果；本仓目前没有完成这些持久刷入验收。

## 恢复路径的实际边界

已验证的软件 fastboot 入口来自当前安装的 **Android 启动镜像补丁**。在其仍可启动时，`adb -s ... reboot bootloader` 曾经可靠进入 fastboot。覆盖该 Android boot 后，不能假设此入口继续存在。Android 在历史 RAM 实验后正常返回、boot_b 未变，也是过去运行的结果，不是未来候选的恢复保证。

物理下载入口只在同一台手机、当前条件下预先实测后才能列入恢复方案。历史记录使用过“完全关机、断开 USB、按住音量上、连接 USB、不按电源”的路径；这段历史不能保证覆盖 Android 后仍进入所需协议，也不能用看到下载画面代替可通信/可恢复的验证。

**EDL 9008 恢复未验证。** 出现 9008 不证明具备匹配并可用的 programmer、授权或分区恢复能力。当前没有请求修改 ABL，本页也没有 ABL 刷写步骤。

独立恢复入口已验证且 fastboot 确实可用时，恢复只写回同机、同槽、完整且哈希已核对的备份：

```sh
sha256sum "/home/lightjunction/Backups/<MATCHED_BACKUP>/boot_b.raw.img"
fastboot -s "$FASTBOOT_SERIAL" flash boot_b \
  "/home/lightjunction/Backups/<MATCHED_BACKUP>/boot_b.raw.img"
```

恢复后从可用环境回读完整分区，SHA 应与完整 `boot_b.raw.img` 一致，再检查 Android 正常启动、槽位仍 b、软件入口是否恢复。`boot_a` 备份保留，但不因为 b 出问题就刷 a 或切槽。没有可通信的已验证入口时，停止本页软件命令，不能把未验证 EDL 当作兜底。
