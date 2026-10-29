// SPDX-License-Identifier: GPL-2.0-only
/* LG G8 ThinQ SW43410 1440x3120 command-mode DSC panel. */

#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>
#include <linux/types.h>

#include <video/mipi_display.h>

#include <drm/drm_mipi_dsi.h>
#include <drm/drm_panel.h>
#include <drm/drm_probe_helper.h>
#include <drm/display/drm_dsc.h>
#include <drm/display/drm_dsc_helper.h>

#include "panel-lg-sw43410-cmds.h"

static const struct regulator_bulk_data sw43410_supplies[] = {
	{ .supply = "vddi", .init_load_uA = 62000 },
	{ .supply = "vpnl", .init_load_uA = 857000 },
};

struct sw43410_panel {
	struct drm_panel base;
	struct mipi_dsi_device *dsi;
	struct regulator_bulk_data *supplies;
	struct gpio_desc *reset_gpio;
	struct drm_dsc_config dsc;
};

static inline struct sw43410_panel *to_sw43410(struct drm_panel *panel)
{
	return container_of(panel, struct sw43410_panel, base);
}

/* Android's command blob uses a 7-byte packet header followed by payload. */
static int sw43410_send_commands(struct sw43410_panel *ctx,
				 const u8 *commands, size_t length)
{
	struct mipi_dsi_device *dsi = ctx->dsi;
	bool pps_sent = false;

	while (length) {
		u8 type, wait_ms;
		size_t payload_len;
		const u8 *payload;
		int ret;

		if (length < 7)
			return -EINVAL;

		type = commands[0];
		wait_ms = commands[4];
		payload_len = ((size_t)commands[5] << 8) | commands[6];
		if (commands[1] > 1 || commands[2] != 0 || commands[3] != 0 ||
		    payload_len > length - 7)
			return -EINVAL;

		payload = commands + 7;
		if (type == MIPI_DSI_COMPRESSION_MODE) {
			struct drm_dsc_picture_parameter_set pps;
			unsigned long mode_flags;

			if (payload_len != 2 || payload[0] != 0x11 || payload[1] ||
			    pps_sent || !dsi->dsc)
				return -EINVAL;

			/* The stock panel requests PPS in HS mode, then returns to LP. */
			drm_dsc_pps_payload_pack(&pps, dsi->dsc);
			mode_flags = dsi->mode_flags;
			dsi->mode_flags &= ~MIPI_DSI_MODE_LPM;
			ret = mipi_dsi_picture_parameter_set(dsi, &pps);
			dsi->mode_flags = mode_flags;
			if (ret < 0)
				return ret;

			ret = mipi_dsi_compression_mode_ext(dsi, true,
							    MIPI_DSI_COMPRESSION_DSC, 1);
			if (ret < 0)
				return ret;
			pps_sent = true;
		} else if ((type == MIPI_DSI_DCS_SHORT_WRITE && payload_len == 1) ||
			   (type == MIPI_DSI_DCS_SHORT_WRITE_PARAM && payload_len == 2) ||
			   (type == MIPI_DSI_DCS_LONG_WRITE && payload_len >= 3)) {
			ret = mipi_dsi_dcs_write_buffer_chatty(dsi, payload,
							       payload_len);
			if (ret < 0)
				return ret;
		} else {
			dev_err(&dsi->dev, "unsupported panel packet type %#x\n", type);
			return -EOPNOTSUPP;
		}

		if (wait_ms)
			msleep(wait_ms);

		commands += 7 + payload_len;
		length -= 7 + payload_len;
	}

	return 0;
}

static void sw43410_reset(struct sw43410_panel *ctx)
{
	/* GPIO_ACTIVE_LOW makes logical 0/1/0 match the stock high/low/high. */
	gpiod_set_value_cansleep(ctx->reset_gpio, 0);
	usleep_range(10000, 11000);
	gpiod_set_value_cansleep(ctx->reset_gpio, 1);
	usleep_range(2000, 3000);
	gpiod_set_value_cansleep(ctx->reset_gpio, 0);
	usleep_range(10000, 11000);
}

static int sw43410_prepare(struct drm_panel *panel)
{
	struct sw43410_panel *ctx = to_sw43410(panel);
	int ret;

	ret = regulator_bulk_enable(ARRAY_SIZE(sw43410_supplies), ctx->supplies);
	if (ret < 0)
		return ret;

	/* VDDI's downstream panel sequence specifies a 20 ms post-enable wait. */
	msleep(20);
	sw43410_reset(ctx);

	ret = sw43410_send_commands(ctx, sw43410_on_commands,
				   sizeof(sw43410_on_commands));
	if (ret < 0)
		goto power_off;

	ret = sw43410_send_commands(ctx, sw43410_post_on_commands,
				   sizeof(sw43410_post_on_commands));
	if (ret < 0)
		goto power_off;

	return 0;

power_off:
	gpiod_set_value_cansleep(ctx->reset_gpio, 0);
	regulator_bulk_disable(ARRAY_SIZE(sw43410_supplies), ctx->supplies);
	return ret;
}

static int sw43410_unprepare(struct drm_panel *panel)
{
	struct sw43410_panel *ctx = to_sw43410(panel);
	int ret, power_ret;

	ret = sw43410_send_commands(ctx, sw43410_off_commands,
				   sizeof(sw43410_off_commands));
	gpiod_set_value_cansleep(ctx->reset_gpio, 0);
	power_ret = regulator_bulk_disable(ARRAY_SIZE(sw43410_supplies),
					   ctx->supplies);

	return ret ? ret : power_ret;
}

static const struct drm_display_mode sw43410_mode = {
	.clock = 320280,
	.hdisplay = 1440,
	.hsync_start = 1608,
	.hsync_end = 1612,
	.htotal = 1700,
	.vdisplay = 3120,
	.vsync_start = 3129,
	.vsync_end = 3130,
	.vtotal = 3140,
	.width_mm = 65,
	.height_mm = 140,
	.type = DRM_MODE_TYPE_DRIVER | DRM_MODE_TYPE_PREFERRED,
};

static int sw43410_get_modes(struct drm_panel *panel,
			     struct drm_connector *connector)
{
	return drm_connector_helper_get_modes_fixed(connector, &sw43410_mode);
}

static int sw43410_backlight_update_status(struct backlight_device *backlight)
{
	struct mipi_dsi_device *dsi = bl_get_data(backlight);
	u16 brightness = backlight_get_brightness(backlight);

	return mipi_dsi_dcs_set_display_brightness_large(dsi, brightness);
}

static const struct backlight_ops sw43410_backlight_ops = {
	.update_status = sw43410_backlight_update_status,
};

static int sw43410_backlight_init(struct sw43410_panel *ctx)
{
	struct device *dev = &ctx->dsi->dev;
	const struct backlight_properties props = {
		.type = BACKLIGHT_PLATFORM,
		.brightness = 4095,
		.max_brightness = 4095,
	};

	ctx->base.backlight = devm_backlight_device_register(dev, dev_name(dev),
							     dev, ctx->dsi,
							     &sw43410_backlight_ops,
							     &props);
	if (IS_ERR(ctx->base.backlight))
		return dev_err_probe(dev, PTR_ERR(ctx->base.backlight),
				     "failed to register DCS backlight\n");

	return 0;
}

static const struct drm_panel_funcs sw43410_panel_funcs = {
	.prepare = sw43410_prepare,
	.unprepare = sw43410_unprepare,
	.get_modes = sw43410_get_modes,
};

static int sw43410_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	struct sw43410_panel *ctx;
	int ret;

	ctx = devm_drm_panel_alloc(dev, struct sw43410_panel, base,
				   &sw43410_panel_funcs,
				   DRM_MODE_CONNECTOR_DSI);
	if (IS_ERR(ctx))
		return PTR_ERR(ctx);

	ctx->dsi = dsi;
	dsi->mode_flags = MIPI_DSI_MODE_LPM |
			  MIPI_DSI_MODE_DSC_ALL_SLICES_IN_PKT;
	dsi->format = MIPI_DSI_FMT_RGB888;
	dsi->lanes = 4;

	ctx->dsc.dsc_version_major = 1;
	ctx->dsc.dsc_version_minor = 1;
	ctx->dsc.scr_revision = 1;
	ctx->dsc.slice_height = 60;
	ctx->dsc.slice_width = 720;
	ctx->dsc.slice_count = 2;
	ctx->dsc.bits_per_component = 8;
	ctx->dsc.bits_per_pixel = 8 << 4;
	ctx->dsc.block_pred_enable = true;
	dsi->dsc = &ctx->dsc;

	ret = devm_regulator_bulk_get_const(dev, ARRAY_SIZE(sw43410_supplies),
					    sw43410_supplies, &ctx->supplies);
	if (ret < 0)
		return dev_err_probe(dev, ret, "failed to get panel supplies\n");

	ctx->reset_gpio = devm_gpiod_get(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(ctx->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(ctx->reset_gpio),
				     "failed to get reset GPIO\n");

	ret = sw43410_backlight_init(ctx);
	if (ret < 0)
		return ret;

	ctx->base.prepare_prev_first = true;
	drm_panel_add(&ctx->base);
	ret = mipi_dsi_attach(dsi);
	if (ret < 0) {
		drm_panel_remove(&ctx->base);
		return dev_err_probe(dev, ret, "failed to attach to DSI host\n");
	}

	mipi_dsi_set_drvdata(dsi, ctx);
	return 0;
}

static void sw43410_remove(struct mipi_dsi_device *dsi)
{
	struct sw43410_panel *ctx = mipi_dsi_get_drvdata(dsi);
	int ret;

	ret = mipi_dsi_detach(dsi);
	if (ret < 0)
		dev_err(&dsi->dev, "failed to detach from DSI host: %d\n", ret);

	drm_panel_remove(&ctx->base);
}

static const struct of_device_id sw43410_of_match[] = {
	{ .compatible = "lg,sw43410" },
	{ }
};
MODULE_DEVICE_TABLE(of, sw43410_of_match);

static struct mipi_dsi_driver sw43410_driver = {
	.driver = {
		.name = "panel-lg-sw43410",
		.of_match_table = sw43410_of_match,
	},
	.probe = sw43410_probe,
	.remove = sw43410_remove,
};
module_mipi_dsi_driver(sw43410_driver);

MODULE_DESCRIPTION("LG G8 ThinQ SW43410 DSC panel");
MODULE_LICENSE("GPL");
