/* SPDX-License-Identifier: GPL-2.0-only */
/* Standalone fault-injection executable; no devices, files, network or sleep. */
#include "lgg8_fg_dma_core.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

static unsigned int cases, checks;

#define CHECK(condition) do { \
    checks++; \
    if (!(condition)) { \
        fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
        exit(EXIT_FAILURE); \
    } \
} while (0)

static struct fg_dma_preconditions ready(void)
{
    return (struct fg_dma_preconditions){ FG_REV_V2, true, true, true, true };
}

static size_t count(const struct fg_dma_model *m, enum fg_dma_stage stage)
{
    size_t i, n = 0;

    for (i = 0; i < m->trace_count; i++)
        n += m->trace[i].stage == stage;
    return n;
}

static void no_writes(const struct fg_dma_model *m)
{
    CHECK(count(m, FG_REQUEST_ARB) == 0);
    CHECK(count(m, FG_REQUEST_DMA) == 0);
    CHECK(count(m, FG_RELEASE_ARB) == 0);
    CHECK(count(m, FG_RELEASE_DMA) == 0);
    CHECK(count(m, FG_DATA) == 0);
}

static void released(const struct fg_dma_model *m)
{
    const enum fg_dma_stage tail[] = {
        FG_RELEASE_DMA, FG_RELEASE_ARB, FG_VERIFY_DMA, FG_VERIFY_ARB
    };
    size_t i;

    CHECK(m->trace_count >= 4);
    CHECK(m->trace_dropped == 0);
    for (i = 0; i < 4; i++) {
        CHECK(count(m, tail[i]) == 1);
        CHECK(m->trace[m->trace_count - 4 + i].stage == tail[i]);
    }
}

static void invalid(struct fg_dma_result r, int rc)
{
    CHECK(r.rc == rc);
    CHECK(!r.valid);
    CHECK(r.decicelsius == 0);
    CHECK(r.error_count > 0 && r.error_count <= FG_DMA_MAX_ERRORS);
    CHECK(r.errors[0].rc == rc);
}

static void isolated(struct fg_dma_model *m, const struct fg_dma_preconditions *p)
{
    size_t before = m->trace_count;
    struct fg_dma_result r = fg_dma_read_temperature(m, p);

    invalid(r, -EBUSY);
    CHECK(r.errors[0].stage == FG_QUARANTINED);
    CHECK(r.cleanup == FG_NOT_REQUESTED);
    CHECK(m->trace_count == before);
}

static void test_success(void)
{
    struct fg_dma_model m;
    struct fg_dma_preconditions p = ready();
    struct fg_dma_result r;
    const enum fg_dma_stage order[] = {
        FG_PREFLIGHT_DMA, FG_PREFLIGHT_ARB, FG_PREFLIGHT_GRANT,
        FG_REQUEST_ARB, FG_REQUEST_DMA, FG_DELAY, FG_GRANT_STATUS,
        FG_DATA, FG_RELEASE_DMA, FG_RELEASE_ARB, FG_VERIFY_DMA, FG_VERIFY_ARB
    };
    size_t i;

    cases++;
    fg_dma_model_init(&m, 100);
    r = fg_dma_read_temperature(&m, &p);
    CHECK(r.rc == 0 && r.valid && r.decicelsius == 250);
    CHECK(r.error_count == 0 && r.cleanup == FG_CLEANUP_VERIFIED);
    CHECK(!m.quarantined && m.arb == 2 && m.intf == 4);
    CHECK(m.trace_count == sizeof(order) / sizeof(order[0]));
    for (i = 0; i < m.trace_count; i++)
        CHECK(m.trace[i].stage == order[i]);
    CHECK(m.trace[3].address == 0x4340 && m.trace[3].mask == 1 &&
          m.trace[3].value == 1);
    CHECK(m.trace[4].address == 0x4350 && m.trace[4].mask == 0xa0 &&
          m.trace[4].value == 0x80);
    CHECK(m.trace[7].address == 0x4858 && m.trace[7].length == 2);
    CHECK(m.trace[8].value == 0 && m.trace[9].value == 0);
    CHECK(m.elapsed_us == 40);
    released(&m);
}

static void test_decoding(void)
{
    unsigned int raw, upper;
    struct fg_dma_preconditions p = ready();

    /* All 10-bit encodings, with and without irrelevant upper bits. */
    for (upper = 0; upper < 2; upper++) {
        for (raw = 0; raw < 1024; raw++) {
            struct fg_dma_model m;
            int signed_raw = raw < 512 ? (int)raw : (int)raw - 1024;
            int expected = (int)(signed_raw * 2.5);
            struct fg_dma_result r;

            cases++;
            fg_dma_model_init(&m, (uint16_t)(raw | (upper ? 0xfc00 : 0)));
            r = fg_dma_read_temperature(&m, &p);
            CHECK(r.rc == 0 && r.valid && r.decicelsius == expected);
        }
    }
}

static void test_gates(void)
{
    unsigned int i;

    for (i = 0; i < 7; i++) {
        struct fg_dma_model m;
        struct fg_dma_preconditions p = ready();
        struct fg_dma_result r;

        cases++;
        fg_dma_model_init(&m, 100);
        switch (i) {
        case 0: p.initialized = false; break;
        case 1: p.revision = FG_REV_UNKNOWN; break;
        case 2: p.peek_configured = false; break; /* V2 must reject. */
        case 3: p.peek_configured = false; p.revision = FG_REV_V1; break;
        case 4: p.battery_present = false; break;
        case 5: p.sample_fresh = false; break;
        default: m.quarantined = true; break;
        }
        r = fg_dma_read_temperature(&m, &p);
        invalid(r, i < 4 ? -EOPNOTSUPP : i < 6 ? -ENODATA : -EBUSY);
        CHECK(m.trace_count == 0 && r.cleanup == FG_NOT_REQUESTED);
        CHECK(!atomic_load(&m.in_transaction));
    }
    for (i = 0; i < 6; i++) {
        struct fg_dma_model m;
        struct fg_dma_preconditions p = ready();
        struct fg_dma_result r;
        uint8_t arb, intf;

        cases++;
        fg_dma_model_init(&m, 100);
        switch (i) {
        case 0: m.arb = 0x04; break; /* Exact C220 observation: reject. */
        case 1: m.arb |= 1; break;
        case 2: m.intf |= 0x80; break;
        case 3: m.intf |= 0x20; break;
        case 4: m.intf |= 0xa0; break;
        default: m.stale_grant = true; break;
        }
        arb = m.arb;
        intf = m.intf;
        r = fg_dma_read_temperature(&m, &p);
        invalid(r, -EBUSY);
        CHECK(r.errors[0].stage == (i < 2 ? FG_PREFLIGHT_ARB :
                                  i < 5 ? FG_PREFLIGHT_DMA : FG_PREFLIGHT_GRANT));
        CHECK(m.arb == arb && m.intf == intf && !m.quarantined);
        CHECK(r.cleanup == FG_NOT_REQUESTED);
        no_writes(&m);
    }
}

static void test_read_failures(void)
{
    const enum fg_dma_stage stages[] = {
        FG_PREFLIGHT_DMA, FG_PREFLIGHT_ARB, FG_PREFLIGHT_GRANT,
        FG_GRANT_STATUS, FG_DATA
    };
    size_t i;

    for (i = 0; i < sizeof(stages) / sizeof(stages[0]); i++) {
        struct fg_dma_model m;
        struct fg_dma_preconditions p = ready();
        struct fg_dma_result r;

        cases++;
        fg_dma_model_init(&m, 100);
        m.faults[stages[i]].rc = -ENXIO;
        r = fg_dma_read_temperature(&m, &p);
        invalid(r, -ENXIO);
        CHECK(r.errors[0].stage == stages[i]);
        if (i < 3) {
            CHECK(!m.quarantined && r.cleanup == FG_NOT_REQUESTED);
            no_writes(&m);
        } else {
            CHECK(r.cleanup == FG_CLEANUP_VERIFIED && m.quarantined);
            released(&m);
            isolated(&m, &p);
        }
    }
}

static void test_request_failures(void)
{
    unsigned int request, applied;

    for (request = 0; request < 2; request++) {
        for (applied = 0; applied < 2; applied++) {
            struct fg_dma_model m;
            struct fg_dma_preconditions p = ready();
            enum fg_dma_stage stage = request ? FG_REQUEST_DMA : FG_REQUEST_ARB;
            struct fg_dma_result r;

            cases++;
            fg_dma_model_init(&m, 100);
            m.faults[stage] = (struct fg_dma_fault){ .rc = -ENXIO,
                                                   .applied = applied != 0 };
            r = fg_dma_read_temperature(&m, &p);
            invalid(r, -ENXIO);
            CHECK(r.errors[0].stage == stage && r.error_count == 1);
            CHECK(r.cleanup == FG_CLEANUP_VERIFIED && m.quarantined);
            CHECK(count(&m, FG_GRANT_STATUS) == 0 && count(&m, FG_DATA) == 0);
            if (!request)
                CHECK(count(&m, FG_REQUEST_DMA) == 0);
            CHECK(m.arb == 2 && m.intf == 4);
            released(&m);
            isolated(&m, &p);
        }
    }
}

static void test_timeouts_and_v1(void)
{
    unsigned int i;

    for (i = 0; i < 6; i++) {
        struct fg_dma_model m;
        struct fg_dma_preconditions p = ready();
        struct fg_dma_result r;

        cases++;
        fg_dma_model_init(&m, 100);
        if (i == 0)
            m.grant_after = -1;
        else if (i == 1)
            m.grant_after = 49;
        else {
            p.revision = FG_REV_V1;
            m.alg_inactive_after = i == 2 ? 1 : i == 5 ? 34 : -1;
            if (i == 4)
                m.faults[FG_ALG_STATUS].rc = -ENXIO;
        }
        r = fg_dma_read_temperature(&m, &p);
        if (i == 0) {
            invalid(r, -ETIMEDOUT);
            CHECK(r.errors[0].stage == FG_GRANT_TIMEOUT);
            CHECK(m.grant_polls == 50 && m.elapsed_us == 500040);
            CHECK(count(&m, FG_DATA) == 0 && m.quarantined);
            released(&m);
            isolated(&m, &p);
        } else if (i == 3 || i == 4) {
            invalid(r, i == 3 ? -ETIMEDOUT : -ENXIO);
            CHECK(r.cleanup == FG_NOT_REQUESTED && !m.quarantined);
            if (i == 3)
                CHECK(m.alg_polls == 35 && m.elapsed_us == 350000);
            no_writes(&m);
        } else {
            CHECK(r.rc == 0 && r.valid);
            CHECK(m.elapsed_us == (i == 1 ? 490040 : i == 2 ? 12040 : 342040));
            if (i == 1)
                CHECK(m.grant_polls == 50);
            else {
                CHECK(count(&m, FG_ALG_STATUS) == (i == 2 ? 2 : 35));
                CHECK(m.trace[3].address == 0x41ef);
            }
            released(&m);
        }
    }
}

static void test_cleanup_matrix(void)
{
    /* Every primary error combined with either/both releases, before/after
     * application. Different error numbers prove primary error precedence. */
    const enum fg_dma_stage primaries[] = {
        FG_STAGE_COUNT, FG_REQUEST_ARB, FG_REQUEST_DMA,
        FG_GRANT_STATUS, FG_GRANT_TIMEOUT, FG_DATA
    };
    size_t primary;
    unsigned int failed, applied;

    for (primary = 0; primary < sizeof(primaries) / sizeof(primaries[0]); primary++) {
        for (failed = 1; failed <= 3; failed++) {
            for (applied = 0; applied < 2; applied++) {
                struct fg_dma_model m;
                struct fg_dma_preconditions p = ready();
                struct fg_dma_result r;
                size_t index = 0;
                int expected = -EIO;

                cases++;
                fg_dma_model_init(&m, 100);
                if (primary) {
                    expected = primaries[primary] == FG_GRANT_TIMEOUT ?
                               -ETIMEDOUT : -ENXIO;
                    if (primaries[primary] == FG_GRANT_TIMEOUT)
                        m.grant_after = -1;
                    else
                        m.faults[primaries[primary]] =
                            (struct fg_dma_fault){ .rc = expected, .applied = true };
                }
                if (failed & 1)
                    m.faults[FG_RELEASE_DMA] =
                        (struct fg_dma_fault){ .rc = -EIO, .applied = applied != 0 };
                if (failed & 2)
                    m.faults[FG_RELEASE_ARB] =
                        (struct fg_dma_fault){ .rc = -EIO, .applied = applied != 0 };
                r = fg_dma_read_temperature(&m, &p);
                invalid(r, expected);
                CHECK(m.quarantined && r.cleanup == FG_CLEANUP_UNCERTAIN);
                if (primary)
                    CHECK(r.errors[index++].stage == primaries[primary]);
                if (failed & 1)
                    CHECK(r.errors[index++].stage == FG_RELEASE_DMA);
                if (failed & 2)
                    CHECK(r.errors[index++].stage == FG_RELEASE_ARB);
                CHECK(r.error_count >= index);
                released(&m);
                isolated(&m, &p);
            }
        }
    }
}

static void test_readback_and_silent_drop(void)
{
    unsigned int failed, silent;

    for (failed = 1; failed <= 3; failed++) {
        for (silent = 0; silent < 2; silent++) {
            struct fg_dma_model m;
            struct fg_dma_preconditions p = ready();
            struct fg_dma_result r;

            cases++;
            fg_dma_model_init(&m, 100);
            if (silent) {
                m.faults[FG_RELEASE_DMA].drop_write = (failed & 1) != 0;
                m.faults[FG_RELEASE_ARB].drop_write = (failed & 2) != 0;
            } else {
                m.faults[FG_VERIFY_DMA].rc = failed & 1 ? -ENXIO : 0;
                m.faults[FG_VERIFY_ARB].rc = failed & 2 ? -ENXIO : 0;
            }
            r = fg_dma_read_temperature(&m, &p);
            invalid(r, silent ? -EIO : -ENXIO);
            CHECK(r.errors[0].stage == (failed & 1 ? FG_VERIFY_DMA : FG_VERIFY_ARB));
            CHECK(r.error_count == (failed == 3 ? 2u : 1u));
            CHECK(r.cleanup == FG_CLEANUP_UNCERTAIN && m.quarantined);
            released(&m);
            isolated(&m, &p);
        }
    }
}

static void test_arguments_lock_and_publication(void)
{
    struct fg_dma_model m;
    struct fg_dma_preconditions p = ready();
    struct fg_dma_result r;
    size_t before;

    cases++;
    fg_dma_model_init(&m, 100);
    invalid(fg_dma_read_temperature(NULL, &p), -EINVAL);
    invalid(fg_dma_read_temperature(&m, NULL), -EINVAL);
    CHECK(m.trace_count == 0);
    atomic_store(&m.in_transaction, true);
    r = fg_dma_read_temperature(&m, &p);
    invalid(r, -EBUSY);
    CHECK(r.errors[0].stage == FG_LOCKED && m.trace_count == 0);
    CHECK(atomic_load(&m.in_transaction)); /* Never release a peer's lock. */
    atomic_store(&m.in_transaction, false);
    r = fg_dma_read_temperature(&m, &p);
    CHECK(r.valid && r.decicelsius == 250);
    m.short_data = true;
    r = fg_dma_read_temperature(&m, &p);
    invalid(r, -EIO);
    CHECK(r.cleanup == FG_CLEANUP_VERIFIED && m.quarantined);
    CHECK(!atomic_load(&m.in_transaction));
    before = m.trace_count;
    isolated(&m, &p);
    CHECK(m.trace_count == before);
}

static void test_full_error_chain(void)
{
    struct fg_dma_model m;
    struct fg_dma_preconditions p = ready();
    struct fg_dma_result r;
    const enum fg_dma_stage expected[] = {
        FG_DATA, FG_RELEASE_DMA, FG_RELEASE_ARB, FG_VERIFY_DMA, FG_VERIFY_ARB
    };
    const int codes[] = {-ENXIO, -EIO, -EACCES, -EIO, -EIO};
    size_t i;

    cases++;
    fg_dma_model_init(&m, 100);
    m.faults[FG_DATA].rc = -ENXIO;
    m.faults[FG_RELEASE_DMA].rc = -EIO;
    m.faults[FG_RELEASE_ARB].rc = -EACCES;
    r = fg_dma_read_temperature(&m, &p);
    invalid(r, -ENXIO);
    CHECK(r.error_count == FG_DMA_MAX_ERRORS);
    for (i = 0; i < FG_DMA_MAX_ERRORS; i++) {
        CHECK(r.errors[i].stage == expected[i]);
        CHECK(r.errors[i].rc == codes[i]);
    }
    CHECK(r.cleanup == FG_CLEANUP_UNCERTAIN);
    released(&m);
    isolated(&m, &p);
}

int main(void)
{
    test_success();
    test_decoding();
    test_gates();
    test_read_failures();
    test_request_failures();
    test_timeouts_and_v1();
    test_cleanup_matrix();
    test_readback_and_silent_drop();
    test_arguments_lock_and_publication();
    test_full_error_chain();
    printf("FG DMA offline: %u cases, %u checks passed\n", cases, checks);
    return EXIT_SUCCESS;
}
