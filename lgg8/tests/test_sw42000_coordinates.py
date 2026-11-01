#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check SW42000 coordinates through the real kernel touchscreen helper.

The production reporting function and touchscreen helper are compiled in
anonymous memory with a recording input-device shim. No phone or /tmp is used.
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
TOUCHSCREEN = ROOT / "drivers/input/touchscreen.c"
HEADER = DRIVER.with_name("lge_sw42000_protocol.h")


def definition(source, pattern):
    match = re.search(pattern, source, re.M)
    if not match:
        raise AssertionError(f"Missing definition: {pattern}")
    opening = source.index("{", match.start())
    end, depth = opening + 1, 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


SHIM = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include "lge_sw42000_protocol.h"
typedef uint32_t u32;
#define ABS_X 1
#define ABS_Y 2
#define ABS_MT_POSITION_X 3
#define ABS_MT_POSITION_Y 4
#define ABS_MT_PRESSURE 5
#define ABS_MT_TOUCH_MAJOR 6
#define ABS_MT_TOUCH_MINOR 7
#define BTN_TOUCH 8
#define ABS_PRESSURE 9
#define MT_TOOL_FINGER 0
#define min_t(type, a, b) ((type)(a) < (type)(b) ? (type)(a) : (type)(b))
#define clamp_t(type, v, lo, hi) ((type)(v) < (type)(lo) ? (type)(lo) : min_t(type, v, hi))
#define swap(a, b) do { __typeof__(a) tmp = (a); (a) = (b); (b) = tmp; } while (0)
#define dev_warn(...) ((void)0)
struct i2c_client;
struct gpio_desc;
struct fake_property { const char *name; u32 value; int error; };
struct device { struct device *parent; struct fake_property props[12]; };
struct touchscreen_properties {
    unsigned int max_x, max_y;
    bool invert_x, invert_y, swap_x_y;
};
struct input_absinfo { int minimum, maximum, fuzz; };
struct input_dev {
    struct device dev;
    struct input_absinfo info[16], *absinfo;
    unsigned long absbit[1];
    int axis[16];
    bool seen[16], active, touch;
    unsigned int slot, syncs;
};
static struct fake_property *find_prop(struct device *dev, const char *name)
{
    for (unsigned int i = 0; i < 12; i++)
        if (dev->props[i].name && !strcmp(dev->props[i].name, name)) return &dev->props[i];
    return NULL;
}
static bool device_property_present(struct device *dev, const char *name)
{ return find_prop(dev, name) != NULL; }
static int device_property_read_u32(struct device *dev, const char *name, u32 *value)
{
    struct fake_property *p = find_prop(dev, name);
    if (!p) return -EINVAL;
    if (p->error) return p->error;
    *value = p->value; return 0;
}
static bool device_property_read_bool(struct device *dev, const char *name)
{ return device_property_present(dev, name); }
static void input_alloc_absinfo(struct input_dev *input) { input->absinfo = input->info; }
static bool test_bit(unsigned long axis, const unsigned long *bits)
{ return !!(*bits & (1UL << axis)); }
static int input_abs_get_min(struct input_dev *input, int axis) { return input->absinfo[axis].minimum; }
static int input_abs_get_max(struct input_dev *input, int axis) { return input->absinfo[axis].maximum; }
static int input_abs_get_fuzz(struct input_dev *input, int axis) { return input->absinfo[axis].fuzz; }
static void set_axis(struct input_dev *input, unsigned int axis, int maximum)
{ input->absbit[0] |= 1UL << axis; input->info[axis].maximum = maximum; }
static void input_mt_slot(struct input_dev *input, unsigned int slot) { input->slot = slot; }
static void input_mt_report_slot_state(struct input_dev *input, int tool, bool active)
{ assert(tool == MT_TOOL_FINGER); input->active = active; }
static void input_mt_sync_frame(struct input_dev *input) { (void)input; }
static void input_report_key(struct input_dev *input, int code, bool value)
{ assert(code == BTN_TOUCH); input->touch = value; }
static void input_report_abs(struct input_dev *input, int code, int value)
{ assert(code > 0 && code < 16); input->axis[code] = value; input->seen[code] = true; }
static void input_sync(struct input_dev *input) { input->syncs++; }
"""


CASES = r"""
int sw42000_coordinate_tests(void)
{
    /* Raw (150,2300), ordered by invert-x, invert-y, then swap flag bits. */
    static const int normal[8][2] = {
        {150,2300}, {1289,2300}, {150,819}, {1289,819},
        {2300,150}, {2300,1289}, {819,150}, {819,1289},
    };
    /* Controller values beyond each raw maximum must clamp before inversion. */
    static const int overflow[8][2] = {
        {1439,3119}, {0,3119}, {1439,0}, {0,0},
        {3119,1439}, {3119,0}, {0,1439}, {0,0},
    };
    /* With physical minima (100,200), raw zero clamps to the raw minimum. */
    static const int underflow[8][2] = {
        {100,200}, {1339,200}, {100,2919}, {1339,2919},
        {200,100}, {200,1339}, {2919,100}, {2919,1339},
    };
    for (unsigned int bits = 0; bits < 8; bits++) {
        for (unsigned int edge = 0; edge < 3; edge++) {
            struct input_dev input = {0};
            struct device dev = {0};
            struct sw42000_ts ts = { .input = &input };
            struct sw42000_frame frame = { .count = 1 };
            const int (*expected)[2] = edge == 2 ? underflow : edge ? overflow : normal;
            u32 max_x, max_y;
            unsigned int x_axis, y_axis;

            dev.props[0] = (struct fake_property){ "touchscreen-size-x", 1440, 0 };
            dev.props[1] = (struct fake_property){ "touchscreen-size-y", 3120, 0 };
            dev.props[2] = (struct fake_property){ "touchscreen-min-x", 100, 0 };
            dev.props[3] = (struct fake_property){ "touchscreen-min-y", 200, 0 };
            if (bits & 1) dev.props[4].name = "touchscreen-inverted-x";
            if (bits & 2) dev.props[5].name = "touchscreen-inverted-y";
            if (bits & 4) dev.props[6].name = "touchscreen-swapped-x-y";
            assert(!sw42000_axis_limits(&dev, "touchscreen-size-x", "touchscreen-min-x",
                                        1440, &ts.raw_min_x, &max_x));
            assert(!sw42000_axis_limits(&dev, "touchscreen-size-y", "touchscreen-min-y",
                                        3120, &ts.raw_min_y, &max_y));
            input.dev.parent = &dev;
            input_alloc_absinfo(&input);
            set_axis(&input, ABS_MT_POSITION_X, 1439);
            set_axis(&input, ABS_MT_POSITION_Y, 3119);
            set_axis(&input, ABS_MT_PRESSURE, 255);
            touchscreen_parse_properties(&input, true, &ts.prop);
            assert(ts.prop.max_x == max_x && ts.prop.max_y == max_y);
            x_axis = ts.prop.swap_x_y ? ABS_MT_POSITION_Y : ABS_MT_POSITION_X;
            y_axis = ts.prop.swap_x_y ? ABS_MT_POSITION_X : ABS_MT_POSITION_Y;
            assert(sw42000_axis_matches(&input, x_axis, ts.raw_min_x, max_x, ts.prop.invert_x));
            assert(sw42000_axis_matches(&input, y_axis, ts.raw_min_y, max_y, ts.prop.invert_y));
            frame.contacts[0].id = 3;
            frame.contacts[0].x = edge == 2 ? 0 : edge ? 14000 : 150;
            frame.contacts[0].y = edge == 2 ? 0 : edge ? 15000 : 2300;
            frame.contacts[0].pressure = 123;
            frame.contacts[0].major = 200; frame.contacts[0].minor = 100;
            sw42000_report_frame(&ts, &frame);
            assert(input.seen[ABS_MT_POSITION_X] && input.seen[ABS_MT_POSITION_Y]);
            assert(input.axis[ABS_MT_POSITION_X] == expected[bits][0]);
            assert(input.axis[ABS_MT_POSITION_Y] == expected[bits][1]);
            assert(input.slot == 3 && input.active && input.touch && input.syncs == 1);
            assert(input.axis[ABS_MT_PRESSURE] == 123);
            assert(input.axis[ABS_MT_TOUCH_MAJOR] == 200 && input.axis[ABS_MT_TOUCH_MINOR] == 100);
        }
    }
    /* Current LG G8 device tree: zero minima, no inversion and no swap. */
    for (unsigned int edge = 0; edge < 2; edge++) {
        struct input_dev input = {0};
        struct device dev = {0};
        struct sw42000_ts ts = { .input = &input };
        struct sw42000_frame frame = { .count = 1 };
        u32 max_x, max_y;

        dev.props[0] = (struct fake_property){ "touchscreen-size-x", 1440, 0 };
        dev.props[1] = (struct fake_property){ "touchscreen-size-y", 3120, 0 };
        assert(!sw42000_axis_limits(&dev, "touchscreen-size-x", "touchscreen-min-x",
                                    1440, &ts.raw_min_x, &max_x));
        assert(!sw42000_axis_limits(&dev, "touchscreen-size-y", "touchscreen-min-y",
                                    3120, &ts.raw_min_y, &max_y));
        input.dev.parent = &dev;
        input_alloc_absinfo(&input);
        set_axis(&input, ABS_MT_POSITION_X, 1439);
        set_axis(&input, ABS_MT_POSITION_Y, 3119);
        set_axis(&input, ABS_MT_PRESSURE, 255);
        touchscreen_parse_properties(&input, true, &ts.prop);
        assert(!ts.raw_min_x && !ts.raw_min_y && max_x == 1439 && max_y == 3119);
        frame.contacts[0].x = edge ? 15000 : 1399;
        frame.contacts[0].y = edge ? 15000 : 3000;
        sw42000_report_frame(&ts, &frame);
        assert(input.axis[ABS_MT_POSITION_X] == (edge ? 1439 : 1399));
        assert(input.axis[ABS_MT_POSITION_Y] == (edge ? 3119 : 3000));
    }
    {
        struct device dev = {0};
        u32 minimum = 77, maximum = 88;
        assert(!sw42000_axis_limits(&dev, "size", "min", 1440, &minimum, &maximum));
        assert(minimum == 0 && maximum == 1439);
        dev.props[0] = (struct fake_property){ "size", 0, 0 };
        for (unsigned int i = 0; i < 4; i++) {
            static const u32 bad[] = {0, 1, 16385, UINT32_MAX};
            dev.props[0].value = bad[i]; minimum = 77; maximum = 88;
            assert(sw42000_axis_limits(&dev, "size", "min", 1440, &minimum, &maximum) == -EINVAL);
            assert(minimum == 77 && maximum == 88);
        }
        dev.props[0].value = 1440;
        dev.props[1] = (struct fake_property){ "min", 1439, 0 };
        assert(sw42000_axis_limits(&dev, "size", "min", 1440, &minimum, &maximum) == -EINVAL);
        dev.props[1].value = 2000;
        assert(sw42000_axis_limits(&dev, "size", "min", 1440, &minimum, &maximum) == -EINVAL);
        dev.props[1].value = 100; dev.props[1].error = -EIO;
        assert(sw42000_axis_limits(&dev, "size", "min", 1440, &minimum, &maximum) == -EIO);
        dev.props[1].error = 0; dev.props[0].error = -EIO;
        assert(sw42000_axis_limits(&dev, "size", "min", 1440, &minimum, &maximum) == -EIO);
        dev.props[0].error = 0; dev.props[0].value = 16384; dev.props[1].value = 16382;
        assert(!sw42000_axis_limits(&dev, "size", "min", 1440, &minimum, &maximum));
        assert(minimum == 16382 && maximum == 16383);
    }
    return 26;
}
"""


class CoordinatesTest(unittest.TestCase):
    def test_report_frame_applies_kernel_touchscreen_properties(self):
        inputs = (DRIVER, TOUCHSCREEN, HEADER)
        before = {path: path.read_bytes() for path in inputs}
        driver, core = before[DRIVER].decode(), before[TOUCHSCREEN].decode()
        defines = []
        for name in ("SW42000_MAX_WIDTH", "SW42000_COORD_MAX"):
            value = re.search(r"^#define " + name + r"\s+\S+", driver, re.M)
            self.assertIsNotNone(value)
            defines.append(value.group())
        ts = definition(driver, r"^struct sw42000_ts\s*\{") + ";"
        limits = definition(driver, r"^static int sw42000_axis_limits\s*\(")
        matches = definition(driver, r"^static bool sw42000_axis_matches\s*\(")
        get_prop = definition(core, r"^static bool touchscreen_get_prop_u32\s*\(")
        set_params = definition(core, r"^static void touchscreen_set_params\s*\(")
        parse = definition(core, r"^void touchscreen_parse_properties\s*\(")
        apply = definition(core, r"^static void\s+touchscreen_apply_prop_to_x_y\s*\(")
        report = definition(core, r"^void touchscreen_report_pos\s*\(")
        frame = definition(driver, r"^static void sw42000_report_frame\s*\(")
        probe = definition(driver, r"^static int sw42000_probe\s*\(")
        self.assertLess(probe.index("sw42000_axis_limits"), probe.index("sw42000_power_on"))
        self.assertLess(probe.index("touchscreen_parse_properties"), probe.index("input_mt_init_slots"))
        program = "\n".join((*defines, SHIM, ts, limits, matches, get_prop,
                             set_params, parse, apply, report, frame, CASES))
        descriptors = []
        try:
            descriptors = [os.memfd_create("sw42000-coordinates-object"),
                           os.memfd_create("sw42000-coordinates-suite")]
            obj, library = [f"/proc/self/fd/{fd}" for fd in descriptors]
            subprocess.run(["cc", "-pipe", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-fPIC", "-O2", "-I", str(DRIVER.parent),
                            "-x", "c", "-c", "-", "-o", obj], input=program, text=True,
                           pass_fds=(descriptors[0],), check=True, timeout=30)
            subprocess.run(["/usr/bin/ld", "-shared", "-o", library, obj],
                           pass_fds=tuple(descriptors), check=True, timeout=30)
            suite = ctypes.CDLL(library)
            suite.sw42000_coordinate_tests.restype = ctypes.c_int
            self.assertEqual(suite.sw42000_coordinate_tests(), 26)
        finally:
            for fd in descriptors:
                os.close(fd)
        self.assertEqual(before, {path: path.read_bytes() for path in inputs})
        print("SW42000 coordinate source SHA-256:", hashlib.sha256(before[DRIVER]).hexdigest())


if __name__ == "__main__":
    unittest.main()
