// SPDX-License-Identifier: GPL-2.0-only
/* Userspace boundary for the verbatim Qualcomm PMIC VBUS read callbacks. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <errno.h>

#define BIT(n) (1U << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define dev_dbg(dev, ...) ((void)(dev))
#define IRQ_HANDLED 1
#define irqreturn_t int
typedef uint32_t u32;

struct device { int unused; };
struct mutex { bool held; unsigned int locks, unlocks; };
struct test_spinlock { bool held; };
struct tcpm_port { unsigned int vbus_events, cc_events; struct test_spinlock *lock; };
struct regmap {
	unsigned int value, reads, address;
	int error;
	struct mutex *required_lock;
	struct test_spinlock *required_spin;
};
struct pmic_typec_port {
	struct device *dev;
	struct tcpm_port *tcpm_port;
	struct regmap *regmap;
	unsigned int base;
	bool vbus_enabled;
	bool debouncing_cc;
	struct mutex vbus_lock;
	struct test_spinlock lock;
};
struct pmic_typec_port_irq_data { int virq; struct pmic_typec_port *pmic_typec_port; };
struct pmic_typec { struct pmic_typec_port *pmic_typec_port; };
struct tcpc_dev { struct pmic_typec *owner; };

#define spin_lock_irqsave(lock, flags) do { \
	(flags) = 0; assert(!(lock)->held); (lock)->held = true; \
} while (0)
#define spin_unlock_irqrestore(lock, flags) do { \
	(void)(flags); assert((lock)->held); (lock)->held = false; \
} while (0)

static void tcpm_vbus_change(struct tcpm_port *port)
{
	assert(!port->lock->held);
	port->vbus_events++;
}

static void tcpm_cc_change(struct tcpm_port *port)
{
	assert(!port->lock->held);
	port->cc_events++;
}

static struct pmic_typec *tcpc_to_tcpm(struct tcpc_dev *tcpc)
{
	return tcpc->owner;
}

static void mutex_lock(struct mutex *lock)
{
	assert(!lock->held);
	lock->held = true;
	lock->locks++;
}

static void mutex_unlock(struct mutex *lock)
{
	assert(lock->held);
	lock->held = false;
	lock->unlocks++;
}

static int regmap_read(struct regmap *map, unsigned int address, unsigned int *value)
{
	assert(address == map->address);
	assert((map->required_lock && map->required_lock->held) ||
	       (map->required_spin && map->required_spin->held));
	map->reads++;
	/* A failed read must not be reinterpreted as either hardware value. */
	*value = map->value;
	return map->error;
}

/* ACTUAL_DRIVER_DEFINITIONS */

unsigned int qcom_pmic_vbus_read_tests(void)
{
	struct device dev = {};
	struct regmap map = { .address = 0x1500 + TYPEC_MISC_STATUS_REG };
	struct pmic_typec_port port = { .dev = &dev, .regmap = &map, .base = 0x1500 };
	struct pmic_typec tcpm = { .pmic_typec_port = &port };
	struct tcpc_dev tcpc = { .owner = &tcpm };
	const int errors[] = { -EIO, -ETIMEDOUT, -EAGAIN };
	unsigned int cases = 0;

	map.required_lock = &port.vbus_lock;
	for (unsigned int status = 0; status <= 0xff; status++) {
		map.value = status;
		assert(qcom_pmic_typec_port_get_vbus(&tcpc) ==
		       !!(status & TYPEC_VBUS_DETECT));
		assert(map.reads == status + 1 && !port.vbus_lock.held);
		cases++;
	}
	for (unsigned int i = 0; i < ARRAY_SIZE(errors); i++) {
		for (unsigned int status = 0; status <= 1; status++) {
			map.error = errors[i];
			map.value = status ? TYPEC_VBUS_DETECT : 0;
			assert(qcom_pmic_typec_port_get_vbus(&tcpc) == errors[i]);
			assert(!port.vbus_lock.held);
			cases++;
		}
	}
	/* Sourcing still reads the bus so a failure cannot be disguised as VBUS. */
	port.vbus_enabled = true;
	for (unsigned int status = 0; status <= 1; status++) {
		map.value = status ? TYPEC_VBUS_DETECT : 0;
		map.error = 0;
		assert(qcom_pmic_typec_port_get_vbus(&tcpc) == 1);
		cases++;
		for (unsigned int i = 0; i < ARRAY_SIZE(errors); i++) {
			map.error = errors[i];
			assert(qcom_pmic_typec_port_get_vbus(&tcpc) == errors[i]);
			cases++;
		}
	}
	assert(port.vbus_lock.locks == port.vbus_lock.unlocks);
	struct tcpm_port event_port = { .lock = &port.lock };
	struct pmic_typec_port_irq_data irq_data = { .pmic_typec_port = &port };
	const struct { int irq, error; bool debouncing; unsigned int vbus, cc; } scenarios[] = {
		{ PMIC_TYPEC_VBUS_IRQ, 0, false, 1, 0 },
		{ PMIC_TYPEC_VBUS_IRQ, -EIO, false, 1, 0 },
		{ PMIC_TYPEC_VBUS_IRQ, -ETIMEDOUT, false, 1, 0 },
		{ PMIC_TYPEC_CC_STATE_IRQ, 0, false, 0, 1 },
		{ PMIC_TYPEC_ATTACH_DETACH_IRQ, 0, false, 0, 1 },
		{ PMIC_TYPEC_CC_STATE_IRQ, 0, true, 0, 0 },
		{ PMIC_TYPEC_CC_STATE_IRQ, -EIO, false, 0, 0 },
		{ PMIC_TYPEC_ATTACH_DETACH_IRQ, -EIO, false, 0, 0 },
	};

	port.tcpm_port = &event_port;
	map.required_lock = NULL;
	map.required_spin = &port.lock;
	for (unsigned int i = 0; i < ARRAY_SIZE(scenarios); i++) {
		irq_data.virq = scenarios[i].irq;
		map.error = scenarios[i].error;
		port.debouncing_cc = scenarios[i].debouncing;
		event_port.vbus_events = event_port.cc_events = 0;
		assert(pmic_typec_port_isr(0, &irq_data) == IRQ_HANDLED);
		assert(!port.lock.held && event_port.vbus_events == scenarios[i].vbus &&
		       event_port.cc_events == scenarios[i].cc);
		cases++;
	}
	return cases;
}
