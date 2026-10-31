/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LGG8_FG_DMA_CORE_H
#define LGG8_FG_DMA_CORE_H

/* Offline C11 model only: no hardware backend, kernel hooks or real delays.
 * Based on pm8150b_dma_model.py and PM8150B_DMA_DESIGN.md in this directory.
 * Preconditions below are synthetic assertions, NOT device verification.
 * One model represents one shared interface. Do not copy/reinitialize a live
 * or quarantined model to bypass ownership/quarantine. No recovery API exists.
 * This is a transaction proposal, not proof that any PMIC write is safe.
 * Grant wait: <=50 reads, 40+50*10000 virtual us. V1 additionally allows
 * <=35 algorithm reads and 350000 virtual us, plus 1000 us at each success.
 * V2 requires PEEK configuration but does not poll ALG_ACTIVE (as in Python).
 * Preflight rejects ARB request/clear-log (including C220 0x04), DMA/IMA
 * ownership and stale grant; it cannot exclude an external master's race.
 * After any request attempt, both releases and both readbacks run once.
 * Any subsequent error quarantines even if cleanup verifies. No retry/IMA
 * fallback, initialization writes, ADC recovery or grant-deassert check.
 * At most five errors are retained in order; only an entirely successful
 * transaction publishes data. Busy lock acquisition fails rather than waits.
 * Trace capacity is bounded; later events increment trace_dropped. Test setup
 * fields may only be changed while no caller owns the model. Trace/time are
 * cumulative; simulated reads do not establish real sensor freshness.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>

enum fg_dma_stage {
    FG_ARGUMENT, FG_LOCKED, FG_PREREQUISITE, FG_PEEK_UNVERIFIED,
    FG_SAMPLE_INVALID, FG_QUARANTINED,
    FG_PREFLIGHT_DMA, FG_PREFLIGHT_ARB, FG_PREFLIGHT_GRANT,
    FG_ALG_STATUS, FG_ALG_TIMEOUT, FG_REQUEST_ARB, FG_REQUEST_DMA,
    FG_GRANT_STATUS, FG_GRANT_TIMEOUT, FG_DATA,
    FG_RELEASE_DMA, FG_RELEASE_ARB, FG_VERIFY_DMA, FG_VERIFY_ARB,
    FG_DELAY, FG_STAGE_COUNT
};

enum fg_dma_cleanup { FG_NOT_REQUESTED, FG_CLEANUP_VERIFIED, FG_CLEANUP_UNCERTAIN };
enum fg_dma_revision { FG_REV_UNKNOWN, FG_REV_V1, FG_REV_V2 };

struct fg_dma_preconditions {
    enum fg_dma_revision revision;
    bool initialized;
    bool peek_configured; /* Required for V2 too; never configured here. */
    bool battery_present;
    bool sample_fresh;
};

struct fg_dma_error {
    enum fg_dma_stage stage;
    int rc; /* Negative errno; first error is never overwritten. */
};

#define FG_DMA_MAX_ERRORS 5 /* Primary + two releases + two verifications. */
struct fg_dma_result {
    int rc;
    bool valid; /* Only true after a complete, error-free transaction. */
    int decicelsius; /* Zero/invalid on EVERY error, never a cached reading. */
    enum fg_dma_cleanup cleanup;
    size_t error_count;
    struct fg_dma_error errors[FG_DMA_MAX_ERRORS];
};

struct fg_dma_fault {
    int rc; /* 0 or negative errno. Positive input is normalized to -EIO. */
    bool applied; /* Write took effect despite error. */
    bool drop_write; /* Silent dropped write, detected by release readback. */
};

struct fg_dma_event {
    enum fg_dma_stage stage;
    uint16_t address;
    uint8_t mask;
    uint8_t value;
    unsigned int length;
    unsigned int delay_us;
};

#define FG_DMA_TRACE_CAPACITY 256
struct fg_dma_model {
    /* Fake register image. Exposed for test fixture setup only. */
    uint8_t arb, intf;
    uint8_t data[2];
    bool stale_grant, short_data;
    int grant_after, alg_inactive_after; /* -1 = never; otherwise zero-based. */
    struct fg_dma_fault faults[FG_STAGE_COUNT];
    struct fg_dma_event trace[FG_DMA_TRACE_CAPACITY];
    size_t trace_count, trace_dropped;
    uint64_t elapsed_us; /* Virtual time; no sleep. Accumulates across calls. */
    unsigned int grant_polls, alg_polls;
    bool quarantined;
    atomic_bool in_transaction; /* Same-image callers fail busy, do not spin. */
};

/* Initialize a NEW synthetic fixture only; not a hardware reset/recovery. */
void fg_dma_model_init(struct fg_dma_model *model, uint16_t raw_temperature);
struct fg_dma_result fg_dma_read_temperature(
    struct fg_dma_model *model, const struct fg_dma_preconditions *preconditions);

/* Build/run from repository root; build directory must already exist:
 * TMPDIR="$PWD/lgg8/tests/.fg-build" cc -pipe -std=c11 -Wall -Wextra -Werror \
 *   -pedantic lgg8/tests/lgg8_fg_dma_core.c lgg8/tests/test_fg_dma_core.c \
 *   -o lgg8/tests/.fg-build/test_fg_dma_core
 * lgg8/tests/.fg-build/test_fg_dma_core
 * Remove only the task-created build directory afterwards.
 */
#endif
