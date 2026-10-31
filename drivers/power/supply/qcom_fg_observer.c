// SPDX-License-Identifier: GPL-2.0-only
/* Read-only PM8150B battery-info measurements; no FG initialization. */
#include <linux/math64.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/power_supply.h>
#include <linux/property.h>
#include <linux/regmap.h>
#include <linux/unaligned.h>
#include <soc/qcom/qcom-spmi-pmic.h>

#define FG_SUBTYPE_OFFSET 0x05
#define FG_BATT_INFO_SUBTYPE 0x11
#define FG_VOLTAGE_OFFSET 0xa0
#define FG_CURRENT_OFFSET 0xa2
#define FG_VOLTAGE_SHADOW_OFFSET 0xa6
#define FG_CURRENT_SHADOW_OFFSET 0xa8
#define FG_READ_ATTEMPTS 5

struct qcom_fg_observer {
	struct regmap *regmap;
	u32 base;
	u32 mem_base;
};

/* Raw status is evidence only; it does not prove temperature freshness. */
#define FG_RAW_STATUS_ATTR(_name, _offset)                                  \
static ssize_t _name##_show(struct device *dev,                              \
			    struct device_attribute *attr, char *buf)        \
{                                                                           \
	struct qcom_fg_observer *fg = dev_get_drvdata(dev);                  \
	unsigned int value;                                                  \
	int ret = regmap_read(fg->regmap, fg->base + (_offset), &value);     \
	if (ret)                                                             \
		return ret;                                                   \
	return sysfs_emit(buf, "0x%02x\n", value);                         \
}                                                                           \
static DEVICE_ATTR_RO(_name)

FG_RAW_STATUS_ATTR(battery_temp_status, 0x06);
FG_RAW_STATUS_ATTR(battery_presence_status, 0x07);

#define FG_MEM_STATUS_ATTR(_name, _offset)                                  \
static ssize_t _name##_show(struct device *dev,                              \
			    struct device_attribute *attr, char *buf)        \
{                                                                           \
	struct qcom_fg_observer *fg = dev_get_drvdata(dev);                  \
	unsigned int value;                                                  \
	int ret = regmap_read(fg->regmap, fg->mem_base + (_offset), &value); \
	if (ret)                                                             \
		return ret;                                                   \
	return sysfs_emit(buf, "0x%02x\n", value);                         \
}                                                                           \
static DEVICE_ATTR_RO(_name)

FG_RAW_STATUS_ATTR(algorithm_peek_config, 0xee);
FG_MEM_STATUS_ATTR(memory_realtime_status, 0x10);
FG_MEM_STATUS_ATTR(memory_arbitration_config, 0x40);
FG_MEM_STATUS_ATTR(memory_interface_config, 0x50);
FG_MEM_STATUS_ATTR(dma_status, 0x70);
FG_MEM_STATUS_ATTR(dma_config, 0x71);

static struct attribute *fg_observer_attrs[] = {
	&dev_attr_battery_temp_status.attr,
	&dev_attr_battery_presence_status.attr,
	&dev_attr_algorithm_peek_config.attr,
	&dev_attr_memory_realtime_status.attr,
	&dev_attr_memory_arbitration_config.attr,
	&dev_attr_memory_interface_config.attr,
	&dev_attr_dma_status.attr,
	&dev_attr_dma_config.attr,
	NULL,
};
ATTRIBUTE_GROUPS(fg_observer);

static int fg_observer_read_pair(struct qcom_fg_observer *fg, u32 offset,
				 u32 shadow_offset, u16 *value)
{
	u8 data[2], shadow[2];
	int ret, i;

	for (i = 0; i < FG_READ_ATTEMPTS; i++) {
		ret = regmap_bulk_read(fg->regmap, fg->base + offset, data, 2);
		if (ret)
			return ret;
		ret = regmap_bulk_read(fg->regmap, fg->base + shadow_offset,
				       shadow, 2);
		if (ret)
			return ret;
		if (data[0] == shadow[0] && data[1] == shadow[1]) {
			*value = get_unaligned_le16(data);
			return 0;
		}
	}
	return -EAGAIN;
}

static enum power_supply_property fg_observer_properties[] = {
	POWER_SUPPLY_PROP_VOLTAGE_NOW,
	POWER_SUPPLY_PROP_CURRENT_NOW,
};

static int fg_observer_get_property(struct power_supply *psy,
				    enum power_supply_property property,
				    union power_supply_propval *val)
{
	struct qcom_fg_observer *fg = power_supply_get_drvdata(psy);
	u16 raw;
	int ret;

	switch (property) {
	case POWER_SUPPLY_PROP_VOLTAGE_NOW:
		ret = fg_observer_read_pair(fg, FG_VOLTAGE_OFFSET,
					    FG_VOLTAGE_SHADOW_OFFSET, &raw);
		if (ret)
			return ret;
		val->intval = div_s64((s64)raw * 122070, 1000);
		return 0;
	case POWER_SUPPLY_PROP_CURRENT_NOW:
		ret = fg_observer_read_pair(fg, FG_CURRENT_OFFSET,
					    FG_CURRENT_SHADOW_OFFSET, &raw);
		if (ret)
			return ret;
		/* FG uses the opposite polarity to the power-supply battery ABI. */
		val->intval = -div_s64((s64)(s16)raw * 488281, 1000);
		return 0;
	default:
		return -EINVAL;
	}
}

static const struct power_supply_desc fg_observer_desc = {
	.name = "pm8150b-fg-observer",
	.type = POWER_SUPPLY_TYPE_BATTERY,
	.properties = fg_observer_properties,
	.num_properties = ARRAY_SIZE(fg_observer_properties),
	.get_property = fg_observer_get_property,
};

static int fg_observer_probe(struct platform_device *pdev)
{
	struct power_supply_config cfg = {};
	const struct qcom_spmi_pmic *pmic;
	struct qcom_fg_observer *fg;
	struct power_supply *psy;
	unsigned int subtype;
	u32 bases[2];
	int ret;

	pmic = qcom_pmic_get(&pdev->dev);
	if (IS_ERR(pmic))
		return dev_err_probe(&pdev->dev, PTR_ERR(pmic), "PMIC revision\n");
	if (pmic->subtype != PM8150B_SUBTYPE)
		return -ENODEV;
	fg = devm_kzalloc(&pdev->dev, sizeof(*fg), GFP_KERNEL);
	if (!fg)
		return -ENOMEM;
	fg->regmap = dev_get_regmap(pdev->dev.parent, NULL);
	if (!fg->regmap)
		return -ENODEV;
	ret = device_property_read_u32_array(&pdev->dev, "reg", bases,
					     ARRAY_SIZE(bases));
	if (ret)
		return ret;
	fg->base = bases[0];
	fg->mem_base = bases[1];
	ret = regmap_read(fg->regmap, fg->base + FG_SUBTYPE_OFFSET, &subtype);
	if (ret)
		return ret;
	if (subtype != FG_BATT_INFO_SUBTYPE)
		return -ENODEV;
	cfg.drv_data = fg;
	cfg.fwnode = dev_fwnode(&pdev->dev);
	psy = devm_power_supply_register(&pdev->dev, &fg_observer_desc, &cfg);
	if (IS_ERR(psy))
		return PTR_ERR(psy);
	platform_set_drvdata(pdev, fg);
	return 0;
}

static const struct of_device_id fg_observer_of_match[] = {
	{ .compatible = "qcom,pm8150b-fg-observer" },
	{}
};
MODULE_DEVICE_TABLE(of, fg_observer_of_match);

static struct platform_driver fg_observer_driver = {
	.probe = fg_observer_probe,
	.driver = {
		.name = "qcom-pm8150b-fg-observer",
		.of_match_table = fg_observer_of_match,
		.dev_groups = fg_observer_groups,
	},
};
module_platform_driver(fg_observer_driver);
MODULE_DESCRIPTION("PM8150B battery-info read-only observer");
MODULE_LICENSE("GPL");
