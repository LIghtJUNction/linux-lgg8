/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _QCOM_FG_DMA_EXPERIMENTAL_H
#define _QCOM_FG_DMA_EXPERIMENTAL_H

#include <linux/ktime.h>
#include <linux/mutex.h>
#include <linux/types.h>

struct regmap;

/*
 * UNWIRED, BLOCKED experimental kernel API. No driver registration, probe,
 * exports, device tree, worker, initialization writes or recovery path.
 *
 * Based on lgg8/tests/PM8150B_DMA_DESIGN.md and lgg8_fg_dma_core.c, referencing
 * downstream d4f335e13d73c4aa2af85581a6ec11b670ee5b94. Those models establish NO
 * hardware safety evidence. This repository supplies none of the approvals
 * below; all remain blockers for actual use. Strings/verdicts cannot establish
 * truth: a future caller must provide independently reviewable real evidence.
 * Never satisfy this contract with model results or unrelated boot snapshots.
 */
enum qcom_fg_dma_requirement {
	/* Exact PM8150B V2 identity, SID, bases and downstream revision mapping. */
	QCOM_FG_DMA_IDENTITY_V2,
	/* Current RAM-only boot, no persistent/profile/charging setup by this API. */
	QCOM_FG_DMA_RAM_ONLY,
	/* Live 8-bit/stride-1 map, no cache-only/cache hits, byte bulk semantics. */
	QCOM_FG_DMA_LIVE_REGMAP,
	/* All software/firmware/bus masters excluded; awake/runtime PM held. */
	QCOM_FG_DMA_OWNERSHIP_AWAKE,
	/* DMA partition mode, temperature address and coherent 2-byte read. */
	QCOM_FG_DMA_SRAM_PROTOCOL,
	/* Full-byte RMW side effects, including MEM_CLR_LOG_BIT and race windows. */
	QCOM_FG_DMA_RMW_SAFETY,
	/* Release after an ambiguously applied write, readback, fault recovery. */
	QCOM_FG_DMA_RELEASE_PROTOCOL,
	/* V2 PEEK configuration AND working ADC lockup detection/recovery. */
	QCOM_FG_DMA_PEEK_ADC_RECOVERY,
	/* Independent battery presence, fresh/calibrated raw temperature validity. */
	QCOM_FG_DMA_SAMPLE_VALIDITY,
	QCOM_FG_DMA_REQUIREMENT_COUNT,
};

enum qcom_fg_dma_review {
	QCOM_FG_DMA_BLOCKED = 0,
	QCOM_FG_DMA_INDEPENDENTLY_REVIEWED,
};

struct qcom_fg_dma_evidence {
	enum qcom_fg_dma_review review;
	/* Stable artifact/hash/location and reviewer identity; not just a label. */
	const char *reference;
	const char *reviewer;
};

enum qcom_fg_dma_phase {
	QCOM_FG_DMA_BEFORE_ACCESS,
	QCOM_FG_DMA_BEFORE_REQUEST,
	QCOM_FG_DMA_AFTER_DATA,
	QCOM_FG_DMA_BEFORE_PUBLISH,
};

enum qcom_fg_dma_variant {
	QCOM_FG_DMA_VARIANT_UNVERIFIED = 0,
	QCOM_FG_DMA_VARIANT_PM8150B_V2,
};

struct qcom_fg_dma_audit {
	/* Caller-decoded hardware identity, backed by IDENTITY_V2 evidence. */
	enum qcom_fg_dma_variant variant;
	const char *transaction_reference; /* Includes device and current boot ID. */
	struct qcom_fg_dma_evidence evidence[QCOM_FG_DMA_REQUIREMENT_COUNT];
	ktime_t valid_until; /* CLOCK_MONOTONIC; expiry is checked at every phase. */
	/*
	 * Mandatory sleepable read-only verifier, called with interface_lock held.
	 * Return 0 ONLY while ALL requirements hold for this device/current boot,
	 * with battery/sample/ADC validity freshly checked at each phase. No DMA
	 * access, recovery writes, re-entry, or acquisition of interface_lock here.
	 * Negative errno refuses operation/publication; positive values are errors.
	 * Ownership and awake protection must span the entire call, not merely
	 * each verifier invocation. The caller owns these holds and their release.
	 */
	int (*verify_live)(void *cookie, enum qcom_fg_dma_phase phase);
	void *cookie;
};

enum qcom_fg_dma_stage {
	QCOM_FG_DMA_ARGUMENT,
	QCOM_FG_DMA_AUDIT,
	QCOM_FG_DMA_BUSY,
	QCOM_FG_DMA_QUARANTINED,
	QCOM_FG_DMA_MAP_FORMAT,
	QCOM_FG_DMA_LIVE_BEFORE_ACCESS,
	QCOM_FG_DMA_MEM_SUBTYPE,
	QCOM_FG_DMA_INFO_SUBTYPE,
	QCOM_FG_DMA_PEEK_CONFIG,
	QCOM_FG_DMA_ADDRESS_MODE,
	QCOM_FG_DMA_DMA_STATUS,
	QCOM_FG_DMA_PREFLIGHT_INTF,
	QCOM_FG_DMA_PREFLIGHT_ARB,
	QCOM_FG_DMA_PREFLIGHT_GRANT,
	QCOM_FG_DMA_LIVE_BEFORE_REQUEST,
	QCOM_FG_DMA_REQUEST_ARB,
	QCOM_FG_DMA_REQUEST_DMA,
	QCOM_FG_DMA_GRANT,
	QCOM_FG_DMA_DATA,
	QCOM_FG_DMA_LIVE_AFTER_DATA,
	QCOM_FG_DMA_RELEASE_DMA,
	QCOM_FG_DMA_RELEASE_ARB,
	QCOM_FG_DMA_VERIFY_DMA,
	QCOM_FG_DMA_VERIFY_ARB,
	QCOM_FG_DMA_LIVE_BEFORE_PUBLISH,
};

enum qcom_fg_dma_cleanup {
	QCOM_FG_DMA_NOT_REQUESTED,
	/* Request fields read back clear; NOT proof of hardware/ADC recovery. */
	QCOM_FG_DMA_REQUEST_FIELDS_CLEAR,
	QCOM_FG_DMA_CLEANUP_UNCERTAIN,
};

#define QCOM_FG_DMA_MAX_ERRORS 5
struct qcom_fg_dma_error {
	enum qcom_fg_dma_stage stage;
	int rc;
};

struct qcom_fg_dma_result {
	int rc; /* First error, including when cleanup subsequently fails. */
	bool valid;
	int decicelsius; /* Zero and invalid on EVERY error. */
	bool request_attempted;
	bool quarantine_observed; /* False on audit/argument/lock rejection. */
	bool quarantined;
	enum qcom_fg_dma_cleanup cleanup;
	unsigned int error_count;
	struct qcom_fg_dma_error errors[QCOM_FG_DMA_MAX_ERRORS];
	/* Missing proof bits (BIT(enum requirement)); preserve with audit record. */
	unsigned long blocked_requirements;
};

struct qcom_fg_dma_experimental {
	struct regmap *map;
	/* One shared lock AND context for every client of this physical MEM_IF. */
	struct mutex *interface_lock;
	bool quarantined; /* Protected by interface_lock; no reset API. */
};

/*
 * Only constructs a NEW context. No regmap I/O, runtime PM or hardware setup.
 * Caller owns lifetime; never copy/reinitialize it to bypass quarantine.
 * Bases are deliberately fixed to the audited candidate layout, not discovered.
 */
int qcom_fg_dma_experimental_init(struct qcom_fg_dma_experimental *ctx,
				  struct regmap *map, struct mutex *interface_lock);

/*
 * This public entry is unconditionally disabled and performs no regmap I/O.
 * Review strings and caller callbacks cannot authorize hardware access.
 * A future enabled implementation would require process context and could
 * sleep ~500 ms plus bus/verifier/scheduler latency.
 * 50 polls bound iterations, NOT a hard wall-clock timeout or bus hang.
 * All arguments/evidence strings must remain stable through this call; result
 * must not alias them. Every error is returned in result (no lossy log-only
 * reporting). Caller must persist it alongside transaction_reference/evidence.
 * No retry, IMA fallback, ADC recovery or charging/protection use is provided.
 */
int qcom_fg_dma_experimental_read(struct qcom_fg_dma_experimental *ctx,
				  const struct qcom_fg_dma_audit *audit,
				  struct qcom_fg_dma_result *result);

#endif /* _QCOM_FG_DMA_EXPERIMENTAL_H */
