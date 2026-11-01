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
	struct iio_dev *indio_dev;
	const struct iio_chan_spec *channel;
	int type_error;
	unsigned int refs;
};
enum iio_chan_type { IIO_VOLTAGE, IIO_TEMP };
struct iio_chan_spec { int channel; enum iio_chan_type type; };
struct device_node;
struct fwnode_handle { struct device_node *node; };
struct fake_property {
	const char *name;
	const char *strings[3];
	u32 cells[3];
	int count, error;
	bool string;
};
struct device_node {
	struct fwnode_handle fwnode;
	struct device_node *parent, *child, *sibling, *provider;
	struct fake_property props[5];
	unsigned int nprops, refs;
	bool available;
	int channel_count, parse_error, args_count;
	u32 args[2];
};
struct of_phandle_args {
	struct device_node *np;
	int args_count;
	u32 args[2];
};
struct qcom_spmi_pmic { unsigned int subtype; };
struct device {
	struct device *parent;
	struct device_node *of_node;
	struct regmap *regmap;
	struct qcom_spmi_pmic pmic;
	struct iio_channel *channel;
	struct iio_channel *managed_channel;
	struct power_supply *registered;
	void *allocation, *drvdata;
	bool channel_present;
	int channel_error, pmic_error, reg_error, register_error;
	unsigned int gets, registrations;
	u32 base;
};
struct platform_device { struct device dev; };
struct iio_dev { struct device dev; };
struct power_supply_config { void *drv_data, *fwnode; };

static struct fake_property *property(const struct device_node *node, const char *name)
{
	for (unsigned int i = 0; i < node->nprops; i++)
		if (node->props[i].name && !strcmp(node->props[i].name, name))
			return (struct fake_property *)&node->props[i];
	return NULL;
}
static bool of_property_present(const struct device_node *node, const char *name)
{
	return property(node, name) != NULL;
}
static int of_property_count_strings(const struct device_node *node, const char *name)
{
	struct fake_property *p = property(node, name);

	return !p || !p->string ? -EINVAL : p->count;
}
static int of_property_match_string(const struct device_node *node, const char *name,
				    const char *string)
{
	struct fake_property *p = property(node, name);

	if (!p || !p->string)
		return -EINVAL;
	for (int i = 0; i < p->count; i++)
		if (!strcmp(p->strings[i], string))
			return i;
	return -ENODATA;
}
static int of_property_count_u32_elems(const struct device_node *node, const char *name)
{
	struct fake_property *p = property(node, name);

	return !p || p->string ? -EINVAL : p->count;
}
static int of_property_read_u32_array(const struct device_node *node, const char *name,
				      u32 *value, size_t count)
{
	struct fake_property *p = property(node, name);

	if (!p || p->string)
		return -EINVAL;
	if (p->error)
		return p->error;
	if (p->count < 0 || (size_t)p->count < count)
		return -EOVERFLOW;
	memcpy(value, p->cells, count * sizeof(*value));
	return 0;
}
static int of_property_read_u32(const struct device_node *node, const char *name,
			       u32 *value)
{
	return of_property_read_u32_array(node, name, value, 1);
}
static struct device_node *of_node_get(struct device_node *node)
{
	if (node)
		node->refs++;
	return node;
}
static void of_node_put(struct device_node *node)
{
	if (node) {
		assert(node->refs > 1);
		node->refs--;
	}
}
static struct device_node *of_get_parent(const struct device_node *node)
{
	return of_node_get(node->parent);
}
static bool of_device_is_available(const struct device_node *node)
{
	return node->available;
}
static bool of_device_is_compatible(const struct device_node *node, const char *compat)
{
	return of_property_match_string(node, "compatible", compat) >= 0;
}
static struct fwnode_handle *of_fwnode_handle(struct device_node *node)
{
	return node ? &node->fwnode : NULL;
}
static struct device_node *of_get_next_available_child(const struct device_node *node,
						    struct device_node *previous)
{
	struct device_node *child = previous ? previous->sibling : node->child;

	of_node_put(previous);
	while (child && !child->available)
		child = child->sibling;
	return of_node_get(child);
}
#define for_each_available_child_of_node(node, child) \
	for (child = of_get_next_available_child(node, NULL); child; \
	     child = of_get_next_available_child(node, child))
static int of_count_phandle_with_args(const struct device_node *node, const char *name,
				      const char *cells)
{
	assert(!strcmp(name, "io-channels") && !strcmp(cells, "#io-channel-cells"));
	return node->channel_count;
}
static int of_parse_phandle_with_args(const struct device_node *node, const char *name,
				      const char *cells, int index,
				      struct of_phandle_args *args)
{
	assert(!strcmp(name, "io-channels") && !strcmp(cells, "#io-channel-cells"));
	assert(index == 0);
	if (node->parse_error)
		return node->parse_error;
	if (!node->provider)
		return -EINVAL;
	args->np = of_node_get(node->provider);
	args->args_count = node->args_count;
	memcpy(args->args, node->args, sizeof(args->args));
	return 0;
}
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
	assert(!dev->registered && !dev->managed_channel);
	dev->gets++;
	if (dev->channel_error)
		return ERR_PTR(dev->channel_error);
	dev->managed_channel = dev->channel;
	dev->channel->refs++;
	return dev->channel;
}
static struct fwnode_handle *dev_fwnode(struct device *dev)
{
	return of_fwnode_handle(dev->of_node);
}
static int iio_get_channel_type(struct iio_channel *channel, enum iio_chan_type *type)
{
	if (channel->type_error)
		return channel->type_error;
	*type = channel->channel->type;
	return 0;
}
static struct power_supply *devm_power_supply_register(struct device *dev,
	const struct power_supply_desc *desc, const struct power_supply_config *cfg)
{
	dev->registrations++;
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

/* Keep the actual ADC5 data, retaining only its prescale field for this check. */
struct adc5_channels { unsigned int prescale_index; };
struct u32_fract { u32 numerator, denominator; };
#define ADC5_CHAN_VOLT(name, pre, scale) { .prescale_index = pre },
#define ADC5_CHAN_TEMP(name, pre, scale) { .prescale_index = pre },
/* ACTUAL_ADC5_DEFAULT_DATA */

enum { PMIC_NODE, CHARGER_NODE, ADC_NODE, MID_NODE, OTHER_NODE, DUP_NODE,
       ALIEN_NODE, SOURCE_NODES };
struct source_fixture {
	struct device_node nodes[SOURCE_NODES];
	struct iio_dev indio;
	struct iio_chan_spec spec;
};
static struct fake_property *add_property(struct device_node *node, const char *name)
{
	assert(node->nprops < ARRAY_SIZE(node->props));
	struct fake_property *p = &node->props[node->nprops++];

	p->name = name;
	return p;
}
static void source_init(struct source_fixture *source, struct platform_device *pdev,
			struct iio_channel *channel)
{
	struct device_node *nodes = source->nodes;
	struct fake_property *p;

	memset(source, 0, sizeof(*source));
	memset(channel, 0, sizeof(*channel));
	for (unsigned int i = 0; i < SOURCE_NODES; i++) {
		nodes[i].refs = 1;
		nodes[i].available = true;
		nodes[i].fwnode.node = &nodes[i];
	}
	nodes[CHARGER_NODE].parent = nodes[ADC_NODE].parent = &nodes[PMIC_NODE];
	nodes[ADC_NODE].child = &nodes[MID_NODE];
	nodes[MID_NODE].sibling = &nodes[OTHER_NODE];
	nodes[OTHER_NODE].sibling = &nodes[DUP_NODE];
	nodes[DUP_NODE].available = false;
	nodes[CHARGER_NODE].provider = &nodes[ADC_NODE];
	nodes[CHARGER_NODE].channel_count = nodes[CHARGER_NODE].args_count = 1;
	nodes[CHARGER_NODE].args[0] = ADC5_MID_CHG_DIV6;
	p = add_property(&nodes[CHARGER_NODE], "io-channel-names");
	p->string = true; p->count = 1; p->strings[0] = "mid-chg";
	p = add_property(&nodes[ADC_NODE], "compatible");
	p->string = true; p->count = 1; p->strings[0] = "qcom,spmi-adc5";
	p = add_property(&nodes[ADC_NODE], "reg");
	p->count = 1; p->cells[0] = 0x3100;
	p = add_property(&nodes[MID_NODE], "reg");
	p->count = 1; p->cells[0] = ADC5_MID_CHG_DIV6;
	p = add_property(&nodes[OTHER_NODE], "reg");
	p->count = 1; p->cells[0] = ADC5_DIE_TEMP;
	p = add_property(&nodes[DUP_NODE], "reg");
	p->count = 1; p->cells[0] = ADC5_MID_CHG_DIV6;
	p = add_property(&nodes[MID_NODE], "qcom,pre-scaling");
	p->count = 2; p->cells[0] = 1; p->cells[1] = 6;
	pdev->dev.of_node = &nodes[CHARGER_NODE];
	pdev->dev.parent->of_node = &nodes[PMIC_NODE];
	source->indio.dev.of_node = &nodes[ADC_NODE];
	source->spec.channel = ADC5_MID_CHG_DIV6;
	source->spec.type = IIO_VOLTAGE;
	channel->indio_dev = &source->indio;
	channel->channel = &source->spec;
	channel->refs = 1;
}
static void source_references_balanced(const struct source_fixture *source)
{
	for (unsigned int i = 0; i < SOURCE_NODES; i++)
		assert(source->nodes[i].refs == 1);
}
static void release_resources(struct device *dev)
{
	/* Model devres LIFO: psy before IIO handle before chip allocation. */
	if (dev->registered) {
		assert(dev->allocation);
		assert(!dev->managed_channel || dev->managed_channel->refs == 2);
		free(dev->registered);
		dev->registered = NULL;
	}
	if (dev->managed_channel) {
		assert(dev->managed_channel->refs == 2);
		dev->managed_channel->refs--;
		dev->managed_channel = NULL;
	}
	free(dev->allocation);
	dev->allocation = dev->drvdata = NULL;
}

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
		struct source_fixture source;
		struct platform_device pdev = { .dev = {
			.parent = &parent, .pmic = { .subtype = PM8150B_SUBTYPE },
			.base = 0x1000, .channel = &channel,
			.channel_present = scenario != 0,
		} };
		int expected = 0;

		source_init(&source, &pdev, &channel);
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
		assert(map.reads == 0 && channel.reads == 0);
		source_references_balanced(&source);
		release_resources(&pdev.dev);
		assert(channel.refs == 1);
		cases++;
	}
}

static void source_cases(void)
{
	enum {
		GOOD, DEFAULT_SCALE, NO_OF, NO_NAMES, BAD_NAME, EXTRA_NAME, DUP_NAME,
		NO_CHANNEL, EXTRA_CHANNEL, MALFORMED_CHANNEL, PARSE_FAIL, NO_PROVIDER,
		NO_ARG, EXTRA_ARG, WRONG_ARG, WRONG_COMPAT, EXTRA_COMPAT, NO_BASE,
		WRONG_BASE, EXTRA_BASE, BASE_READ_FAIL, DISABLED_ADC, OTHER_PMIC,
		NO_ADC_PARENT, OTHER_CHARGER_PARENT, WRONG_DEVICE_PARENT, NO_DEVICE_PARENT,
		NO_MID, DISABLED_MID, DUP_MID, BAD_OTHER_REG, EXTRA_CHILD_REG,
		EMPTY_SCALE, SHORT_SCALE, LONG_SCALE, MALFORMED_SCALE, SCALE_READ_FAIL,
		WRONG_NUMERATOR, WRONG_DENOMINATOR, IIO_DEFER, IIO_FAIL, TYPE_FAIL,
		WRONG_TYPE, WRONG_FWNODE, NO_FWNODE, REGISTER_FAIL,
		SOURCE_CASES
	};
	for (unsigned int scenario = 0; scenario < SOURCE_CASES; scenario++) {
		struct regmap map = {0};
		struct iio_channel channel;
		struct device parent = { .regmap = &map };
		struct platform_device pdev = { .dev = {
			.parent = &parent, .pmic = { .subtype = PM8150B_SUBTYPE },
			.base = 0x1000, .channel = &channel, .channel_present = true,
		} };
		struct source_fixture source;
		struct device_node *n = source.nodes;
		struct fake_property *names, *compat, *base, *reg, *scale;
		int expected = -EINVAL;
		bool acquired = false;

		source_init(&source, &pdev, &channel);
		names = property(&n[CHARGER_NODE], "io-channel-names");
		compat = property(&n[ADC_NODE], "compatible");
		base = property(&n[ADC_NODE], "reg");
		reg = property(&n[MID_NODE], "reg");
		scale = property(&n[MID_NODE], "qcom,pre-scaling");
		switch (scenario) {
		case GOOD: expected = 0; break;
		case DEFAULT_SCALE: scale->name = NULL; expected = 0; break;
		case NO_OF: pdev.dev.of_node = NULL; break;
		case NO_NAMES: names->name = NULL; break;
		case BAD_NAME: names->strings[0] = "other"; break;
		case EXTRA_NAME: names->count = 2; names->strings[1] = "other"; break;
		case DUP_NAME: names->count = 2; names->strings[1] = "mid-chg"; break;
		case NO_CHANNEL: n[CHARGER_NODE].channel_count = 0; break;
		case EXTRA_CHANNEL: n[CHARGER_NODE].channel_count = 2; break;
		case MALFORMED_CHANNEL: n[CHARGER_NODE].channel_count = -EINVAL; break;
		case PARSE_FAIL: n[CHARGER_NODE].parse_error = expected = -ENOENT; break;
		case NO_PROVIDER: n[CHARGER_NODE].provider = NULL; break;
		case NO_ARG: n[CHARGER_NODE].args_count = 0; break;
		case EXTRA_ARG: n[CHARGER_NODE].args_count = 2; break;
		case WRONG_ARG: n[CHARGER_NODE].args[0] = ADC5_DIE_TEMP; break;
		case WRONG_COMPAT: compat->strings[0] = "qcom,spmi-adc7"; break;
		case EXTRA_COMPAT: compat->count = 2; compat->strings[1] = "qcom,spmi-adc7"; break;
		case NO_BASE: base->name = NULL; break;
		case WRONG_BASE: base->cells[0] = 0x3200; break;
		case EXTRA_BASE: base->count = 2; break;
		case BASE_READ_FAIL: base->error = -EIO; break;
		case DISABLED_ADC: n[ADC_NODE].available = false; break;
		case OTHER_PMIC: n[ADC_NODE].parent = &n[ALIEN_NODE]; break;
		case NO_ADC_PARENT: n[ADC_NODE].parent = NULL; break;
		case OTHER_CHARGER_PARENT: n[CHARGER_NODE].parent = &n[ALIEN_NODE]; break;
		case WRONG_DEVICE_PARENT: parent.of_node = &n[ALIEN_NODE]; break;
		case NO_DEVICE_PARENT: pdev.dev.parent = NULL; break;
		case NO_MID: reg->cells[0] = ADC5_SBUx; break;
		case DISABLED_MID: n[MID_NODE].available = false; break;
		case DUP_MID: n[DUP_NODE].available = true; break;
		case BAD_OTHER_REG: property(&n[OTHER_NODE], "reg")->count = -EINVAL; break;
		case EXTRA_CHILD_REG: reg->count = 2; break;
		case EMPTY_SCALE: scale->count = 0; break;
		case SHORT_SCALE: scale->count = 1; break;
		case LONG_SCALE: scale->count = 3; break;
		case MALFORMED_SCALE: scale->count = -EOVERFLOW; break;
		case SCALE_READ_FAIL: scale->error = -EIO; break;
		case WRONG_NUMERATOR: scale->cells[0] = 2; break;
		case WRONG_DENOMINATOR: scale->cells[1] = 3; break;
		case IIO_DEFER: pdev.dev.channel_error = expected = -EPROBE_DEFER; break;
		case IIO_FAIL: pdev.dev.channel_error = expected = -ENOMEM; break;
		case TYPE_FAIL: channel.type_error = expected = -ENODEV; acquired = true; break;
		case WRONG_TYPE: source.spec.type = IIO_TEMP; acquired = true; break;
		case WRONG_FWNODE: source.indio.dev.of_node = &n[ALIEN_NODE]; acquired = true; break;
		case NO_FWNODE: source.indio.dev.of_node = NULL; acquired = true; break;
		case REGISTER_FAIL: pdev.dev.register_error = expected = -ENOMEM; acquired = true; break;
		}
		if (scenario == NO_DEVICE_PARENT) {
			/* Test the helper directly: probe requires a real PMIC parent first. */
			struct qcom_smb5 chip = {0};

			assert(qcom_smb5_get_mid_chg(&pdev.dev, &chip) == expected);
		} else {
			assert(qcom_smb5_probe(&pdev) == expected);
		}
		assert(!map.reads && !map.writes && !channel.reads);
		assert(pdev.dev.registrations == (unsigned int)(!expected || scenario == REGISTER_FAIL));
		assert(channel.refs == (acquired || !expected ? 2U : 1U));
		if (expected && scenario < IIO_DEFER)
			assert(pdev.dev.gets == 0);
		if (expected) {
			assert(!pdev.dev.registered && !pdev.dev.drvdata);
			if (pdev.dev.allocation)
				assert(!((struct qcom_smb5 *)pdev.dev.allocation)->mid_chg ||
				       scenario == REGISTER_FAIL);
		}
		source_references_balanced(&source);
		release_resources(&pdev.dev);
		assert(channel.refs == 1);
		if (scenario == IIO_DEFER) {
			pdev.dev.channel_error = 0;
			assert(!qcom_smb5_probe(&pdev));
			assert(pdev.dev.gets == 2 && !channel.reads && !map.reads);
			source_references_balanced(&source);
			release_resources(&pdev.dev);
			assert(channel.refs == 1);
		}
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
	unsigned int pre = adc5_chans_pmic[ADC5_MID_CHG_DIV6].prescale_index;

	assert(ADC5_MID_CHG_DIV6 == 0x1e && pre < ARRAY_SIZE(adc5_prescale_ratios));
	assert(adc5_prescale_ratios[pre].numerator == 1);
	assert(adc5_prescale_ratios[pre].denominator == 6);
	source_cases();
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
	expect_mid_voltage(&psy, 0x10, 0x10, 0, 0, 0, 5000, -ENODATA, 0, 2, 1);
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
