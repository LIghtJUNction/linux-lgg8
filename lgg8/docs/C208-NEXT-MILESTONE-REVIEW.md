# LG G8：C208 阶段审查与 M1 验收

日期：2026-10-31  
基线：`LIghtJUNction/linux-lgg8@dbff2e50685d2f87655179850bba0a9d54e08b27`  
独立分支：`lgg8/review-c208-drm-client-config`  
代码提交：`0eaf7ce5cf87a388cccdd3c2d4a480b158ef6624`

## M1：同次 Weston 桌面与 ACM 已通过

Candidate C208-R3 复用原 C208 镜像，镜像零改动。用户在 Linux 阶段观察到蓝色背景、终端和极简桌面；同一启动的 ACM shell 严格标记探针通过。按本项目验收条件，M1 已通过。用户同时报告 Linux 阶段没有触控响应，触摸仍未适配。

C208 镜像 SHA-256：

```text
3ead08159f1f99d7582ad21dd3af45b69bd05fe4e1ea8a9d99ab6d4b9c767176
```

当前 rootfs 启动 Weston，并设置 require-input=false；无需先有触摸才能验收桌面。[S1][S2] R3 使用已核对的原始 C208 制品，没有重新构建镜像。

## 证据排序与真实支持状态

| 项目 | 已知证据 | 未证明 |
| --- | --- | --- |
| C208-R3 USB/ACM | 物理口 1-2、18d1:4ee7、标记探针通过；519 行／39,716 字节 | 不证明其他镜像的 USB 行为 |
| C208-R3 显示 | 用户观察到蓝色背景、终端和极简桌面；用户态标记含 Weston 工作进程 | 没有录像，画面观察来自用户报告 |
| Android 回收 | boot_completed=1、slot _b、boot ID 轮转、boot_a/b 哈希不变 | 不覆盖 PMIC SDAM、FG SRAM 或触摸固件 |
| Android 充电绑定 | 当前 Android 的 battery/dc/main/pc_port/usb supply 归属 qcom,qpnp-smb5；bms 归属 qcom,fg-gen4 | 不证明本仓主线有充电支持或本轮实测充电闭环 |
| Android 触摸绑定 | I2C client 4-0028 名称 sw42000、驱动 lge_touch、运行 DT compatible lge,sw42000；用户报告 Linux 阶段无触控 | 不证明本仓主线有 SW42000 驱动或触摸输入 |

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

SW42000 的专用两字节请求头与 132 字节触点报告不兼容通用 Synaptics RMI4、SiS 或 Silead。下游依赖 LG touch_core、复位／电源、显示选择与 firmware updater。[S15][S16] 下游 `devices_lge.c` 对 `lge.touchid=0` 的选择解释，与本机 Android 运行态中 `4-0028` 已绑定 `sw42000` 的观察需要结合该 ROM 的精确构建与选型路径继续核对；不能仅凭 bootarg 推断驱动绑定。

Android 只读采集已把 input event、I2C client、driver 与 of_node 的一部分关系连起来：运行态出现 `4-0028` / `sw42000` / `lge_touch`，触摸 IRQ 行名为 `lge_touch`，输入列表含 `touch_dev`，bootarg 为 `lge.touchid=0`。运行设备树还包含 `synaptics,s3707` compatible，但本轮没有发现相应 I2C client；这只限本次采集结果。下一步仍需采集 SW42000 节点实际生效的 IRQ/reset/power/pinctrl/maker 属性、board revision 和缓存能力；精确 ABS 数值范围需另用已核对实现的只读 EVIOCGABS 采集器。

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

下面命令是只读采集示例。C208-R3 已执行身份字段、power_supply/I2C/input 绑定、触摸相关中断行、`lge.touchid` 和已知电源/触摸 compatible 子集；完整电池 profile、目标节点的全部属性与 `/proc/config.gz` 尚未采集。序列号仅本地使用；分享时删去序列号、IMEI、账户与无关日志。无权限的项目记为不可读取，不重启 adbd、不改 SELinux、不重新绑定驱动。

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

## C208-R3：视觉复测记录与证据

镜像 SHA-256：`3ead08159f1f99d7582ad21dd3af45b69bd05fe4e1ea8a9d99ab6d4b9c767176`。候选通过 manifest 与组件哈希预检，执行 RAM-only `fastboot boot`，没有使用 `flash`、`erase` 或其他分区写入命令。

同次启动证据：

- 物理 USB 1-2 的 Fastboot `18d1:4ee0` 出现，随后断开；Linux Gadget `18d1:4ee7` 于 +37.077 秒出现，ACM `ttyACM0` 绑定到该物理端口。
- ACM shell 探针随机首尾标记、snapshot 与 dmesg 退出码全部通过；收到 519 行、39,716 字节，38 行包含 DRM/DPU 诊断特征。
- 用户在这段 Linux 阶段看到蓝色背景、终端和极简桌面；同次启动用户态状态包含 `WPROC=1`。这不是独立录像证据，故明确标注为用户观察。
- USB 于 +93.935 秒断开；Android ADB 在 +114.027 秒恢复。整轮 124.51 秒完成。
- Android 回收后仍为 LM-G820 / alphalm_lao_com、slot `_b`、`boot_completed=1`；boot ID 轮转，boot_a 与 boot_b 哈希均未变，且 boot_b 仍匹配已知基线。启动前、早期回连和回收后 pstore 快照均通过清单及源哈希核验。
- 用户未观察到 Linux 触控响应。该候选没有 SW42000 主线驱动和板级触摸节点；此结果与当前代码缺口一致，不能据此断言控制器或面板损坏。

本次测试结束后在 Android 中做了只读 sysfs/proc/运行设备树采集，结果仅保存在忽略目录 `out/lgg8-c208-drm-log-enabled/run-03/android-readonly.txt`。运行 Android 的 SMB5/FG 驱动绑定与本仓主线状态分开记录，不能拿 Android 驱动绑定代替 Linux 适配验收。

继续限定在静态运行设备树和 `/proc/config.gz` 的只读采集中：SW42000 节点 `status=okay`、I²C 地址 `0x28`、中断号 122；相邻 `synaptics,s3707@20` 节点 `status=disabled`。运行配置包含 `CONFIG_LGE_TOUCH_LGSIC_SW42000=y`、`CONFIG_QPNP_SMB5=y`、`CONFIG_QPNP_FG_GEN4=y`、`CONFIG_SMB1355_SLAVE_CHARGER=y`、`CONFIG_QPNP_QNOVO5=y` 和 `CONFIG_LGE_PM=y`。节点同时含 GPIO、pinctrl、面板选择和测试属性；本轮只读取了属性名及必要的 compatible/status/reg/interrupts 字节，尚未读取或应用复位／供电脚值、坐标、profile 内容或测试控制属性。Android 配置属于当前已安装系统，不声称是 LG 原厂构建。

SMB5 与 FG GEN4 的 `qcom,battery-data` 引用值可见，但 profile 节点和选中 battery ID 未完成解析；因此仍不能确定主线充电所需的电芯曲线、保护责任分工和安全参数。宽范围扫描 phandle 超过了 35 秒只读采集期限，未留下结果文件；不把它算作采集成功，也没有重试全树扫描。

### 后续 RAM-only 复测流程

如果需要重复显示验收，仍复用原 C208 镜像，镜像零改动；本轮 packer guard 不要求重打包它。

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

6. 本次同一启动中 ACM 往返成功且用户观察到终端与极简桌面，已满足 M1。若后续需要形成录像证据，再从 Android → Linux → Android 同步记录；只有可读 boot log 仍只算部分显示进展。
7. 自动回 Android 后核对 boot_completed=1、slot _b、boot ID 轮转、boot_a/b 哈希一致与 pstore。保留视频、时间轴、collector 返回、manifest 和前后检查。

| 观察 | 下一步 |
| --- | --- |
| 可读 Weston 与 ACM 同时成立 | C208-R3 已验收 M1；接着评估 SW42000 专用驱动 |
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
