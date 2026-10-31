/* SPDX-License-Identifier: GPL-2.0-only */
#include "lgg8_fg_dma_core.h"

#include <errno.h>
#include <string.h>

#define ARB 0x4340
#define INTF 0x4350
#define STATUS 0x4310
#define PEEK 0x41ef
#define TEMP (0x4800 + 0x20 + (328 - 300) * 2)
#define ARB_REQ 0x01
#define ARB_CLEAR_LOG 0x04
#define INTF_MASK 0xa0
#define GRANT 0x08

void fg_dma_model_init(struct fg_dma_model *m, uint16_t raw)
{
    /* Do not memset an atomic object; initialize the lock separately. */
    m->arb = 0x02;
    m->intf = 0x04;
    m->data[0] = (uint8_t)raw;
    m->data[1] = (uint8_t)(raw >> 8);
    m->stale_grant = false;
    m->short_data = false;
    m->grant_after = 0;
    m->alg_inactive_after = 0;
    memset(m->faults, 0, sizeof(m->faults));
    memset(m->trace, 0, sizeof(m->trace));
    m->trace_count = 0;
    m->trace_dropped = 0;
    m->elapsed_us = 0;
    m->grant_polls = 0;
    m->alg_polls = 0;
    m->quarantined = false;
    atomic_init(&m->in_transaction, false);
}

static void record(struct fg_dma_model *m, struct fg_dma_event e)
{
    if (m->trace_count < FG_DMA_TRACE_CAPACITY)
        m->trace[m->trace_count++] = e;
    else
        m->trace_dropped++;
}

static int fault_rc(const struct fg_dma_model *m, enum fg_dma_stage stage)
{
    int rc = m->faults[stage].rc;

    return rc > 0 ? -EIO : rc;
}

static int read_byte(struct fg_dma_model *m, enum fg_dma_stage stage,
                     uint16_t address, uint8_t *value)
{
    int rc;

    record(m, (struct fg_dma_event){ .stage = stage, .address = address,
                                    .length = 1 });
    rc = fault_rc(m, stage);
    if (rc)
        return rc;
    switch (address) {
    case ARB:
        *value = m->arb;
        break;
    case INTF:
        *value = m->intf;
        break;
    case STATUS:
        if (stage == FG_PREFLIGHT_GRANT) {
            *value = m->stale_grant ? GRANT : 0;
        } else {
            *value = m->grant_after >= 0 &&
                     m->grant_polls >= (unsigned int)m->grant_after ? GRANT : 0;
            m->grant_polls++;
        }
        break;
    case PEEK:
        *value = m->alg_inactive_after >= 0 &&
                 m->alg_polls >= (unsigned int)m->alg_inactive_after ? 0 : 0x08;
        m->alg_polls++;
        break;
    default:
        return -EINVAL;
    }
    return 0;
}

static int update_bits(struct fg_dma_model *m, enum fg_dma_stage stage,
                       uint16_t address, uint8_t mask, uint8_t value)
{
    uint8_t *reg;
    int rc = fault_rc(m, stage);

    record(m, (struct fg_dma_event){ .stage = stage, .address = address,
                                    .mask = mask, .value = value });
    if (address == ARB && mask == ARB_REQ)
        reg = &m->arb;
    else if (address == INTF && mask == INTF_MASK)
        reg = &m->intf;
    else
        return -EINVAL;
    if ((!rc || m->faults[stage].applied) && !m->faults[stage].drop_write)
        *reg = (uint8_t)((*reg & (uint8_t)~mask) | (value & mask));
    return rc;
}

static void delay(struct fg_dma_model *m, unsigned int us)
{
    record(m, (struct fg_dma_event){ .stage = FG_DELAY, .delay_us = us });
    m->elapsed_us += us;
}

static int read_data(struct fg_dma_model *m, int *temperature)
{
    unsigned int raw;
    int signed_raw, rc;

    record(m, (struct fg_dma_event){ .stage = FG_DATA, .address = TEMP,
                                    .length = 2 });
    rc = fault_rc(m, FG_DATA);
    if (rc)
        return rc;
    if (m->short_data)
        return -EIO;
    raw = ((unsigned int)m->data[0] | ((unsigned int)m->data[1] << 8)) & 0x3ff;
    signed_raw = raw >= 512 ? (int)raw - 1024 : (int)raw;
    *temperature = signed_raw * 100 / 40; /* C11 truncates toward zero. */
    return 0;
}

static void add_error(struct fg_dma_result *r, enum fg_dma_stage stage, int rc)
{
    if (!r->rc)
        r->rc = rc;
    /* Fixed flow has at most five errors; no retries can grow this list. */
    if (r->error_count < FG_DMA_MAX_ERRORS)
        r->errors[r->error_count++] = (struct fg_dma_error){stage, rc};
}

static int preflight(struct fg_dma_model *m, enum fg_dma_stage *stage)
{
    static const struct { enum fg_dma_stage stage; uint16_t address; uint8_t mask; }
    checks[] = {
        {FG_PREFLIGHT_DMA, INTF, INTF_MASK},
        {FG_PREFLIGHT_ARB, ARB, ARB_REQ | ARB_CLEAR_LOG},
        {FG_PREFLIGHT_GRANT, STATUS, GRANT},
    };
    size_t i;

    for (i = 0; i < sizeof(checks) / sizeof(checks[0]); i++) {
        uint8_t value = 0;
        int rc;

        *stage = checks[i].stage;
        rc = read_byte(m, *stage, checks[i].address, &value);
        if (rc)
            return rc;
        if (value & checks[i].mask)
            return -EBUSY;
    }
    return 0;
}

static int poll_algorithm(struct fg_dma_model *m, enum fg_dma_stage *stage)
{
    unsigned int i;

    for (i = 0; i < 35; i++) {
        uint8_t value = 0;
        int rc;

        *stage = FG_ALG_STATUS;
        rc = read_byte(m, *stage, PEEK, &value);
        if (rc)
            return rc;
        if (!(value & 0x08)) {
            delay(m, 1000);
            return 0;
        }
        delay(m, 10000);
    }
    *stage = FG_ALG_TIMEOUT;
    return -ETIMEDOUT;
}

static int poll_grant(struct fg_dma_model *m, enum fg_dma_stage *stage,
                      enum fg_dma_revision revision)
{
    unsigned int i;

    delay(m, 40);
    for (i = 0; i < 50; i++) {
        uint8_t value = 0;
        int rc;

        *stage = FG_GRANT_STATUS;
        rc = read_byte(m, *stage, STATUS, &value);
        if (rc)
            return rc;
        if (value & GRANT) {
            if (revision == FG_REV_V1)
                delay(m, 1000);
            return 0;
        }
        delay(m, 10000);
    }
    *stage = FG_GRANT_TIMEOUT;
    return -ETIMEDOUT;
}

static void cleanup(struct fg_dma_model *m, struct fg_dma_result *r)
{
    static const struct { enum fg_dma_stage stage; uint16_t address; uint8_t mask; }
    steps[] = {
        {FG_RELEASE_DMA, INTF, INTF_MASK}, {FG_RELEASE_ARB, ARB, ARB_REQ},
        {FG_VERIFY_DMA, INTF, INTF_MASK}, {FG_VERIFY_ARB, ARB, ARB_REQ},
    };
    size_t i;

    r->cleanup = FG_CLEANUP_VERIFIED;
    for (i = 0; i < sizeof(steps) / sizeof(steps[0]); i++) {
        int rc;
        uint8_t value = 0;

        if (i < 2) {
            rc = update_bits(m, steps[i].stage, steps[i].address, steps[i].mask, 0);
        } else {
            rc = read_byte(m, steps[i].stage, steps[i].address, &value);
            if (!rc && (value & steps[i].mask))
                rc = -EIO;
        }
        if (rc) {
            add_error(r, steps[i].stage, rc);
            r->cleanup = FG_CLEANUP_UNCERTAIN;
        }
    }
}

struct fg_dma_result fg_dma_read_temperature(
    struct fg_dma_model *m, const struct fg_dma_preconditions *p)
{
    struct fg_dma_result r = {0};
    enum fg_dma_stage stage = FG_ARGUMENT;
    int rc = -EINVAL, temperature = 0;
    bool requested = false;

    if (!m || !p) {
        add_error(&r, FG_ARGUMENT, -EINVAL);
        return r;
    }
    if (atomic_exchange_explicit(&m->in_transaction, true, memory_order_acquire)) {
        add_error(&r, FG_LOCKED, -EBUSY);
        return r;
    }
    stage = FG_PREREQUISITE;
    rc = -EOPNOTSUPP;
    if (!p->initialized || (p->revision != FG_REV_V1 && p->revision != FG_REV_V2))
        goto out;
    stage = FG_PEEK_UNVERIFIED;
    if (!p->peek_configured)
        goto out;
    stage = FG_SAMPLE_INVALID;
    rc = -ENODATA;
    if (!p->battery_present || !p->sample_fresh)
        goto out;
    stage = FG_QUARANTINED;
    rc = -EBUSY;
    if (m->quarantined)
        goto out;
    rc = preflight(m, &stage);
    if (rc)
        goto out;
    m->alg_polls = 0;
    m->grant_polls = 0;
    if (p->revision == FG_REV_V1) {
        rc = poll_algorithm(m, &stage);
        if (rc)
            goto out;
    }
    /* A failed bus write may have applied: set this BEFORE the first write. */
    requested = true;
    stage = FG_REQUEST_ARB;
    rc = update_bits(m, stage, ARB, ARB_REQ, ARB_REQ);
    if (rc)
        goto out;
    stage = FG_REQUEST_DMA;
    rc = update_bits(m, stage, INTF, INTF_MASK, 0x80);
    if (rc)
        goto out;
    rc = poll_grant(m, &stage, p->revision);
    if (rc)
        goto out;
    stage = FG_DATA;
    rc = read_data(m, &temperature);
out:
    if (rc)
        add_error(&r, stage, rc);
    if (requested) {
        cleanup(m, &r);
        if (r.rc)
            m->quarantined = true; /* Even when cleanup readback succeeded. */
    }
    if (!r.rc) {
        r.valid = true;
        r.decicelsius = temperature;
    }
    atomic_store_explicit(&m->in_transaction, false, memory_order_release);
    return r;
}
