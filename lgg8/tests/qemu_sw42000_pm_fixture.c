// SPDX-License-Identifier: GPL-2.0-only
/*
 * QEMU virt ONLY. Real SW42000 probe, I2C/input/IRQ APIs and device PM core;
 * RAM-only I2C registers, GPIO chip and software IRQ. No MMIO or phone access.
 *
 * The runner inserts the WHOLE production driver, removing only its automatic
 * module registration. Normal runs retain its real dev_pm_ops and callbacks.
 * Registration names/IDs are private, so the older built-in driver cannot bind.
 * This tests prepare/suspend/resume/complete, NOT late/noirq, s2idle entry,
 * electrical timing, power retention, gesture wakeup or real silicon recovery.
 * The private irqchip uses eager masking; this is not an LG irqchip model.
 * The fake finger is lifted before resume; hardware read-to-clear semantics
 * and pending physical-edge freshness are deliberately not asserted.
 */
#include <linux/atomic.h>
#include <linux/completion.h>
#include <linux/gpio/driver.h>
#include <linux/gpio/machine.h>
#include <linux/input/mt.h>
#include <linux/irq.h>
#include <linux/kthread.h>
#include <linux/numa.h>
#include <linux/pm.h>
#include <linux/suspend.h>
#include <linux/unaligned.h>
#include <linux/wait.h>

/* LGG8_SW42000_COMPLETE_DRIVER */

static bool skip_pm;
module_param(skip_pm, bool, 0400);
MODULE_PARM_DESC(skip_pm, "Negative control: remove the driver PM table");

static struct {
	struct device *root;
	struct i2c_adapter adapter;
	struct i2c_client *client;
	struct gpio_chip gpio;
	struct task_struct *worker;
	struct kobject *kobj;
	wait_queue_head_t wait;
	struct mutex bus_lock;
	struct completion report_entered, release_report;
	atomic_t started, result, cases, gpio_changes;
	atomic_t stop_writes, active_writes, report_reads, fail_stop, fail_version;
	atomic_t masks, unmasks, pm_starts, pm_ends, hold_report, overlap;
	u16 address;
	u32 driving;
	int gpio_value[3];
	int irq;
	bool down, adapter_added, gpio_added, driver_added, lookup_added, group_added;
	char client_name[32];
} fx = { .irq = -1 };

static struct gpiod_lookup_table fixture_lookup = {
	.table = {
		GPIO_LOOKUP("sw42000-pm-ram", 0, "reset", GPIO_ACTIVE_HIGH),
		GPIO_LOOKUP("sw42000-pm-ram", 1, "vdd", GPIO_ACTIVE_HIGH),
		GPIO_LOOKUP("sw42000-pm-ram", 2, "vcl", GPIO_ACTIVE_HIGH),
		{ }
	},
};

static int fixture_gpio_get(struct gpio_chip *chip, unsigned int offset)
{
	return READ_ONCE(fx.gpio_value[offset]);
}

static int fixture_gpio_set(struct gpio_chip *chip, unsigned int offset, int value)
{
	WRITE_ONCE(fx.gpio_value[offset], value);
	atomic_inc(&fx.gpio_changes);
	return 0;
}

static int fixture_gpio_direction(struct gpio_chip *chip, unsigned int offset)
{
	return GPIO_LINE_DIRECTION_OUT;
}

static int fixture_gpio_output(struct gpio_chip *chip, unsigned int offset, int value)
{
	return fixture_gpio_set(chip, offset, value);
}

static void fixture_irq_mask(struct irq_data *data) { atomic_inc(&fx.masks); }
static void fixture_irq_unmask(struct irq_data *data) { atomic_inc(&fx.unmasks); }
static void fixture_irq_noop(struct irq_data *data) { }
static int fixture_irq_type(struct irq_data *data, unsigned int type) { return 0; }
static struct irq_chip fixture_irq_chip = {
	.name = "sw42000-pm-ram",
	.irq_mask = fixture_irq_mask,
	.irq_unmask = fixture_irq_unmask,
	.irq_ack = fixture_irq_noop,
	.irq_set_type = fixture_irq_type,
};

static u32 fixture_functionality(struct i2c_adapter *adapter) { return I2C_FUNC_I2C; }

static int fixture_transfer(struct i2c_adapter *adapter, struct i2c_msg *msgs, int count)
{
	struct i2c_msg *m = msgs;
	u32 value;
	int ret = -EINVAL;

	if (count != 1 || m->addr != 0x28)
		return -EINVAL;
	mutex_lock(&fx.bus_lock);
	if (!(m->flags & I2C_M_RD) && (m->len == 2 || m->len == 6)) {
		fx.address = ((m->buf[0] & 0xf) << 8) | m->buf[1];
		if (m->len == 6) {
			value = get_unaligned_le32(m->buf + 2);
			if (fx.address == SW42000_REG_DRIVING_CONTROL) {
				fx.driving = value;
				if (value == SW42000_STOP_DRIVING) {
					atomic_inc(&fx.stop_writes);
					/* Ambiguous write: effect happens BEFORE the error. */
					if (atomic_xchg(&fx.fail_stop, 0)) {
						ret = -ENXIO;
						goto out;
					}
				} else if (value == SW42000_ACTIVE_DRIVING) {
					atomic_inc(&fx.active_writes);
				}
			}
		}
		ret = 1;
	} else if (m->flags & I2C_M_RD) {
		memset(m->buf, 0, m->len);
		if (fx.address == SW42000_REG_TOUCH_STATUS && m->len == SW42000_REPORT_SIZE) {
			if (atomic_xchg(&fx.hold_report, 0)) {
				complete(&fx.report_entered);
				if (!wait_for_completion_timeout(&fx.release_report,
							 msecs_to_jiffies(2000))) {
					ret = -ETIMEDOUT;
					goto out;
				}
			}
			atomic_inc(&fx.report_reads);
			put_unaligned_le32(5U << 16, m->buf + 4);
			put_unaligned_le32(1U << 8, m->buf + 8);
			put_unaligned_le32((fx.down ? SW42000_EVENT_DOWN : SW42000_EVENT_UP)
					   << 16, m->buf + 12);
			ret = 1;
		} else if (m->len == 4) {
			switch (fx.address) {
			case SW42000_REG_VERSION:
				if (atomic_xchg(&fx.fail_version, 0)) {
					ret = -EREMOTEIO;
					goto out;
				}
				m->buf[2] = SW42000_CHIP_ID;
				m->buf[3] = SW42000_PROTOCOL_VERSION;
				break;
			case SW42000_REG_BOOT_CRC_RESULT:
				put_unaligned_le32(SW42000_CRC_FIXED_VALUE, m->buf);
				break;
			case SW42000_REG_BOOT_CRC_PASS:
			case SW42000_REG_INFO_POINTER:
				put_unaligned_le32(1, m->buf);
				break;
			default:
				goto out;
			}
			ret = 1;
		}
	}
out:
	mutex_unlock(&fx.bus_lock);
	return ret;
}

static const struct i2c_algorithm fixture_algorithm = {
	.master_xfer = fixture_transfer,
	.functionality = fixture_functionality,
};

static bool contacts_released(struct sw42000_ts *ts)
{
	unsigned long flags;
	bool released;
	int i;

	spin_lock_irqsave(&ts->input->event_lock, flags);
	released = !test_bit(BTN_TOUCH, ts->input->key);
	for (i = 0; i < SW42000_REPORT_CONTACTS; i++)
		released &= input_mt_get_value(&ts->input->mt->slots[i], ABS_MT_TRACKING_ID) < 0;
	spin_unlock_irqrestore(&ts->input->event_lock, flags);
	return released;
}

/* Exported API only. This says NOTHING about the exact IRQ nesting depth. */
static bool irq_disabled(void)
{
	struct irq_data *data = irq_get_irq_data(fx.irq);

	return data && irqd_irq_disabled(data);
}

static int release_inflight_report(void *unused)
{
	int before = atomic_read(&fx.stop_writes);
	int i;

	/* disable_irq() must inhibit dispatch while waiting for the real IRQ thread. */
	for (i = 0; i < 1000 && !kthread_should_stop(); i++) {
		if (irq_disabled()) {
			atomic_set(&fx.overlap, atomic_read(&fx.stop_writes) == before ? 1 : -1);
			break;
		}
		usleep_range(1000, 1500);
	}
	complete_all(&fx.release_report);
	/* Keep a valid task reference until pm_cycle() calls kthread_stop(). */
	wait_event_interruptible(fx.wait, kthread_should_stop());
	return 0;
}

static int inject_touch(struct sw42000_ts *ts)
{
	int ret;

	mutex_lock(&fx.bus_lock);
	fx.down = true;
	mutex_unlock(&fx.bus_lock);
	ret = generic_handle_irq_safe(fx.irq);
	if (ret)
		return ret;
	synchronize_irq(fx.irq);
	return contacts_released(ts) ? -EUCLEAN : 0;
}

/* No direct call to a production PM callback occurs anywhere in this fixture. */
static int pm_cycle(int scenario)
{
	struct sw42000_ts *ts = i2c_get_clientdata(fx.client);
	struct task_struct *releaser = NULL;
	unsigned int flags;
	int ret, gpios, active, masks, unmasks, reads;
	bool good, initially_enabled = ts->irq_enabled;

	if (ts->irq_enabled && inject_touch(ts))
		return -EUCLEAN;
	gpios = atomic_read(&fx.gpio_changes);
	active = atomic_read(&fx.active_writes);
	masks = atomic_read(&fx.masks);
	unmasks = atomic_read(&fx.unmasks);
	if (scenario == 6) {
		reinit_completion(&fx.report_entered);
		reinit_completion(&fx.release_report);
		atomic_set(&fx.hold_report, 1);
		atomic_set(&fx.overlap, 0);
		ret = generic_handle_irq_safe(fx.irq);
		if (ret || !wait_for_completion_timeout(&fx.report_entered,
						       msecs_to_jiffies(1000))) {
			complete_all(&fx.release_report);
			synchronize_irq(fx.irq);
			return -ETIMEDOUT;
		}
		releaser = kthread_run(release_inflight_report, NULL, "sw42000-pm-release");
		if (IS_ERR(releaser)) {
			complete_all(&fx.release_report);
			synchronize_irq(fx.irq);
			return PTR_ERR(releaser);
		}
	}
	if (scenario == 1 || scenario == 4)
		atomic_set(&fx.fail_stop, 1);
	if (scenario == 4)
		atomic_set(&fx.fail_version, 1);

	flags = lock_system_sleep();
	atomic_inc(&fx.pm_starts);
	ret = dpm_suspend_start(PMSG_SUSPEND);
	/* Snapshot after the real PM core returns; always unwind, including errors. */
	if (scenario == 1) {
		good = ret == -ENXIO && !fx.client->dev.power.is_suspended &&
			ts->irq_enabled && !irq_disabled() &&
			fx.driving == SW42000_ACTIVE_DRIVING && contacts_released(ts);
	} else if (scenario == 4) {
		good = ret == -ENXIO && !fx.client->dev.power.is_suspended &&
			!ts->irq_enabled && irq_disabled() && contacts_released(ts);
	} else {
		good = !ret && fx.client->dev.power.is_suspended &&
			!ts->irq_enabled && irq_disabled() &&
			fx.driving == SW42000_STOP_DRIVING && contacts_released(ts);
	}
	if (!ret && irq_disabled()) {
		/* Attempt real dispatch while disabled: there must be no bus report read. */
		reads = atomic_read(&fx.report_reads);
		good &= !generic_handle_irq_safe(fx.irq);
		synchronize_irq(fx.irq);
		good &= reads == atomic_read(&fx.report_reads);
	}
	if (scenario == 2)
		atomic_set(&fx.fail_version, 1);
	/* A disabled software IRQ may be replayed when enabled. Supply an UP report,
	 * rather than inventing undocumented hardware report-consumption behavior.
	 */
	mutex_lock(&fx.bus_lock);
	fx.down = false;
	mutex_unlock(&fx.bus_lock);
	dpm_resume_end(PMSG_RESUME);
	atomic_inc(&fx.pm_ends);
	unlock_system_sleep(flags);
	if (releaser)
		kthread_stop(releaser);
	synchronize_irq(fx.irq);

	good &= gpios == atomic_read(&fx.gpio_changes);
	good &= contacts_released(ts) && !fx.client->dev.power.is_suspended;
	good &= !fx.client->dev.power.is_prepared;
	good &= !atomic_read(&fx.fail_stop) && !atomic_read(&fx.fail_version);
	if (scenario == 2 || scenario == 4) {
		good &= !ts->irq_enabled && irq_disabled() &&
			fx.driving == SW42000_STOP_DRIVING;
	} else {
		good &= ts->irq_enabled && !irq_disabled() &&
			fx.driving == SW42000_ACTIVE_DRIVING;
		/* Delivery after resume proves inhibition was actually lifted. */
		reads = atomic_read(&fx.report_reads);
		good &= !inject_touch(ts) && atomic_read(&fx.report_reads) > reads;
		/* Release through the real IRQ/report/input path, not a direct callback. */
		mutex_lock(&fx.bus_lock);
		fx.down = false;
		mutex_unlock(&fx.bus_lock);
		good &= !generic_handle_irq_safe(fx.irq);
		synchronize_irq(fx.irq);
		good &= contacts_released(ts);
	}
	if (!skip_pm) {
		if (initially_enabled)
			good &= atomic_read(&fx.masks) > masks;
		if (scenario != 2 && scenario != 4)
			good &= atomic_read(&fx.unmasks) > unmasks;
	}
	if (scenario == 6)
		good &= atomic_read(&fx.overlap) == 1;
	/* A failed own suspend must not receive a second resume from PM core. */
	if (scenario == 1)
		good &= atomic_read(&fx.active_writes) == active + 1;
	return good ? 0 : -EUCLEAN;
}

static int fixture_worker(void *unused)
{
	static const int scenarios[] = { 0, 1, 2, 3, 4, 5, 6 };
	int ret = 0, i;

	wait_event_interruptible(fx.wait, atomic_read(&fx.started) || kthread_should_stop());
	if (kthread_should_stop())
		return 0;
	for (i = 0; i < ARRAY_SIZE(scenarios); i++) {
		if (kthread_should_stop()) {
			ret = -ECANCELED;
			break;
		}
		ret = pm_cycle(scenarios[i]);
		if (ret)
			break;
		atomic_or(BIT(i), &fx.cases);
		pr_info("SW42000_QEMU_PM: scenario %d passed via device PM core\n", i);
	}
	/* Publish case/cycle counters before the guest observes completion. */
	atomic_set_release(&fx.result, ret);
	/* Keep the task alive until module_exit can join it safely. */
	wait_event_interruptible(fx.wait, kthread_should_stop());
	return 0;
}

static ssize_t run_store(struct kobject *k, struct kobj_attribute *a,
			const char *buf, size_t count)
{
	if (!sysfs_streq(buf, "1"))
		return -EINVAL;
	if (atomic_cmpxchg(&fx.started, 0, 1))
		return -EALREADY;
	wake_up(&fx.wait);
	return count;
}

static ssize_t status_show(struct kobject *k, struct kobj_attribute *a, char *buf)
{
	int result = atomic_read_acquire(&fx.result);

	return sysfs_emit(buf, "%d %u %d %d\n", result,
			  (unsigned int)atomic_read(&fx.cases),
			  atomic_read(&fx.pm_starts), atomic_read(&fx.pm_ends));
}

/* Read-only observations of simulated bus writes, also usable when the
 * real /sys/power/state path drives the PM dispatcher instead of the worker.
 */
static ssize_t bus_counts_show(struct kobject *k, struct kobj_attribute *a, char *buf)
{
	return sysfs_emit(buf, "%d %d\n", atomic_read(&fx.stop_writes),
			  atomic_read(&fx.active_writes));
}

static struct kobj_attribute run_attribute = __ATTR_WO(run);
static struct kobj_attribute status_attribute = __ATTR_RO(status);
static struct kobj_attribute bus_counts_attribute = __ATTR_RO(bus_counts);
static struct attribute *fixture_attrs[] = {
	&run_attribute.attr, &status_attribute.attr, &bus_counts_attribute.attr, NULL,
};
static const struct attribute_group fixture_group = { .attrs = fixture_attrs };
static const struct i2c_device_id fixture_ids[] = { { "sw42000-pm-qemu", 0 }, { } };

static void fixture_cleanup(void)
{
	if (fx.group_added)
		sysfs_remove_group(fx.kobj, &fixture_group);
	complete_all(&fx.release_report);
	if (fx.worker)
		kthread_stop(fx.worker);
	if (fx.kobj)
		kobject_put(fx.kobj);
	if (fx.client)
		i2c_unregister_device(fx.client);
	if (fx.driver_added)
		i2c_del_driver(&sw42000_driver);
	if (fx.lookup_added)
		gpiod_remove_lookup_table(&fixture_lookup);
	if (fx.adapter_added)
		i2c_del_adapter(&fx.adapter);
	if (fx.gpio_added)
		gpiochip_remove(&fx.gpio);
	if (fx.irq >= 0) {
		irq_set_chip_and_handler(fx.irq, NULL, NULL);
		irq_free_descs(fx.irq, 1);
	}
	if (fx.root)
		root_device_unregister(fx.root);
}

static int __init fixture_init(void)
{
	struct i2c_board_info board = { I2C_BOARD_INFO("sw42000-pm-qemu", 0x28) };
	int ret;

	/* First executable action: reject every non-virt tree, before registration. */
	if (!of_machine_is_compatible("linux,dummy-virt"))
		return -ENODEV;
	mutex_init(&fx.bus_lock);
	init_waitqueue_head(&fx.wait);
	init_completion(&fx.report_entered);
	init_completion(&fx.release_report);
	atomic_set(&fx.result, -EINPROGRESS);
	fx.root = root_device_register("sw42000-pm-ram");
	if (IS_ERR(fx.root)) {
		ret = PTR_ERR(fx.root);
		fx.root = NULL;
		return ret;
	}
	/* NULL owners avoid self-pinning; cleanup removes consumers before providers. */
	fx.gpio.label = "sw42000-pm-ram";
	fx.gpio.parent = fx.root;
	fx.gpio.base = -1;
	fx.gpio.ngpio = 3;
	fx.gpio.can_sleep = true;
	fx.gpio.get = fixture_gpio_get;
	fx.gpio.set = fixture_gpio_set;
	fx.gpio.get_direction = fixture_gpio_direction;
	fx.gpio.direction_output = fixture_gpio_output;
	ret = gpiochip_add_data(&fx.gpio, NULL);
	if (ret)
		goto fail;
	fx.gpio_added = true;
	fx.irq = __irq_alloc_descs(-1, 1, 1, NUMA_NO_NODE, NULL, NULL);
	if (fx.irq < 0) {
		ret = fx.irq;
		goto fail;
	}
	irq_set_chip_and_handler(fx.irq, &fixture_irq_chip, handle_simple_irq);
	/* Eager masking makes mask/unmask observations deterministic in this model. */
	irq_modify_status(fx.irq, IRQ_NOREQUEST | IRQ_NOAUTOEN | IRQ_NOTHREAD,
			  IRQ_NOPROBE | IRQ_DISABLE_UNLAZY);
	fx.adapter.dev.parent = fx.root;
	fx.adapter.algo = &fixture_algorithm;
	strscpy(fx.adapter.name, "sw42000-pm-ram", sizeof(fx.adapter.name));
	ret = i2c_add_adapter(&fx.adapter);
	if (ret)
		goto fail;
	fx.adapter_added = true;
	snprintf(fx.client_name, sizeof(fx.client_name), "%d-0028", fx.adapter.nr);
	fixture_lookup.dev_id = fx.client_name;
	gpiod_add_lookup_table(&fixture_lookup);
	fx.lookup_added = true;
	sw42000_driver.driver.name = "sw42000-pm-qemu";
	sw42000_driver.driver.of_match_table = NULL;
	sw42000_driver.id_table = fixture_ids;
	if (skip_pm)
		sw42000_driver.driver.pm = NULL;
	ret = i2c_add_driver(&sw42000_driver);
	if (ret)
		goto fail;
	fx.driver_added = true;
	board.irq = fx.irq;
	fx.client = i2c_new_client_device(&fx.adapter, &board);
	if (IS_ERR(fx.client)) {
		ret = PTR_ERR(fx.client);
		fx.client = NULL;
		goto fail;
	}
	if (fx.client->dev.driver != &sw42000_driver.driver || !i2c_get_clientdata(fx.client)) {
		ret = -ENODEV;
		goto fail;
	}
	if (!skip_pm && fx.client->dev.driver->pm != &sw42000_pm_ops) {
		ret = -EINVAL;
		goto fail;
	}
	fx.worker = kthread_run(fixture_worker, NULL, "sw42000-pm-test");
	if (IS_ERR(fx.worker)) {
		ret = PTR_ERR(fx.worker);
		fx.worker = NULL;
		goto fail;
	}
	fx.kobj = kobject_create_and_add("sw42000-pm-qemu", kernel_kobj);
	if (!fx.kobj) {
		ret = -ENOMEM;
		goto fail;
	}
	ret = sysfs_create_group(fx.kobj, &fixture_group);
	if (ret)
		goto fail;
	fx.group_added = true;
	pr_info("SW42000_QEMU_PM: real production probe bound to RAM-only I2C/GPIO/IRQ\n");
	return 0;
fail:
	fixture_cleanup();
	return ret;
}

static void __exit fixture_exit(void)
{
	fixture_cleanup();
	pr_info("SW42000_QEMU_PM: cleanup passed\n");
}
module_init(fixture_init);
module_exit(fixture_exit);
MODULE_LICENSE("GPL");
