/* SPDX-License-Identifier: GPL-2.0-only */
/* Host substitutes for kernel APIs; observer logic stays in its actual .c. */
#ifndef TEST_FG_OBSERVER_SHIM_H
#define TEST_FG_OBSERVER_SHIM_H
#ifndef TEST_FG_OBSERVER_OFFLINE
#error "This header is only for the offline observer test"
#endif
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef int16_t s16;
typedef uint32_t u32;
typedef int64_t s64;
#define BIT(n) (1U << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define GFP_KERNEL 0
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define MODULE_DEVICE_TABLE(...)
#define MODULE_DESCRIPTION(...)
#define MODULE_LICENSE(...)
#define module_platform_driver(d) \
    static const void *const test_registered_driver __attribute__((used)) = &(d)

struct regmap {
    u8 bytes[0x10000];
    unsigned int reads[256], read_count, writes;
    unsigned int fail_reg;
    int read_error;
};
struct fwnode_handle {
    u32 bases[4];
    int count, count_error, read_error;
};
struct qcom_spmi_pmic { unsigned int subtype; };
struct power_supply;
struct device {
    struct device *parent;
    struct regmap *map;
    struct fwnode_handle node;
    struct qcom_spmi_pmic pmic;
    void *drvdata, *allocation;
    struct power_supply *psy;
    int pmic_error, register_error;
};
struct platform_device { struct device dev; };
struct attribute { const char *name; };
struct device_attribute {
    struct attribute attr;
    ssize_t (*show)(struct device *, struct device_attribute *, char *);
};
#define DEVICE_ATTR_RO(n) \
    struct device_attribute dev_attr_##n = { { #n }, n##_show }
struct attribute_group { struct attribute **attrs; };
#define ATTRIBUTE_GROUPS(n) \
    static const struct attribute_group n##_group = { n##_attrs }; \
    static const struct attribute_group *n##_groups[] = { &n##_group, NULL }
enum power_supply_property {
    POWER_SUPPLY_PROP_VOLTAGE_NOW, POWER_SUPPLY_PROP_CURRENT_NOW,
    POWER_SUPPLY_PROP_PRESENT,
};
#define POWER_SUPPLY_TYPE_BATTERY 1
union power_supply_propval { int intval; };
struct power_supply_desc {
    const char *name;
    int type;
    const enum power_supply_property *properties;
    size_t num_properties;
    int (*get_property)(struct power_supply *, enum power_supply_property,
                        union power_supply_propval *);
};
struct power_supply_config { void *drv_data; struct fwnode_handle *fwnode; };
struct power_supply {
    const struct power_supply_desc *desc;
    struct power_supply_config config;
};
struct of_device_id { const char *compatible; };
struct platform_driver {
    int (*probe)(struct platform_device *);
    struct {
        const char *name;
        const struct of_device_id *of_match_table;
        const struct attribute_group **dev_groups;
    } driver;
};

static inline int regmap_read(struct regmap *map, unsigned int reg, unsigned int *v)
{
    assert(reg < sizeof(map->bytes));
    assert(map->read_count < ARRAY_SIZE(map->reads));
    map->reads[map->read_count++] = reg;
    if (reg == map->fail_reg && map->read_error)
        return map->read_error;
    *v = map->bytes[reg];
    return 0;
}
static inline int regmap_read_bypassed(struct regmap *map, unsigned int reg,
                                      unsigned int *v)
{ return regmap_read(map, reg, v); }
static inline int regmap_bulk_read(struct regmap *map, unsigned int reg,
                                  void *data, size_t size)
{
    for (size_t i = 0; i < size; i++) {
        unsigned int value;
        int ret = regmap_read(map, reg + i, &value);
        if (ret) return ret;
        ((u8 *)data)[i] = value;
    }
    return 0;
}
/* Any production write is recorded and fails; tests also assert zero writes. */
static inline int regmap_write(struct regmap *map, unsigned int reg, unsigned int v)
{ (void)reg; (void)v; map->writes++; return -EIO; }
static inline int regmap_bulk_write(struct regmap *map, unsigned int reg,
                                   const void *data, size_t size)
{ (void)data; (void)size; return regmap_write(map, reg, 0); }
static inline int regmap_update_bits(struct regmap *map, unsigned int reg,
                                    unsigned int mask, unsigned int v)
{ (void)mask; return regmap_write(map, reg, v); }
static inline int regmap_write_bits(struct regmap *map, unsigned int reg,
                                   unsigned int mask, unsigned int v)
{ return regmap_update_bits(map, reg, mask, v); }
static inline const struct qcom_spmi_pmic *qcom_pmic_get(struct device *dev)
{ return dev->pmic_error ? ERR_PTR(dev->pmic_error) : &dev->pmic; }
static inline struct regmap *dev_get_regmap(struct device *dev, const char *name)
{ (void)name; return dev->map; }
static inline int dev_err_probe(struct device *dev, int ret, const char *fmt, ...)
{ (void)dev; (void)fmt; return ret; }
static inline void *devm_kzalloc(struct device *dev, size_t size, int flags)
{ (void)flags; assert(!dev->allocation); return dev->allocation = calloc(1, size); }
static inline int device_property_count_u32(struct device *dev, const char *name)
{ assert(!strcmp(name, "reg")); return dev->node.count_error ?: dev->node.count; }
static inline int device_property_read_u32_array(struct device *dev, const char *name,
                                               u32 *values, size_t count)
{
    assert(!strcmp(name, "reg"));
    if (dev->node.read_error) return dev->node.read_error;
    if (dev->node.count < 0 || count > (size_t)dev->node.count) return -EOVERFLOW;
    memcpy(values, dev->node.bases, count * sizeof(*values));
    return 0;
}
static inline struct fwnode_handle *dev_fwnode(struct device *dev) { return &dev->node; }
static inline struct power_supply *devm_power_supply_register(struct device *dev,
    const struct power_supply_desc *desc, const struct power_supply_config *cfg)
{
    if (dev->register_error) return ERR_PTR(dev->register_error);
    dev->psy = calloc(1, sizeof(*dev->psy));
    assert(dev->psy);
    dev->psy->desc = desc;
    dev->psy->config = *cfg;
    return dev->psy;
}
static inline void *power_supply_get_drvdata(struct power_supply *psy)
{ return psy->config.drv_data; }
static inline void platform_set_drvdata(struct platform_device *pdev, void *data)
{ pdev->dev.drvdata = data; }
static inline void *dev_get_drvdata(struct device *dev) { return dev->drvdata; }
static inline s64 div_s64(s64 value, int divisor) { return value / divisor; }
static inline u16 get_unaligned_le16(const void *p)
{ const u8 *b = p; return b[0] | ((u16)b[1] << 8); }
static inline int sysfs_emit(char *buf, const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    int ret = vsnprintf(buf, 4096, fmt, args);
    va_end(args);
    return ret;
}
#endif
