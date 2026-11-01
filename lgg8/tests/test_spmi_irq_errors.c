/* SPDX-License-Identifier: GPL-2.0-only */
/* Host transport/MMIO boundary; the five irqchip functions are production code. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define BIT(n) (1U << (n))
#define GENMASK(h, l) ((~0U << (l)) & (~0U >> (31 - (h))))
#define FIELD_GET(mask, value) (((value) & (mask)) >> __builtin_ctz(mask))
#define SPMI_CMD_EXT_WRITEL 0x30
#define SPMI_CMD_EXT_READL 0x38

struct device { int unused; };
struct spmi_controller { struct device dev; };
struct spmi_pmic_arb_bus;
struct pmic_arb_ver_ops {
	void *(*acc_enable)(struct spmi_pmic_arb_bus *, u16);
};
struct spmi_pmic_arb {
	const struct pmic_arb_ver_ops *ver_ops;
	unsigned int ee;
};
struct spmi_pmic_arb_bus {
	struct spmi_controller *spmic;
	struct spmi_pmic_arb *pmic_arb;
	struct { unsigned int irq_ee; } apid_data[8];
};
struct irq_data {
	u32 hwirq;
	unsigned int irq;
	struct spmi_pmic_arb_bus *chip_data;
};
struct irq_domain { int unused; };
enum irqchip_irq_state { IRQCHIP_STATE_PENDING, IRQCHIP_STATE_LINE_LEVEL };

static struct {
	struct spmi_controller *ctrl;
	struct spmi_pmic_arb_bus *bus;
	unsigned int sid, per, apid;
	u8 read_data[2];
	int read_error, write_error;
	unsigned int fail_write, reads, writes, mmios, logs, steps, last_read;
	unsigned int addr[2], read_addr;
	size_t read_length;
	u8 payload[2][2];
	size_t length[2];
	u32 access;
} trace;

static void dev_err(struct device *dev, const char *fmt, ...)
{
	(void)dev;
	(void)fmt;
	trace.logs++;
}
#define dev_err_ratelimited dev_err
static void *irq_data_get_irq_chip_data(struct irq_data *d) { return d->chip_data; }
static int pmic_arb_read_cmd(struct spmi_controller *ctrl, u8 opcode, u8 sid,
			     u16 addr, void *buf, size_t len)
{
	assert(ctrl == trace.ctrl && opcode == SPMI_CMD_EXT_READL && sid == trace.sid);
	assert((addr >> 8) == trace.per && len && len <= 2);
	trace.reads++;
	trace.read_addr = addr;
	trace.read_length = len;
	trace.last_read = ++trace.steps;
	/* A failed transport may have touched its buffer; callers must handle errno. */
	memcpy(buf, trace.read_data, len);
	return trace.read_error;
}
static int pmic_arb_write_cmd(struct spmi_controller *ctrl, u8 opcode, u8 sid,
			      u16 addr, const void *buf, size_t len)
{
	assert(ctrl == trace.ctrl && opcode == SPMI_CMD_EXT_WRITEL && sid == trace.sid);
	assert((addr >> 8) == trace.per && len && len <= 2 && trace.writes < 2);
	unsigned int i = trace.writes++;
	trace.steps++;
	trace.addr[i] = addr;
	trace.length[i] = len;
	memcpy(trace.payload[i], buf, len);
	return trace.fail_write == i + 1 ? trace.write_error : 0;
}
static void *acc_enable(struct spmi_pmic_arb_bus *bus, u16 apid)
{
	assert(bus == trace.bus && apid == trace.apid);
	return &trace.access;
}
static void writel_relaxed(u32 value, void *addr)
{
	assert(addr == &trace.access);
	trace.mmios++;
	trace.steps++;
	trace.access = value;
}

/* ACTUAL_IRQCHIP_DEFINITIONS */

static const struct pmic_arb_ver_ops ops = { .acc_enable = acc_enable };
static struct spmi_controller ctrl;
static struct spmi_pmic_arb arb;
static struct spmi_pmic_arb_bus bus;
static struct irq_data data;
static unsigned int cases;

static void setup(unsigned int bit)
{
	memset(&trace, 0, sizeof(trace));
	memset(&bus, 0, sizeof(bus));
	arb = (struct spmi_pmic_arb) { .ver_ops = &ops, .ee = 1 };
	bus.spmic = &ctrl;
	bus.pmic_arb = &arb;
	bus.apid_data[5].irq_ee = 1;
	data = (struct irq_data) { .hwirq = (2U << 24) | (0x40U << 16) |
		(bit << 13) | 5, .irq = 123, .chip_data = &bus };
	trace.ctrl = &ctrl;
	trace.bus = &bus;
	trace.sid = 2;
	trace.per = 0x40;
	trace.apid = 5;
}

unsigned int spmi_irq_errors_tests(void)
{
	const int errors[] = { -EIO, -ETIMEDOUT, -EACCES };
	cases = 0;
	for (unsigned int bit = 0; bit < 8; bit++) {
		for (size_t e = 0; e <= sizeof(errors) / sizeof(errors[0]); e++) {
			int error = e ? errors[e - 1] : 0;
			u8 bytes[2] = {0, 0};
			setup(bit);
			trace.read_data[0] = 0xa5;
			trace.read_data[1] = 0x5a;
			trace.read_error = error;
			assert(qpnpint_spmi_read(&data, 0x10, bytes, 2) == error);
			assert(trace.reads == 1 && !trace.writes && !trace.mmios);
			assert(trace.read_addr == 0x4010 && trace.read_length == 2);
			assert(trace.logs == (unsigned int)!!error);
			if (!error) assert(bytes[0] == 0xa5 && bytes[1] == 0x5a);
			cases++;
			setup(bit);
			trace.fail_write = 1;
			trace.write_error = error;
			assert(qpnpint_spmi_write(&data, 0x14, bytes, 2) == error);
			assert(trace.writes == 1 && !trace.reads && !trace.mmios);
			assert(trace.addr[0] == 0x4014 && trace.length[0] == 2);
			assert(!memcmp(trace.payload[0], bytes, 2));
			assert(trace.logs == (unsigned int)!!error);
			cases++;
			for (unsigned int initial = 0; initial < 2; initial++) {
				bool state = initial;
				setup(bit);
				trace.read_error = error;
				trace.read_data[0] = initial ? (u8)~BIT(bit) : (u8)BIT(bit);
				int rc = qpnpint_get_irqchip_state(&data, IRQCHIP_STATE_LINE_LEVEL, &state);
				assert(rc == error && trace.reads == 1 && !trace.writes);
				assert(trace.read_addr == 0x4010 && trace.read_length == 1);
				assert(state == (error ? !!initial : !initial));
				cases++;
			}
			for (unsigned int enabled = 0; enabled < 2; enabled++) {
				setup(bit);
				trace.read_data[0] = enabled ? (u8)BIT(bit) : 0;
				trace.read_error = error;
				qpnpint_irq_unmask(&data);
				assert(trace.reads == 1);
				assert(trace.read_addr == 0x4015 && trace.read_length == 1);
				if (error) {
					/* Earlier arbiter access-enable MMIO is allowed, later writes are not. */
					assert(!trace.writes && trace.steps == trace.last_read);
				} else {
					assert(trace.mmios == 1 && trace.access == SPMI_PIC_ACC_ENABLE_BIT);
					assert(trace.writes == !enabled);
					if (!enabled) {
						assert(trace.addr[0] == 0x4014 && trace.length[0] == 2);
						assert(trace.payload[0][0] == BIT(bit) && trace.payload[0][1] == BIT(bit));
					}
				}
				cases++;
			}
			for (unsigned int failure = 1; failure <= 2; failure++) {
				setup(bit);
				trace.fail_write = failure;
				trace.write_error = error;
				assert(qpnpint_irq_domain_activate(NULL, &data, false) == error);
				assert(trace.writes == (error ? failure : 2) && !trace.reads && !trace.mmios);
				assert(trace.addr[0] == 0x4016 && trace.length[0] == 1);
				assert(trace.payload[0][0] == BIT(bit));
				if (trace.writes == 2)
					assert(trace.addr[1] == 0x4014 && trace.length[1] == 1 && trace.payload[1][0] == BIT(bit));
				cases++;
			}
			if (error) {
				setup(bit);
				trace.fail_write = 1;
				trace.write_error = error;
				qpnpint_irq_unmask(&data);
				assert(trace.reads == 1 && trace.writes == 1 && trace.logs == 1);
				cases++;
			}
		}
		setup(bit);
		bus.apid_data[5].irq_ee = 0;
		assert(qpnpint_irq_domain_activate(NULL, &data, true) == -ENODEV);
		assert(!trace.reads && !trace.writes && !trace.mmios && trace.logs == 1);
		cases++;
		for (unsigned int initial = 0; initial < 2; initial++) {
			bool state = initial;
			setup(bit);
			assert(qpnpint_get_irqchip_state(&data, IRQCHIP_STATE_PENDING, &state) == -EINVAL);
			assert(state == !!initial && !trace.reads && !trace.writes && !trace.mmios);
			cases++;
		}
	}
	return cases;
}
