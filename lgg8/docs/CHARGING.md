# LG G8 ThinQ charging support

## Target

Aim to reproduce the factory wired charging behavior and reach the highest
rate that this LM-G820 variant, its battery, adapter, cable, temperature, and
state of charge safely negotiate. LG Canada's G8 specification lists Qualcomm
Quick Charge 3.0 at 16.2 W and USB Power Delivery at 21 W. Treat those figures
as a reference target, not a confirmed ceiling for the `alphalm_lao_com`
variant; verify the exact regional hardware and source profile before setting
limits.

## What is known on this device

Read-only Android runtime captures in
`out/lgg8-c208-drm-log-enabled/run-03/` show:

- PM8150B `qcom,qpnp-smb5` supplies `battery`, `dc`, `main`, `pc_port`, and
  `usb` power supplies.
- PM8150B `qpnp,fg` uses `qcom,fg-gen4` and supplies `bms`.
- PM8150B `qcom,sdam-qnovo@b000` uses `qcom,qpnp-qnovo5`.
- An I²C SMB1355 at `0x0c` is enabled and supplies `parallel`.
- SMB5 and FG both reference the runtime `qcom,battery-data` node. Android's
  BMS reports the Tocad profile; thermal conversion and protection ownership
  in mainline are not yet validated.

The current upstream tree's `qcom_smbx` driver binds to PMI8998 and PM660
charger compatibles; it is not a PM8150B SMB5 driver. This tree also lacks the
LG combination of SMB5, FG Gen4, Qnovo5, and SMB1355 drivers. Reusing the
existing SMB2 driver or copying charger register writes without a complete
profile and safety review is not a valid substitute.
The built-in `qcom_smbx` initialization also explicitly caps fast-charge
current at 1 A. That conservative setting is not the LG charger profile and
must not be raised or reused as a route to factory-rate charging. See
[`qcom_smbx.c`](../../drivers/power/supply/qcom_smbx.c).

The fixed downstream SMB5 driver is not a passive telemetry probe. Its
`smb5_probe()` calls `smblib_init()` and then `smb5_init_hw()` before registering
the USB and battery power supplies. `smb5_init_hw()` programs thermal
regulation and HVDCP settings, among other charger setup. Do not bind this
driver merely to inspect status on a baseline boot; first split and audit a
read-only observation path from the initialization writes.

## Alpha-family downstream reference

An additional fixed-source audit of
[`android_kernel_lge_sm8150` at `d4f335e`](https://github.com/LineageOS/android_kernel_lge_sm8150/tree/d4f335e13d73c4aa2af85581a6ec11b670ee5b94)
confirmed that its LAO config maps to `sm8150-alpha_lao_com`, whose regional PM
DTSI includes the alpha-family power DTSI. That DTSI contains two BLT41 3500
mAh battery profiles: Tocad (battery ID 91 kΩ) and LGC (12 kΩ). Both source
profiles state `qcom,max-voltage-uv = <4430000>` and
`qcom,fastchg-current-ma = <3000>`; the DTSI sets Tocad/91 kΩ as its default.
The SMB5 library consumes `fastchg-current-ma` as the battery-side FCC ceiling
and checks the JEITA FCC entries against it; it is not USB input current and
does not specify the negotiated PD/QC wattage. These are candidate source
values, not confirmed settings for the live phone.
An unprivileged, read-only Android check on 2026-10-31 returned
`ro.boot.vendor.lge.battid=91695`. Under the downstream selector's ±15% ID
matching rule, this value fits the 91 kΩ Tocad range and not the 12 kΩ LGC
range, making Tocad the likely profile for the current Android boot.

On 2026-10-31 a root ADB read of the running Android system gave stronger
evidence: `bms/battery_type` reported `LGE_BLT41_Tocad_3500mAh` and
`bms/resistance_id` returned `91695`. The live FG and SMB5 `qcom,battery-data`
properties both contained phandle `0x643`, matching the live
`/vendor/qcom,battery-data` node. Its Tocad child reported ID 91 kΩ, FCC
3000 mA, maximum voltage 4430000 µV, thermistor pull-up 100, center offset 91,
and coefficient cells `0x230d 0x0cf0 0x0042 0xccbe 0x81ca`. The BMS reported
`voltage_max_design=4430000`, `charge_full_design=3530000` and `temp=326`
(32.6 °C). These are Android runtime observations, not independent physical
pack identification or validation of the Linux thermal path. Reading Android
FG properties can itself use the vendor driver's SRAM arbitration; the
observation does not prove an electrically passive register path. ADB was
returned to non-root mode after collection. Do not use these profile values as
mainline charging limits until the physical pack and protection ownership are
confirmed.

A second read-only snapshot on 2026-10-31 identified `alphalm_lao_com` /
`LM-G820`. Android reported the battery full at 100%, 4421 mV and 32.9 °C,
with USB power present and reported maximums of 500 mA at 5 V. This is a
low-power USB connection while the battery is full, not a measured charge
current, fast-charge negotiation, or maximum-rate test. It is useful only as a
baseline sanity check; it provides no evidence that Linux charging works.

The downstream profile selector also needs special care: it can fall back to
the default profile when ID matching fails, then set `battery_valid` based on
whether a profile object exists. A true value therefore does not necessarily
prove that the physical pack matched the profile. Its battery-ID path may use
the vendor boot argument before consulting the ADC; mainline must not silently
inherit the default-on-unknown behavior.

The same alpha-family DTSI has a vendor charging-time entry labelled 15 W
(9 V × 1.66 A or 5 V × 3 A). That is not, by itself, proof of the hardware's
maximum negotiated input power or the correct Linux input-current limit. LG's
Canada specification for LM-G820UM2 separately lists QC 3.0 at 16.2 W and PD
at 21 W; those figures are variant-specific published capabilities, not a
verified ceiling for `alphalm_lao_com`.

The mainline tree already has a PM8150B Type-C/PD controller driver
(`TYPEC_QCOM_PMIC` is enabled in the build config), and the target DTS includes
its PM8150B Type-C node but leaves it disabled. Mainline now has a PM8150B
SMB5 read-only status probe, but no full charger provider; the Type-C driver
has no safe way to apply negotiated sink
current or control input suspend. A generic regulator consumer was prototyped
and then discarded: regulator error paths can make consumer reference counts
ambiguous, while reading the hardware enable state cannot recover that
ownership. Do not wire a generic regulator as the charger input switch. The
required design is an SMB5-owned interface that serializes and verifies input
current limits, sink enable/suspend, and fault state within the provider. The
downstream SMB5 ICL helper can unsuspend the input as a side effect, so that
behavior must be split before connecting TCPM. TCPM also ignores some callback
errors in sink transitions; the local TCPM change now checks negotiated and
standby current-limit failures, requests sink stop, and enters error recovery.
That is not a hardware fail-safe by itself: the PMIC Type-C driver's current
`set_vbus()` ignores its `sink` argument, so it must be wired to the future
SMB5-owned input-control interface. That provider must latch safe input
shutdown on failure, contract reduction, and detach. The target DTS's
`simple-battery` 4.43 V field is static metadata, not active charge
termination or overvoltage protection.

The first PM8150B-specific slice is a separate read-only status driver. It
validates the PMIC subtype and exposes only USB presence and USB input-path
selection from SMB5 status registers. It has no register writes, charger IRQs,
APSD work, or writable power-supply properties. C211 compiled and booted it
RAM-only; on physical USB 1-2 Linux ACM reported `present=1` and `online=1`.

C212 adds the PM8150B `ADC5_USB_IN_I` and `ADC5_USB_IN_V_16` IIO channels using
the prescaling from LG's alpha-family device tree. The RAM-only ACM readback
reported USB input `4875776 µV` and current-sense output `64489 µV`. LG's SMB5
code converts the PM8150B current-sense voltage using 0.2 V/A in buck mode,
which corresponds to about `322445 µA` of USB input current. This is not
battery current. The test was powered from the host USB port while the phone
was already full; the Android baseline reported a 500 mA USB input ceiling.
So this validates measurement only, not battery charging, negotiated PD/QC,
or factory charging speed. The measurement data was captured, but the ACM
probe did not capture its final marker; the run is therefore a partial
telemetry capture. Android returned with `boot_completed=1`, slot `_b`, a
rotated boot ID, unchanged `boot_a`/`boot_b` hashes, and an empty pstore before
and after. C211 and C212 artifacts are in
`out/lgg8-c211-smb5-ro-20261031/` and
`out/lgg8-c212-usb-adc-20261031/`.

C213 adds voltage-only IIO channels for the PM8150B battery thermistor at the
factory's 30 kΩ, 100 kΩ, and 400 kΩ pull-ups, plus `VBAT_SNS`. On a RAM-only
boot, the ADCs returned `1160553`, `606682`, and `198399 µV` for those three
thermistor paths and `4421559 µV` for VBAT. Using the ADC's 1.875 V reference
and nominal pull-up values gives a provisional cross-check of about 48.7, 47.8,
and 47.3 kΩ, assuming the NTC excitation equals the ADC reference and a simple
divider. The actual excitation, calibration and circuit paths remain to be
verified; agreement alone does not prove board scaling or temperature. The
FG Gen4 factory thermistor coefficients are programmed into PMIC SRAM, so the
mainline charge path must not depend on these values until that mapping is
reproduced and checked against Android readings.

The ADC reads request conversions and write ADC configuration registers;
they are not a zero-PMIC-write observation. The same run saw USB
`present=1`, `online=1`, `4891344 µV` input voltage, and
`79801 µV` current-sense voltage (about `399005 µA` USB input in buck mode).
VBAT and USB measurements are telemetry, not battery charge current or proof
that charging was enabled. The phone was on host USB and Android reported a
full battery. The ACM capture contains every requested measurement, but its
end marker was not received; record it as partial. Android recovered after
about 124 seconds with `boot_completed=1`, slot `_b`, unchanged boot partition
hashes, and a rotated boot ID. The before-run pstore was empty; a console
ramoops was captured after recovery, but its contents have not been validated
as a C213 crash trace. C213's boot image
SHA-256 is `c7ef8a33234ff230b43b075a3ca36990ef6bd73fe422f7c9ad53c070ec7e0c2e`;
evidence is in `out/lgg8-c213-battery-sense-20261031/`.

Neither candidate wrote charger registers or enabled charging. Before
charge-control work, add reviewed battery-side current/temperature and fault
telemetry, establish ownership of termination and thermal protections, then
connect TCPM through an SMB5-owned, verified input-control interface. No
high-current or charging-enabled Linux test has been performed.

The downstream FG Gen4 implementation also writes battery-profile data to
PMIC SRAM and learning state through the SDAM NVMEM provider. RAM-only boot
protects flash partitions but does not make those PMIC side effects read-only.
Before considering FG Gen4 for Linux, audit each write, its ownership and its
interaction with the following Android boot. Do not enable the downstream FG
driver or its DT node as a shortcut to charging.

The pinned downstream `fg_get_battery_current()` reads two bytes at offsets
`0xa2` and `0xa8` relative to the discovered battery-info peripheral base,
compares the original and shadow values, sign-extends the 16-bit result, and
scales it by `488281 / 1000` to obtain microamps. This is a candidate for
battery-current telemetry without the FG SRAM read interface. The base must
be identified for this device and the peripheral's read semantics and
measurement validity established before using the result. LG's downstream
PM8150B device tree declares the battery-info resource at `0x4100`, giving
candidate register addresses `0x41a2` and `0x41a8`; verify the peripheral
subtype and actual hardware mapping before accessing them. The downstream
retry loop must not be copied unchanged: its post-incremented counter can
reject a match on the final attempt or accept an unmatched value when all
attempts fail. A new implementation must explicitly track a matching pair and
return an error when no match is obtained. Neither the sign convention nor
current accuracy has yet been validated on this mainline boot.

The experimental observer exposes only voltage and current getters. The
power-supply core can call those getters while creating or publishing uevents,
so registration may itself cause register reads; it is not an on-demand-only
interface. Each getter performs the bounded main/shadow comparison separately,
so voltage and current are not an atomic snapshot. The observer negates the
downstream FG current sign when exposing the Linux
battery `current_now` ABI, matching the downstream SMB5 battery getter and the
upstream convention of positive charging current. Real-device direction and
measurement freshness remain unverified; earlier C214–C218 observations used
the old, opposite sign and must not be reinterpreted as direct measurements
from this revised binary.

Sources: [FG current read](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-util.c#L979),
[register offsets](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-reg.h#L250).
[PM8150B resource](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/arch/arm64/boot/dts/qcom/pm8150b.dtsi#L413).

There are other coupled safeguards to account for during a port. The
downstream SMB5 initialization disables hardware JEITA compensation for cold
and warm zones; LG's extension also disables a battery-temperature interrupt.
Those paths depend on equivalent software temperature protection. The SMB5
and mainline PMIC Type-C drivers also overlap in Type-C/VCONN/role handling, so
the port must preserve one owner for each controller state machine. Finally,
SMB1355 needs a shared current budget and its own watchdog/termination audit;
loading its driver alone does not make parallel charging safe. Keep Qnovo
disabled until its Android userspace daemon/config dependency is understood.

The running Android device tree's `/vendor/lge-veneer-psy/protection-battemp`
node was read on 2026-10-31. The eight upward/downward temperature threshold
cells were respectively `30, 120, 450, 550` and `520, 430, 100, 0`; the LG
policy obtains temperature from `POWER_SUPPLY_PROP_TEMP`, whose unit is 0.1 °C.
Thus the configured thresholds include 45/43 °C for warm entry/recovery and
55/52 °C for hot entry/recovery. The emergency, warning and normal polling
intervals were 10, 30 and 60 seconds. The live node also had cool alert
current 500 mA, cool current percentage 30, warm float 4000 mV and warm
current percentage 50. These are configuration values, not proof that this
policy actually ran or that its votes reached hardware on this Android build.
The thresholds and timing cannot be copied into mainline as a complete safety
policy: the downstream code has hysteresis, voltage-dependent branches, votes,
and a compensated temperature source. The observation does not validate the
one-degree raw Linux value or establish appropriate failure handling.
[LG common power configuration](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/arch/arm64/boot/dts/lge/sm8150_common/sm8150_common-pm.dtsi#L120-L154),
[temperature policy](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/lge/protection-battemp.c),
[temperature input](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/lge/veneer-psy.c#L1051-L1075).

## Implementation and acceptance sequence

The downstream FG driver obtains its underlying battery temperature from FG
SRAM word 328, offset 0, as a signed 10-bit value in quarter-degree Celsius
units. Its `POWER_SUPPLY_PROP_TEMP` path invokes that reader. In the LG
extension, the property is replaced with `calculate_battery_temperature()`
when the fake-temperature override is unset, and with the override otherwise.
The compensated value incorporates a bias table and current-related correction.
Consequently, comparing a Linux raw FG temperature with Android `bms/temp`
alone does not independently validate the raw sensor. This identifies a
candidate source, not a verified mainline sensor: the FG SRAM access protocol
and its side effects still need auditing before use. The earlier ADC resistance
estimates do not independently validate this temperature or the board circuit.
[Downstream temperature reader](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-fg-gen4.c#L798).
[LG temperature property override](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/lge/extension-fg-gen4.c#L717).
The shared register header also names battery-info offsets `0x50`/`0x51` as
temperature registers; the Gen3 driver reads those directly, while this
device's downstream Gen4 driver uses SRAM. That difference is an investigation
lead, not evidence that the direct register encoding or validity applies to
PM8150B Gen4. Do not use it for protection without a hardware-specific audit
and comparison against an independent temperature measurement.
[Register definitions](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-reg.h#L115),
[Gen3 reader](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-fg-gen3.c#L568).

The experimental observer now exposes raw battery-info status bytes at offsets
`0x06` and `0x07`. The downstream header names bit 0 of the first byte
`BATT_TEMP_AVAIL_BIT` and bits 0–2 of the second as battery-missing indicators.
The attributes were read on this device in C219 and C220. Both bytes read
zero; Android also returned zero for the first byte while its FG reported a
plausible temperature. The shared-header names therefore do not establish the
bits' Gen4 meaning. Neither value proves sample freshness, calibration, or a
working temperature protection path.

### Gen4 temperature SRAM access audit

For a PM8150B subtype, the pinned LG Gen4 driver selects direct DMA; it does
not fall back to interleaved access after a DMA error. The temperature is two
bytes at SRAM word 328, mapped by that driver's Gen4 table to SPMI
`0x4858`–`0x4859`. A normal read requests arbitration via `0x4340` bit 0,
requests DMA via `0x4350` mask `0xa0` (value `0x80`), waits for the grant at
`0x4310` bit 3, reads the bytes, then clears both requests. Thus it does not
write the temperature data, but it does modify PMIC access-control registers.
PM8150B V1 additionally waits for FG algorithm inactivity before the request
and uses extra delays; this depends on initialized PEEK_MUX state, which has
not been independently verified for the running mainline environment.

The reference release path returns immediately if clearing `0x4350` fails,
without attempting to clear `0x4340`. Initial arbitration-write failure also
returns directly. A failed bus write may still have taken effect, but it is
not yet established whether forcing either release after an error is safe.
The recovery sequence, hardware ownership and serialization across all clients
therefore need independent verification before hardware testing.

The unwired `qcom_fg_dma_experimental` draft is not a charging driver. Its
public read entry always returns `-EOPNOTSUPP` without accessing the PMIC.
Review found that caller-provided attestations and a per-instance lock cannot
prove device identity or exclusive ownership. Cached regmap reads and
read-modify-write operations can also misrepresent hardware state. A successful
transaction alone would not validate sample freshness, calibration or battery
temperature. These gaps must be resolved with device-specific evidence before
the draft is connected to a running kernel.

The downstream Gen4 register header separately names ADC_RR battery-temperature
bytes at offsets `0x88` and `0x89`; with the PM8150B ADC_RR base `0x4200`,
these suggest addresses `0x4288` and `0x4289`. This is a possible path around
SRAM DMA, not a verified temperature interface: the Gen4 temperature getter
actually reads SRAM, and the encoding, freshness, update conditions, read side
effects and coherent two-byte read protocol for these ADC_RR registers remain
unknown. No charging protection may depend on the candidate until those facts
are established. Do not reuse the Gen3 BATT_INFO or older RRADC temperature
conversion merely because their names are similar.

Historical Qualcomm Gen4 code did read `ADC_RR_BATT_TEMP_LSB` directly as a
single signed 8-bit integer in degrees Celsius, including in a version that
already supported PM8150B V2. The subsequent change to a two-byte SRAM reading
states that the goal was higher resolution: 0.25 °C instead of 1 °C. This
supports the historical interpretation but does not establish freshness or
validity when the Android FG driver is absent. In particular, do not infer
that `0x4289` is part of the earlier single-byte reading.
[Original temperature change](https://github.com/LineageOS/android_kernel_lge_sm8150/commit/068a59303cbf3455643ee08f47284377a4e8e0c6),
[V2 support before the change](https://github.com/LineageOS/android_kernel_lge_sm8150/commit/d8e40bbfc2be38b1988276f4bb2df3919e7c90ea).

On 2026-10-31, on the running Android system, three successive debugfs regmap
reads of PM8150B `spmi0-02:0x4288` each returned `0x1f`. The historical
signed-byte interpretation would be 31 °C. Android `bms/temp` was 322
(32.2 °C) immediately before and after; it is a vendor property that may
include temperature compensation and an SRAM access. This is a single short
cross-check, not independent calibration, an atomic comparison, a freshness
test, or proof that the register updates under mainline Linux. Debugfs address
and count were restored to `0x00000000` and `1`; Android remained booted and
ADB was returned to shell mode. The experiment read only the one PMIC address;
the debugfs selector writes are host interface state, and the BMS property can
perform vendor FG arbitration. No charging-control register was changed.

C221 then tested the same raw byte in mainline using the observer's
`battery_temp_rr_raw` attribute. The independently verified RAM-only image
(`da155c433f4b2f86fb54c6b8b5caca400637afc0b2f06cf2c6681cb171bb9094`)
enumerated Linux ACM on physical USB 1-2 and returned `0x1f` with the end marker
verified. The result matches the nearby Android raw byte, but one sample does
not establish that the register updates after Linux takes over, that it tracks
an independent temperature, or that a charging protection can rely on it.
The phone returned to Android with `boot_completed=1`, slot `_b`, a changed
boot ID, and unchanged `boot_a` and `boot_b` hashes. No partition was written.
The full raw capture and runner result are in
`out/lgg8-c221-fg-rr-temp-20261031/run-01/`.

C221 run 02 reused the identical verified image and collected eight further
raw samples about four seconds apart (about 28 seconds from first to last).
All were `0x20`; the ACM end marker and all sample labels were received.
Android Battery Service reported 33.5 °C before the reboot and 34.5 °C after
returning. These compensated Android readings are not simultaneous with Linux
samples, and `0x20` differs from run 01's `0x1f` across an intervening Android
boot. Neither observation proves the register updated while Linux ran. The
phone returned to Android, and both boot partition hashes matched the pre-run
values. Evidence: `out/lgg8-c221-fg-rr-temp-20261031/run-02/` and the adjacent
`android-before-series.txt` / `android-after-series.txt` snapshots.

The vendor FG driver configures ADC_RR thermistor pull-up at `0x4281[1:0]`
and sample period at `0x4282`; the target vendor device tree specifies an
eight-second period. A same-boot Android regmap observation read `0x4210=02`,
`0x4281=02`, `0x4282=08`, and `0x4288=21`, while `bms/temp=339` (33.9 °C).
The pull-up field matches the vendor's 100 kΩ selection and the period byte
matches its configuration. These are register snapshots, not proof of sample
freshness or of a shared calibration path. The Gen4 battery-missing indication
is `0x4210` bit 0; a clear bit does not certify temperature validity. No
Gen4 sample-ready indicator has been established. Debugfs selectors were
restored and ADB returned to shell mode after the Android observation.

C222 tested these observer attributes in a verified RAM-only image
(`44e089a41225fa90cc3efa0f21efd42095c3bf1a902b29922dbc82ba7a84530b`).
Linux read `0x4210=02`, `0x4281=02`, `0x4282=01`, and `0x4288=21`; the
ACM shell capture and end marker passed. Android's earlier period byte was
`0x08`, so the configurations differ across the two boots. The vendor binding
defines this field as a direct interval in seconds and the vendor driver
writes it without a conversion, so the observed configurations correspond to
1 and 8 seconds respectively. These snapshots do not prove when the value
changed, whether the hardware actually samples at the configured interval, or
whether results are fresh. The vendor software default of eight seconds is
not evidence for the silicon reset value, and reset or bootloader involvement
in the Linux value has not been established. Android recovered with both boot
partition hashes unchanged. The full record is in
`out/lgg8-c222-fg-rr-config-20261031/run-01/`.
[Vendor ADC_RR period setup](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-fg-gen4.c#L5428),
[sample period units](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/Documentation/devicetree/bindings/power/supply/qcom/qpnp-fg-gen4.txt#L231).

The vendor ADC5 driver treats the three battery-thermistor channels as voltage
for the SM8150 alpha/beta boards, rather than applying its generic thermistor
temperature mapping. This further rules out treating a generic LUT as an
already verified G8 battery-temperature conversion.

[Gen4 register definitions](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-reg.h#L20-L48),
[PM8150B peripheral bases](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/arch/arm64/boot/dts/qcom/pm8150b.dtsi#L425-L437),
[Gen4 temperature getter](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-fg-gen4.c#L798-L816),
[alpha/beta ADC5 channels](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/iio/adc/qcom-spmi-adc5.c#L740-L754).

[Revision selection](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-fg-gen4.c#L5820),
[DMA transaction](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-memif.c#L827),
[Gen4 address table](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/fg-memif.c#L1194).

1. Resolve the exact running battery-data profile and all SMB5, FG, Qnovo,
   SMB1355, Type-C, and thermal properties from the matching LG source and
   runtime device tree. Record the exact board variant and component revisions.
   Separately resolve who owns battery-temperature, overvoltage, termination,
   and fault shutdown when Linux runs without the Android vendor stack.
2. Preserve the existing mainline PM8150B Type-C/PD path. Map SMB5 input-current
   control to the negotiated sink contract and required power-supply framework
   interfaces before enabling either side. Audit all FG SRAM/SDAM writes and
   do not enable the downstream FG implementation until its state effects are
   bounded and safe across the next Android boot.
3. Port SMB5 and the required telemetry/protection pieces with validated
   battery and thermal limits. First boot RAM-only without a charger and
   confirm telemetry, watchdog recovery, and fault shutdown. Then test
   conservative single-charger wired charging.
4. Add the factory charging modes in stages: USB-PD through TCPM and SMB5 ICL
   coordination; QC3/HVDCP and BC1.2 detection through SMB5; then SMB1355
   parallel-current sharing. Keep each mode behind its own verified protocol,
   temperature, termination, and fault handling.
5. Restore Qnovo only after its kernel state and Android-daemon/config
   dependencies are understood. Full factory parity requires the matching
   battery profile, SMB5 policy, parallel-charger coordination, and Qnovo
   behavior to be present together.
6. Measure negotiated input voltage/current, battery voltage/current, battery
   and connector temperatures, SOC, and charge duration with known adapters
   and cables. Compare against stock under the same conditions. The maximum
   rate is accepted only when the correct protocol is negotiated and current,
   voltage, thermal throttling, termination, and fault protections all work.

No intentional charger-control register writes, persistent partition writes, or
controlled charging-enable tests have been performed. The PMIC can retain its
previous configuration, so this does not establish that charging was disabled
during Linux tests. Keep the established RAM-only boot baseline. Do not use a
charging-rate increase as the first hardware test.

## References

- [LG Canada G8 ThinQ specifications](https://www.lg.com/ca_en/cell-phones/lmg820um2/)
- [LG SM8150 kernel source](https://github.com/LineageOS/android_kernel_lge_sm8150)
- [Pinned alpha-family power DTSI](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/arch/arm64/boot/dts/lge/sm8150-alpha/sm8150-alpha_common/sm8150-alpha_common-pm.dtsi)
- [Tocad 3500 mAh battery profile](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/arch/arm64/boot/dts/lge/battery_profile/LGE_BLT41_Tocad_3500mAh.dtsi)
- [LGC 3500 mAh battery profile](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/arch/arm64/boot/dts/lge/battery_profile/LGE_BLT41_LGC_3500mAh.dtsi)
- [LG SMB5 probe and hardware initialization](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/qpnp-smb5.c#L3976)
- [SMB5 battery FCC and JEITA profile parsing](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/smb5-lib.c#L8083)
- [LG charging-time profile parser](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/lge/charging-time.c)
- [LAO model-to-DTS mapping](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/arch/arm64/boot/dts/lge/Makefile) and [LAO PM include](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/arch/arm64/boot/dts/lge/sm8150-alpha/sm8150-alpha_lao_com/sm8150-alpha_lao_com-pm.dtsi)
- [Battery profile selector](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/lge/extension-fg-gen4.c) and [LG battery-temperature protection](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/lge/protection-battemp.c)
- [LG battery-voltage protection](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/lge/protection-batvolt.c)
- [Mainline alphalm DTS](../../arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dts) and [PM8150B Type-C node](../../arch/arm64/boot/dts/qcom/pm8150b.dtsi)
- [Mainline PM8150B Type-C callbacks](../../drivers/usb/typec/tcpm/qcom/qcom_pmic_typec_port.c)
- [Earlier charging safety audit](C208-NEXT-MILESTONE-REVIEW.md)
- [Upstream Qualcomm SMBx charger driver at `2a500a0`](https://github.com/torvalds/linux/blob/2a500a04d6f969318c05f46aedb6e73fc1963a00/drivers/power/supply/qcom_smbx.c)

### Type-C control gap in the current tree

The current Qualcomm PMIC Type-C driver registers `set_vbus` but no
`set_current_limit` callback. Its `set_vbus(on, sink)` implementation controls
source VBUS through `on` and does not act on the `sink` argument. Therefore a
TCPM request to disable sink charging does not, by itself, establish that
SMB5 charging or the input path has been disabled. The local TCPM error path
also permits a missing `set_current_limit` callback. The local
`tcpm_set_current_limit()` now preserves its previous reported values when an
existing callback returns an error; absent callbacks retain the existing TCPM
reporting behavior and do not establish a hardware limit. These interfaces
must not be treated as proof of an enforced
hardware limit or a fail-safe stop. A future design must supply one coordinated
SMB5 owner and verify register writes, error propagation and stop behavior
before using PD or enabling charge control.

An unmerged TCPM recovery draft was independently reviewed after it added
bounded retries for failed VBUS shutdown. Three gaps remain under correction:
queued PD messages can survive a failed shutdown and affect the recovery
state; initial shutdown failure can skip the initial VBUS/CC state reads even
after a later retry succeeds; and some source-role branches can continue
hardware actions after a VBUS callback fails. The draft must not be treated as
a safe or tested charging path. The existing `tcpm_set_cc()` wrapper discards
the underlying callback's error, so a request to open CC is not evidence that
the physical pins opened. The Qualcomm PMIC Type-C callback also currently
ignores sink control, independently of these TCPM issues.

The downstream `smblib_set_icl_current()` is not a transactional enable
operation. For a non-suspend request it configures a current/mode, clears USB
suspend, and only then may rerun AICL. If that last operation fails, the helper
returns an error after the input was already unsuspended. Therefore an ICL
setter failure cannot be interpreted as proof that the input remained stopped.
Any future owner must explicitly track and verify the resulting hardware state
and independently handle failure after an unsuspend; merely propagating the
return code to TCPM is insufficient. This is a source-level finding, not a
fault-injection result on the device.
[Downstream ICL sequencing](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/smb5-lib.c#L1448).

The current tree's generic `qcom_smbx` driver is not an immediately usable
PM8150B replacement. Its probe executes `smb_init_hw()` before registering
the supply, including charge-enable, watchdog, AICL and FCC configuration;
its match table currently lists PMI8998 and PM660, not PM8150B. In addition,
its `STATUS` setter passes `!val->intval` to the input-suspend bit. Since
standard `POWER_SUPPLY_STATUS_*` values are enum values rather than an on/off
boolean, callers cannot assume a `NOT_CHARGING` status request suspends USB.
This is a source-level observation, not a tested PM8150B control path; do not
bind the generic driver to this device or use that setter as stop proof without
a separate fix and complete hardware validation.
[Generic setter](../../drivers/power/supply/qcom_smbx.c),
[power-supply status values](../../include/linux/power_supply.h).

The downstream SMB5 driver distinguishes two commands: charging disable clears
bit 0 of `CHARGING_ENABLE_CMD_REG` (charger base + `0x042`), while USB input
suspend sets bit 0 of `USBIN_CMD_IL_REG` (charger base + `0x340`). These are
different operations: suspending the input also affects system power, while
disabling battery charging does not itself prove that input current is zero.
The status observer exposes the raw charging-enable command byte as
`charge_enable_command` on demand; it does not modify that byte. This new
attribute has not yet been verified on the device. A command bit reports a
requested state, not actual battery current, the effective power path, or
availability of temperature and fault protections.
On 2026-10-31, Android debugfs reads returned charging command `0x1042=01`,
input-suspend command `0x1340=00`, and charger status byte `0x1006=04`;
Android Battery Service subsequently reported full (`status=5`, level 100%).
This illustrates why an enabled command cannot establish that the battery is
actively charging. These are non-atomic observations under Android, not a
Linux charging result; the debugfs address/count selectors were restored and
ADB was returned to shell mode.

For a future input-limit comparison, the status observer also exposes raw
USB ICL override command, load configuration, ICL options, AICL options,
ICL-maximum status, AICL current-limit status, and AICL status bytes on
demand. These are read-only and not yet verified on the device. The values
must be interpreted together with the negotiated source, USB mode and input
path; no single byte establishes an enforced limit or a safe charge rate.
[Vendor SMB5 registers](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/smb5-reg.h).
On 2026-10-31 an Android snapshot read `0x1106=0a`, `0x1108=0a`,
`0x110a=01`, `0x1340=00`, `0x1342=00`, `0x1365=a0`, `0x1366=03`,
`0x1370=0a`, and `0x1380=d4` while on host USB. Under the vendor PM8150B
parameter table's 50 mA encoding, both ICL status bytes are 500 mA; AICL
status bit 0 is named done. These are separate non-atomic status/configuration
reads, not measured current or evidence of the Linux state. Debugfs selectors
were restored and ADB returned to shell mode.

C223 used the verified RAM-only image
`5ba74b93049fcdf6b95bf7a2c14977f4dba765ea8641fb8d98ed4f68fdddc203`
and obtained a complete ACM capture on physical USB 1-2. Linux returned
`0x1042=01`, `0x1340=00`, `0x1342=00`, `0x1365=a5`, `0x1366=02`,
`0x1380=d4`, `0x1106=0a`, `0x1108=0a`, `0x110a=01`, and `0x1370=1e`.
Under the vendor's PM8150B 50 mA encoding, the ICL configuration represents
1.5 A while both status bytes represent 0.5 A. These are sequential reads,
not a measured current, an atomic snapshot, or proof of a particular active
limit mode. They demonstrate why the configured ICL byte alone is insufficient
to establish what is enforced. Temperature raw/config/period were `21/02/01`.
Android returned with `boot_completed=1`, a rotated boot ID, and unchanged
hashes for both boot partitions. Raw evidence and the exact-port runner are in
`out/lgg8-c223-smb5-icl-observe-20261031/run-01/`; no partition was written.
The `0x1366` USB2/USB3 selection bits in this Linux snapshot match the bit
pattern used by the vendor's 500 mA SDP setter, but the three sampled mode and
override bits do not match that setter's complete software-override tuple or
the vendor helper's complete hardware-auto tuple. Because the reads were not
atomic and Linux did not invoke that vendor setter, this is a source-level
comparison, not identification of the effective mode.
[Vendor ICL mode helper](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/smb5-lib.c#L178-L225),
[vendor SDP selection](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/smb5-lib.c#L1389-L1440).
The experimental observer exposes the raw input-suspend command byte read-only;
its value is not evidence of actual input current or a verified shutdown. Source:
[downstream SMB5 register definitions](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/smb5-reg.h),
[downstream command implementation](https://github.com/LineageOS/android_kernel_lge_sm8150/blob/d4f335e13d73c4aa2af85581a6ec11b670ee5b94/drivers/power/supply/qcom/smb5-lib.c).
