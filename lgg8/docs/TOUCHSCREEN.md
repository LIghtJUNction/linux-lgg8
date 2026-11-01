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
suspend/resume and a runtime Linux EVIOCGABS comparison remain open.

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
C210 passed the user's tap/drag observation. Probe logs, runtime Linux
EVIOCGABS-coordinate comparison, suspend/resume, and gesture support remain
open; parser and build success do not establish those behaviors.

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
C234 configuration lacks `CONFIG_PM_DEBUG` and has the PM8xxx RTC driver as
a module not included in the initramfs. The user-space guardian can be frozen
during system sleep, and the Qualcomm watchdog driver stops an active
watchdog in its suspend callback. No automatic wake source or hard recovery
deadline has been verified on this phone.

A future diagnostic kernel can enable `CONFIG_PM_DEBUG` and select `devices`
in `/sys/power/pm_test` to exercise device suspend/resume without entering
platform sleep. First validate the PM flow locally and establish a practical
recovery method: another driver's callback can still hang, and neither this
test nor a returned USB connection proves real sleep, wakeup, or touch input
after resume. Do not count injected input events as physical touch acceptance.

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
`out/lgg8-pairing-audit-20261101/pairing.json`. No phone boot, real suspend,
module load or charging acceptance was performed by this audit.

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
