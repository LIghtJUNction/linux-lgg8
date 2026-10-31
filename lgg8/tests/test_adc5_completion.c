/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
#define BIT(n) (1U << (n))
#define msecs_to_jiffies(ms) (ms)
#define dev_err(...) ((void)0)
#define dev_dbg(...) ((void)0)

struct adc5_chip { bool poll_eoc; int lock, complete; void *dev; };
struct adc5_channel_prop { int unused; };
struct iio_chan_spec { int unused; };
static struct {
    int configure_error, status_error, data_error;
    unsigned int status_reads, data_reads, waits, sleeps, locks, unlocks;
    unsigned long irq_result;
    bool held;
    u8 status[3];
    unsigned int status_count;
} bus;

static void mutex_lock(int *lock)
{ (void)lock; assert(!bus.held); bus.held = true; bus.locks++; }
static void mutex_unlock(int *lock)
{ (void)lock; assert(bus.held); bus.held = false; bus.unlocks++; }
static int adc5_configure(struct adc5_chip *adc, struct adc5_channel_prop *prop)
{ assert(bus.held); return bus.configure_error; }
static unsigned long wait_for_completion_timeout(int *complete, unsigned int timeout)
{ assert(bus.held); assert(timeout); bus.waits++; return bus.irq_result; }
static void usleep_range(unsigned int min, unsigned int max)
{ assert(bus.held); assert(min <= max); bus.sleeps++; }
static int adc5_read(struct adc5_chip *adc, unsigned int reg, void *data, size_t size)
{
    assert(bus.held && reg == 8 && size == 1 && bus.status_count);
    unsigned int index = bus.status_reads++;
    if (bus.status_error) return bus.status_error;
    *(u8 *)data = bus.status[index < bus.status_count ? index : bus.status_count - 1];
    return 0;
}
static int adc5_read_voltage_data(struct adc5_chip *adc, u16 *data)
{
    assert(bus.held);
    bus.data_reads++;
    if (bus.data_error) return bus.data_error;
    *data = 0x1234;
    return 0;
}

#include "actual-adc5.h"

static unsigned int cases;
static void reset(void)
{
    memset(&bus, 0, sizeof(bus));
    bus.irq_result = 1;
    bus.status_count = 1;
    bus.status[0] = 1;
}
static void check(bool polling, int expected, unsigned int reads, unsigned int data_reads)
{
    struct adc5_chip adc = { .poll_eoc = polling };
    struct adc5_channel_prop prop = {0};
    struct iio_chan_spec channel = {0};
    u16 voltage = 0xbeef, current = 0xcafe;
    assert(adc5_do_conversion(&adc, &prop, &channel, &voltage, &current) == expected);
    assert(voltage == (expected ? 0xbeef : 0x1234));
    assert(current == 0xcafe);
    assert(bus.status_reads == reads && bus.data_reads == data_reads);
    assert(bus.waits == (!polling && !bus.configure_error ? 1U : 0U));
    assert(bus.locks == 1 && bus.unlocks == 1 && !bus.held);
    cases++;
}

int main(void)
{
    /* An early IRQ must not publish data while the request is still active. */
    reset(); bus.status[0] = 2;
    check(false, -ETIMEDOUT, ADC5_CONV_TIME_RETRY, 0);
    for (unsigned int polling = 0; polling <= 1; polling++) {
        reset(); check(polling, 0, 1, 1);
        reset(); bus.status_count = 2; bus.status[0] = 3; bus.status[1] = 1;
        check(polling, 0, 2, 1); assert(bus.sleeps == 1);
        reset(); bus.status[0] = 0;
        check(polling, -ETIMEDOUT, ADC5_CONV_TIME_RETRY, 0);
        reset(); bus.status[0] = 3;
        check(polling, -ETIMEDOUT, ADC5_CONV_TIME_RETRY, 0);
        reset(); bus.status_error = -EIO; check(polling, -EIO, 1, 0);
        reset(); bus.configure_error = -EIO; check(polling, -EIO, 0, 0);
        reset(); bus.data_error = -EIO; check(polling, -EIO, 1, 1);
    }
    reset(); bus.irq_result = 0; check(false, 0, 1, 1);
    reset(); bus.irq_result = 0; bus.status[0] = 0;
    check(false, -ETIMEDOUT, ADC5_CONV_TIME_RETRY, 0);
    printf("ADC5 actual-source: %u IRQ/status/error cases passed\n", cases);
    return 0;
}
