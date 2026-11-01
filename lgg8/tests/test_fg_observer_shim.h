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
#define DIV_ROUND_CLOSEST(x, y) (((x) + (y) / 2) / (y))
#define GFP_KERNEL 0
#define EPROBE_DEFER 517
#define IRQ_HANDLED 1
#define IRQF_ONESHOT 0x2000
typedef int irqreturn_t;
typedef irqreturn_t (*irq_handler_t)(int, void *);
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
    unsigned int fail_at_count, change_at_count, change_reg;
    u8 change_value;
};
struct fwnode_handle {
    u32 bases[4];
    int count, count_error, read_error;
    bool interrupts, extended, interrupt_names;
    int irq_count, name_count, name_error;
    const char *names[4];
    int irqs[3];
    unsigned int count_calls;
};
struct qcom_spmi_pmic { unsigned int subtype; };
struct power_supply;
struct device {
    struct device *parent;
    struct regmap *map;
    struct fwnode_handle node;
    struct fwnode_handle *of_node;
    struct qcom_spmi_pmic pmic;
    void *drvdata, *allocation;
    struct power_supply *psy;
    int pmic_error, register_error;
    unsigned int irq_lookups, irq_requests, active_irqs, released_irqs, notifications;
    unsigned int fail_request;
    int request_error;
    bool immediate_irq, irq_during_release;
    struct {
        int irq;
        irq_handler_t thread;
        void *data;
    } handlers[3];
    unsigned int resources[4], resource_count;
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
    POWER_SUPPLY_PROP_PRESENT, POWER_SUPPLY_PROP_CAPACITY,
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
    struct device *owner;
    bool live;
};
struct dev_pm_ops {
    int (*suspend)(struct device *);
    int (*resume)(struct device *);
    int (*thaw)(struct device *);
    int (*restore)(struct device *);
};
#define DEFINE_SIMPLE_DEV_PM_OPS(n, s, r) \
    const struct dev_pm_ops n = { .suspend = s, .resume = r, .thaw = r, .restore = r }
#define pm_sleep_ptr(p) (p)
struct of_device_id { const char *compatible; };
struct platform_driver {
    int (*probe)(struct platform_device *);
    struct {
        const char *name;
        const struct of_device_id *of_match_table;
        const struct attribute_group **dev_groups;
        const struct dev_pm_ops *pm;
    } driver;
};

static inline int regmap_read(struct regmap *map, unsigned int reg, unsigned int *v)
{
    assert(reg < sizeof(map->bytes));
    assert(map->read_count < ARRAY_SIZE(map->reads));
    map->reads[map->read_count++] = reg;
    if (map->read_count == map->change_at_count)
        map->bytes[map->change_reg] = map->change_value;
    if (map->read_count == map->fail_at_count && map->read_error)
        return map->read_error;
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
static inline bool device_property_present(struct device *dev, const char *name)
{
    if (!strcmp(name, "interrupts")) return dev->node.interrupts;
    if (!strcmp(name, "interrupts-extended")) return dev->node.extended;
    assert(!strcmp(name, "interrupt-names"));
    return dev->node.interrupt_names;
}
static inline int device_property_string_array_count(const struct device *dev, const char *name)
{
    assert(!strcmp(name, "interrupt-names"));
    return dev->node.name_error ?: dev->node.name_count;
}
static inline int device_property_match_string(struct device *dev, const char *property,
                                               const char *name)
{
    assert(!strcmp(property, "interrupt-names"));
    for (int i = 0; i < dev->node.name_count; i++)
        if (!strcmp(dev->node.names[i], name)) return i;
    return -EINVAL;
}
static inline int of_irq_count(struct fwnode_handle *node)
{ assert(node); node->count_calls++; return node->irq_count; }
static inline int platform_get_irq_byname(struct platform_device *pdev, const char *name)
{
    struct device *dev = &pdev->dev;
    dev->irq_lookups++;
    for (int i = 0; i < dev->node.name_count; i++)
        if (!strcmp(dev->node.names[i], name)) return dev->node.irqs[i];
    return -ENXIO;
}
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
    dev->psy->owner = dev;
    dev->psy->live = true;
    assert(dev->resource_count < ARRAY_SIZE(dev->resources));
    dev->resources[dev->resource_count++] = 0;
    return dev->psy;
}
static inline void power_supply_changed(struct power_supply *psy)
{
    assert(psy && psy->live && psy->owner->psy == psy);
    psy->owner->notifications++;
}
static inline int devm_request_threaded_irq(struct device *dev, unsigned int irq,
    irq_handler_t top, irq_handler_t thread, unsigned long flags,
    const char *name, void *data)
{
    assert(dev->psy && dev->psy->live && dev->drvdata == data);
    assert(!top && thread && flags == IRQF_ONESHOT);
    unsigned int index = dev->irq_requests++;
    assert(index < 3 && !strcmp(name, dev->node.names[index]));
    assert((int)irq == dev->node.irqs[index]);
    if (dev->fail_request == index + 1) return dev->request_error;
    dev->handlers[index].irq = (int)irq;
    dev->handlers[index].thread = thread;
    dev->handlers[index].data = data;
    dev->active_irqs++;
    assert(dev->resource_count < ARRAY_SIZE(dev->resources));
    dev->resources[dev->resource_count++] = index + 1;
    if (dev->immediate_irq) assert(thread((int)irq, data) == IRQ_HANDLED);
    return 0;
}
/* Model API acquisition order only, not real kernel IRQ synchronization. */
static inline void host_release_resources(struct device *dev)
{
    while (dev->resource_count) {
        unsigned int resource = dev->resources[--dev->resource_count];
        if (resource) {
            unsigned int i = resource - 1;
            assert(dev->psy && dev->psy->live && dev->active_irqs);
            if (dev->irq_during_release)
                assert(dev->handlers[i].thread(dev->handlers[i].irq,
                                               dev->handlers[i].data) == IRQ_HANDLED);
            dev->handlers[i].thread = NULL;
            dev->active_irqs--;
            dev->released_irqs++;
        } else {
            assert(!dev->active_irqs && dev->psy && dev->psy->live);
            dev->psy->live = false;
            free(dev->psy);
            dev->psy = NULL;
        }
    }
    free(dev->allocation);
    dev->allocation = dev->drvdata = NULL;
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
