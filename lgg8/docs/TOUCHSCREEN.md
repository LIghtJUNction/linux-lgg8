# LG G8 ThinQ touch support

## Current state

The `lgg8/sw42000-touch` branch contains an initial mainline driver for the
SW42000 controller at I²C address `0x28`. The current Android kernel's
`lge,sw42000` runtime node was read without accessing touch sysfs, issuing I²C
transactions, or changing GPIOs. Its IRQ, reset, power, and coordinate values
match the pinned LineageOS `alphalm_lao_com` device tree. The raw Android
captures are under the ignored `out/lgg8-c208-drm-log-enabled/run-03/` folder.

The driver and board node are implemented. The standalone parser test and the
full configured kernel build pass. `dt_binding_check` and targeted validation
of the compiled LG G8 DTB also pass. Candidate C210 was booted with `fastboot
boot`; the user confirmed touch input worked on the Linux desktop. The phone
returned to Android with `boot_completed=1`, and both boot partition hashes
were unchanged. ACM serial permissions prevented collecting the Linux dmesg
snapshot, so probe-log confirmation remains unavailable.

## What the driver does

- Uses the QUP SE17 I²C client at `0x28`, GPIO 122 falling-edge IRQ, reset GPIO
  54, VCL GPIO 59, and VDD GPIO 152.
- Uses the observed reset and rail sequence: reset low, VDD/VCL low, 1 ms off,
  VCL then VDD high, 10 ms settling, reset high, then 40 ms boot delay.
- Reads the four-byte version and read-only boot CRC/pass/info-pointer
  registers. It requires chip ID 10, protocol version 4, the expected boot CRC,
  and nonzero boot-pass/info-pointer values before writing controller setup.
- Enables the normal I²C interface, scan mode and interrupt register, then
  reports up to ten MT contacts using the observed 1440×3120 coordinates.
- Rejects a zero contact count, matching the downstream driver's invalid-frame
  rule. An UP-only packet releases the prior slot; a palm packet clears active
  contacts.
- Applies the common device-tree axis inversion and swap properties when
  reporting positions. Raw coordinates are bounded to their configured
  pre-transform minima and maxima before inversion. Invalid or unrepresentable
  axis ranges are rejected before powering on the controller. The current LG
  G8 device tree does not request inversion or swapping; these options have
  local behavioral coverage but have not been exercised on the phone.

The 132-byte report format and register sequence were checked against
LineageOS `android_kernel_lge_sm8150` commit
`f43e8f17061239356b05abc00a4dbbbf3b56eac8`, files
`drivers/input/touchscreen/lge/lgsic/sw42000/touch_sw42000.c` and
`touch_sw42000.h`.

The driver now also has system suspend/resume callbacks: it synchronizes and
disables the IRQ, releases active touches and stops scanning before suspend;
on resume it checks firmware, restarts normal scanning and reenables the IRQ
only after initialization succeeds. The callbacks retain the touch power
rails and do not request gesture wake or clock-off mode. This path has local
simulated fault and concurrency coverage but has **not** been tested on the
phone. It cannot yet recover from lost controller power or clock state. If
resume or recovery from an aborted suspend fails, the IRQ stays disabled; the
driver does not automatically retry, and input remains unavailable until a
later successful resume or rebind.

The driver does not contain firmware upgrade, bus factory-test, gesture or
vendor sysfs code. It does not read or write firmware files. Real-device
suspend/resume remains open. A later RAM-only run captured Linux EVIOCGABS
ranges and a contact event, with the qualifications recorded below.

## Offline parser check

```sh
python3 -m unittest lgg8.tests.test_sw42000_parser -v
python3 -B lgg8/tests/test_sw42000_pm.py
python3 -B lgg8/tests/test_sw42000_coordinates.py
```

The parser fixture uses an isolated work directory under `out/lgg8/validation/`
and removes it after the test. It covers field decoding, two contacts, UP
release, zero and oversized counts, truncated reports, duplicate IDs,
non-touch interrupts, and palm cancellation. The PM test compiles production
functions against simulated I²C, input and IRQ APIs; it exercises 73 normal,
fault and in-flight IRQ sequences. The coordinate test compiles the production
range validation and reporting functions with the kernel's real touchscreen
property parser and transform helper. A fake input device covers each
inversion/swap combination, boundary clamping and invalid ranges.
These tests do not exercise real hardware.

## Build and device acceptance

Build the kernel and board DTB with the repository's existing output directory:

```sh
JOBS=2 ./lgg8/build.sh kernel out/lgg8
```

Run the repository's DT schema check for this binding when the host has the
kernel `dt-schema` tooling installed. Package the resulting Image and DTB with
the existing verified boot template, then use `fastboot boot` only. Do not
write boot, abl, or other partitions for the touch experiment. Keep physical
USB port 1-2 passive monitoring and compare Android boot completion, slot, and
boot partition hashes before and after.

For repeat acceptance, confirm that `LG SW42000 Touchscreen` appears in
`/proc/bus/input/devices`, then tap and drag on the Weston desktop. Candidate
C210 passed the user's tap/drag observation. Probe logs, suspend/resume, and gesture support remain open. A later
RAM-only run captured Linux EVIOCGABS ranges; parser and build success alone do
not establish any of these behaviors.

C234 booted the newer touch driver from source revision
`2cac5083555092d953d7ec439385a7ffd16d197f` and observed a single
`LG SW42000 Touchscreen` input device with an `event2` handler and a GPIO 122
IRQ whose counter was zero in both snapshots. The other boot inputs matched
C232; the kernel included several later changes. The phone
returned to Android with both boot partitions unchanged. This run did not
collect a touch gesture, test suspend/resume, or validate a wakeup path; it
only confirms registration during this normal boot. The result is recorded in
`out/lgg8-c234-integration-20261101/run-20261101-045735-f7dc0504/result.json`.

Do not treat the current recovery timer as a tested wakeup mechanism. The
C234 kernel configuration includes `CONFIG_QCOM_WDT=y`, but the mainline
`qcom-wdt` driver's late system-sleep callback calls `qcom_wdt_stop()` when
`watchdog_active()` is true and restarts it on resume. Thus an active watchdog
cannot be assumed to reset the phone after a hang later in suspend; clock and
reset behavior are also unverified on this device. The callback is conditional,
so this source finding does not establish whether a watchdog was active or
stopped in any particular boot. This is a separate device from the SMB5 charger
watchdog. See [qcom-wdt](../../drivers/watchdog/qcom-wdt.c).

The user has offered to attempt a manual wake. Static inspection of the
RAM-only touch candidate's compiled `linux.dtb` shows `wakeup-source` on
`/gpio-keys/key-vol-up` and `qcom,pm8941-pwrkey` on the PON power-key node;
its kernel configuration enables `CONFIG_SUSPEND`, `CONFIG_PM_SLEEP`,
`CONFIG_KEYBOARD_GPIO` and `CONFIG_INPUT_PM8941_PWRKEY`. The power-key driver
defaults this compatible to wake-enabled and arms IRQ wake when allowed.
These are candidate inputs, not evidence that either physical key can wake this
phone or recover a hung PM callback. On 2026-11-01, with the phone running Android and the user operating the
power and volume-down keys, a manual restart was observed: USB disconnected,
Android returned with a new boot ID, slot `_b` and unchanged boot partition
hashes; passive USB 1-2 monitor coverage and integrity passed. The record is
`out/lgg8-touch-candidate-20261101/manual-restart-20261101-080825-b14b230a/`.
Android was responsive before this test, so this does not establish whether the
key path can reset a hung Linux kernel or wake it from suspend. Normal Android
reboots should be initiated through ADB rather than asking the user to press
buttons. Manual wake cooperation does not replace
an independently verified hang-recovery path. A real experiment still needs
bounded capture, explicit stop conditions and before/after Android/slot/boot
verification; do not equate screen-off with completed system suspend.
For interpreting a future `freeze` test, kernel source increments
`/sys/power/suspend_stats/success` when `enter_state()` returns zero, but
`s2idle_loop()` can exit on an already-pending wakeup before it waits in
`s2idle_enter()`. A successful write or counter increment therefore does not
alone prove a nonzero sleep interval. Capture the selected state, entry/exit,
wakeup evidence and an independently meaningful interval as well as touch
events after resume; if those observations are unavailable or ambiguous,
report only the observed PM transition, not verified sleep duration. See
[suspend core](../../kernel/power/suspend.c) and
[suspend statistics](../../kernel/power/main.c).

A later
read-only Android root snapshot identified `rtc0` as the PM8150 Qualcomm RTC;
`/proc/driver/rtc` reported `alarm_IRQ: no` and `alrm_pending: no`, and
`/sys/power/state` listed `freeze mem`. The RTC date read as 1970-01-08, not
wall time. The snapshot is retained at
`out/lgg8-qemu-pm-paired-20261101/observations/android-rtc-readonly.stdout`.
It does not establish the clock's offset, wake capability, future alarm
ownership, or that an alarm will recover a hung suspend. No alarm was set.
Mainline `rtc-pm8xxx` probe enables the RTC; setting an alarm disables its
existing alarm, writes alarm registers and may re-enable it. Its set-time path
can also write an offset to persistent storage or modify the hardware clock.
Thus adding this driver is not a passive observation, and its effects and
wake path must be independently reviewed before a phone experiment.

The C234 configuration lacks `CONFIG_PM_DEBUG` and has the PM8xxx RTC driver as
a module not included in the initramfs. The user-space guardian can be frozen
during system sleep, and the Qualcomm watchdog driver stops an active
watchdog in its suspend callback. No automatic wake source or hard recovery
deadline has been verified on this phone.

A diagnostic kernel can enable `CONFIG_PM_DEBUG` and select `devices`
in `/sys/power/pm_test` to exercise device suspend/resume without entering
platform sleep. The PM core calls `dpm_suspend_start()` (prepare and normal
suspend callbacks), then tests `TEST_DEVICES` before `suspend_enter()`; it does
not reach late/noirq device suspend in that successful test path. Its default
five-second test delay runs only after normal callbacks return, and an already
pending wakeup can shorten it. The qcom watchdog stop callback is a *late*
suspend callback, so it is not reached on this successful `devices` test
path. Neither fact proves a watchdog is active, will fire, or can recover an
earlier hung callback; user-space helpers can also be frozen. First validate
the PM flow locally and establish a practical recovery method. Neither this
test nor a returned USB connection proves real sleep, wakeup, or touch input
after resume. Do not count injected input events as physical touch acceptance.

A separate diskless QEMU `virt` test now exercises this actual userspace
`pm_test=devices` entry, using the complete SW42000 driver and simulated I2C,
GPIO and IRQ. In the normal boot, simulated stop/active writes increased by
2/1; with the driver's PM table deliberately removed, they increased by 0/0.
Both boots logged the five-second PM test delay, suspend exit and clean module
teardown. Seven existing PM cases and the non-virt rejection also passed.
The `s2idle` entry banner identifies the requested mode, not actual entry:
`pm_test=devices` stops before `suspend_enter()`. The saved run is
`out/lgg8-qemu-pm-debug-20261101/runs/run-20261101-084239-81e607bd/`.
A follow-up repeated the system PM operation twice in the same boot: each
normal cycle again produced 2/1 stop/active writes, while both negative-control
cycles remained 0/0. The repeat is retained at
`out/lgg8-qemu-pm-debug-20261101/runs/run-20261101-084448-e8577319/`.
Its private kernel, headers and symbol list came from one fresh build; the
kernel-only `vmlinux.symvers` was copied into that private build for module
modpost. This does not repair or prove C232 ABI compatibility and it does not
exercise actual phone hardware, late/noirq suspend or real sleep.

A private local-only diagnostic kernel was built at
`out/lgg8-pm-test-20261101/kernel/` from tracked commit
`9c58979846d96501a4136b17bab7226cbe625bdd`. Its effective config differs from
the preceding touch candidate only by enabling `CONFIG_PM_DEBUG` and its
`CONFIG_PM_SLEEP_DEBUG` dependency; `CONFIG_PM_ADVANCED_DEBUG` and
`CONFIG_PM_TEST_SUSPEND` remain disabled. The resulting Image SHA-256 is
`1d600d62f6c6c88204d32f0414fc87d0e453f316bf9d13f5404a7c8c86cb2b7d`,
and its compiled DTB matches that candidate byte for byte (SHA-256
`90cd099ecb1666a9547c22a15fb88d441daef5d01240d672832655c76d2a9c86`).
The build log and named artifact hashes are in that output directory. This is
not a boot image and has not been run in QEMU or on the phone. Both its
configuration and the preceding `out/lgg8/kernel/.config` have
`CONFIG_QCOM_WDT=y` but `CONFIG_WATCHDOG_SYSFS` disabled: the latter means the
watchdog's optional identity/state/timeout sysfs attributes are not available.
Do not treat a failed attribute read as evidence that the watchdog did not
register. Opening `/dev/watchdog*` to issue an identity or timeout ioctl is
also not a passive substitute: the watchdog core starts the timer on open.
Its unexpected close need not stop the timer. Any such test therefore needs an
explicit bounded arming, disarming/reboot and recovery plan, and must not be
reported as a read-only observation. Driver presence and a device-tree node do
not establish that this boot registered a working watchdog.
[Watchdog core](../../drivers/watchdog/watchdog_dev.c).

A subsequent RAM-only boot of the known touch candidate observed `/proc/misc`
listing minor 130 `watchdog`; `/sys/class/watchdog/watchdog0/device` resolved
to `/sys/devices/platform/soc@0/17c10000.watchdog`, whose driver link resolved
to `/sys/bus/platform/drivers/qcom_wdt`. This is read-only registration and
binding evidence for that boot, not proof the timer was active or can reset
hardware. No watchdog device was opened and no suspend was attempted. The
session verified USB port 1-2 monitoring and Android/slot/boot-hash recovery;
its unauthenticated USB capture and complete receipts are retained at
`out/lgg8-touch-candidate-20261101/watchdog-registration-20261101-095242-306b1a80/`.

`lgg8/tests/qcom_watchdog_probe.c` is an offline-tested preparation for an
explicit arming/reset experiment, **not yet integrated into a guarded phone
runner and not approved for direct execution**. It starts a watchdog on open,
checks identity and capabilities, requests 10 seconds, and tries magic close on
all ordinary exit paths. That close can fail or be disallowed by nowayout; a
killed or hung process may leave the timer running. Ten fake-backend scenarios
test sequencing and failure paths, not hardware. A future supervised experiment
needs bounded deadlines, validated identity and recovery before opening the
device, retained timing/serial evidence, and post-reset Android/slot/hash
checks. A disconnect or reboot alone cannot establish watchdog causality.

More importantly, an awake watchdog-reset test would not establish recovery
from the full suspend sequence: `qcom_wdt_suspend()` stops an active watchdog
in the late suspend callback and `qcom_wdt_resume()` restarts it. Recovery
coverage therefore depends on where a hang occurs, and whether the timer and
its clock actually run at that point; neither has been proven. Do not run the
awake probe merely to claim a suspend hang is recoverable. A separate,
independently validated recovery mechanism is still required before relying
on unattended suspend testing.

A narrower possible experiment is `pm_test=devices`: in the current kernel,
`kernel/power/suspend.c` checks that test immediately after
`dpm_suspend_start()` and returns before `suspend_enter()` reaches late
suspend, so the Qualcomm watchdog's *late* suspend callback is not called on
that successful path. This source ordering does not establish watchdog clock
continuity, its actual reset behavior or recovery from a hang; those would
need separate evidence. It also is not real system sleep. QEMU has exercised
this entry path already, but a phone test remains unperformed.

## QEMU PM build-pairing blocker

The draft run at
`out/lgg8-c234-integration-20261101/qemu-pm-draft/run-20261101-055926-7c284170/`
never ran its PM scenarios: the guest rejected module version
`7.3.0-lgg8+` against kernel `7.3.0-lgg8`.
Do not remove the suffix and assume ABI compatibility.

A read-only follow-up audit is reproducible with:

```sh
python3 -B lgg8/tests/check_qemu_build_pairing.py --self-test
python3 -B lgg8/tests/check_qemu_build_pairing.py
```

For the current C232 build, the audit deliberately exits 1
(`PAIRING_REJECTED`). Image SHA-256 remains
`d4a37b083e0bc025247760166ebdce45eebae3c2b5db41e53dd83f8fec8bb2d2`;
the receipt, embedded IKCONFIG, `.config` and generated `autoconf.h` agree.
The ELF export sections match the corresponding Image bytes, but
`Module.symvers` claims **13,386** built-in exports against **12,893** in the
binary, including **493** extra names (predominantly tracing-related).
The configuration disables FTRACE. Thus this is not just a release-string
mismatch: the existing symbol manifest is not an exact export inventory of
this Image. Preserve `out/lgg8/kernel` unchanged while investigating a private
reproducible build. The audit does not prove source/header ABI compatibility,
namespace/license metadata or runtime PM even if all its tripwires pass.

The complete local audit is retained at
`out/lgg8-pairing-audit-20261101/pairing.json`. A second, read-only candidate
check can select the existing kernel-only manifest without replacing anything:

```sh
python3 -B lgg8/tests/check_qemu_build_pairing.py \
  --symvers out/lgg8/kernel/vmlinux.symvers
```

That candidate returns `PAIRING_TRIPWIRES_PASS`, with `abi_proven=false`;
its 12,893 built-in export names exactly match the binary. Candidate manifest
SHA-256 is
`42e5cbb9113e2f2ea68992c15786c6852619e9ced145fd6d5174bd286a91b0c4`.
The result is retained at
`out/lgg8-pairing-audit-20261101/vmlinux-symvers-candidate.json`.
`scripts/Makefile.modpost` selects `vmlinux.symvers` for a kernel-only build,
but an external-module build reads `Module.symvers`. This explains how a
kernel-only rebuild can coexist with an obsolete module manifest. The extra
names in the old manifest do not by themselves prove that this particular
fixture imports a missing symbol; its complete imports must still be checked
against the binary. Matching export names does not authenticate every
generated header, type layout, namespace or license flag. It is not permission
to patch the release string or load a module. No phone boot, real suspend,
module load or charging acceptance was performed by either audit.

### Dedicated QEMU PM build (not C232)

A separately built minimal ARM64 QEMU kernel from source commit
`da9abdc8584c9dbac95ec7589f8bffcb99b22e2c` used
`lgg8/tests/qemu_sw42000_pm.config` with `allnoconfig`, followed by `Image`
and `modules_prepare`. Its Image, generated headers and export manifest come
from that private build, not the uncertain C232 artifacts. The Image SHA-256
is `0c6544cefe42da00ab063745a008362d19f09b87610d88468fbc1e21c2559d52`.
The resulting fixture loaded and ran seven device-PM scenarios, with missing-PM
and non-virt negative controls and teardown. The full log and build provenance
are in `out/lgg8-qemu-pm-paired-20261101/`; the passing run is
`out/lgg8-qemu-pm-paired-20261101/runs/run-20261101-063141-340b12f2/`.
The initial private build lacked `scripts/module.lds`; `modules_prepare` fixed
that. A subsequent run executed the scenarios but could not see the info-level
teardown marker at `loglevel=6`; the passing run used `loglevel=7`.

This is a real device-PM core with a simulated bus and touch controller, not
real system sleep, retained phone power, physical IRQ or touch input. It does
not resolve the C232 header provenance or prove C232 module ABI. The fresh
QEMU configuration is not a phone image. The private build and receipt are
local artifacts, not a claim that another build is byte-identical.

### Bounded evdev observer (local only)

`lgg8/tests/sw42000_event_probe.c` is a diagnostic prototype for a future
RAM-only run. It opens a selected event node read-only, requires the exact
SW42000 device name and MT X/Y axis ioctls, then waits at most 20 seconds for
a tracking-ID contact, in-range coordinates and release on the same slot.
Overflow (`SYN_DROPPED`) invalidates the capture. It logs coordinates, so run
it only for an intentional tap. A matching event stream alone does not prove
physical origin: combine it with a timed human tap and IRQ observation; do not
inject events. It does not issue suspend or change charger settings.

A local diagnostic initramfs was created by inserting the ARM64 observer into
the SHA-256-pinned C198 USB-shell initramfs, without overwriting the original.
The builder verifies every pre-existing newc entry retains its mode and bytes;
the rest of the original archive before its trailer is copied verbatim. The
candidate `out/lgg8-touch-candidate-20261101/touch-initramfs.cpio` has SHA-256
`b23d48adb4d3a7aed61de18dab7dcf0bb0d54b5bab026a27563d6819785c99a8`.
The local candidate `out/lgg8-touch-candidate-20261101/boot/boot.img` has
SHA-256 `d9ef349136a2440287757f1121e351bead48d545898f7a45fb9a655b78bf3431`;
its container was independently compared with C234. The shim's instruction
bytes are identical to C234 after excluding only the image-size header and the
DTB-address and payload-length constants. Their values were independently
checked against both manifests; label offsets were checked using the assembled
source. The changed DTB address reflects the larger initramfs. See
`out/lgg8-touch-candidate-20261101/shim-independent-verify.json`. This is not
proof that the shim executes or resets successfully on the phone. The ARM64
observer's synthetic self-test also passed under QEMU user mode.

The image was subsequently run on the phone as described below. Synthetic
self-tests are not physical input evidence. For any future use, review the USB
observer and recovery deadline and verify Android, slot and boot hashes before
and after.

## RAM-only coordinate candidate touch capture

On 2026-11-01 a RAM-only candidate with boot image SHA-256
`d9ef349136a2440287757f1121e351bead48d545898f7a45fb9a655b78bf3431`
was started on LM-G820 `alphalm_lao_com`. The run identified
`LG SW42000 Touchscreen` on `/dev/input/event2` and reported EVIOCGABS
ranges X `0..1439`, Y `0..3119`, followed by a contact and release at
`(916, 2009)`. The event capture is unauthenticated and does not by itself
prove its physical origin. Raw serial and structured receipts are retained in
`out/lgg8-touch-candidate-20261101/touch-run-20261101-073639-11e85cb0/`.
No suspend was requested or tested.

The phone returned to Android with slot `_b` and `sys.boot_completed=1`.
Before and after SHA-256 values were unchanged for `boot_a`
(`a826651669b4e9c8e2835e315082cedb821585a683fea9afede3f23517cfe4e6`)
and `boot_b`
(`fec418e5227a31927af27daf71d2225246f5adcf8dda38b5856200760b5205cd`).
Passive USB 1-2 monitor coverage and log integrity checks passed. These
observations do not establish charging safety or a reliable suspend wake path.

## Android axis comparison (C235)

On the running Android device, read-only `getevent -lp` reported `touch_dev`
with X `0..1439`, Y `0..3119`, pressure `0..255`, and ten slots. The C234
source declares those same maxima, and its packed DTB declares a size of
`1440 × 3120` and maximum pressure `255`. This compares Android's input
ioctl results with the mainline source and compiled DTB: no Linux EVIOCGABS or
physical touch events were captured in this observation. The Android boot ID
was unchanged across the read.

The Android driver advertises `ABS_MT_WIDTH_MAJOR/MINOR` and orientation;
the current mainline driver instead reports the decoded major/minor values as
`ABS_MT_TOUCH_MAJOR/MINOR` and does not report orientation. The pinned vendor
[controller](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/input/touchscreen/lge/lgsic/sw42000/touch_sw42000.c#L3643-L3656)
and [input core](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/input/touchscreen/lge/touch_core.c#L102-L121)
also associate those fields with the width events. Linux's
[multi-touch protocol](../../Documentation/input/multi-touch-protocol.rst)
assigns different meanings to touch and tool width. The physical meaning of
the device's width fields and the effect on Linux userspace remain unverified;
do not assume the two event types are interchangeable.

The redacted capability listing and result are in
`out/lgg8-c235-android-touch-axes-20261101/`; result SHA-256:
`106a6b3522ffb2dedf935dfb2ee941c8df013d6e444782b58465e7bdc1633b96`.

A later awake-only RAM boot attempted to prepare a watchdog reset observation,
not suspend. Watchdog registration and driver binding were read successfully,
then the transfer's first long interactive shell line timed out. The probe was
not executed and no watchdog reset was tested. The ordinary reboot command was
not confirmed because the shell was left at a continuation prompt; Android
subsequently returned, but the reset cause was not established. Slot `_b`, both boot partition
hashes and passive USB monitoring were verified after recovery. Logs are in
`out/lgg8-touch-candidate-20261101/watchdog-reset-20261101-101743-edd7702e/`.

The same failure was reproduced locally with an interactive BusyBox PTY: four
512-byte chunks joined into one command exceeded the line editor's capacity.
The transfer now sends and acknowledges one chunk per line; a real PTY test
also transfers more data than the actual probe while enforcing the existing
1 MiB serial capture limit. On failure the runner attempts Ctrl-C before
resynchronizing for reboot, but that is not guaranteed recovery. A matching
PTY test exercises interruption of an unterminated command. These are local
checks, not proof that a subsequent device transfer or watchdog reset works.

A second awake-only RAM boot completed all 951 transfer acknowledgements and
the probe emitted `ARMED timeout_seconds=10`. The physical USB 1-2 monitor
first recorded absence about 16.13 seconds after the host received that line;
Android subsequently returned, boot-completed on slot `_b`, and both boot
partition hashes matched the pre-run baseline. Android reported `bootloader`
as its boot reason and the post-run pstore inventory was verified empty.
Therefore the timing is consistent with a reset but does not identify its
cause, and this observation does not establish watchdog-controlled recovery or
safety during suspend. The full run is in
`out/lgg8-touch-candidate-20261101/watchdog-reset-20261101-102801-6a1af497/`.
No suspend was attempted.

As noted above, the driver stops an actively opened watchdog during late
suspend, so an awake expiry cannot establish a reset deadline for a hung
suspend. Behavior for an inherited running watchdog with no active userspace
owner is distinct and has not been proven on this phone. Do not enter suspend
relying on this watchdog as the sole recovery mechanism.
