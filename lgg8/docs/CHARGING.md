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

## Implementation and acceptance sequence

1. Resolve the exact running battery-data profile and all SMB5, FG, Qnovo,
   SMB1355, Type-C, and thermal properties from the matching LG source and
   runtime device tree. Record the exact board variant and component revisions.
2. Map each downstream component to current mainline power-supply, regulator,
   ADC, Type-C, and USB-PD frameworks. Port only the required pieces and add
   bindings with explicit, validated battery and thermal limits.
3. First boot RAM-only without a charger and confirm fuel-gauge readings and
   fault/temperature handling. Next test conservative wired charging and
   Type-C negotiation; add QC/PD fast modes and the SMB1355 parallel path only
   after each safety gate is proven.
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
- [Upstream Qualcomm SMBx charger driver](https://github.com/torvalds/linux/blob/master/drivers/power/supply/qcom_smbx.c)
