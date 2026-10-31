// SPDX-License-Identifier: GPL-2.0-only
/*
 * Read-only status reporting for the Qualcomm PM8150B SMB5 charger.
 *
 * Charging control is intentionally not implemented here. The PM8150B SMB5
 * charger requires a separate, reviewed control path for input limits,
 * suspend, battery limits, and fault handling.
 */

#include <linux/bits.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/power_supply.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <soc/qcom/qcom-spmi-pmic.h>

#define SMB5_USBIN_INT_RT_STS		0x0310
#define SMB5_USBIN_PLUGIN_RT_STS_BIT	BIT(4)

#define SMB5_POWER_PATH_STATUS		0x010b
#define SMB5_P_PATH_USE_USBIN_BIT	BIT(4)
#define SMB5_P_PATH_VALID_INPUT_BIT	BIT(0)

struct qcom_smb5 {
	struct regmap *regmap;
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
SMB5_RAW_STATUS_ATTR(usb_suspend_command, 0x340);
SMB5_RAW_STATUS_ATTR(fcc_config, 0x061);
SMB5_RAW_STATUS_ATTR(fv_config, 0x070);
SMB5_RAW_STATUS_ATTR(usb_icl_config, 0x370);
SMB5_RAW_STATUS_ATTR(jeita_config, 0x090);
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
	&dev_attr_usb_suspend_command.attr,
	&dev_attr_fcc_config.attr,
	&dev_attr_fv_config.attr,
	&dev_attr_usb_icl_config.attr,
	&dev_attr_jeita_config.attr,
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
};

static int qcom_smb5_get_property(struct power_supply *psy,
				  enum power_supply_property psp,
				  union power_supply_propval *val)
{
	struct qcom_smb5 *smb5 = power_supply_get_drvdata(psy);
	unsigned int status;
	unsigned int reg;
	int ret;

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

	psy_cfg.drv_data = smb5;
	psy_cfg.fwnode = dev_fwnode(&pdev->dev);
	psy = devm_power_supply_register(&pdev->dev, &qcom_smb5_desc,
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
