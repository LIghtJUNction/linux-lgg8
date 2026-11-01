// SPDX-License-Identifier: GPL-2.0-only
/*
 * QEMU arm64 virt-only software IRQ -> real power_supply notification fixture.
 *
 * The build script must replace LGG8_FG_PRODUCTION_DEFINITIONS below with the
 * VERBATIM struct qcom_fg_observer and fg_observer_irq() definitions from
 * drivers/power/supply/qcom_fg_observer.c. There is deliberately no replacement
 * callback here. The unexpanded source must not compile.
 *
 * No PMIC, SPMI, DT IRQ lookup, hardware IRQ, or FG initialization is used.
 * Flushing kernel work does not drain a userspace listener's netlink socket.
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
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/numa.h>
#include <linux/of.h>
#include <linux/power_supply.h>
#include <linux/regmap.h>
#include <linux/sysfs.h>
#include <linux/workqueue.h>

/* LGG8_FG_PRODUCTION_DEFINITIONS */

static struct {
	struct device *root;
	struct power_supply *psy;
	struct qcom_fg_observer fg;
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

static enum power_supply_property fixture_properties[] = {
	POWER_SUPPLY_PROP_PRESENT,
	POWER_SUPPLY_PROP_CAPACITY,
};

static int fixture_get_property(struct power_supply *psy,
				enum power_supply_property property,
				union power_supply_propval *value)
{
	switch (property) {
	case POWER_SUPPLY_PROP_PRESENT:
		value->intval = 1;
		return 0;
	case POWER_SUPPLY_PROP_CAPACITY:
		value->intval = 50;
		return 0;
	default:
		return -EINVAL;
	}
}

static const struct power_supply_desc fixture_psy_desc = {
	.name = "lgg8-fg-irq-test",
	.type = POWER_SUPPLY_TYPE_BATTERY,
	.properties = fixture_properties,
	.num_properties = ARRAY_SIZE(fixture_properties),
	.get_property = fixture_get_property,
};

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
	if (READ_ONCE(fixture.mode) == 1)
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
	if (mode > 1)
		return -EINVAL;

	mutex_lock(&fixture_lock);
	if (fixture.stopping) {
		ret = -ENODEV;
	} else {
		/* An old positive trigger must finish before entering negative mode. */
		synchronize_irq(fixture.irq);
		flush_work(&fixture.psy->changed_work);
		WRITE_ONCE(fixture.mode, mode);
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

static struct kobj_attribute mode_attr = __ATTR_RW(mode);
static struct kobj_attribute trigger_attr = __ATTR_WO(trigger);
static struct kobj_attribute handler_count_attr = __ATTR_RO(handler_count);
static struct attribute *fixture_attrs[] = {
	&mode_attr.attr,
	&trigger_attr.attr,
	&handler_count_attr.attr,
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
	if (fixture.root) {
		/* Resources here are manual; no fixture devres actions remain. */
		root_device_unregister(fixture.root);
		fixture.root = NULL;
	}
}

static int __init fixture_init(void)
{
	struct power_supply_config config = { .drv_data = &fixture };
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
	fixture.psy = power_supply_register(fixture.root, &fixture_psy_desc, &config);
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
