/* SPDX-License-Identifier: GPL-2.0-only */
/* Compile the UNMODIFIED actual source in this offline-only translation unit.
 * static stays static. No wrapper/export is added to the production source.
 */
#include "test_fg_dma_kernel_shim.h"
#include <stdio.h>
#include <stdlib.h>

#include "../../drivers/power/supply/qcom_fg_dma_experimental.c"

static unsigned int checks, cases, warnings;
static atomic_int_fast64_t now_ns;
static unsigned int sleeps;
#define CHECK(c) do { checks++; if (!(c)) { \
    fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #c); \
    exit(EXIT_FAILURE); } } while (0)

int test_kernel_warn(bool c) { warnings += c; return c; }
ktime_t ktime_get(void) { return atomic_load(&now_ns); }
int ktime_compare(ktime_t a, ktime_t b) { return (a > b) - (a < b); }
void might_sleep(void) { }
void usleep_range(unsigned long lo, unsigned long hi)
{
    CHECK(hi >= lo);
    CHECK(lo == 40 || lo == 10000);
    sleeps++;
    atomic_fetch_add(&now_ns, (int64_t)lo * 1000);
}
int mutex_trylock(struct mutex *m)
{
    int rc;

    atomic_fetch_add(&m->attempts, 1);
    rc = pthread_mutex_trylock(&m->native);
    CHECK(rc == 0 || rc == EBUSY);
    if (rc)
        return 0;
    m->held = true;
    m->owner = pthread_self();
    return 1;
}
void mutex_unlock(struct mutex *m)
{
    CHECK(m->held && pthread_equal(m->owner, pthread_self()));
    m->held = false;
    m->unlocks++;
    CHECK(pthread_mutex_unlock(&m->native) == 0);
}
static void owned(struct regmap *m)
{
    CHECK(m->lock->held && pthread_equal(m->lock->owner, pthread_self()));
}
int regmap_get_val_bytes(struct regmap *m)
{
    owned(m); m->format_calls++; return m->val_bytes;
}
int regmap_get_reg_stride(struct regmap *m)
{
    owned(m); m->format_calls++; return m->stride;
}
static void event(struct regmap *m, enum test_io tag, unsigned int reg,
                  unsigned int mask, unsigned int value, size_t len)
{
    owned(m);
    CHECK(m->event_count < ARRAY_SIZE(m->events));
    m->events[m->event_count++] = (struct test_event){tag, reg, mask, value, len};
    m->calls[tag]++;
}
int regmap_read_bypassed(struct regmap *m, unsigned int reg, unsigned int *v)
{
    enum test_io tag;
    bool in_request = m->attempted;

    switch (reg) {
    case 0x4305: tag = T_MEM; break;
    case 0x4105: tag = T_INFO; break;
    case 0x41ee: tag = T_PEEK; break;
    case 0x4371: tag = T_MODE; break;
    case 0x4370: tag = T_STATUS; break;
    case 0x4350: tag = in_request ? T_VERIFY_DMA : T_PREFLIGHT_DMA; break;
    case 0x4340: tag = in_request ? T_VERIFY_ARB : T_PREFLIGHT_ARB; break;
    case 0x4310: tag = in_request ? T_GRANT : T_STALE_GRANT; break;
    default: CHECK(false); return -EINVAL;
    }
    event(m, tag, reg, 0, 0, 1);
    if (tag == T_VERIFY_ARB)
        m->attempted = false;
    if (m->faults[tag].rc)
        return m->faults[tag].rc;
    if (tag == T_STALE_GRANT)
        *v = m->stale_grant ? 8 : 0;
    else if (tag == T_GRANT) {
        *v = m->grant_after >= 0 && m->polls >= (unsigned int)m->grant_after ? 8 : 0;
        m->polls++;
    } else
        *v = m->regs[reg];
    return 0;
}
int regmap_write_bits(struct regmap *m, unsigned int reg,
                      unsigned int mask, unsigned int value)
{
    enum test_io tag;
    struct test_fault fault;

    CHECK((reg == 0x4340 && mask == 1) || (reg == 0x4350 && mask == 0xa0));
    CHECK(value == 0 || value == (reg == 0x4340 ? 1u : 0x80u));
    tag = reg == 0x4340 ? (value ? T_REQUEST_ARB : T_RELEASE_ARB) :
                         (value ? T_REQUEST_DMA : T_RELEASE_DMA);
    event(m, tag, reg, mask, value, 1);
    m->attempted = true;
    fault = m->faults[tag];
    if ((!fault.rc || fault.applied) && !fault.drop)
        m->regs[reg] = (uint8_t)((m->regs[reg] & ~mask) | (value & mask));
    return fault.rc;
}
int regmap_bulk_read(struct regmap *m, unsigned int reg, void *data, size_t size)
{
    CHECK(reg == 0x4858 && size == 2);
    event(m, T_DATA, reg, 0, 0, size);
    if (m->partial_data_error) {
        ((u8 *)data)[0] = m->regs[reg];
        return -EIO;
    }
    if (m->faults[T_DATA].rc)
        return m->faults[T_DATA].rc;
    memcpy(data, &m->regs[reg], size);
    return 0;
}

struct fixture {
    struct regmap map;
    struct mutex lock;
    struct qcom_fg_dma_experimental ctx;
    struct qcom_fg_dma_audit audit;
    unsigned int live_calls[4];
    int live_rc[4];
    int expire_phase;
};
static int verifier(void *cookie, enum qcom_fg_dma_phase phase)
{
    struct fixture *f = cookie;

    owned(&f->map);
    CHECK((unsigned int)phase < ARRAY_SIZE(f->live_calls));
    f->live_calls[phase]++;
    if (f->expire_phase == (int)phase)
        atomic_store(&now_ns, f->audit.valid_until);
    return f->live_rc[phase];
}
static void setup(struct fixture *f)
{
    unsigned int i;

    cases++;
    memset(f, 0, sizeof(*f));
    atomic_store(&now_ns, 0);
    sleeps = 0;
    CHECK(pthread_mutex_init(&f->lock.native, NULL) == 0);
    atomic_init(&f->lock.attempts, 0);
    f->map.lock = &f->lock;
    f->map.val_bytes = 1;
    f->map.stride = 1;
    f->map.grant_after = 0;
    f->map.regs[0x4305] = 0x0d;
    f->map.regs[0x4105] = 0x11;
    f->map.regs[0x41ee] = 0xac;
    f->map.regs[0x4371] = 2;
    f->map.regs[0x4340] = 2;
    f->map.regs[0x4350] = 4;
    f->map.regs[0x4858] = 100;
    f->expire_phase = -1;
    CHECK(qcom_fg_dma_experimental_init(&f->ctx, &f->map, &f->lock) == 0);
    f->audit.variant = QCOM_FG_DMA_VARIANT_PM8150B_V2;
    /* Deliberately forged test inputs. These are NOT hardware evidence. */
    f->audit.transaction_reference = "OFFLINE-FORGED-device-boot";
    f->audit.valid_until = 1000000000;
    f->audit.verify_live = verifier;
    f->audit.cookie = f;
    for (i = 0; i < QCOM_FG_DMA_REQUIREMENT_COUNT; i++) {
        f->audit.evidence[i].review = QCOM_FG_DMA_INDEPENDENTLY_REVIEWED;
        f->audit.evidence[i].reference = "OFFLINE-FORGED-artifact";
        f->audit.evidence[i].reviewer = "OFFLINE-FORGED-reviewer";
    }
}
static void teardown(struct fixture *f)
{
    CHECK(!f->lock.held);
    CHECK(pthread_mutex_destroy(&f->lock.native) == 0);
}
static void invalid(struct qcom_fg_dma_result *r, int rc,
                    enum qcom_fg_dma_stage stage)
{
    CHECK(r->rc == rc && !r->valid && r->decicelsius == 0);
    CHECK(r->error_count > 0 && r->error_count <= QCOM_FG_DMA_MAX_ERRORS);
    CHECK(r->errors[0].rc == rc && r->errors[0].stage == stage);
}
static void no_bus(struct fixture *f)
{
    CHECK(f->map.event_count == 0 && f->map.format_calls == 0);
    CHECK(sleeps == 0);
}
static void no_requests(struct fixture *f)
{
    CHECK(!f->ctx.quarantined);
    CHECK(f->map.calls[T_REQUEST_ARB] == 0 && f->map.calls[T_REQUEST_DMA] == 0);
    CHECK(f->map.calls[T_RELEASE_ARB] == 0 && f->map.calls[T_RELEASE_DMA] == 0);
    CHECK(f->map.calls[T_DATA] == 0);
}
static void released(struct fixture *f)
{
    const enum test_io tail[] = {T_RELEASE_DMA, T_RELEASE_ARB, T_VERIFY_DMA, T_VERIFY_ARB};
    size_t i;

    CHECK(f->map.event_count >= 4);
    for (i = 0; i < ARRAY_SIZE(tail); i++) {
        CHECK(f->map.calls[tail[i]] == 1);
        CHECK(f->map.events[f->map.event_count - 4 + i].tag == tail[i]);
    }
    CHECK(!f->lock.held && f->lock.unlocks == 1);
}
static void isolated(struct fixture *f)
{
    struct qcom_fg_dma_result r;
    size_t events = f->map.event_count;
    unsigned int formats = f->map.format_calls;

    CHECK(f->ctx.quarantined);
    CHECK(qcom_fg_dma_experimental_read_draft(&f->ctx, &f->audit, &r) == -EBUSY);
    invalid(&r, -EBUSY, QCOM_FG_DMA_QUARANTINED);
    CHECK(r.quarantine_observed && r.quarantined && !r.request_attempted);
    CHECK(f->map.event_count == events && f->map.format_calls == formats);
}

/* This MUST run first; no call to the private draft authorizes public I/O. */
static void test_public_hard_block(void)
{
    struct fixture f;
    struct qcom_fg_dma_result r;
    unsigned int i;

    setup(&f);
    memset(&r, 0xa5, sizeof(r));
    CHECK(qcom_fg_dma_experimental_read(&f.ctx, &f.audit, &r) == -EOPNOTSUPP);
    invalid(&r, -EOPNOTSUPP, QCOM_FG_DMA_AUDIT);
    CHECK(!r.request_attempted && !r.quarantine_observed);
    CHECK(r.cleanup == QCOM_FG_DMA_NOT_REQUESTED);
    for (i = 0; i < ARRAY_SIZE(f.live_calls); i++)
        CHECK(f.live_calls[i] == 0);
    CHECK(atomic_load(&f.lock.attempts) == 0);
    no_bus(&f);
    CHECK(qcom_fg_dma_experimental_read(NULL, NULL, &r) == -EOPNOTSUPP);
    CHECK(qcom_fg_dma_experimental_read(&f.ctx, &f.audit, NULL) == -EINVAL);
    no_bus(&f);
    teardown(&f);
    puts("public entry: forged evidence/callback blocked; zero callback/lock/bus/delay");
}

static void test_draft_gates(void)
{
    unsigned int i;

    for (i = 0; i < QCOM_FG_DMA_REQUIREMENT_COUNT * 3; i++) {
        struct fixture f;
        struct qcom_fg_dma_result r;
        unsigned int item = i / 3;

        setup(&f);
        if (i % 3 == 0) f.audit.evidence[item].review = QCOM_FG_DMA_BLOCKED;
        if (i % 3 == 1) f.audit.evidence[item].reference = "";
        if (i % 3 == 2) f.audit.evidence[item].reviewer = NULL;
        CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, &r) == -EOPNOTSUPP);
        invalid(&r, -EOPNOTSUPP, QCOM_FG_DMA_AUDIT);
        CHECK(r.blocked_requirements == BIT(item));
        no_bus(&f);
        teardown(&f);
    }
    for (i = 0; i < 9; i++) {
        struct fixture f;
        struct qcom_fg_dma_result r;
        int rc = -EINVAL;
        enum qcom_fg_dma_stage stage = QCOM_FG_DMA_AUDIT;

        setup(&f);
        switch (i) {
        case 0: f.audit.variant = QCOM_FG_DMA_VARIANT_UNVERIFIED; rc = -EOPNOTSUPP; break;
        case 1: f.audit.verify_live = NULL; break;
        case 2: f.audit.transaction_reference = NULL; break;
        case 3: f.audit.valid_until = 0; rc = -ESTALE; break;
        case 4: CHECK(mutex_trylock(&f.lock)); stage = QCOM_FG_DMA_BUSY; rc = -EBUSY; break;
        case 5: f.map.val_bytes = 2; stage = QCOM_FG_DMA_MAP_FORMAT; rc = -EOPNOTSUPP; break;
        case 6: f.map.stride = 2; stage = QCOM_FG_DMA_MAP_FORMAT; rc = -EOPNOTSUPP; break;
        case 7: f.live_rc[0] = -ENODATA; stage = QCOM_FG_DMA_LIVE_BEFORE_ACCESS; rc = -ENODATA; break;
        default: f.expire_phase = 0; stage = QCOM_FG_DMA_LIVE_BEFORE_ACCESS; rc = -ESTALE; break;
        }
        CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, &r) == rc);
        invalid(&r, rc, stage);
        if (i < 5) no_bus(&f);
        else CHECK(f.map.event_count == 0);
        no_requests(&f);
        if (i == 4) {
            CHECK(f.lock.held && f.lock.unlocks == 0);
            mutex_unlock(&f.lock);
        }
        teardown(&f);
    }
}

static void test_arguments_and_null_audit(void)
{
    struct fixture f;
    struct qcom_fg_dma_result r;
    struct regmap *map;
    struct mutex *lock;

    setup(&f);
    CHECK(qcom_fg_dma_experimental_init(NULL, &f.map, &f.lock) == -EINVAL);
    CHECK(qcom_fg_dma_experimental_init(&f.ctx, NULL, &f.lock) == -EINVAL);
    CHECK(qcom_fg_dma_experimental_init(&f.ctx, &f.map, NULL) == -EINVAL);
    CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, NULL) == -EINVAL);
    CHECK(qcom_fg_dma_experimental_read_draft(NULL, &f.audit, &r) == -EINVAL);
    invalid(&r, -EINVAL, QCOM_FG_DMA_ARGUMENT);
    map = f.ctx.map;
    f.ctx.map = (struct regmap *)(intptr_t)-EIO;
    CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, &r) == -EINVAL);
    f.ctx.map = map;
    lock = f.ctx.interface_lock;
    f.ctx.interface_lock = NULL;
    CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, &r) == -EINVAL);
    f.ctx.interface_lock = lock;
    CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, NULL, &r) == -EOPNOTSUPP);
    CHECK(r.blocked_requirements == BIT(QCOM_FG_DMA_REQUIREMENT_COUNT) - 1);
    no_bus(&f);
    CHECK(atomic_load(&f.lock.attempts) == 0);
    teardown(&f);
}

static void test_preflight(void)
{
    const struct { unsigned int reg, value; enum qcom_fg_dma_stage stage; int rc; } bad[] = {
        {0x4305, 0, QCOM_FG_DMA_MEM_SUBTYPE, -ENODEV},
        {0x4105, 0, QCOM_FG_DMA_INFO_SUBTYPE, -ENODEV},
        {0x41ee, 0, QCOM_FG_DMA_PEEK_CONFIG, -EOPNOTSUPP},
        {0x4371, 0, QCOM_FG_DMA_ADDRESS_MODE, -EOPNOTSUPP},
        {0x4370, 1, QCOM_FG_DMA_DMA_STATUS, -EIO},
        {0x4350, 0x80, QCOM_FG_DMA_PREFLIGHT_INTF, -EBUSY},
        {0x4350, 0x20, QCOM_FG_DMA_PREFLIGHT_INTF, -EBUSY},
        {0x4340, 0x04, QCOM_FG_DMA_PREFLIGHT_ARB, -EBUSY},
        {0x4340, 0x01, QCOM_FG_DMA_PREFLIGHT_ARB, -EBUSY},
        {0x4310, 8, QCOM_FG_DMA_PREFLIGHT_GRANT, -EBUSY},
    };
    const enum qcom_fg_dma_stage stages[] = {
        QCOM_FG_DMA_MEM_SUBTYPE, QCOM_FG_DMA_INFO_SUBTYPE, QCOM_FG_DMA_PEEK_CONFIG,
        QCOM_FG_DMA_ADDRESS_MODE, QCOM_FG_DMA_DMA_STATUS, QCOM_FG_DMA_PREFLIGHT_INTF,
        QCOM_FG_DMA_PREFLIGHT_ARB, QCOM_FG_DMA_PREFLIGHT_GRANT
    };
    size_t i;

    for (i = 0; i < ARRAY_SIZE(bad); i++) {
        struct fixture f;
        struct qcom_fg_dma_result r;

        setup(&f);
        f.map.regs[bad[i].reg] = (uint8_t)bad[i].value;
        f.map.stale_grant = bad[i].reg == 0x4310;
        CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, &r) == bad[i].rc);
        invalid(&r, bad[i].rc, bad[i].stage);
        CHECK(f.map.regs[bad[i].reg] == bad[i].value);
        no_requests(&f);
        teardown(&f);
    }
    for (i = 0; i < ARRAY_SIZE(stages); i++) {
        struct fixture f;
        struct qcom_fg_dma_result r;

        setup(&f);
        f.map.faults[i].rc = -ENXIO; /* First eight bus tags are preflight reads. */
        CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, &r) == -ENXIO);
        invalid(&r, -ENXIO, stages[i]);
        no_requests(&f);
        teardown(&f);
    }
}

static void test_success_and_decode(void)
{
    unsigned int raw, upper;

    for (upper = 0; upper < 2; upper++) for (raw = 0; raw < 1024; raw++) {
        struct fixture f;
        struct qcom_fg_dma_result r;
        unsigned int word = raw | (upper ? 0xfc00 : 0);
        int signed_raw = raw < 512 ? (int)raw : (int)raw - 1024;
        const enum test_io order[] = {
            T_MEM,T_INFO,T_PEEK,T_MODE,T_STATUS,T_PREFLIGHT_DMA,T_PREFLIGHT_ARB,
            T_STALE_GRANT,T_REQUEST_ARB,T_REQUEST_DMA,T_GRANT,T_DATA,
            T_RELEASE_DMA,T_RELEASE_ARB,T_VERIFY_DMA,T_VERIFY_ARB
        };
        size_t i;

        setup(&f);
        f.map.regs[0x4858] = (uint8_t)word;
        f.map.regs[0x4859] = (uint8_t)(word >> 8);
        CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, &r) == 0);
        CHECK(r.valid && r.decicelsius == (int)(signed_raw * 2.5));
        CHECK(r.error_count == 0 && !r.quarantined && r.request_attempted);
        CHECK(r.cleanup == QCOM_FG_DMA_REQUEST_FIELDS_CLEAR);
        CHECK(f.map.event_count == ARRAY_SIZE(order));
        for (i = 0; i < ARRAY_SIZE(order); i++) CHECK(f.map.events[i].tag == order[i]);
        CHECK(f.map.regs[0x4340] == 2 && f.map.regs[0x4350] == 4);
        CHECK(ktime_get() == 40000 && sleeps == 1);
        for (i = 0; i < 4; i++) CHECK(f.live_calls[i] == 1);
        released(&f);
        teardown(&f);
    }
}

static void test_primary_and_cleanup_matrix(void)
{
    const enum test_io primary[] = {T_IO_COUNT,T_REQUEST_ARB,T_REQUEST_DMA,T_GRANT,T_DATA};
    const enum qcom_fg_dma_stage primary_stage[] = {
        QCOM_FG_DMA_ARGUMENT,QCOM_FG_DMA_REQUEST_ARB,QCOM_FG_DMA_REQUEST_DMA,
        QCOM_FG_DMA_GRANT,QCOM_FG_DMA_DATA
    };
    unsigned int p, failure, applied, request_applied;

    /* Every primary, both request application outcomes, all 16 combinations
     * of two release errors and two readback errors. */
    for (p = 0; p < ARRAY_SIZE(primary); p++)
    for (failure = 0; failure < 16; failure++)
    for (applied = 0; applied < 2; applied++)
    for (request_applied = 0; request_applied < 2; request_applied++) {
        struct fixture f;
        struct qcom_fg_dma_result r;
        const enum test_io cleanup[] = {T_RELEASE_DMA,T_RELEASE_ARB,T_VERIFY_DMA,T_VERIFY_ARB};
        const enum qcom_fg_dma_stage cleanup_stage[] = {
            QCOM_FG_DMA_RELEASE_DMA,QCOM_FG_DMA_RELEASE_ARB,
            QCOM_FG_DMA_VERIFY_DMA,QCOM_FG_DMA_VERIFY_ARB
        };
        struct qcom_fg_dma_error expected[5];
        unsigned int n = 0, i;

        setup(&f);
        if (p) {
            f.map.faults[primary[p]] = (struct test_fault){-ENXIO, request_applied != 0, false};
            expected[n++] = (struct qcom_fg_dma_error){primary_stage[p], -ENXIO};
        }
        for (i = 0; i < 4; i++)
            if (failure & (1u << i))
                f.map.faults[cleanup[i]] = (struct test_fault){-EACCES, applied != 0, false};
        /* A non-applied release leaves bits set only if the request applied. */
        if (failure & 1) expected[n++] = (struct qcom_fg_dma_error){cleanup_stage[0], -EACCES};
        if (failure & 2) expected[n++] = (struct qcom_fg_dma_error){cleanup_stage[1], -EACCES};
        {
            bool arb_set = p != 1 || request_applied;
            bool dma_set = p != 1 && (p != 2 || request_applied);
            if (failure & 4)
                expected[n++] = (struct qcom_fg_dma_error){cleanup_stage[2], -EACCES};
            else if ((failure & 1) && !applied && dma_set)
                expected[n++] = (struct qcom_fg_dma_error){cleanup_stage[2], -EIO};
            if (failure & 8)
                expected[n++] = (struct qcom_fg_dma_error){cleanup_stage[3], -EACCES};
            else if ((failure & 2) && !applied && arb_set)
                expected[n++] = (struct qcom_fg_dma_error){cleanup_stage[3], -EIO};
        }
        CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, &r) == (n ? expected[0].rc : 0));
        CHECK(r.error_count == n);
        for (i = 0; i < n; i++) {
            CHECK(r.errors[i].stage == expected[i].stage);
            CHECK(r.errors[i].rc == expected[i].rc);
        }
        if (n) {
            invalid(&r, expected[0].rc, expected[0].stage);
            CHECK(r.cleanup == (failure ? QCOM_FG_DMA_CLEANUP_UNCERTAIN :
                                         QCOM_FG_DMA_REQUEST_FIELDS_CLEAR));
        } else CHECK(r.valid && r.decicelsius == 250);
        if (p) CHECK(f.map.calls[T_DATA] == (p == 4 ? 1u : 0u));
        if (p == 1) CHECK(f.map.calls[T_REQUEST_DMA] == 0);
        released(&f);
        if (n) isolated(&f);
        teardown(&f);
    }
}

static void test_time_live_partial_and_drop(void)
{
    unsigned int i;

    for (i = 0; i < 14; i++) {
        struct fixture f;
        struct qcom_fg_dma_result r;
        int rc = -EIO;
        enum qcom_fg_dma_stage stage = QCOM_FG_DMA_DATA;

        setup(&f);
        switch (i) {
        case 0: f.map.grant_after = -1; rc = -ETIMEDOUT; stage = QCOM_FG_DMA_GRANT; break;
        case 1: f.map.grant_after = 49; rc = 0; break;
        case 2: f.map.grant_after = -1; f.audit.valid_until = 5000000; rc = -ESTALE; stage = QCOM_FG_DMA_GRANT; break;
        case 3: f.map.partial_data_error = true; break;
        case 4: f.map.faults[T_RELEASE_DMA].drop = true; stage = QCOM_FG_DMA_VERIFY_DMA; break;
        case 5: f.map.faults[T_RELEASE_ARB].drop = true; stage = QCOM_FG_DMA_VERIFY_ARB; break;
        case 6: f.live_rc[1] = -ENODATA; rc = -ENODATA; stage = QCOM_FG_DMA_LIVE_BEFORE_REQUEST; break;
        case 7: f.live_rc[2] = -ENODATA; rc = -ENODATA; stage = QCOM_FG_DMA_LIVE_AFTER_DATA; break;
        case 8: f.live_rc[3] = -ENODATA; rc = -ENODATA; stage = QCOM_FG_DMA_LIVE_BEFORE_PUBLISH; break;
        case 9: f.live_rc[2] = 1; stage = QCOM_FG_DMA_LIVE_AFTER_DATA; break;
        case 10: f.expire_phase = 1; rc = -ESTALE; stage = QCOM_FG_DMA_LIVE_BEFORE_REQUEST; break;
        case 11: f.expire_phase = 2; rc = -ESTALE; stage = QCOM_FG_DMA_LIVE_AFTER_DATA; break;
        case 12: f.expire_phase = 3; rc = -ESTALE; stage = QCOM_FG_DMA_LIVE_BEFORE_PUBLISH; break;
        default:
            f.map.grant_after = -1;
            f.map.faults[T_RELEASE_DMA].rc = -EACCES;
            f.map.faults[T_RELEASE_ARB].rc = -EACCES;
            rc = -ETIMEDOUT; stage = QCOM_FG_DMA_GRANT;
        }
        CHECK(qcom_fg_dma_experimental_read_draft(&f.ctx, &f.audit, &r) == rc);
        if (rc) invalid(&r, rc, stage);
        else CHECK(r.valid && r.decicelsius == 250);
        if (i == 0 || i == 13) {
            CHECK(f.map.calls[T_GRANT] == 50 && ktime_get() == 500040000);
            CHECK(f.map.calls[T_DATA] == 0);
        }
        if (i == 1) CHECK(f.map.calls[T_GRANT] == 50 && ktime_get() == 490040000);
        if (i == 2) CHECK(f.map.calls[T_GRANT] == 1 && f.map.calls[T_DATA] == 0);
        if (i == 6 || i == 10) no_requests(&f);
        else {
            released(&f);
            if (rc) {
                /* Expired audit must be renewed for quarantine observation. */
                f.audit.valid_until = ktime_get() + 1000000000;
                isolated(&f);
            }
        }
        if (i == 13) CHECK(r.error_count == 5);
        teardown(&f);
    }
}

int main(void)
{
    test_public_hard_block();
    test_arguments_and_null_audit();
    test_draft_gates();
    test_preflight();
    test_success_and_decode();
    test_primary_and_cleanup_matrix();
    test_time_live_partial_and_drop();
    CHECK(warnings == 0);
    printf("actual-source offline tests: %u cases, %u checks passed\n", cases, checks);
    return 0;
}
