#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual driver PM/transport bodies with a simulated IRQ and I2C bus.

No hardware, kernel build, temporary directory or disk compiler outputs. Run:
    python3 -B lgg8/tests/test_sw42000_pm.py
The fake bus cannot establish electrical safety or real suspend recovery.
"""

import ctypes
import hashlib
import os
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "drivers/input/touchscreen/lge_sw42000.c"


def definition(source, name):
    """Copy a complete function/struct, rather than reimplementing its logic."""
    pattern = (r"struct " + name + r"\s*\{" if name == "sw42000_ts" else
               r"static [^{;]+\b" + name + r"\([^;]*?\)\s*\{")
    match = re.search(pattern, source)
    if not match:
        raise AssertionError(f"Missing definition: {name}")
    opening = source.index("{", match.start())
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end] + (";" if name == "sw42000_ts" else "")


SHIM = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <time.h>
#include "lge_sw42000_protocol.h"
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int irqreturn_t;
#define IRQ_HANDLED 1
#define MT_TOOL_FINGER 0
#define BTN_TOUCH 1
#define ABS_MT_POSITION_X 2
#define ABS_MT_POSITION_Y 3
#define ABS_MT_PRESSURE 4
#define ABS_MT_TOUCH_MAJOR 5
#define ABS_MT_TOUCH_MINOR 6
#define min_t(type, a, b) ((type)(a) < (type)(b) ? (type)(a) : (type)(b))
#define clamp_t(type, v, lo, hi) ((type)(v) < (type)(lo) ? (type)(lo) : min_t(type, v, hi))
#define dev_err(...) ((void)0)
#define dev_dbg_ratelimited(...) ((void)0)
#define dev_warn_ratelimited(...) ((void)0)
struct i2c_client;
struct device { struct i2c_client *client; };
struct i2c_client { struct device dev; int irq; void *data; };
struct input_dev { bool slots[10], touch; unsigned slot, syncs; };
struct gpio_desc { int unused; };
struct touchscreen_properties { unsigned int max_x, max_y; };
static int depth, disables, enables, transfers, writes, gpios, sleeps;
static int fail_at, fail_second, short_io, after_effect, invalid_fw;
static u16 address;
static u32 driving;
static bool irq_running, blocked_read, read_entered, release_read, disable_waiting;
static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static void wait_changed(void)
{
    struct timespec deadline;
    assert(timespec_get(&deadline, TIME_UTC) == TIME_UTC);
    deadline.tv_sec += 5;
    assert(!pthread_cond_timedwait(&changed, &gate, &deadline));
}
static struct i2c_client *to_i2c_client(struct device *dev) { return dev->client; }
static void *i2c_get_clientdata(struct i2c_client *c) { return c->data; }
static void input_mt_slot(struct input_dev *i, unsigned slot) { i->slot = slot; }
static void input_mt_report_slot_state(struct input_dev *i, int tool, bool active)
{ (void)tool; i->slots[i->slot] = active; }
static void input_mt_sync_frame(struct input_dev *i) { (void)i; }
static void input_report_key(struct input_dev *i, int code, bool value)
{ assert(code == BTN_TOUCH); i->touch = value; }
static void input_report_abs(struct input_dev *i, int code, int value)
{ (void)i; (void)code; (void)value; }
static void touchscreen_report_pos(struct input_dev *i,
                                   const struct touchscreen_properties *p,
                                   unsigned int x, unsigned int y, bool multitouch)
{
    assert(multitouch && x <= p->max_x && y <= p->max_y);
    input_report_abs(i, ABS_MT_POSITION_X, (int)x);
    input_report_abs(i, ABS_MT_POSITION_Y, (int)y);
}
static void input_sync(struct input_dev *i) { i->syncs++; }
static void disable_irq(int irq)
{
    (void)irq; assert(depth == 0);
    pthread_mutex_lock(&gate);
    disable_waiting = true; pthread_cond_broadcast(&changed);
    while (irq_running) wait_changed();
    pthread_mutex_unlock(&gate);
    depth = 1; disables++;
}
static void enable_irq(int irq) { (void)irq; assert(depth == 1); depth = 0; enables++; }
static void msleep(int ms) { assert(ms == 30); sleeps++; }
static void usleep_range(int lo, int hi) { (void)lo; (void)hi; }
static void gpiod_set_value_cansleep(struct gpio_desc *g, int value)
{ (void)g; (void)value; assert(depth == 1); gpios++; }
static void put32(u8 *p, u32 n)
{ for (int i = 0; i < 4; i++) p[i] = (u8)(n >> (i * 8)); }
static int transfer_error(void)
{
    transfers++;
    if (transfers == fail_at) return -ENXIO;
    if (transfers == fail_second) return -EREMOTEIO;
    return 0;
}
static int i2c_master_send(struct i2c_client *c, const u8 *p, size_t n)
{
    (void)c; int error = transfer_error();
    assert(n == 2 || n == 6);
    if (!error || after_effect) {
        address = (u16)(((p[0] & 15) << 8) | p[1]);
        if (n == 6) {
            assert(depth == 1); writes++;
            if (address == SW42000_REG_DRIVING_CONTROL) driving = sw42000_get_le32(p + 2);
        }
    }
    return error ? (short_io ? (int)n - 1 : error) : (int)n;
}
static int i2c_master_recv(struct i2c_client *c, u8 *p, size_t n)
{
    (void)c; int error = transfer_error(); memset(p, 0, n);
    if (address == SW42000_REG_TOUCH_STATUS) {
        pthread_mutex_lock(&gate);
        if (blocked_read) {
            read_entered = true; pthread_cond_broadcast(&changed);
            while (!release_read) wait_changed();
        }
        pthread_mutex_unlock(&gate);
        assert(n == SW42000_REPORT_SIZE);
        put32(p + 4, 5U << 16); put32(p + 8, 1U << 8);
        put32(p + 12, 1U << 16); /* A pending DOWN must not be replayed on resume. */
    } else {
        assert(n == 4);
        if (address == SW42000_REG_VERSION) {
            p[2] = invalid_fw == 1 ? 0 : 10; p[3] = invalid_fw == 5 ? 0 : 4;
        } else if (address == SW42000_REG_BOOT_CRC_RESULT)
            put32(p, invalid_fw == 2 ? 0 : SW42000_CRC_FIXED_VALUE);
        else if (address == SW42000_REG_BOOT_CRC_PASS)
            put32(p, invalid_fw == 3 ? 0 : 1);
        else { assert(address == SW42000_REG_INFO_POINTER); put32(p, invalid_fw == 4 ? 0 : 1); }
    }
    return error ? (short_io ? (int)n - 1 : error) : (int)n;
}
"""


CASES = r"""
static struct i2c_client client;
static struct input_dev input;
static struct sw42000_ts ts;
static void setup(bool running)
{
    memset(&client, 0, sizeof(client)); memset(&input, 0, sizeof(input));
    memset(&ts, 0, sizeof(ts)); client.dev.client = &client; client.data = &ts;
    ts.client = &client; ts.input = &input; ts.irq_enabled = running;
    ts.prop.max_x = 1439; ts.prop.max_y = 3119;
    for (int i = 0; i < 10; i++) input.slots[i] = true;
    input.touch = true; depth = running ? 0 : 1;
    disables = enables = transfers = writes = gpios = sleeps = 0;
    fail_at = fail_second = short_io = after_effect = invalid_fw = 0;
    driving = SW42000_ACTIVE_DRIVING;
    irq_running = blocked_read = read_entered = release_read = disable_waiting = false;
}
static void released(void)
{
    assert(!input.touch && input.syncs);
    for (int i = 0; i < 10; i++) assert(!input.slots[i]);
    assert(!gpios); /* PM must never change rails or reset. */
}
static void *report_thread(void *unused)
{
    (void)unused; sw42000_irq_thread(0, &ts);
    pthread_mutex_lock(&gate); irq_running = false;
    pthread_cond_broadcast(&changed); pthread_mutex_unlock(&gate); return NULL;
}
static void *suspend_thread(void *unused)
{ (void)unused; assert(!sw42000_suspend(&client.dev)); return NULL; }
int sw42000_pm_tests(void)
{
    unsigned cases = 0;
    setup(true);
    assert(!sw42000_suspend(&client.dev)); released();
    assert(depth == 1 && disables == 1 && driving == SW42000_STOP_DRIVING && sleeps == 1);
    assert(!sw42000_suspend(&client.dev) && disables == 1);
    assert(!sw42000_resume(&client.dev)); released();
    assert(depth == 0 && enables == 1 && ts.irq_enabled && driving == SW42000_ACTIVE_DRIVING);
    assert(!sw42000_resume(&client.dev) && depth == 0 && disables == 2 && enables == 2);
    cases++;
    /* Every transport operation: negative/short result, before/after effect. */
    for (int n = 1; n <= 15; n++) for (int short_result = 0; short_result < 2; short_result++)
    for (int effect = 0; effect < 2; effect++) {
        setup(false); fail_at = n; short_io = short_result; after_effect = effect;
        assert(sw42000_resume(&client.dev) == (short_result ? -EIO : -ENXIO));
        released(); assert(depth == 1 && !ts.irq_enabled && !enables && !disables);
        if (n <= 8) assert(!writes); /* Identity/boot failures never write setup. */
        else assert(driving == SW42000_STOP_DRIVING);
        fail_at = 0;
        assert(!sw42000_resume(&client.dev) && depth == 0 && enables == 1);
        released(); cases++;
    }
    for (int bad = 1; bad <= 5; bad++) {
        setup(false); invalid_fw = bad;
        assert(sw42000_resume(&client.dev) < 0 && !writes && depth == 1);
        released(); cases++;
    }
    setup(false); fail_at = 9; fail_second = 10;
    assert(sw42000_resume(&client.dev) == -ENXIO && depth == 1 && !enables);
    released(); cases++;
    for (int effect = 0; effect < 2; effect++) {
        setup(true); fail_at = 1; after_effect = effect;
        assert(sw42000_suspend(&client.dev) == -ENXIO);
        assert(depth == 0 && enables == 1 && driving == SW42000_ACTIVE_DRIVING);
        released(); cases++;
    }
    setup(true); fail_at = 1; fail_second = 2;
    assert(sw42000_suspend(&client.dev) == -ENXIO && depth == 1 && !enables);
    released(); fail_at = fail_second = 0;
    assert(!sw42000_resume(&client.dev) && depth == 0); cases++;
    setup(true);
    blocked_read = irq_running = true;
    pthread_t reporter, suspender;
    assert(!pthread_create(&reporter, NULL, report_thread, NULL));
    pthread_mutex_lock(&gate);
    while (!read_entered) wait_changed();
    pthread_mutex_unlock(&gate);
    assert(!pthread_create(&suspender, NULL, suspend_thread, NULL));
    pthread_mutex_lock(&gate);
    while (!disable_waiting) wait_changed();
    assert(!writes && !input.syncs); /* No bus write or release before IRQ drains. */
    release_read = true; pthread_cond_broadcast(&changed); pthread_mutex_unlock(&gate);
    assert(!pthread_join(reporter, NULL)); assert(!pthread_join(suspender, NULL));
    released(); assert(depth == 1); cases++;
    for (int running = 0; running < 2; running++) {
        setup(running); sw42000_remove(&client);
        assert(depth == 1 && gpios == 3 && !ts.irq_enabled);
        assert(disables == running && !input.touch); cases++;
    }
    printf("SW42000 PM: %u behavioral sequences passed (simulated hardware only)\n", cases);
    fflush(stdout); return 0;
}
"""


class Sw42000PmTest(unittest.TestCase):
    def test_pm_ordering_errors_and_inflight_irq(self):
        before = DRIVER.read_bytes()
        source = before.decode()
        defines = "\n".join(re.findall(r"^#define SW42000_.*$", source, re.M))
        names = ["sw42000_read_reg", "sw42000_write_u32", "sw42000_power_off",
                 "sw42000_check_firmware", "sw42000_initialize_controller",
                 "sw42000_quiesce", "sw42000_stop_controller", "sw42000_start_controller",
                 "sw42000_resume", "sw42000_suspend", "sw42000_report_frame",
                 "sw42000_irq_thread", "sw42000_remove"]
        program = (defines + SHIM + definition(source, "sw42000_ts") + "\n" +
                   "\n".join(definition(source, name) for name in names) + CASES)
        descriptors = []
        try:
            descriptors = [os.memfd_create("sw42000-pm-object"),
                           os.memfd_create("sw42000-pm-suite")]
            obj, library = [f"/proc/self/fd/{fd}" for fd in descriptors]
            subprocess.run(["cc", "-pipe", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-fPIC", "-pthread", "-O2", "-I", str(DRIVER.parent),
                            "-x", "c", "-c", "-", "-o", obj], input=program, text=True,
                           pass_fds=(descriptors[0],), check=True, timeout=30)
            subprocess.run(["/usr/bin/ld", "-shared", "-o", library, obj],
                           pass_fds=tuple(descriptors), check=True, timeout=30)
            suite = ctypes.CDLL(library)
            suite.sw42000_pm_tests.restype = ctypes.c_int
            self.assertEqual(suite.sw42000_pm_tests(), 0)
        finally:
            for fd in descriptors:
                os.close(fd)
        self.assertEqual(before, DRIVER.read_bytes())
        print("Driver SHA-256:", hashlib.sha256(before).hexdigest())


if __name__ == "__main__":
    unittest.main()
