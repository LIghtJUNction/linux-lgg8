/* SPDX-License-Identifier: GPL-2.0-only */
/* Offline kernel API boundary; production definitions are injected verbatim. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef uint32_t u32;
#define BIT(n) (1U << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define GFP_KERNEL 0
#define EPROBE_DEFER 517
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))

enum power_supply_property {
	POWER_SUPPLY_PROP_PRESENT,
	POWER_SUPPLY_PROP_ONLINE,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE,
	POWER_SUPPLY_PROP_VOLTAGE_NOW,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT_MAX,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX,
	POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT,
};
enum { POWER_SUPPLY_TYPE_USB = 1 };
union power_supply_propval { int intval; };
struct power_supply {
	void *drv_data;
	const struct power_supply_desc *desc;
};
struct power_supply_desc {
	const char *name;
	int type;
	const enum power_supply_property *properties;
	size_t num_properties;
	int (*get_property)(struct power_supply *, enum power_supply_property,
			    union power_supply_propval *);
	int (*set_property)(struct power_supply *, enum power_supply_property,
			    const union power_supply_propval *);
	int (*property_is_writeable)(struct power_supply *, enum power_supply_property);
};
struct regmap {
	unsigned int expected_reg, raw, reads, writes;
	int error;
	bool sequence;
	unsigned int readings[2];
	int errors[2];
};
struct iio_channel {
	int voltage, error;
	unsigned int reads;
};
struct qcom_spmi_pmic { unsigned int subtype; };
struct device {
	struct device *parent;
	struct regmap *regmap;
	struct qcom_spmi_pmic pmic;
	struct iio_channel *channel;
	struct power_supply *registered;
	void *allocation, *drvdata;
	bool channel_present;
	int channel_error, pmic_error, reg_error, register_error;
	u32 base;
};
struct platform_device { struct device dev; };
struct power_supply_config { void *drv_data, *fwnode; };
static const struct qcom_spmi_pmic *qcom_pmic_get(struct device *dev)
{
	return dev->pmic_error ? ERR_PTR(dev->pmic_error) : &dev->pmic;
}
static int dev_err_probe(struct device *dev, int error, const char *format, ...)
{
	(void)dev;
	(void)format;
	return error;
}
static void *devm_kzalloc(struct device *dev, size_t size, int flags)
{
	(void)flags;
	assert(!dev->allocation);
	return dev->allocation = calloc(1, size);
}
static struct regmap *dev_get_regmap(struct device *parent, const char *name)
{
	(void)name;
	return parent->regmap;
}
static int device_property_read_u32(struct device *dev, const char *name, u32 *value)
{
	assert(!strcmp(name, "reg"));
	*value = dev->base;
	return dev->reg_error;
}
static bool device_property_present(struct device *dev, const char *name)
{
	assert(!strcmp(name, "io-channels"));
	return dev->channel_present;
}
static struct iio_channel *devm_iio_channel_get(struct device *dev, const char *name)
{
	assert(!strcmp(name, "mid-chg"));
	return dev->channel_error ? ERR_PTR(dev->channel_error) : dev->channel;
}
static void *dev_fwnode(struct device *dev) { return dev; }
static struct power_supply *devm_power_supply_register(struct device *dev,
	const struct power_supply_desc *desc, const struct power_supply_config *cfg)
{
	if (dev->register_error)
		return ERR_PTR(dev->register_error);
	dev->registered = calloc(1, sizeof(*dev->registered));
	assert(dev->registered);
	dev->registered->desc = desc;
	dev->registered->drv_data = cfg->drv_data;
	return dev->registered;
}
static void platform_set_drvdata(struct platform_device *pdev, void *data)
{
	pdev->dev.drvdata = data;
}
static void *power_supply_get_drvdata(struct power_supply *psy)
{
	return psy->drv_data;
}
static int regmap_read(struct regmap *map, unsigned int reg, unsigned int *value)
{
	assert(reg == map->expected_reg);
	map->reads++;
	if (map->sequence) {
		unsigned int index = map->reads - 1;

		assert(index < ARRAY_SIZE(map->readings));
		*value = map->readings[index];
		return map->errors[index];
	}
	/* Deliberately overwrite the temporary even on failure. */
	*value = map->raw;
	return map->error;
}
static int iio_read_channel_processed(struct iio_channel *chan, int *value)
{
	chan->reads++;
	*value = chan->voltage;
	return chan->error;
}
/* Any added write must fail and be observable, never silently succeed. */
static inline int regmap_write(struct regmap *map, unsigned int reg, unsigned int value)
{
	(void)reg;
	(void)value;
	map->writes++;
	return -EIO;
}
static inline int regmap_update_bits(struct regmap *map, unsigned int reg,
				     unsigned int mask, unsigned int value)
{
	(void)mask;
	return regmap_write(map, reg, value);
}

/* ACTUAL_DRIVER_DEFINITIONS */

static unsigned int cases;

static void expect(struct power_supply *psy, enum power_supply_property property,
		   unsigned int offset, unsigned int raw, int error,
		   int expected_ret, int expected_value)
{
	struct qcom_smb5 *chip = psy->drv_data;
	struct regmap *map = chip->regmap;
	union power_supply_propval value = { .intval = -1234567 };

	map->expected_reg = chip->base + offset;
	map->raw = raw;
	map->error = error;
	map->reads = 0;
	assert(qcom_smb5_desc.get_property(psy, property, &value) == expected_ret);
	assert(map->reads == 1 && map->writes == 0);
	assert(value.intval == (expected_ret ? -1234567 : expected_value));
	cases++;
}

static void expect_mid_voltage(struct power_supply *psy, unsigned int first,
			       unsigned int last, int first_error, int adc_error,
			       int last_error, int adc_uv, int expected,
			       int expected_value, unsigned int expected_reads,
			       unsigned int expected_adc_reads)
{
	struct qcom_smb5 *chip = psy->drv_data;
	struct regmap *map = chip->regmap;
	struct iio_channel *chan = chip->mid_chg;
	union power_supply_propval value = { .intval = -1234567 };

	map->expected_reg = chip->base + SMB5_USBIN_INT_RT_STS;
	map->sequence = true;
	map->readings[0] = first;
	map->readings[1] = last;
	map->errors[0] = first_error;
	map->errors[1] = last_error;
	map->reads = 0;
	if (chan) {
		chan->voltage = adc_uv;
		chan->error = adc_error;
		chan->reads = 0;
	}
	assert(qcom_smb5_desc.get_property(psy, POWER_SUPPLY_PROP_VOLTAGE_NOW,
					    &value) == expected);
	assert(value.intval == (expected ? -1234567 : expected_value));
	assert(map->reads == expected_reads && map->writes == 0);
	assert(!chan || chan->reads == expected_adc_reads);
	cases++;
}

static void probe_cases(void)
{
	struct regmap map = {0};
	struct iio_channel channel = {0};
	struct device parent = { .regmap = &map };

	for (unsigned int scenario = 0; scenario < 7; scenario++) {
		struct platform_device pdev = { .dev = {
			.parent = &parent, .pmic = { .subtype = PM8150B_SUBTYPE },
			.base = 0x1000, .channel = &channel,
			.channel_present = scenario != 0,
		} };
		int expected = 0;

		switch (scenario) {
		case 2: pdev.dev.channel_error = expected = -EPROBE_DEFER; break;
		case 3: pdev.dev.channel_error = expected = -ENODEV; break;
		case 4: pdev.dev.pmic.subtype = 0; expected = -ENODEV; break;
		case 5: pdev.dev.reg_error = expected = -EIO; break;
		case 6: pdev.dev.register_error = expected = -ENOMEM; break;
		}
		assert(qcom_smb5_probe(&pdev) == expected);
		if (!expected) {
			assert(pdev.dev.registered && pdev.dev.drvdata);
			assert(pdev.dev.registered->desc->num_properties == (scenario ? 5U : 4U));
			assert(pdev.dev.registered->desc->properties[4] == POWER_SUPPLY_PROP_VOLTAGE_NOW);
			assert(((struct qcom_smb5 *)pdev.dev.drvdata)->mid_chg ==
			       (scenario ? &channel : NULL));
		} else {
			assert(!pdev.dev.registered && !pdev.dev.drvdata);
		}
		assert(map.writes == 0);
		free(pdev.dev.registered);
		free(pdev.dev.allocation);
		cases++;
	}
}

unsigned int smb5_config_properties_tests(void)
{
	struct regmap map = {0};
	struct qcom_smb5 chip = { .regmap = &map, .base = 0x1000 };
	struct power_supply psy = { .drv_data = &chip };
	struct iio_channel mid = {0};
	const int errors[] = { -EIO, -ETIMEDOUT, -EAGAIN, -ENODATA };
	const enum power_supply_property unsupported[] = {
		POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT_MAX,
		POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX,
		POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT,
	};

	cases = 0;
	probe_cases();
	assert(qcom_smb5_desc.num_properties == 5);
	for (unsigned int p = 0; p < 5; p++) {
		unsigned int occurrences = 0;

		for (size_t i = 0; i < qcom_smb5_desc.num_properties; i++)
			occurrences += qcom_smb5_desc.properties[i] == (enum power_supply_property)p;
		assert(occurrences == 1);
	}
	assert(qcom_smb5_desc.get_property == qcom_smb5_get_property);
	assert(!qcom_smb5_desc.set_property && !qcom_smb5_desc.property_is_writeable);

	for (unsigned int online = 0; online < 2; online++) {
		expect(&psy, POWER_SUPPLY_PROP_PRESENT, 0x310, online ? 0x10 : 0,
		       0, 0, (int)online);
		expect(&psy, POWER_SUPPLY_PROP_ONLINE, 0x10b, online ? 0x11 : 0,
		       0, 0, (int)online);
		/* Only the requested config register may be read. No online gate. */
		for (unsigned int raw = 0; raw < 256; raw++) {
			expect(&psy, POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT, 0x061,
			       raw, 0, raw <= 160 ? 0 : -ENODATA, (int)raw * 50000);
			expect(&psy, POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE, 0x070,
			       raw, 0, raw <= 119 ? 0 : -ENODATA,
			       3600000 + (int)raw * 10000);
		}
		for (size_t i = 0; i < ARRAY_SIZE(errors); i++) {
			/* Zero and out-of-range readbacks must not hide bus errors. */
			for (unsigned int raw = 0; raw <= 255; raw += 255) {
				expect(&psy, POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,
				       0x061, raw, errors[i], errors[i], 0);
				expect(&psy, POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE,
				       0x070, raw, errors[i], errors[i], 0);
			}
		}
	}
	/* Fixed anchors and a relocated base also catch wrong units/addresses. */
	chip.base = 0x2000;
	expect(&psy, POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT, 0x061, 20, 0, 0, 1000000);
	expect(&psy, POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE, 0x070, 80, 0, 0, 4400000);
	expect(&psy, POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT, 0x061, 0, 0, 0, 0);
	expect(&psy, POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE, 0x070, 0, 0, 0, 3600000);
	/* A missing channel or changing USB presence must never publish a value. */
	expect_mid_voltage(&psy, 0, 0, 0, 0, 0, 5000000, -ENODATA, 0, 0, 0);
	chip.mid_chg = &mid;
	expect_mid_voltage(&psy, 0, 0, 0, 0, 0, 5000000, -ENODATA, 0, 1, 0);
	expect_mid_voltage(&psy, 0x10, 0x10, 0, 0, 0, 5000000, 0, 5000000, 2, 1);
	expect_mid_voltage(&psy, 0x10, 0, 0, 0, 0, 5000000, -ENODATA, 0, 2, 1);
	expect_mid_voltage(&psy, 0x10, 0x10, 0, 0, 0, 999999, -ENODATA, 0, 2, 1);
	expect_mid_voltage(&psy, 0x10, 0x10, 0, 0, 0, 1000000, 0, 1000000, 2, 1);
	expect_mid_voltage(&psy, 0x10, 0x10, -EIO, 0, 0, 5000000, -EIO, 0, 1, 0);
	expect_mid_voltage(&psy, 0x10, 0x10, 0, -ETIMEDOUT, 0, 5000000, -ETIMEDOUT, 0, 1, 1);
	expect_mid_voltage(&psy, 0x10, 0x10, 0, 0, -EIO, 5000000, -EIO, 0, 2, 1);
	for (size_t i = 0; i < ARRAY_SIZE(unsupported); i++) {
		union power_supply_propval value = { .intval = -1234567 };

		map.reads = 0;
		assert(qcom_smb5_desc.get_property(&psy, unsupported[i], &value) == -EINVAL);
		assert(value.intval == -1234567 && map.reads == 0 && map.writes == 0);
		cases++;
	}
	return cases;
}
