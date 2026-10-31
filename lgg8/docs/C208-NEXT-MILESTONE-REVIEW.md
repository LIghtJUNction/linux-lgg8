# LG G8：C208 后的证据约束攻关

日期：2026-10-31  
基线：`LIghtJUNction/linux-lgg8@dbff2e50685d2f87655179850bba0a9d54e08b27`  
独立分支：`lgg8/review-c208-drm-client-config`  
代码提交：`0eaf7ce5cf87a388cccdd3c2d4a480b158ef6624`

## 首选里程碑

**先验收同一次 RAM-only 启动中的可读 Weston 桌面与 ACM shell。** 下一次硬件候选复用 C208 原镜像，镜像零改动。先完成本机静态检查和当前 Android 的只读取证。

C208 镜像 SHA-256：

```text
3ead08159f1f99d7582ad21dd3af45b69bd05fe4e1ea8a9d99ab6d4b9c767176
```

当前 rootfs 已启动 Weston，并设置 require-input=false；无需先有触摸才能验收桌面。[S1][S2] 没有原 C208 制品或 manifest 时，先恢复精确制品身份，不把重新构建的镜像称为同一候选。

本轮完成源码审查、公开上游／LG 下游对照、主机校验补丁与测试；未访问、重启手机或运行 fastboot。C208 的设备结果来自用户记录及固定提交 STATUS，本轮没有重复设备验证。

## 证据排序与真实支持状态

| 项目 | 已知证据 | 未证明 |
| --- | --- | --- |
| C208 USB/ACM | 物理口 1-2、18d1:4ee7、shell 探针通过，519 行／39,716 字节 | 本轮未重跑 |
| C208 DRM | LOG=y、active=log，无 Unknown，有 DPU framebuffer 活动 | 屏幕可读、输出归属、Weston 可见 |
| Android 回收 | boot_completed=1、slot _b、boot ID 轮转、boot_a/b 哈希不变 | 不覆盖 PMIC SDAM、FG SRAM、触摸固件 |
| 充电 | simple-battery，SMB2 对象已编入 | PM8150B charger/FG、profile、温控和充电闭环 |
| 触摸 | GENI I2C 和 input 基础配置已开 | touchscreen child、SW42000 主线驱动、实际输入事件 |

强度依次是：同次真机完整回执；精确源码合同／匹配表；相邻候选受控对照；同板族下游参考；connector/fb0、历史目测与跨启动地址巧合。C196 缺 beacon、未试 gadget 的纠正保留，但已不能用于解释当前 USB。C208 已有 shell，不沿用旧版“无 ttyGS0 shell”结论。[S1]

## 充电：没有可直接启用的 PM8150B 支持闭环

板级 simple-battery 是静态描述，没有 monitored-battery 消费者。准确配置名 CONFIG_CHARGER_QCOM_SMB2=y 对应 qcom_smbx.o，其 match table 只有 qcom,pmi8998-charger 与 qcom,pm660-charger。驱动与仓库记载的官方基线 torvalds/linux@c03c1a14507dfaf8b856c2608f9ac216021fc222 的 blob 相同。[S3][S4][S5]

pm8150b.dtsi 没有本板 charger/FG 节点；VBUS regulator 与 Type-C 默认 disabled，板树未覆盖。die/charger temperature ADC 不是电池 thermistor、SOC 或 battery ID 的证据。SMB2 注册的是 USB supply，输入电流／电压属性不是电池 SOC。[S4][S6]

**不能假造 compatible 试 probe。** smb_probe 先执行 smb_init_hw，随后才读 battery info；初始化已修改充电、电流、Type-C、watchdog 等，后续还写 float voltage。失败的 probe 也可能已有副作用。本轮不提出任何猜测的寄存器、电流、电压或温控值。[S4]

公开 LG 下游固定参考为 LineageOS/android_kernel_lge_sm8150@f43e8f17061239356b05abc00a4dbbbf3b56eac8。它使用 qcom,qpnp-smb5 与 qcom,fg-gen4，并包含 BLT41 Tocad/LGC 两份 profile、battery ID 选择、LG 温度／电压保护、parallel 与 Qnovo 相关策略。它尚未与当前 Android 精确构建对齐。[S7][S8][S9]

下游某些 JEITA/battery-data 属性是 optional，不是所有 probe 的硬依赖；真正缺的是实际保护责任分工及选中 profile 的证据。FG 会写 profile SRAM，并通过 nvmem_device_write 写 PMIC SDAM 学习状态。**RAM-only 和 boot 哈希不变不能覆盖这些状态。** 本轮不新增或启用 charger/FG 节点。[S10][S11]

| 缺少的原厂信息 | 取得方式 |
| --- | --- |
| Android 内核构建、板 revision、有效配置 | uname -r、build fingerprint、hardware revision、可读的 /proc/config.gz |
| charger/FG/parallel 的真实驱动 | power_supply 父路径与 driver/of_node 链接 |
| 生效 DT／overlay、PMIC revision、IIO、PBS、SDAM、battery-data | 实际节点及 phandle 引用；仅从静态 DT 导出 |
| 实际 battery ID 与选中 profile | DT profile 容器及已有启动日志；未出现则保留未知 |
| 温控／充电保护责任分工 | 实际 LG protection、thermal、JEITA、parallel 配置与对应实现 |

无主线 charger 实例不等于物理上绝无充电；既存 PMIC 状态可能有影响，本轮没有测量。

## 触摸：控制器已开，缺协议驱动和本机硬件合同

板级 i2c17、qupv3_id_2 已启用；SoC 控制器是 i2c@c80000、GENI I2C，GPIO55/56 function qup17。没有 touchscreen child 或 SW42000 主线实现，也没有固定 i2c17 alias。因此不能假定运行总线编号为 17；0xc80000 是控制器 MMIO，不是触摸 slave address。[S3][S12]

公开下游普通 alpha_lao_com 启用 lge,sw42000@28，基础 DTS 给出 IRQ GPIO122、reset GPIO54、vdd GPIO152、vcl GPIO59，raw 最大坐标 1439×3119。存在多触摸方案和 early revision 差异，必须对照本机运行实例；这些值不是可直接写入主线的参数清单。[S13][S14]

SW42000 的专用两字节请求头与 132 字节触点报告不兼容通用 Synaptics RMI4、SiS 或 Silead。下游依赖 LG touch_core、复位／电源、显示选择与 firmware updater。lge.touchid=0 映射到 SIW，内部 TYPE_SW42000=9 不是应填写的 bootarg。[S15][S16]

先取得实际 input event → I2C client → driver/of_node 的对应关系，以及生效的 IRQ/reset/power/pinctrl/maker selection、board revision 和 input sysfs 的缓存能力。精确 ABS 数值范围需另用已核对实现的只读 EVIOCGABS 采集器。若实际绑定 Synaptics，就停止沿 SW42000 假设实现。

**不能递归 cat vendor touch sysfs。** 已核实读取 fw_upgrade 会排队固件升级，读取 click_test 会注入触摸。这不是泛泛风险提示，是下游 show 函数的实际行为。[S17]

确认器件后可独立开发最小协议驱动和离线报文解析测试，初版排除固件烧写、工厂测试、手势及 vendor sysfs。现在加一个无驱动节点不能产生触摸功能。

## 显示：保留已知参数，补齐画面与输出归属

C201 有 round_rate=-22 的实机日志；C202 改 lane rate 后曾有正常画面目测，但没有 ACM。C203 默认 fbdev 无 ACM；C206 空 client、C207 未编译的 log 选择、C208 真正 log client 均到达 ACM。对照支持优先调查 fbdev 初始化路径，尚未证明内部阻塞函数。[S1]

现有 SW43410 driver 已是 HS rate 836496000、1440×3120 模式与 DSC。不要把旧 Android 的时钟数字直接回填，也不新增 PLL/DSI/GPIO/splash 映射变量。[S18]

active=log 选择的是内核日志 client；它只在能取得 internal DRM master 时画日志，而现有 rootfs 之后仍启动 Weston。Weston 接管后日志不再继续画可以是正常行为。无 Unknown、framebuffer prepare、Weston 进程存在都不单独证明可读画面。**只见可读 boot log 算部分进展，不算本次“Weston 桌面＋ACM”验收。**[S2][S19]

## 无需真机重启的主机检查

以下是供维护者在已有源码目录执行的建议，不覆盖 dirty 工作区。源码身份检查先于任何构建。

```sh
BASE=dbff2e50685d2f87655179850bba0a9d54e08b27
git show --no-patch --format=fuller "$BASE"
git status --short
git grep -n -E 'CHARGER_QCOM_SMB2|DRM_CLIENT_(LOG|LIB|SETUP|DEFAULT)|DRM_FBDEV_EMULATION' \
  "$BASE" -- lgg8/configs/lgg8.config
git show "$BASE":drivers/power/supply/qcom_smbx.c |
  rg -n 'compatible|smb_init_hw|power_supply_get_battery_info|FLOAT_VOLTAGE'
git grep -n -E 'simple-battery|monitored-battery|smb5|fg-gen4|i2c17|sw42000' \
  "$BASE" -- arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dts \
  arch/arm64/boot/dts/qcom/pm8150b.dtsi
git grep -n -i -e sw42000 "$BASE" -- drivers/input/touchscreen \
  Documentation/devicetree/bindings/input
```

最后一项无匹配是该固定树的源码缺口；退出码 1 不算硬件失败。使用真实绝对路径设置 C208_IMAGE、C208_MANIFEST、C208_RAW：

```sh
printf '3ead08159f1f99d7582ad21dd3af45b69bd05fe4e1ea8a9d99ab6d4b9c767176  %s\n' \
  "$C208_IMAGE" | sha256sum -c -
python3 lgg8/tools/bootimg.py verify \
  --image "$C208_IMAGE" --manifest "$C208_MANIFEST"
rg -n 'Unknown DRM client|drm_client_lib.active|FB\[|frame done timeout|failed wait_for_idle|fault|LGG8_|weston|DSI' \
  "$C208_RAW"
```

核对 manifest 的 kernel/source-DTB/initramfs/cmdline/template 与 kernel-build receipt。seed config 不证明 Image 的有效配置。rootfs package-lock 仍锁旧 kernel，C208 kernel 是 2a9d1be7…765c9dcc；不要改一个锁值后继承旧 QEMU 验收。

补丁测试在独立 checkout 运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s lgg8/tests -p test_bootimg.py -v
```

本补丁未修改 DTS，无需重编内核或跑 QEMU。未来真的修改板级节点时，再针对精确 binding 和目标 DTB 做 schema／编译检查。

## 手机已在 Android 时的只读取证

下面命令均为建议，未执行。序列号仅本地使用；分享时删去序列号、IMEI、账户与无关日志。无权限的项目记为不可读取，不重启 adbd、不改 SELinux、不重新绑定驱动。

### 1. 身份、回收状态与服务缓存

```sh
LGG8_SERIAL='本地填写已确认的设备序列号'
adb -s "$LGG8_SERIAL" shell -T '
uname -r
getprop ro.product.model
getprop ro.product.device
getprop ro.build.fingerprint
getprop ro.boot.hardware.revision
getprop sys.boot_completed
getprop ro.boot.slot_suffix
cat /proc/sys/kernel/random/boot_id
dumpsys battery
'
```

仅用无参数 dumpsys battery；不执行 set/unplug/reset。它是 Android 状态，不是主线充电证据。使用此前已验证的 root 读取渠道取 boot 哈希；失效时记录，不临时改变权限：

```sh
adb -s "$LGG8_SERIAL" shell -T \
  "su -c 'sha256sum /dev/block/by-name/boot_a /dev/block/by-name/boot_b'"
```

### 2. 实际 power_supply、I2C、input 绑定

```sh
adb -s "$LGG8_SERIAL" shell -T '
for supply in /sys/class/power_supply/*; do
    [ -e "$supply" ] || continue
    printf "\nSUPPLY %s\n" "$supply"
    readlink -f "$supply"
    parent=$(readlink -f "$supply/device")
    while [ -n "$parent" ] && [ "$parent" != /sys ] && [ "$parent" != / ]; do
        [ ! -L "$parent/driver" ] || readlink -f "$parent/driver"
        [ ! -L "$parent/of_node" ] || readlink -f "$parent/of_node"
        parent=$(dirname "$parent")
    done
done
for dev in /sys/bus/i2c/devices/*; do
    [ -r "$dev/name" ] || continue
    printf "\nI2C %s\n" "$dev"
    cat "$dev/name"
    readlink -f "$dev/driver"
    readlink -f "$dev/of_node"
done
cat /proc/bus/input/devices
for event in /sys/class/input/event*/device; do
    [ -r "$event/name" ] || continue
    printf "\nINPUT %s\n" "$event"
    cat "$event/name"
    readlink -f "$event"
    [ ! -r "$event/capabilities/abs" ] || cat "$event/capabilities/abs"
done
cat /proc/interrupts
tr " " "\n" < /proc/cmdline | grep "^lge.touchid="
'
```

首批不包含 getevent -lp：核查的 AOSP 实现会以 O_RDWR 打开 event 并执行 EVIOCSCLOCKID，不应称为纯粹的缓存读取；当前只需 sysfs/proc 元数据就能确定绑定。后续若需要数值 ABS 范围，应核对运行工具实现或使用仅 O_RDONLY/EVIOCGABS 的采集器。[S23]

只提取已知 touch token，不输出完整 cmdline。对实际发现的 eventN，读 /sys/class/input/eventN/device 的链接，沿父路径关联到 I2C client；不要猜 bus number。

### 3. 定位实际 DT 与引用

以下 find/cat 仅限静态设备树文件系统：

```sh
adb -s "$LGG8_SERIAL" shell -T '
dtroot=/sys/firmware/devicetree/base
[ -d "$dtroot" ] || dtroot=/proc/device-tree
[ -d "$dtroot" ] || exit 2
find "$dtroot" -type f -name compatible |
while IFS= read -r property; do
    value=$(tr "\000" "\n" < "$property")
    case "$value" in
        *smb5*|*smb1355*|*fg-gen4*|*pm8150b*|*qnovo*|*veneer*|*sw42000*|*s3707*|*mdss-dsi-panel*|*sw43410*)
            dirname "$property"
            printf "%s\n" "$value"
            ;;
    esac
done
'
```

对实际发现的节点逐个保存属性，字符串用 tr，二进制 cells 用 od -An -tx1，保留原始字节并按大端解码：

| 子系统 | 必须取得的静态 DT 信息 |
| --- | --- |
| charger/FG | compatible/status/reg、interrupts/names、IIO、PMIC revision、PBS、SDAM/nvmem、battery-data、实际 thermal/JEITA/充电/profile 属性及子节点 |
| 触摸 | compatible/status/reg、interrupt-parent/interrupts/irqflags、reset/irq/power GPIO 或 supply、maker、pinctrl、max_x/y/id、reset delays、fw_image |
| 面板 | 实际 panel 名、command/video mode、timing/lane、DSC bpc/bpp/slice、clockrate、PHY timing、TE/pinctrl/supply |

qcom,battery-data 等 phandle 不是 profile 内容。取其原始大端值，再仅在 DT 内用 find 的 phandle 或 linux,phandle 属性与 od 找相同值，保存匹配节点和 profile 子节点。status 不存在不能当作 disabled。

若 Android 已有 tar，需保留完整的**已定位 DT 子树**时：

```sh
OUT=$(mktemp -d ./lgg8-c208-android.XXXXXX)
DT_NODE='填入上一步实际发现的 /sys/firmware/devicetree/base/...'
adb -s "$LGG8_SERIAL" exec-out tar -C "$DT_NODE" -cf - . \
  > "$OUT/selected-node.dt.tar"
```

每个节点用独立输出名，检查退出码、长度和归档内容。该命令只读静态 DT，归档写到主机。不要归档 vendor sysfs、整棵含设备身份的 DT、userdata 或整分区。

若可读，采相关有效配置：

```sh
adb -s "$LGG8_SERIAL" exec-out cat /proc/config.gz |
  gzip -dc |
  rg '^(CONFIG_(QPNP_SMB5|QPNP_FG_GEN4|SMB1355_SLAVE_CHARGER|LGE_PM[^=]*|LGE_TOUCH[^=]*|QPNP_QNOVO[^=]*)=|# CONFIG_(QPNP_SMB5|QPNP_FG_GEN4|LGE_PM[^ ]*|LGE_TOUCH[^ ]*) is not set)'
```

已有日志仅保留 SMB5/FG/profile/revision/触摸识别相关行。battery ID、profile 或 PMIC revision 未出现在缓存中就保留未知，不为补字段启动寄存器、I2C 或 MEMIF 探测。

### 4. 当前 Android 的显示对照

只读实际存在的 fb0 name、mode、modes、virtual_size、bits_per_pixel、stride 和 driver 链接，配合运行面板 DT。它用于确认 Android 真正在选哪个 profile，不直接生成主线时钟参数。

本批不用 i2cdetect/i2cget、new_device、bind/unbind、GPIO export、regmap/debugfs 寄存器读取或充电写入。power_supply getter 也不能统一承诺为“硬件零写”，所以优先取链接、DT、服务缓存，不扫描全部 uevent/IIO/vendor 属性。

## 下一次 RAM-only 视觉复测

**候选仍是原 C208，镜像零改动。** 本轮 packer guard 不要求重打包它。

1. 启动前核对镜像 SHA、manifest、当前 Android 的 boot_completed、slot、boot ID、boot_a/b 哈希，并沿用已验证的 pstore 快照。
2. 物理口 1-2 用现有被动监视器／sysfs 缓存观察。不要循环 fastboot getvar、USB reset 或 lsusb -v。启动只沿用已核对设备的 RAM-only fastboot boot 流程。
3. 从 Android → Linux → Android 全程拍摄屏幕，包含能与主机对齐的时间。需要读出 Linux 内容，不能以 LG 标志、亮屏或花屏代替。
4. 只有物理路径、18d1:4ee7、tty 父链都匹配后才用既有严格随机首尾标记的 ACM collector；不把命令回显当回执。
5. 原自动回收窗口内做一次短采样，不改变 watchdog：

```sh
cat /proc/uptime
cat /sys/module/drm_client_lib/parameters/active
cat /proc/consoles
cat /run/desktop-stage
cat /run/desktop-events.log
cat /run/weston.ini
tail -n 80 /run/weston.log
tail -n 30 /run/weston.stdout
```

由已有 collector 包裹严格起止标记、退出码与超时。若某个可选文件不存在，保留该结果，不把整个采集吞成成功。若已有 debugfs 挂载，确认实际路径后才读 dri/<minor>/internal_clients；其源码只列内部 client。没有挂载就记录，本候选不要求新增挂载。继续不读 per-CRTC status/state，不写 debugfs 控制。[S20]

6. 同一时间段 ACM 往返成功，手机上能读出当前 Weston 终端和桌面布局，才算 M1。只有可读 boot log 算部分显示进展；没有可靠实拍，显示仍未知。
7. 自动回 Android 后核对 boot_completed=1、slot _b、boot ID 轮转、boot_a/b 哈希一致与 pstore。保留视频、时间轴、collector 返回、manifest 和前后检查。

| 观察 | 下一步 |
| --- | --- |
| 可读 Weston 与 ACM 同时成立 | M1 可验收，随后评估触摸专用驱动 |
| boot log 可读、Weston 不可见 | 查 Weston backend、输出选择、接管时间与 client |
| 有进程／framebuffer 活动、黑屏或花屏 | 补同次 DPU/DSI/scanout 证据，不猜面板参数 |
| 相同原镜像不再有 ACM | 先核对制品、端口和回收，不能直接归因充电／触摸 |
| 回收失败、slot/哈希异常、明显温升／电池异常 | 停止后续试验，按既有已验证恢复流程处理 |

## 已提交改动与实际验证

[代码提交 0eaf7ce5cf87a388cccdd3c2d4a480b158ef6624][S21] 的父提交是本轮精确基线。本轮只更新独立审查分支，没有操作 lgg8/mainline。最终回读发现主分支已并行推进到 568959ead426fbcb13b8a2745583f848d090cf55，其父提交是 0eaf7ce5…，新增改动把测试临时目录放到项目 out/。下列测试结果覆盖 0eaf7ce5… 的实现，不覆盖该后续目录调整。

| 文件 | 改动 |
| --- | --- |
| lgg8/tools/bootimg.py | 构造 shim／发布镜像前检查显式 DRM client 与所提供配置 |
| lgg8/tests/test_bootimg.py | 新增 15 项行为及构建拒绝边界测试 |
| lgg8/docs/BUILD.md | 解释参数、无配置、模块和 provenance 边界 |

合同：log 要求 LOG=y；fbdev 要求 FBDEV_EMULATION=y；非空值需 LIB=y/m、SETUP=y；空值允许禁用；最终成功赋值的未知非空值按 packer 合同拒绝。扫描遵循内核双引号、名称 -/_、--、最后成功 setter，不误用 shell 单引号规则。

这解决 C207 暴露的无效打包输入，**不是显示修复**。配置无 receipt 时不能证明属于该 Image；无 --config 的路径和当前 rootfs/build.py pack 未被覆盖；LIB=m 也不证明实际模块加载。没有改内核、DTS、rootfs 或硬件参数。[S21][S22]

实际测试：

```text
42 tests discovered
29 passed
13 existing LLVM build integration tests skipped (toolchain absent)
All 15 new tests passed
```

构建拒绝测试确认 compile_shim/publish 未调用，输出目录不存在。实际补丁经过独立只读复核，远端逐字回读与父提交核对。本轮未跑全内核构建、QEMU 或真机验收。

## 自审

| 维度 | 结果 |
| --- | --- |
| 贡献 | 修复一个已出现的无效实验输入，未声称硬件修复 |
| 清晰度 | USB、boot log、Weston、触摸、充电分开标注 |
| 实验证据 | C208 属用户／仓库记录；新执行结果只限本机测试 |
| 完整性 | 明确 LLVM 跳过、receipt 边界、未运行硬件 |
| 方法 | 先读缓存与静态 DT；下一候选保持精确镜像不变 |

尚未完成：同次可见 Weston＋ACM、真实触摸输入，以及有原厂信息和保护责任分工支持的主线电源管理。

## 固定源码与证据

正文的 S1–S23 链接分别指向精确提交的状态、源码与补丁。公开 LG 下游仅作为参考，不冒充本机 Android 的精确构建。

[S1]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/lgg8/docs/STATUS.md
[S2]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/lgg8/rootfs/desktop-start.sh
[S3]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dts
[S4]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/drivers/power/supply/qcom_smbx.c
[S5]: https://github.com/torvalds/linux/blob/c03c1a14507dfaf8b856c2608f9ac216021fc222/drivers/power/supply/qcom_smbx.c
[S6]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/arch/arm64/boot/dts/qcom/pm8150b.dtsi
[S7]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/arch/arm64/boot/dts/qcom/pm8150b.dtsi
[S8]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/arch/arm64/boot/dts/lge/sm8150-alpha/sm8150-alpha_common/sm8150-alpha_common-pm.dtsi
[S9]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/arch/arm64/boot/dts/lge/sm8150_common/sm8150_common-pm.dtsi
[S10]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/drivers/power/supply/qcom/qpnp-fg-gen4.c
[S11]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/arch/arm64/boot/dts/qcom/sm8150-pmic-overlay.dtsi
[S12]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/arch/arm64/boot/dts/qcom/sm8150.dtsi
[S13]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/arch/arm64/boot/dts/lge/sm8150-alpha/sm8150-alpha-touch-sic-sw42000.dtsi
[S14]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/arch/arm64/boot/dts/lge/sm8150-alpha/sm8150-alpha_lao_com/sm8150-alpha_lao_com-touch.dtsi
[S15]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/drivers/input/touchscreen/lge/lgsic/sw42000/touch_sw42000.c
[S16]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/drivers/soc/qcom/lge/devices_lge.c
[S17]: https://github.com/LineageOS/android_kernel_lge_sm8150/blob/f43e8f17061239356b05abc00a4dbbbf3b56eac8/drivers/input/touchscreen/lge/touch_core_sysfs.c
[S18]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/drivers/gpu/drm/panel/panel-lg-sw43410.c
[S19]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/drivers/gpu/drm/clients/drm_log.c
[S20]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/drivers/gpu/drm/drm_client_event.c
[S21]: https://github.com/LIghtJUNction/linux-lgg8/commit/0eaf7ce5cf87a388cccdd3c2d4a480b158ef6624
[S22]: https://github.com/LIghtJUNction/linux-lgg8/blob/dbff2e50685d2f87655179850bba0a9d54e08b27/lgg8/rootfs/build.py
[S23]: https://github.com/aosp-mirror/platform_system_core/blob/android-9.0.0_r1/toolbox/getevent.c
