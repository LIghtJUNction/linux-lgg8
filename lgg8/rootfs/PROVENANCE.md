# 输入、插件和验收边界

构建输入由 [package-lock.json](package-lock.json) 锁定。每个 APK 的 URL、精确版本、实际 SHA-256、aarch64/noarch 架构和验证结果都记录在其中。仓库 APKINDEX 的 C 字段不是这里计算的 SHA-256；aports commit 是索引中的构建来源元数据。没有重新编译发行版包。

## 信任与数据来源

- ARM 基础归档：[Alpine 3.24.3 aarch64 mini](https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/aarch64/alpine-minirootfs-3.24.3-aarch64.tar.gz)，SHA-256 `4d3f80afaebd447c5591a63a73bde380a149fe8b2d85488cafabb2ff97551f50`。复用已有同哈希归档。
- 验证工具归档：[同版本 x86_64 mini](https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-minirootfs-3.24.3-x86_64.tar.gz)，SHA-256 `f8e1cafba9b1b283b5d30d06f9885c8d2bc161ffe9083ade8e2e157813a53407`，3704080 字节。作为 HTTPS 发布元数据/SHA-256 锁定的自举信任输入；不是声称 root tar 自身通过 APK 签名验证。
- 主仓库：[v3.24/main/aarch64](https://dl-cdn.alpinelinux.org/alpine/v3.24/main/aarch64/APKINDEX.tar.gz)。
- 社区仓库：[v3.24/community/aarch64](https://dl-cdn.alpinelinux.org/alpine/v3.24/community/aarch64/APKINDEX.tar.gz)。
- 包验证使用自举根自己的 x86_64 apk 3.0.8、musl 和库，读取 ARM mini 的 Alpine 公钥；每个 APK 都独立验证签名，不用 `--allow-untrusted`。参考 [apk verify 手册](https://raw.githubusercontent.com/alpinelinux/apk-tools/v3.0.8/doc/apk-verify.8.scd)。
- 用 [apk extract](https://raw.githubusercontent.com/alpinelinux/apk-tools/v3.0.8/doc/apk-extract.8.scd) 提取文件，无安装脚本、trigger 或包依赖求解。最终根没有伪造的 installed 数据库。实际保留文件以 file-origins.json 为准。

锁定 URL 所在的 v3.24 仓库仍会变化。复现优先使用已保存且重新核验 SHA-256 的 APK 缓存；若文件消失或哈希改变，停止，不静默升级或换成 edge。

## ELF 以外的加载路径

| 路径 | 当前策略 | 已验证范围 |
| --- | --- | --- |
| libweston pixman renderer | 编译在 libweston 内，显式 renderer=pixman | QEMU 日志显示 Using Pixman renderer，并有两条实际提交/完成的帧链 |
| headless-backend.so | 仅显式 QEMU profile 加载 | 已在同一 ARM 根运行 |
| drm-backend.so | 手机默认；真实链接 libgbm/libva/libseat/libinput 等小型库均保留 | ELF 依赖闭包通过；设备调用未测试 |
| desktop-shell.so / libexec_weston.so / helper | 保留，配置明确选择 desktop-shell | 模块及 helper 启动，终端 surface 实际配置并完成 frame callback |
| gl-renderer / PipeWire / remoting / 其他后端 | 文件移除，配置不选择，不自动 fallback | CPIO 文件清单和关键文件审计可核对 |
| libseat | 固定 LIBSEAT_BACKEND=seatd；无需启动 elogind | libelogind 链接库仍按实际 NEEDED 保留；seatd 手机分支未在 headless 中执行 |
| GBM/Gallium | libgbm.so 保留；未包含 Mesa DRI/Gallium 插件 | Weston 明确 pixman 分支用 dumb buffer；实际 DRM 模式设置仍需设备验收 |
| 字体/xkb/udev 数据 | 保留 Liberation Mono、fontconfig、键盘规则和输入规则 | 文件/哈希检查通过；终端实际启动和提交 buffer；触控识别未验收 |

DRM 的 pixman 分支与 GL 初始化分开，见 [Weston 14.0.2 drm_backend_create / init_pixman](https://raw.githubusercontent.com/wayland-mirror/weston/14.0.2/libweston/backend-drm/drm.c)。这支持裁剪设计，但不是实际 LG KMS/scanout 的证明。没有选择 VAAPI 录屏、EGL、远程输出或 GPU 加速路径。

seatd 的 socket 是编译期路径，版本 0.9.3 不接受 `-s`；[该版本手册](https://raw.githubusercontent.com/kennylevinsen/seatd/0.9.3/man/seatd.1.scd) 明确 `SEATD_VTBOUND=0` 表示不绑定 VT。这个设置仅适用于当前单会话 RAM 原型。DRM card/connector 从实际 sysfs 取得，模式选 preferred；没有 headless 兜底。

终端使用 [Weston 14.0.2 --shell 入口](https://raw.githubusercontent.com/wayland-mirror/weston/14.0.2/clients/terminal.c) 启动自带英文 banner 脚本；shell 执行标记、buffer attach/damage/commit 和绑定 callback.done 同时成立后，才报告本地用户态通过。

## 保留与恢复界限

CPIO、boot.img、静态监督入口和源文件的最终哈希在 out/lgg8/desktop/provenance.json；QEMU 报告同时绑定实际 Image、CPIO 与原始日志哈希。手机镜像使用 DRM 命令行，QEMU 参数只存在于测试报告。打包显式传入已核验模板和已确认容量，没有旧实验 manifest、默认容量或私人工作区路径依赖。

PID1 按 960 字节以内的记录将 RAM 文本日志镜像到 kmsg，console 仍用于本地测试捕获。QEMU 已观察到实际 printk 镜像，不能推导 pstore、Android 读取、跨重启保留或日志完整性；限流及写入丢失仍可能发生。90 秒计时器是用户态恢复措施，也不是任意硬卡死的恢复保证。

此目录没有设备操作步骤。离线格式检查、QEMU headless 用户态和真实手机 DRM/触控/桌面是不同验收状态；后续 C208-R3 获得可见桌面与同次 ACM 证据，C210 获得用户触控确认，具体范围和限制见 [状态记录](../docs/STATUS.md)。这些后续结果不改变本文件所述历史镜像的验收状态。
