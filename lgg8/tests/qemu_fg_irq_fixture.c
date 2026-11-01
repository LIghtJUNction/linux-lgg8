// SPDX-License-Identifier: GPL-2.0-only
/*
 * QEMU arm64 virt-only software IRQ -> real power_supply notification fixture.
 *
 * The build script must replace LGG8_FG_PRODUCTION_DEFINITIONS below with the
 * VERBATIM definitions from drivers/power/supply/qcom_fg_observer.c, in order:
 * all FG_* macros; struct qcom_fg_observer; the block from
 * fg_observer_read_pair() through fg_observer_desc; and fg_observer_irq().
 * This includes the production property array, getter, and its dependencies.
 * There is no replacement getter or callback. The unexpanded source must fail
 * to compile.
 *
 * No PMIC, SPMI, DT IRQ lookup, hardware IRQ, or FG initialization is used.
 * Flushing kernel work does not drain a userspace listener's netlink socket.
 * Mode changes do not notify by themselves; trigger exercises the IRQ path.
 * This does not exercise the production probe, SPMI transport, or irqchip.
 */
#include <linux/atomic.h>
#include <linux/device.h>
#include <linux/err.h>
#include <linux/init.h>
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <linux/irqdesc.h>
#include <linux/kernel.h>
#include <linux/kobject.h>
#include <linux/math64.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/numa.h>
#include <linux/of.h>
#include <linux/power_supply.h>
#include <linux/regmap.h>
#include <linux/sysfs.h>
#include <linux/unaligned.h>
#include <linux/workqueue.h>

/* LGG8_FG_PRODUCTION_DEFINITIONS */

/* Match the four address resources, but back every byte solely with RAM. */
#define FIXTURE_SOC_BASE 0x4000
#define FIXTURE_BATT_BASE 0x4100
#define FIXTURE_RRADC_BASE 0x4200
#define FIXTURE_MEM_BASE 0x4300
#define FIXTURE_PAGE_SIZE 0x100

struct fixture_memory {
	struct mutex lock;
	u8 registers[4 * FIXTURE_PAGE_SIZE];
	atomic64_t io_error_count;
	bool voltage_error;
};

static struct {
	struct device *root;
	struct power_supply *psy;
	struct qcom_fg_observer fg;
	struct fixture_memory memory;
	struct kobject *kobj;
	atomic64_t handler_count;
	unsigned int mode;
	int irq;
	bool requested;
	bool group_created;
	bool stopping;
} fixture = {
	.handler_count = ATOMIC64_INIT(0),
	.irq = -1,
};
static DEFINE_MUTEX(fixture_lock);

static int fixture_reg_read(void *context, unsigned int reg, unsigned int *value)
{
	struct fixture_memory *memory = context;
	int ret = 0;

	if (reg < FIXTURE_SOC_BASE ||
	    reg >= FIXTURE_SOC_BASE + sizeof(memory->registers))
		return -EINVAL;
	mutex_lock(&memory->lock);
	/* Fail the first voltage byte; presence and the other registers still work. */
	if (memory->voltage_error && reg == FIXTURE_BATT_BASE + FG_VOLTAGE_OFFSET) {
		atomic64_inc(&memory->io_error_count);
		ret = -EIO;
	} else {
		*value = memory->registers[reg - FIXTURE_SOC_BASE];
	}
	mutex_unlock(&memory->lock);
	return ret;
}

static int fixture_reg_write(void *context, unsigned int reg, unsigned int value)
{
	/* Even an unexpected regmap write cannot modify the fixture or any hardware. */
	return -EACCES;
}

static const struct regmap_bus fixture_regmap_bus = {
	.reg_read = fixture_reg_read,
	.reg_write = fixture_reg_write,
};

static const struct regmap_config fixture_regmap_config = {
	.name = "lgg8-fg-irq-memory",
	.reg_bits = 16,
	.val_bits = 8,
	.max_register = FIXTURE_MEM_BASE + FIXTURE_PAGE_SIZE - 1,
	.cache_type = REGCACHE_NONE,
};

/* fixture_lock serializes mode changes with triggers; readers use memory.lock. */
static void fixture_set_mode(unsigned int mode)
{
	struct fixture_memory *memory = &fixture.memory;
	u8 *rradc = &memory->registers[FIXTURE_RRADC_BASE - FIXTURE_SOC_BASE];

	mutex_lock(&memory->lock);
	rradc[FG_RRADC_STATUS_OFFSET] = mode == 2 ? FG_RRADC_BATTERY_MISSING : 0;
	memory->voltage_error = mode == 3;
	WRITE_ONCE(fixture.mode, mode);
	mutex_unlock(&memory->lock);
}

static void fixture_init_registers(void)
{
	struct fixture_memory *memory = &fixture.memory;
	u8 *batt = &memory->registers[FIXTURE_BATT_BASE - FIXTURE_SOC_BASE];
	u8 *mem = &memory->registers[FIXTURE_MEM_BASE - FIXTURE_SOC_BASE];
	u8 *rradc = &memory->registers[FIXTURE_RRADC_BASE - FIXTURE_SOC_BASE];
	u8 *soc = &memory->registers[0];

	mutex_init(&memory->lock);
	atomic64_set(&memory->io_error_count, 0);
	batt[FG_SUBTYPE_OFFSET] = FG_BATT_INFO_SUBTYPE;
	mem[FG_SUBTYPE_OFFSET] = FG_MEM_IF_SUBTYPE;
	rradc[FG_SUBTYPE_OFFSET] = FG_RRADC_SUBTYPE;
	soc[FG_SUBTYPE_OFFSET] = FG_BATT_SOC_SUBTYPE;

	/* Production conversions: 3999989 uV, +499999 uA, and 50 percent. */
	put_unaligned_le16(0x8000, batt + FG_VOLTAGE_OFFSET);
	put_unaligned_le16(0x8000, batt + FG_VOLTAGE_SHADOW_OFFSET);
	put_unaligned_le16(0xfc00, batt + FG_CURRENT_OFFSET);
	put_unaligned_le16(0xfc00, batt + FG_CURRENT_SHADOW_OFFSET);
	soc[FG_SOC_RT_STATUS_OFFSET] = FG_SOC_READY;
	soc[FG_MONOTONIC_SOC_OFFSET] = 128;
	soc[FG_MONOTONIC_SOC_OFFSET + 1] = 128;
	fixture_set_mode(0);
}

/* These callbacks intentionally perform no MMIO or transport operation. */
static void fixture_irq_noop(struct irq_data *data)
{
}

static struct irq_chip fixture_irq_chip = {
	.name = "lgg8-fg-irqtest",
	.irq_ack = fixture_irq_noop,
	.irq_mask = fixture_irq_noop,
	.irq_unmask = fixture_irq_noop,
};

static irqreturn_t fixture_irq_thread(int irq, void *data)
{
	atomic64_inc(&fixture.handler_count);
	if (READ_ONCE(fixture.mode) != 0)
		return fg_observer_irq(irq, &fixture.fg);
	return IRQ_HANDLED;
}

static ssize_t mode_show(struct kobject *kobj, struct kobj_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%u\n", READ_ONCE(fixture.mode));
}

static ssize_t mode_store(struct kobject *kobj, struct kobj_attribute *attr,
			  const char *buf, size_t count)
{
	unsigned int mode;
	int ret;

	ret = kstrtouint(buf, 10, &mode);
	if (ret)
		return ret;
	if (mode > 3)
		return -EINVAL;

	mutex_lock(&fixture_lock);
	if (fixture.stopping) {
		ret = -ENODEV;
	} else {
		/* Finish old IRQs and their getter work before changing memory/errors. */
		synchronize_irq(fixture.irq);
		flush_work(&fixture.psy->changed_work);
		fixture_set_mode(mode);
		ret = 0;
	}
	mutex_unlock(&fixture_lock);
	return ret ? ret : count;
}

static ssize_t trigger_store(struct kobject *kobj, struct kobj_attribute *attr,
			     const char *buf, size_t count)
{
	u64 before;
	int ret;

	if (!sysfs_streq(buf, "1"))
		return -EINVAL;

	mutex_lock(&fixture_lock);
	if (fixture.stopping) {
		ret = -ENODEV;
		goto out;
	}
	before = atomic64_read(&fixture.handler_count);
	/* This number belongs exclusively to our newly allocated descriptor. */
	ret = generic_handle_irq_safe(fixture.irq);
	if (ret)
		goto out;
	synchronize_irq(fixture.irq);
	flush_work(&fixture.psy->changed_work);
	if ((u64)atomic64_read(&fixture.handler_count) != before + 1)
		ret = -EIO;
out:
	mutex_unlock(&fixture_lock);
	return ret ? ret : count;
}

static ssize_t handler_count_show(struct kobject *kobj, struct kobj_attribute *attr,
				 char *buf)
{
	return sysfs_emit(buf, "%llu\n",
			  (unsigned long long)atomic64_read(&fixture.handler_count));
}

static ssize_t io_error_count_show(struct kobject *kobj, struct kobj_attribute *attr,
				  char *buf)
{
	/* Cumulative across modes; count actual failing bus reads, not IRQ intent. */
	return sysfs_emit(buf, "%llu\n",
			  (unsigned long long)atomic64_read(&fixture.memory.io_error_count));
}

static struct kobj_attribute mode_attr = __ATTR_RW(mode);
static struct kobj_attribute trigger_attr = __ATTR_WO(trigger);
static struct kobj_attribute handler_count_attr = __ATTR_RO(handler_count);
static struct kobj_attribute io_error_count_attr = __ATTR_RO(io_error_count);
static struct attribute *fixture_attrs[] = {
	&mode_attr.attr,
	&trigger_attr.attr,
	&handler_count_attr.attr,
	&io_error_count_attr.attr,
	NULL,
};
static const struct attribute_group fixture_group = {
	.attrs = fixture_attrs,
};

static void fixture_cleanup(void)
{
	mutex_lock(&fixture_lock);
	fixture.stopping = true;
	mutex_unlock(&fixture_lock);
	/* No lock held: removing sysfs waits for active stores that take it. */
	if (fixture.kobj) {
		if (fixture.group_created)
			sysfs_remove_group(fixture.kobj, &fixture_group);
		kobject_put(fixture.kobj);
		fixture.kobj = NULL;
	}
	if (fixture.requested) {
		/* free_irq synchronizes the thread before psy/fg can disappear. */
		free_irq(fixture.irq, &fixture);
		fixture.requested = false;
	}
	if (fixture.irq >= 0) {
		irq_set_chip_and_handler(fixture.irq, NULL, NULL);
		irq_free_descs(fixture.irq, 1);
		fixture.irq = -1;
	}
	if (fixture.psy) {
		/* Unregister also cancels pending/deferred power_supply work. */
		power_supply_unregister(fixture.psy);
		fixture.psy = fixture.fg.psy = NULL;
	}
	if (fixture.fg.regmap) {
		/* Getters and pending power_supply work must be gone first. */
		regmap_exit(fixture.fg.regmap);
		fixture.fg.regmap = NULL;
	}
	if (fixture.root) {
		/* Resources here are manual; no fixture devres actions remain. */
		root_device_unregister(fixture.root);
		fixture.root = NULL;
	}
}

static int __init fixture_init(void)
{
	struct power_supply_config ps_config = { .drv_data = &fixture.fg };
	int ret;

	/* Must precede every allocation, registration, and IRQ operation. */
	if (!of_machine_is_compatible("linux,dummy-virt"))
		return -ENODEV;

	fixture.root = root_device_register("lgg8-fg-irq-fixture");
	if (IS_ERR(fixture.root)) {
		ret = PTR_ERR(fixture.root);
		fixture.root = NULL;
		return ret;
	}
	fixture_init_registers();
	fixture.fg.base = FIXTURE_BATT_BASE;
	fixture.fg.mem_base = FIXTURE_MEM_BASE;
	fixture.fg.rradc_base = FIXTURE_RRADC_BASE;
	fixture.fg.soc_base = FIXTURE_SOC_BASE;
	fixture.fg.has_rradc = true;
	fixture.fg.has_soc = true;
	fixture.fg.regmap = regmap_init(fixture.root, &fixture_regmap_bus,
				      &fixture.memory, &fixture_regmap_config);
	if (IS_ERR(fixture.fg.regmap)) {
		ret = PTR_ERR(fixture.fg.regmap);
		fixture.fg.regmap = NULL;
		goto fail;
	}
	fixture.fg.desc = fg_observer_desc;
	fixture.fg.desc.name = "lgg8-fg-irq-test";
	fixture.psy = power_supply_register(fixture.root, &fixture.fg.desc, &ps_config);
	if (IS_ERR(fixture.psy)) {
		ret = PTR_ERR(fixture.psy);
		fixture.psy = NULL;
		goto fail;
	}
	fixture.fg.psy = fixture.psy;
	/* changed_work alone misses the delayed initial-registration notifier. */
	flush_delayed_work(&fixture.psy->deferred_register_work);
	flush_work(&fixture.psy->changed_work);

	/*
	 * The fixture owns both descriptor and action; a THIS_MODULE owner would
	 * self-pin on request_irq and prevent module_exit from freeing the action.
	 * Teardown synchronizes and frees the IRQ before releasing fixture state.
	 */
	fixture.irq = __irq_alloc_descs(-1, 1, 1, NUMA_NO_NODE, NULL, NULL);
	if (fixture.irq < 0) {
		ret = fixture.irq;
		goto fail;
	}
	irq_set_chip_and_handler(fixture.irq, &fixture_irq_chip, handle_simple_irq);
	irq_modify_status(fixture.irq, IRQ_NOREQUEST | IRQ_NOAUTOEN | IRQ_NOTHREAD,
			  IRQ_NOPROBE);
	ret = request_threaded_irq(fixture.irq, NULL, fixture_irq_thread, IRQF_ONESHOT,
				   "lgg8-fg-irqtest", &fixture);
	if (ret)
		goto fail;
	fixture.requested = true;

	fixture.kobj = kobject_create_and_add("lgg8-fg-irqtest", kernel_kobj);
	if (!fixture.kobj) {
		ret = -ENOMEM;
		goto fail;
	}
	ret = sysfs_create_group(fixture.kobj, &fixture_group);
	if (ret)
		goto fail;
	fixture.group_created = true;
	pr_info("lgg8-fg-irqtest: QEMU software IRQ %d ready, mode=0\n", fixture.irq);
	return 0;
fail:
	fixture_cleanup();
	return ret;
}

module_init(fixture_init);
module_exit(fixture_cleanup);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("QEMU virt-only FG callback to power_supply notification test");
