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
- SMB5 and FG both reference `qcom,battery-data`; the runtime capture has not
  resolved the phandle to the selected battery profile or decoded its
  thermistor, resistance, and charge-limit tables.

The current upstream tree's `qcom_smbx` driver binds to PMI8998 and PM660
charger compatibles; it is not a PM8150B SMB5 driver. This tree also lacks the
LG combination of SMB5, FG Gen4, Qnovo5, and SMB1355 drivers. Reusing the
existing SMB2 driver or copying charger register writes without a complete
profile and safety review is not a valid substitute.

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
range, making Tocad the likely profile for the current Android boot. The live
device tree exposes both profile node names, but ordinary ADB cannot read the
profile properties or the SMB5/FG phandles; the physical pack ID and active
driver selection are therefore not independently confirmed. Do not use the
candidate profile values as mainline charging limits until the exact
pack/profile and protection ownership are confirmed.

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
its PM8150B node but leaves it disabled. The driver does not implement TCPM's
optional `set_current_limit` callback, so merely enabling the node does not
program the SMB5 input-current limit from the negotiated sink contract. The
missing piece is a PM8150B SMB5 charger implementation plus an explicit,
reviewed contract-to-charger control path. Bring these up together; successful
PD negotiation alone does not establish safe charging. The target DTS's
`simple-battery` 4.43 V field is static battery metadata, not an active charge
termination or overvoltage protection mechanism.

The downstream FG Gen4 implementation also writes battery-profile data to
PMIC SRAM and learning state through the SDAM NVMEM provider. RAM-only boot
protects flash partitions but does not make those PMIC side effects read-only.
Before considering FG Gen4 for Linux, audit each write, its ownership and its
interaction with the following Android boot. Do not enable the downstream FG
driver or its DT node as a shortcut to charging.

There are other coupled safeguards to account for during a port. The
downstream SMB5 initialization disables hardware JEITA compensation for cold
and warm zones; LG's extension also disables a battery-temperature interrupt.
Those paths depend on equivalent software temperature protection. The SMB5
and mainline PMIC Type-C drivers also overlap in Type-C/VCONN/role handling, so
the port must preserve one owner for each controller state machine. Finally,
SMB1355 needs a shared current budget and its own watchdog/termination audit;
loading its driver alone does not make parallel charging safe. Keep Qnovo
disabled until its Android userspace daemon/config dependency is understood.

## Implementation and acceptance sequence

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
3. Port only the necessary charger/telemetry pieces and add bindings with
   validated battery and thermal limits. First boot RAM-only without a charger
   and confirm telemetry and fault handling; then test conservative wired
   charging. Add QC/PD fast modes and SMB1355 parallel charging only after
   each safety gate is proven.
4. Measure negotiated input voltage/current, battery voltage/current, battery
   and connector temperatures, SOC, and charge duration with known adapters
   and cables. Compare against stock under the same conditions. The maximum
   rate is accepted only when the correct protocol is negotiated and current,
   voltage, thermal throttling, termination, and fault protections all work.

No charger-register writes, persistent partition writes, or charging-enabled
Linux device test have been performed. Keep the established RAM-only boot
baseline. Do not use a charging-rate increase as the first hardware test.

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
