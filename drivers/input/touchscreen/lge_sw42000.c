// SPDX-License-Identifier: GPL-2.0-only
/* Minimal mainline driver for the LG SW42000 touchscreen. */

#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/input/mt.h>
#include <linux/input/touchscreen.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>

#include "lge_sw42000_protocol.h"

#define SW42000_REG_TOUCH_STATUS	0x600
#define SW42000_REG_VERSION		0x642
#define SW42000_REG_I2C_MODE		0xfe4
#define SW42000_REG_DEVICE_CONTROL	0xc00
#define SW42000_REG_INTERRUPT_CONTROL	0xc01
#define SW42000_REG_DRIVING_CONTROL	0xc03
#define SW42000_REG_BOOT_CRC_RESULT	0x05d
#define SW42000_REG_BOOT_CRC_PASS	0x05e
#define SW42000_REG_INFO_POINTER		0x01b

#define SW42000_CHIP_ID			10
#define SW42000_PROTOCOL_VERSION	4
#define SW42000_CRC_FIXED_VALUE		0x800d800d
#define SW42000_HW_RESET_DELAY_MS	40
#define SW42000_POWER_OFF_DELAY_US	1000
#define SW42000_TC_STOP_DELAY_MS	30
#define SW42000_ACTIVE_DRIVING		0x311
#define SW42000_MAX_X			1439
#define SW42000_MAX_Y			3119
#define SW42000_MAX_WIDTH		3119
#define SW42000_MAX_PRESSURE		255

struct sw42000_ts {
	struct i2c_client *client;
	struct input_dev *input;
	struct gpio_desc *reset_gpio;
	struct gpio_desc *vdd_gpio;
	struct gpio_desc *vcl_gpio;
	struct touchscreen_properties prop;
};

/* Vendor QCT transport sends the two-byte address separately from the read. */
static int sw42000_read_reg(struct sw42000_ts *ts, u16 addr,
			    u8 *data, size_t len)
{
	u8 request[2] = {
		(len > 4 ? 0x20 : 0x00) | ((addr >> 8) & 0x0f),
		addr & 0xff,
	};
	int ret;

	ret = i2c_master_send(ts->client, request, sizeof(request));
	if (ret != (int)sizeof(request))
		return ret < 0 ? ret : -EIO;

	ret = i2c_master_recv(ts->client, data, len);
	if (ret != (int)len)
		return ret < 0 ? ret : -EIO;

	return 0;
}

static int sw42000_write_u32(struct sw42000_ts *ts, u16 addr, u32 value)
{
	u8 request[6] = {
		0x40 | ((addr >> 8) & 0x0f),
		addr & 0xff,
		value & 0xff,
		(value >> 8) & 0xff,
		(value >> 16) & 0xff,
		(value >> 24) & 0xff,
	};
	int ret;

	ret = i2c_master_send(ts->client, request, sizeof(request));
	if (ret != (int)sizeof(request))
		return ret < 0 ? ret : -EIO;

	return 0;
}

static void sw42000_power_off(struct sw42000_ts *ts)
{
	gpiod_set_value_cansleep(ts->reset_gpio, 0);
	gpiod_set_value_cansleep(ts->vdd_gpio, 0);
	gpiod_set_value_cansleep(ts->vcl_gpio, 0);
	usleep_range(SW42000_POWER_OFF_DELAY_US,
		     SW42000_POWER_OFF_DELAY_US + 500);
}

static void sw42000_power_on(struct sw42000_ts *ts)
{
	gpiod_set_value_cansleep(ts->vcl_gpio, 1);
	gpiod_set_value_cansleep(ts->vdd_gpio, 1);
	msleep(10);
	gpiod_set_value_cansleep(ts->reset_gpio, 1);
	msleep(SW42000_HW_RESET_DELAY_MS);
}

static int sw42000_check_firmware(struct sw42000_ts *ts)
{
	u8 version[4];
	u8 value[4];
	int ret;

	ret = sw42000_read_reg(ts, SW42000_REG_VERSION, version,
			       sizeof(version));
	if (ret)
		return ret;

	/* Layout and expected chip/protocol IDs match the vendor SW42000 ABI. */
	if (version[2] != SW42000_CHIP_ID ||
	    (version[3] & 0x0f) != SW42000_PROTOCOL_VERSION) {
		dev_err(&ts->client->dev,
			"unexpected SW42000 version id=%u protocol=%u\n",
			version[2], version[3] & 0x0f);
		return -ENODEV;
	}

	/* Read-only boot checks prevent register setup on an unbooted controller. */
	ret = sw42000_read_reg(ts, SW42000_REG_BOOT_CRC_RESULT, value,
			       sizeof(value));
	if (ret)
		return ret;
	if (sw42000_get_le32(value) != SW42000_CRC_FIXED_VALUE)
		return -EIO;

	ret = sw42000_read_reg(ts, SW42000_REG_BOOT_CRC_PASS, value,
			       sizeof(value));
	if (ret)
		return ret;
	if (!sw42000_get_le32(value))
		return -EIO;

	ret = sw42000_read_reg(ts, SW42000_REG_INFO_POINTER, value,
			       sizeof(value));
	if (ret)
		return ret;
	if (!sw42000_get_le32(value))
		return -EIO;

	return 0;
}

static int sw42000_initialize_controller(struct sw42000_ts *ts)
{
	int ret;

	/* No bus test, updater, or factory-test path is included. */
	ret = sw42000_write_u32(ts, SW42000_REG_I2C_MODE, 0);
	if (ret)
		return ret;

	ret = sw42000_write_u32(ts, SW42000_REG_DEVICE_CONTROL, 1);
	if (ret)
		return ret;

	/* Match the vendor normal-mode stop then U3 1/2-swing sequence. */
	ret = sw42000_write_u32(ts, SW42000_REG_DRIVING_CONTROL, 0x02);
	if (ret)
		return ret;
	msleep(SW42000_TC_STOP_DELAY_MS);

	ret = sw42000_write_u32(ts, SW42000_REG_DRIVING_CONTROL, 0x311);
	if (ret)
		return ret;

	/* Enable controller interrupts only after the Linux IRQ is installed. */
	return sw42000_write_u32(ts, SW42000_REG_INTERRUPT_CONTROL, 1);
}

static void sw42000_report_frame(struct sw42000_ts *ts,
				 const struct sw42000_frame *frame)
{
	struct input_dev *input = ts->input;
	int max_x = input_abs_get_max(input, ABS_MT_POSITION_X);
	int max_y = input_abs_get_max(input, ABS_MT_POSITION_Y);
	unsigned int i;

	for (i = 0; i < frame->count; i++) {
		const struct sw42000_contact *contact = &frame->contacts[i];

		input_mt_slot(input, contact->id);
		input_mt_report_slot_state(input, MT_TOOL_FINGER, true);
		input_report_abs(input, ABS_MT_POSITION_X,
				 min_t(int, contact->x, max_x));
		input_report_abs(input, ABS_MT_POSITION_Y,
				 min_t(int, contact->y, max_y));
		input_report_abs(input, ABS_MT_PRESSURE, contact->pressure);
		input_report_abs(input, ABS_MT_TOUCH_MAJOR,
				 min_t(int, contact->major, SW42000_MAX_WIDTH));
		input_report_abs(input, ABS_MT_TOUCH_MINOR,
				 min_t(int, contact->minor, SW42000_MAX_WIDTH));
	}

	input_mt_sync_frame(input);
	input_report_key(input, BTN_TOUCH, frame->count != 0);
	input_sync(input);
}

static irqreturn_t sw42000_irq_thread(int irq, void *data)
{
	struct sw42000_ts *ts = data;
	u8 report[SW42000_REPORT_SIZE];
	struct sw42000_frame frame;
	int ret;

	(void)irq;

	ret = sw42000_read_reg(ts, SW42000_REG_TOUCH_STATUS,
			       report, sizeof(report));
	if (ret) {
		dev_dbg_ratelimited(&ts->client->dev,
				    "touch report read failed: %d\n", ret);
		return IRQ_HANDLED;
	}

	ret = sw42000_parse_report(report, sizeof(report), &frame);
	if (ret == SW42000_PARSE_IGNORE)
		return IRQ_HANDLED;
	if (ret) {
		dev_warn_ratelimited(&ts->client->dev,
				     "invalid SW42000 report\n");
		return IRQ_HANDLED;
	}

	sw42000_report_frame(ts, &frame);
	return IRQ_HANDLED;
}

static int sw42000_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct sw42000_ts *ts;
	struct input_dev *input;
	int ret;

	if (client->irq < 0)
		return dev_err_probe(dev, client->irq, "failed to get IRQ\n");
	if (!client->irq)
		return dev_err_probe(dev, -EINVAL, "missing IRQ\n");
	if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
		return -EOPNOTSUPP;

	ts = devm_kzalloc(dev, sizeof(*ts), GFP_KERNEL);
	if (!ts)
		return -ENOMEM;
	ts->client = client;

	ts->reset_gpio = devm_gpiod_get(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(ts->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(ts->reset_gpio),
				     "failed to get reset GPIO\n");
	ts->vdd_gpio = devm_gpiod_get(dev, "vdd", GPIOD_OUT_LOW);
	if (IS_ERR(ts->vdd_gpio))
		return dev_err_probe(dev, PTR_ERR(ts->vdd_gpio),
				     "failed to get VDD GPIO\n");
	ts->vcl_gpio = devm_gpiod_get(dev, "vcl", GPIOD_OUT_LOW);
	if (IS_ERR(ts->vcl_gpio))
		return dev_err_probe(dev, PTR_ERR(ts->vcl_gpio),
				     "failed to get VCL GPIO\n");

	sw42000_power_off(ts);
	sw42000_power_on(ts);

	ret = sw42000_check_firmware(ts);
	if (ret) {
		sw42000_power_off(ts);
		return dev_err_probe(dev, ret,
				     "SW42000 version check failed\n");
	}

	input = devm_input_allocate_device(dev);
	if (!input) {
		sw42000_power_off(ts);
		return -ENOMEM;
	}
	ts->input = input;
	input->name = "LG SW42000 Touchscreen";
	input->id.bustype = BUS_I2C;
	input_set_capability(input, EV_KEY, BTN_TOUCH);
	input_set_abs_params(input, ABS_MT_POSITION_X, 0, SW42000_MAX_X, 0, 0);
	input_set_abs_params(input, ABS_MT_POSITION_Y, 0, SW42000_MAX_Y, 0, 0);
	input_set_abs_params(input, ABS_MT_PRESSURE, 0,
			     SW42000_MAX_PRESSURE, 0, 0);
	input_set_abs_params(input, ABS_MT_TOUCH_MAJOR, 0,
			     SW42000_MAX_WIDTH, 0, 0);
	input_set_abs_params(input, ABS_MT_TOUCH_MINOR, 0,
			     SW42000_MAX_WIDTH, 0, 0);

	ret = input_mt_init_slots(input, SW42000_REPORT_CONTACTS,
			 INPUT_MT_DIRECT | INPUT_MT_DROP_UNUSED);
	if (ret) {
		sw42000_power_off(ts);
		return ret;
	}

	touchscreen_parse_properties(input, true, &ts->prop);
	if (!input_abs_get_max(input, ABS_MT_POSITION_X) ||
	    !input_abs_get_max(input, ABS_MT_POSITION_Y)) {
		sw42000_power_off(ts);
		return dev_err_probe(dev, -EINVAL,
				     "missing touchscreen dimensions\n");
	}

	ret = input_register_device(input);
	if (ret) {
		sw42000_power_off(ts);
		return ret;
	}

	ret = devm_request_threaded_irq(dev, client->irq, NULL,
					sw42000_irq_thread,
					IRQF_TRIGGER_FALLING | IRQF_ONESHOT,
					dev_name(dev), ts);
	if (ret) {
		sw42000_power_off(ts);
		return dev_err_probe(dev, ret, "failed to request IRQ\n");
	}

	ret = sw42000_initialize_controller(ts);
	if (ret) {
		sw42000_power_off(ts);
		return dev_err_probe(dev, ret,
				     "controller initialization failed\n");
	}

	i2c_set_clientdata(client, ts);
	dev_info(dev, "SW42000 touchscreen ready (%dx%d)\n",
		 input_abs_get_max(input, ABS_MT_POSITION_X) + 1,
		 input_abs_get_max(input, ABS_MT_POSITION_Y) + 1);
	return 0;
}

static void sw42000_remove(struct i2c_client *client)
{
	struct sw42000_ts *ts = i2c_get_clientdata(client);

	sw42000_power_off(ts);
}

static const struct of_device_id sw42000_of_match[] = {
	{ .compatible = "lge,sw42000" },
	{ }
};
MODULE_DEVICE_TABLE(of, sw42000_of_match);

static const struct i2c_device_id sw42000_id[] = {
	{ "sw42000", 0 },
	{ }
};
MODULE_DEVICE_TABLE(i2c, sw42000_id);

static struct i2c_driver sw42000_driver = {
	.driver = {
		.name = "lge-sw42000",
		.of_match_table = sw42000_of_match,
	},
	.probe = sw42000_probe,
	.remove = sw42000_remove,
	.id_table = sw42000_id,
};
module_i2c_driver(sw42000_driver);

MODULE_DESCRIPTION("LG SW42000 touchscreen driver");
MODULE_LICENSE("GPL");
