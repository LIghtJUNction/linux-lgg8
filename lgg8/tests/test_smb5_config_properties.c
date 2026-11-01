/* SPDX-License-Identifier: GPL-2.0-only */
/* Offline kernel API boundary; production definitions are injected verbatim. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef uint32_t u32;
#define BIT(n) (1U << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))

enum power_supply_property {
	POWER_SUPPLY_PROP_PRESENT,
	POWER_SUPPLY_PROP_ONLINE,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT_MAX,
	POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX,
	POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT,
};
enum { POWER_SUPPLY_TYPE_USB = 1 };
union power_supply_propval { int intval; };
struct power_supply { void *drv_data; };
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
};
static void *power_supply_get_drvdata(struct power_supply *psy)
{
	return psy->drv_data;
}
static int regmap_read(struct regmap *map, unsigned int reg, unsigned int *value)
{
	assert(reg == map->expected_reg);
	map->reads++;
	/* Deliberately overwrite the temporary even on failure. */
	*value = map->raw;
	return map->error;
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

unsigned int smb5_config_properties_tests(void)
{
	struct regmap map = {0};
	struct qcom_smb5 chip = { .regmap = &map, .base = 0x1000 };
	struct power_supply psy = { .drv_data = &chip };
	const int errors[] = { -EIO, -ETIMEDOUT, -EAGAIN, -ENODATA };
	const enum power_supply_property unsupported[] = {
		POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT_MAX,
		POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX,
		POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT,
	};

	cases = 0;
	assert(qcom_smb5_desc.num_properties == 4);
	for (unsigned int p = 0; p < 4; p++) {
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
	for (size_t i = 0; i < ARRAY_SIZE(unsupported); i++) {
		union power_supply_propval value = { .intval = -1234567 };

		map.reads = 0;
		assert(qcom_smb5_desc.get_property(&psy, unsupported[i], &value) == -EINVAL);
		assert(value.intval == -1234567 && map.reads == 0 && map.writes == 0);
		cases++;
	}
	return cases;
}
