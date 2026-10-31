// SPDX-License-Identifier: GPL-2.0-only
/*
 * Unwired PM8150B V2-only transaction proposal; see the header's blockers.
 * This is real regmap code, not a simulated bus. Never invoke it on the basis
 * of offline tests. No platform/module init, probe, exports or power_supply.
 */
#include <linux/bitops.h>
#include <linux/delay.h>
#include <linux/err.h>
#include <linux/errno.h>
#include <linux/kernel.h>
#include <linux/regmap.h>
#include <linux/string.h>

#include "qcom_fg_dma_experimental.h"

#define FG_INFO_SUBTYPE		0x4105
#define FG_PEEK_MUX4		0x41ee
#define FG_MEM_SUBTYPE		0x4305
#define FG_MEM_STATUS		0x4310
#define FG_ARB_CFG		0x4340
#define FG_INTF_CFG		0x4350
#define FG_DMA_STATUS		0x4370
#define FG_DMA_CTL		0x4371
#define FG_TEMP_DMA		(0x4800 + 0x20 + (328 - 300) * 2)
#define FG_ARB_REQUEST		BIT(0)
#define FG_ARB_CLEAR_LOG		BIT(2)
#define FG_INTF_MASK		(BIT(7) | BIT(5))
#define FG_DMA_REQUEST		BIT(7)
#define FG_MEM_GRANT		BIT(3)
#define FG_DMA_PARTITION_MODE	BIT(1)
#define FG_PEEK_ALG_ACTIVE	0xac
#define FG_GRANT_POLLS		50

static void fg_error(struct qcom_fg_dma_result *r,
		     enum qcom_fg_dma_stage stage, int rc)
{
	if (!r->rc)
		r->rc = rc;
	/* At most one primary plus two release and two verification errors. */
	if (WARN_ON_ONCE(r->error_count >= ARRAY_SIZE(r->errors)))
		return;
	r->errors[r->error_count++] = (struct qcom_fg_dma_error) { stage, rc };
}

static bool fg_reference(const char *reference)
{
	return reference && reference[0];
}

static int fg_check_audit(const struct qcom_fg_dma_audit *a,
			  struct qcom_fg_dma_result *r)
{
	unsigned int i;

	for (i = 0; i < QCOM_FG_DMA_REQUIREMENT_COUNT; i++) {
		if (!a || a->evidence[i].review != QCOM_FG_DMA_INDEPENDENTLY_REVIEWED ||
		    !fg_reference(a->evidence[i].reference) ||
		    !fg_reference(a->evidence[i].reviewer))
			r->blocked_requirements |= BIT(i);
	}
	if (r->blocked_requirements)
		return -EOPNOTSUPP;
	if (a->variant != QCOM_FG_DMA_VARIANT_PM8150B_V2) {
		r->blocked_requirements |= BIT(QCOM_FG_DMA_IDENTITY_V2);
		return -EOPNOTSUPP;
	}
	if (!fg_reference(a->transaction_reference) || !a->verify_live)
		return -EINVAL;
	if (ktime_compare(ktime_get(), a->valid_until) >= 0)
		return -ESTALE;
	return 0;
}

static int fg_verify_live(const struct qcom_fg_dma_audit *a,
			  enum qcom_fg_dma_phase phase)
{
	int rc;

	if (ktime_compare(ktime_get(), a->valid_until) >= 0)
		return -ESTALE;
	rc = a->verify_live(a->cookie, phase);
	if (rc)
		return rc < 0 ? rc : -EIO;
	if (ktime_compare(ktime_get(), a->valid_until) >= 0)
		return -ESTALE;
	return 0;
}

static int fg_preflight(struct regmap *map, enum qcom_fg_dma_stage *stage)
{
	static const struct {
		enum qcom_fg_dma_stage stage;
		unsigned int reg;
		unsigned int mask;
		unsigned int expected;
		int mismatch;
	} checks[] = {
		{ QCOM_FG_DMA_MEM_SUBTYPE, FG_MEM_SUBTYPE, 0xff, 0x0d, -ENODEV },
		{ QCOM_FG_DMA_INFO_SUBTYPE, FG_INFO_SUBTYPE, 0xff, 0x11, -ENODEV },
		{ QCOM_FG_DMA_PEEK_CONFIG, FG_PEEK_MUX4, 0xff,
		  FG_PEEK_ALG_ACTIVE, -EOPNOTSUPP },
		{ QCOM_FG_DMA_ADDRESS_MODE, FG_DMA_CTL,
		  FG_DMA_PARTITION_MODE, FG_DMA_PARTITION_MODE, -EOPNOTSUPP },
		/* Unknown nonzero status is conservatively rejected, never cleared. */
		{ QCOM_FG_DMA_DMA_STATUS, FG_DMA_STATUS, 0xff, 0, -EIO },
		{ QCOM_FG_DMA_PREFLIGHT_INTF, FG_INTF_CFG, FG_INTF_MASK, 0, -EBUSY },
		{ QCOM_FG_DMA_PREFLIGHT_ARB, FG_ARB_CFG,
		  FG_ARB_REQUEST | FG_ARB_CLEAR_LOG, 0, -EBUSY },
		{ QCOM_FG_DMA_PREFLIGHT_GRANT, FG_MEM_STATUS, FG_MEM_GRANT, 0, -EBUSY },
	};
	unsigned int value, i;
	int rc;

	for (i = 0; i < ARRAY_SIZE(checks); i++) {
		*stage = checks[i].stage;
		/* Bypass reads temporarily alter cache flags under the regmap lock. */
		rc = regmap_read_bypassed(map, checks[i].reg, &value);
		if (rc)
			return rc;
		if ((value & checks[i].mask) != checks[i].expected)
			return checks[i].mismatch;
	}
	return 0;
}

static int fg_wait_grant(struct regmap *map, const struct qcom_fg_dma_audit *audit)
{
	unsigned int i, value;
	int rc;

	usleep_range(40, 41);
	for (i = 0; i < FG_GRANT_POLLS; i++) {
		if (ktime_compare(ktime_get(), audit->valid_until) >= 0)
			return -ESTALE;
		rc = regmap_read_bypassed(map, FG_MEM_STATUS, &value);
		if (rc)
			return rc;
		if (value & FG_MEM_GRANT)
			return ktime_compare(ktime_get(), audit->valid_until) < 0 ?
				0 : -ESTALE;
		usleep_range(10000, 10001);
	}
	return -ETIMEDOUT;
}

static void fg_cleanup(struct regmap *map, struct qcom_fg_dma_result *r)
{
	static const struct {
		enum qcom_fg_dma_stage stage;
		unsigned int reg;
		unsigned int mask;
	} steps[] = {
		{ QCOM_FG_DMA_RELEASE_DMA, FG_INTF_CFG, FG_INTF_MASK },
		{ QCOM_FG_DMA_RELEASE_ARB, FG_ARB_CFG, FG_ARB_REQUEST },
		{ QCOM_FG_DMA_VERIFY_DMA, FG_INTF_CFG, FG_INTF_MASK },
		{ QCOM_FG_DMA_VERIFY_ARB, FG_ARB_CFG, FG_ARB_REQUEST },
	};
	unsigned int i, value;
	int rc;

	r->cleanup = QCOM_FG_DMA_REQUEST_FIELDS_CLEAR;
	for (i = 0; i < ARRAY_SIZE(steps); i++) {
		if (i < 2) {
			/*
			 * Force a write attempt even if regmap thinks bits are clear.
			 * BLOCKER: RMW/ambiguous-failure release safety must be proven
			 * by caller evidence; a zero preflight cannot prove it.
			 */
			rc = regmap_write_bits(map, steps[i].reg, steps[i].mask, 0);
		} else {
			rc = regmap_read_bypassed(map, steps[i].reg, &value);
			if (!rc && (value & steps[i].mask))
				rc = -EIO;
		}
		if (rc) {
			fg_error(r, steps[i].stage, rc);
			r->cleanup = QCOM_FG_DMA_CLEANUP_UNCERTAIN;
		}
	}
}

int qcom_fg_dma_experimental_init(struct qcom_fg_dma_experimental *ctx,
				  struct regmap *map, struct mutex *interface_lock)
{
	if (!ctx || IS_ERR_OR_NULL(map) || IS_ERR_OR_NULL(interface_lock))
		return -EINVAL;
	ctx->map = map;
	ctx->interface_lock = interface_lock;
	ctx->quarantined = false;
	return 0;
}

static int __maybe_unused
qcom_fg_dma_experimental_read_draft(struct qcom_fg_dma_experimental *ctx,
				    const struct qcom_fg_dma_audit *audit,
				    struct qcom_fg_dma_result *r)
{
	enum qcom_fg_dma_stage stage;
	unsigned int raw;
	u8 data[2];
	int rc;

	if (!r)
		return -EINVAL;
	memset(r, 0, sizeof(*r));
	if (!ctx || IS_ERR_OR_NULL(ctx->map) || IS_ERR_OR_NULL(ctx->interface_lock)) {
		fg_error(r, QCOM_FG_DMA_ARGUMENT, -EINVAL);
		return r->rc;
	}
	/* Missing real evidence is rejected before any regmap I/O or callback. */
	rc = fg_check_audit(audit, r);
	if (rc) {
		fg_error(r, QCOM_FG_DMA_AUDIT, rc);
		return r->rc;
	}
	might_sleep();
	if (!mutex_trylock(ctx->interface_lock)) {
		fg_error(r, QCOM_FG_DMA_BUSY, -EBUSY);
		return r->rc;
	}
	r->quarantine_observed = true;
	stage = QCOM_FG_DMA_QUARANTINED;
	rc = -EBUSY;
	if (ctx->quarantined)
		goto out;
	stage = QCOM_FG_DMA_MAP_FORMAT;
	rc = -EOPNOTSUPP;
	if (regmap_get_val_bytes(ctx->map) != 1 ||
	    regmap_get_reg_stride(ctx->map) != 1)
		goto out;
	stage = QCOM_FG_DMA_LIVE_BEFORE_ACCESS;
	rc = fg_verify_live(audit, QCOM_FG_DMA_BEFORE_ACCESS);
	if (rc)
		goto out;
	rc = fg_preflight(ctx->map, &stage);
	if (rc)
		goto out;
	stage = QCOM_FG_DMA_LIVE_BEFORE_REQUEST;
	rc = fg_verify_live(audit, QCOM_FG_DMA_BEFORE_REQUEST);
	if (rc)
		goto out;
	/* V2 only. No V1 ALG_ACTIVE waiting or initialization is attempted. */
	r->request_attempted = true;
	stage = QCOM_FG_DMA_REQUEST_ARB;
	rc = regmap_write_bits(ctx->map, FG_ARB_CFG, FG_ARB_REQUEST, FG_ARB_REQUEST);
	if (rc)
		goto out;
	stage = QCOM_FG_DMA_REQUEST_DMA;
	rc = regmap_write_bits(ctx->map, FG_INTF_CFG, FG_INTF_MASK, FG_DMA_REQUEST);
	if (rc)
		goto out;
	stage = QCOM_FG_DMA_GRANT;
	rc = fg_wait_grant(ctx->map, audit);
	if (rc)
		goto out;
	stage = QCOM_FG_DMA_DATA;
	/*
	 * LIVE_REGMAP proof must exclude cached/cache-only data and establish
	 * the controller's complete, coherent two-byte transfer semantics.
	 * regmap reports errno, not a byte count; short bus reads are its duty.
	 */
	rc = regmap_bulk_read(ctx->map, FG_TEMP_DMA, data, sizeof(data));
	if (rc)
		goto out;
	stage = QCOM_FG_DMA_LIVE_AFTER_DATA;
	rc = fg_verify_live(audit, QCOM_FG_DMA_AFTER_DATA);
out:
	if (rc)
		fg_error(r, stage, rc);
	if (r->request_attempted)
		fg_cleanup(ctx->map, r);
	if (!r->rc) {
		rc = fg_verify_live(audit, QCOM_FG_DMA_BEFORE_PUBLISH);
		if (rc)
			fg_error(r, QCOM_FG_DMA_LIVE_BEFORE_PUBLISH, rc);
	}
	if (r->request_attempted && r->rc)
		ctx->quarantined = true;
	r->quarantined = ctx->quarantined;
	if (!r->rc) {
		raw = (data[0] | ((unsigned int)data[1] << 8)) & 0x3ff;
		r->decicelsius = sign_extend32(raw, 9) * 100 / 40;
		r->valid = true;
	}
	mutex_unlock(ctx->interface_lock);
	return r->rc;
}

int qcom_fg_dma_experimental_read(struct qcom_fg_dma_experimental *ctx,
				  const struct qcom_fg_dma_audit *audit,
				  struct qcom_fg_dma_result *r)
{
	/* Caller-supplied attestations cannot establish hardware safety. */
	if (!r)
		return -EINVAL;
	memset(r, 0, sizeof(*r));
	fg_error(r, QCOM_FG_DMA_AUDIT, -EOPNOTSUPP);
	return r->rc;
}
