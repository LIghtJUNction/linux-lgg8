// SPDX-License-Identifier: GPL-2.0-only
/*
 * Read-only status reporting for the Qualcomm PM8150B SMB5 charger.
 *
 * Charging control is intentionally not implemented here. The PM8150B SMB5
 * charger requires a separate, reviewed control path for input limits,
 * suspend, battery limits, and fault handling.
 */

#include <linux/bits.h>
#include <linux/iio/consumer.h>
#include <linux/iio/iio.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/power_supply.h>
#include <linux/property.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <soc/qcom/qcom-spmi-pmic.h>

#include <dt-bindings/iio/qcom,spmi-vadc.h>

#define SMB5_USBIN_INT_RT_STS		0x0310
#define SMB5_USBIN_PLUGIN_RT_STS_BIT	BIT(4)

#define SMB5_POWER_PATH_STATUS		0x010b
#define SMB5_P_PATH_USE_USBIN_BIT	BIT(4)
#define SMB5_P_PATH_VALID_INPUT_BIT	BIT(0)

/* PM8150B parameters from LG downstream d4f335e13d73, qpnp-smb5.c. */
#define SMB5_FCC_CFG			0x0061
#define SMB5_FCC_STEP_UA			50000
#define SMB5_FCC_MAX_RAW			160
#define SMB5_FV_CFG			0x0070
#define SMB5_FV_MIN_UV			3600000
#define SMB5_FV_STEP_UV			10000
#define SMB5_FV_MAX_RAW			119
#define SMB5_MID_CHG_MIN_UV		1000000
#define SMB5_ADC5_BASE			0x3100

struct qcom_smb5 {
	struct regmap *regmap;
	struct iio_channel *mid_chg;
	struct power_supply_desc desc;
	u32 base;
};

/* Raw status bytes are exposed individually so failures cannot read as zero. */
#define SMB5_RAW_STATUS_ATTR(_name, _offset)                                  \
static ssize_t _name##_show(struct device *dev,                             \
			    struct device_attribute *attr, char *buf)        \
{                                                                           \
	struct qcom_smb5 *smb5 = dev_get_drvdata(dev);                       \
	unsigned int value;                                                  \
	int ret = regmap_read(smb5->regmap, smb5->base + (_offset), &value); \
	if (ret)                                                             \
		return ret;                                                   \
	return sysfs_emit(buf, "0x%02x\n", value);                         \
}                                                                           \
static DEVICE_ATTR_RO(_name)

SMB5_RAW_STATUS_ATTR(charger_status, 0x006);
SMB5_RAW_STATUS_ATTR(battery_status, 0x007);
SMB5_RAW_STATUS_ATTR(temperature_status, 0x00d);
SMB5_RAW_STATUS_ATTR(batif_realtime_status, 0x210);
SMB5_RAW_STATUS_ATTR(charge_enable_command, 0x042);
SMB5_RAW_STATUS_ATTR(charge_pause_command, 0x043);
SMB5_RAW_STATUS_ATTR(usb_suspend_command, 0x340);
SMB5_RAW_STATUS_ATTR(usb_icl_override_command, 0x342);
SMB5_RAW_STATUS_ATTR(usb_load_config, 0x365);
SMB5_RAW_STATUS_ATTR(usb_icl_options, 0x366);
SMB5_RAW_STATUS_ATTR(usb_aicl_options, 0x380);
SMB5_RAW_STATUS_ATTR(icl_max_status, 0x106);
SMB5_RAW_STATUS_ATTR(aicl_icl_status, 0x108);
SMB5_RAW_STATUS_ATTR(aicl_status, 0x10a);
SMB5_RAW_STATUS_ATTR(fcc_config, SMB5_FCC_CFG);
SMB5_RAW_STATUS_ATTR(fv_config, SMB5_FV_CFG);
SMB5_RAW_STATUS_ATTR(usb_icl_config, 0x370);
SMB5_RAW_STATUS_ATTR(jeita_config, 0x090);
/* Raw, independently read bytes; not a coherent snapshot or temperatures. */
SMB5_RAW_STATUS_ATTR(jeita_soft_hot_msb, 0x094);
SMB5_RAW_STATUS_ATTR(jeita_soft_hot_lsb, 0x095);
SMB5_RAW_STATUS_ATTR(jeita_soft_cold_msb, 0x096);
SMB5_RAW_STATUS_ATTR(jeita_soft_cold_lsb, 0x097);
SMB5_RAW_STATUS_ATTR(watchdog_config, 0x651);
SMB5_RAW_STATUS_ATTR(watchdog_timeout_config, 0x653);
SMB5_RAW_STATUS_ATTR(thermal_source_config, 0x670);
SMB5_RAW_STATUS_ATTR(safety_timer_enable_config, 0x0a0);
SMB5_RAW_STATUS_ATTR(safety_timer_duration_config, 0x0a2);
SMB5_RAW_STATUS_ATTR(recharge_mode_config, 0x051);
SMB5_RAW_STATUS_ATTR(term_upper_msb, 0x067);
SMB5_RAW_STATUS_ATTR(term_upper_lsb, 0x068);
SMB5_RAW_STATUS_ATTR(term_lower_msb, 0x069);
SMB5_RAW_STATUS_ATTR(term_lower_lsb, 0x06a);
SMB5_RAW_STATUS_ATTR(recharge_samples_config, 0x06b);
SMB5_RAW_STATUS_ATTR(term_samples_config, 0x06c);
SMB5_RAW_STATUS_ATTR(recharge_soc_config, 0x07d);
SMB5_RAW_STATUS_ATTR(recharge_voltage_msb, 0x07e);
SMB5_RAW_STATUS_ATTR(recharge_voltage_lsb, 0x07f);
SMB5_RAW_STATUS_ATTR(term_source_config, 0x0c0);

static struct attribute *qcom_smb5_status_attrs[] = {
	&dev_attr_charger_status.attr,
	&dev_attr_battery_status.attr,
	&dev_attr_temperature_status.attr,
	&dev_attr_batif_realtime_status.attr,
	&dev_attr_charge_enable_command.attr,
	&dev_attr_charge_pause_command.attr,
	&dev_attr_usb_suspend_command.attr,
	&dev_attr_usb_icl_override_command.attr,
	&dev_attr_usb_load_config.attr,
	&dev_attr_usb_icl_options.attr,
	&dev_attr_usb_aicl_options.attr,
	&dev_attr_icl_max_status.attr,
	&dev_attr_aicl_icl_status.attr,
	&dev_attr_aicl_status.attr,
	&dev_attr_fcc_config.attr,
	&dev_attr_fv_config.attr,
	&dev_attr_usb_icl_config.attr,
	&dev_attr_jeita_config.attr,
	&dev_attr_jeita_soft_hot_msb.attr,
	&dev_attr_jeita_soft_hot_lsb.attr,
	&dev_attr_jeita_soft_cold_msb.attr,
	&dev_attr_jeita_soft_cold_lsb.attr,
	&dev_attr_watchdog_config.attr,
	&dev_attr_watchdog_timeout_config.attr,
	&dev_attr_thermal_source_config.attr,
	&dev_attr_safety_timer_enable_config.attr,
	&dev_attr_safety_timer_duration_config.attr,
	&dev_attr_recharge_mode_config.attr,
	&dev_attr_term_upper_msb.attr,
	&dev_attr_term_upper_lsb.attr,
	&dev_attr_term_lower_msb.attr,
	&dev_attr_term_lower_lsb.attr,
	&dev_attr_recharge_samples_config.attr,
	&dev_attr_term_samples_config.attr,
	&dev_attr_recharge_soc_config.attr,
	&dev_attr_recharge_voltage_msb.attr,
	&dev_attr_recharge_voltage_lsb.attr,
	&dev_attr_term_source_config.attr,
	NULL,
};
ATTRIBUTE_GROUPS(qcom_smb5_status);

static enum power_supply_property qcom_smb5_properties[] = {
	POWER_SUPPLY_PROP_PRESENT,
	POWER_SUPPLY_PROP_ONLINE,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE,
	/* Optional MID_CHG channel; keep last for descriptors without an ADC. */
	POWER_SUPPLY_PROP_VOLTAGE_NOW,
};

static int qcom_smb5_get_property(struct power_supply *psy,
				  enum power_supply_property psp,
				  union power_supply_propval *val)
{
	struct qcom_smb5 *smb5 = power_supply_get_drvdata(psy);
	unsigned int status;
	unsigned int reg;
	int ret, voltage_uv;

	switch (psp) {
	case POWER_SUPPLY_PROP_PRESENT:
		reg = smb5->base + SMB5_USBIN_INT_RT_STS;
		ret = regmap_read(smb5->regmap, reg, &status);
		if (ret)
			return ret;

		val->intval = !!(status & SMB5_USBIN_PLUGIN_RT_STS_BIT);
		return 0;
	case POWER_SUPPLY_PROP_ONLINE:
		reg = smb5->base + SMB5_POWER_PATH_STATUS;
		ret = regmap_read(smb5->regmap, reg, &status);
		if (ret)
			return ret;

		val->intval = (status & SMB5_P_PATH_USE_USBIN_BIT) &&
			      (status & SMB5_P_PATH_VALID_INPUT_BIT);
		return 0;
	/*
	 * Programmed base settings, including when offline. These are not
	 * measured IBAT/VBAT, post-JEITA effective limits, or proof of charging.
	 * Zero FCC is a valid setting, not confirmation of physical shutdown.
	 */
	case POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT:
		ret = regmap_read(smb5->regmap, smb5->base + SMB5_FCC_CFG, &status);
		if (ret)
			return ret;
		if (status > SMB5_FCC_MAX_RAW)
			return -ENODATA;

		val->intval = (int)status * SMB5_FCC_STEP_UA;
		return 0;
	case POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE:
		ret = regmap_read(smb5->regmap, smb5->base + SMB5_FV_CFG, &status);
		if (ret)
			return ret;
		if (status > SMB5_FV_MAX_RAW)
			return -ENODATA;

		val->intval = SMB5_FV_MIN_UV + (int)status * SMB5_FV_STEP_UV;
		return 0;
	case POWER_SUPPLY_PROP_VOLTAGE_NOW:
		if (!smb5->mid_chg)
			return -ENODATA;
		reg = smb5->base + SMB5_USBIN_INT_RT_STS;
		ret = regmap_read(smb5->regmap, reg, &status);
		if (ret)
			return ret;
		if (!(status & SMB5_USBIN_PLUGIN_RT_STS_BIT))
			return -ENODATA;
		ret = iio_read_channel_processed(smb5->mid_chg, &voltage_uv);
		if (ret)
			return ret;
		ret = regmap_read(smb5->regmap, reg, &status);
		if (ret)
			return ret;
		/* The vendor driver considers MID_CHG below 1 V unreliable. */
		if (!(status & SMB5_USBIN_PLUGIN_RT_STS_BIT) ||
		    voltage_uv < SMB5_MID_CHG_MIN_UV)
			return -ENODATA;
		val->intval = voltage_uv;
		return 0;
	default:
		return -EINVAL;
	}
}

static const struct power_supply_desc qcom_smb5_desc = {
	.name			= "pm8150b-smb5-status",
	.type			= POWER_SUPPLY_TYPE_USB,
	.properties		= qcom_smb5_properties,
	.num_properties		= ARRAY_SIZE(qcom_smb5_properties),
	.get_property		= qcom_smb5_get_property,
};

/*
 * ADC5 processed voltages are in uV. A generic IIO voltage channel may use mV;
 * establish the source before registering a supply whose uevents can read it.
 * These checks only inspect DT and IIO metadata, never perform a conversion.
 */
static int qcom_smb5_get_mid_chg(struct device *dev, struct qcom_smb5 *smb5)
{
	struct device_node *np = dev->of_node;
	struct device_node *parent, *charger_parent, *child;
	struct of_phandle_args args;
	struct iio_channel *channel;
	enum iio_chan_type type;
	u32 reg, prescale[2];
	unsigned int matches = 0;
	int ret;

	if (!np ||
	    of_property_count_strings(np, "io-channel-names") != 1 ||
	    of_property_match_string(np, "io-channel-names", "mid-chg") != 0 ||
	    of_count_phandle_with_args(np, "io-channels", "#io-channel-cells") != 1)
		return -EINVAL;

	ret = of_parse_phandle_with_args(np, "io-channels", "#io-channel-cells",
					 0, &args);
	if (ret)
		return ret;

	ret = -EINVAL;
	if (args.args_count != 1 || args.args[0] != ADC5_MID_CHG_DIV6 ||
	    of_property_count_strings(args.np, "compatible") != 1 ||
	    !of_device_is_compatible(args.np, "qcom,spmi-adc5") ||
	    !of_device_is_available(args.np) ||
	    of_property_count_u32_elems(args.np, "reg") != 1 ||
	    of_property_read_u32(args.np, "reg", &reg) || reg != SMB5_ADC5_BASE)
		goto put_provider;

	parent = of_get_parent(args.np);
	charger_parent = of_get_parent(np);
	if (!parent || parent != charger_parent || !dev->parent ||
	    parent != dev->parent->of_node) {
		of_node_put(charger_parent);
		of_node_put(parent);
		goto put_provider;
	}
	of_node_put(charger_parent);
	of_node_put(parent);

	/* Match ADC5's fwnode iterator: disabled channel nodes are not parsed. */
	for_each_available_child_of_node(args.np, child) {
		if (of_property_count_u32_elems(child, "reg") != 1 ||
		    of_property_read_u32(child, "reg", &reg))
			goto put_child;
		if (reg != ADC5_MID_CHG_DIV6)
			continue;
		if (++matches != 1)
			goto put_child;

		/* Omitted: ADC5 MID_CHG defaults to ratio index 3, i.e. 1/6. */
		if (of_property_present(child, "qcom,pre-scaling") &&
		    (of_property_count_u32_elems(child, "qcom,pre-scaling") != 2 ||
		     of_property_read_u32_array(child, "qcom,pre-scaling", prescale, 2) ||
		     prescale[0] != 1 || prescale[1] != 6))
			goto put_child;
	}
	if (matches != 1)
		goto put_provider;

	channel = devm_iio_channel_get(dev, "mid-chg");
	if (IS_ERR(channel)) {
		ret = PTR_ERR(channel);
		goto put_provider;
	}
	ret = iio_get_channel_type(channel, &type);
	if (ret)
		goto put_provider;
	if (type != IIO_VOLTAGE ||
	    dev_fwnode(&channel->indio_dev->dev) != of_fwnode_handle(args.np)) {
		ret = -EINVAL;
		goto put_provider;
	}

	smb5->mid_chg = channel;
	ret = 0;
put_provider:
	of_node_put(args.np);
	return ret;
put_child:
	of_node_put(child);
	goto put_provider;
}

static int qcom_smb5_probe(struct platform_device *pdev)
{
	struct power_supply_config psy_cfg = {};
	const struct qcom_spmi_pmic *pmic;
	struct power_supply *psy;
	struct qcom_smb5 *smb5;
	int ret;

	pmic = qcom_pmic_get(&pdev->dev);
	if (IS_ERR(pmic))
		return dev_err_probe(&pdev->dev, PTR_ERR(pmic),
				     "failed to get PMIC revision\n");
	if (pmic->subtype != PM8150B_SUBTYPE)
		return dev_err_probe(&pdev->dev, -ENODEV,
				     "SMB5 status node is not under PM8150B\n");

	smb5 = devm_kzalloc(&pdev->dev, sizeof(*smb5), GFP_KERNEL);
	if (!smb5)
		return -ENOMEM;

	smb5->regmap = dev_get_regmap(pdev->dev.parent, NULL);
	if (!smb5->regmap)
		return dev_err_probe(&pdev->dev, -ENODEV,
				     "failed to locate PMIC regmap\n");

	ret = device_property_read_u32(&pdev->dev, "reg", &smb5->base);
	if (ret)
		return dev_err_probe(&pdev->dev, ret,
				     "failed to read charger register base\n");

	if (device_property_present(&pdev->dev, "io-channels")) {
		ret = qcom_smb5_get_mid_chg(&pdev->dev, smb5);
		if (ret)
			return dev_err_probe(&pdev->dev, ret,
					     "invalid or unavailable MID_CHG ADC source\n");
	}

	smb5->desc = qcom_smb5_desc;
	if (!smb5->mid_chg)
		smb5->desc.num_properties--;
	psy_cfg.drv_data = smb5;
	psy_cfg.fwnode = dev_fwnode(&pdev->dev);
	psy = devm_power_supply_register(&pdev->dev, &smb5->desc,
					 &psy_cfg);
	if (IS_ERR(psy))
		return dev_err_probe(&pdev->dev, PTR_ERR(psy),
				     "failed to register status power supply\n");

	platform_set_drvdata(pdev, smb5);

	return 0;
}

static const struct of_device_id qcom_smb5_of_match[] = {
	{ .compatible = "qcom,pm8150b-charger" },
	{ }
};
MODULE_DEVICE_TABLE(of, qcom_smb5_of_match);

static struct platform_driver qcom_smb5_driver = {
	.probe = qcom_smb5_probe,
	.driver = {
		.name = "qcom-pm8150b-smb5-status",
		.of_match_table = qcom_smb5_of_match,
		.dev_groups = qcom_smb5_status_groups,
	},
};
module_platform_driver(qcom_smb5_driver);

MODULE_DESCRIPTION("Read-only status driver for Qualcomm PM8150B SMB5");
MODULE_LICENSE("GPL");
MODULE_IMPORT_NS("IIO_CONSUMER");
