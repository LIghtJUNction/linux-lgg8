// SPDX-License-Identifier: GPL-2.0-only
#include <stdio.h>
#include <string.h>

#include "../../drivers/input/touchscreen/lge_sw42000_protocol.h"

static int failures;

#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition); \
	failures++; \
	} \
} while (0)

static void put_le32(sw42000_u8 *buf, sw42000_u32 value)
{
	buf[0] = value & 0xff;
	buf[1] = (value >> 8) & 0xff;
	buf[2] = (value >> 16) & 0xff;
	buf[3] = (value >> 24) & 0xff;
}

static void make_header(sw42000_u8 *report, sw42000_u8 count,
			sw42000_u8 wakeup, sw42000_u8 intr_type)
{
	put_le32(report + 4, (sw42000_u32)intr_type << 16);
	put_le32(report + 8, wakeup | ((sw42000_u32)count << 8));
}

static void make_contact(sw42000_u8 *record, sw42000_u8 id,
			sw42000_u8 event, sw42000_u16 x, sw42000_u16 y,
			sw42000_u8 pressure, sw42000_u16 major,
			sw42000_u16 minor)
{
	sw42000_u32 word0 = id | (1U << 5) | (0x21U << 8) |
			    ((sw42000_u32)event << 16) | ((sw42000_u32)x << 18);
	sw42000_u32 word1 = y | ((sw42000_u32)pressure << 14);
	sw42000_u32 word2 = ((sw42000_u32)major << 4) |
			    ((sw42000_u32)minor << 18);

	put_le32(record, word0);
	put_le32(record + 4, word1);
	put_le32(record + 8, word2);
}

static void test_contact_decode(void)
{
	sw42000_u8 report[SW42000_REPORT_SIZE] = { 0 };
	struct sw42000_frame frame;
	int ret;

	make_header(report, 2, 0, 5);
	make_contact(report + 12, 3, SW42000_EVENT_DOWN,
		     0x1234, 0x2abc, 218, 0x2abc, 0x1234);
	make_contact(report + 24, 9, SW42000_EVENT_MOVE,
		     1439, 3119, 255, 3119, 3000);

	ret = sw42000_parse_report(report, sizeof(report), &frame);
	CHECK(ret == SW42000_PARSE_OK);
	CHECK(frame.count == 2);
	CHECK(frame.contacts[0].id == 3);
	CHECK(frame.contacts[0].event == SW42000_EVENT_DOWN);
	CHECK(frame.contacts[0].x == 0x1234);
	CHECK(frame.contacts[0].y == 0x2abc);
	CHECK(frame.contacts[0].pressure == 218);
	CHECK(frame.contacts[0].major == 0x2abc);
	CHECK(frame.contacts[0].minor == 0x1234);
	CHECK(frame.contacts[1].id == 9);
	CHECK(frame.contacts[1].x == 1439);
	CHECK(frame.contacts[1].y == 3119);
	CHECK(frame.contacts[1].pressure == 255);
}

static void test_release_semantics(void)
{
	sw42000_u8 report[SW42000_REPORT_SIZE] = { 0 };
	struct sw42000_frame frame;

	make_header(report, 1, 0, 5);
	make_contact(report + 12, 3, SW42000_EVENT_UP, 10, 20, 0, 0, 0);
	CHECK(sw42000_parse_report(report, sizeof(report), &frame) ==
	      SW42000_PARSE_OK);
	CHECK(frame.count == 0);

	make_header(report, 0, 0, 5);
	CHECK(sw42000_parse_report(report, sizeof(report), &frame) ==
	      SW42000_PARSE_INVALID);
	CHECK(frame.count == 0);
}

static void test_rejects_bad_frames(void)
{
	sw42000_u8 report[SW42000_REPORT_SIZE] = { 0 };
	struct sw42000_frame frame;

	make_header(report, 1, 0, 5);
	make_contact(report + 12, 1, SW42000_EVENT_DOWN, 1, 1, 1, 1, 1);
	CHECK(sw42000_parse_report(report, sizeof(report) - 1, &frame) ==
	      SW42000_PARSE_INVALID);

	make_header(report, 11, 0, 5);
	CHECK(sw42000_parse_report(report, sizeof(report), &frame) ==
	      SW42000_PARSE_INVALID);

	make_header(report, 2, 0, 5);
	make_contact(report + 12, 2, SW42000_EVENT_DOWN, 1, 1, 1, 1, 1);
	make_contact(report + 24, 2, SW42000_EVENT_MOVE, 2, 2, 2, 2, 2);
	CHECK(sw42000_parse_report(report, sizeof(report), &frame) ==
	      SW42000_PARSE_INVALID);
}

static void test_ignores_non_touch_reports(void)
{
	sw42000_u8 report[SW42000_REPORT_SIZE] = { 0 };
	struct sw42000_frame frame;

	make_header(report, 1, 0, 2);
	CHECK(sw42000_parse_report(report, sizeof(report), &frame) ==
	      SW42000_PARSE_IGNORE);

	make_header(report, 1, 1, 5);
	CHECK(sw42000_parse_report(report, sizeof(report), &frame) ==
	      SW42000_PARSE_IGNORE);
}

static void test_palm_cancels_contacts(void)
{
	sw42000_u8 report[SW42000_REPORT_SIZE] = { 0 };
	struct sw42000_frame frame;

	make_header(report, 1, 0, 5);
	make_contact(report + 12, 15, SW42000_EVENT_DOWN, 500, 600, 255, 0, 0);
	CHECK(sw42000_parse_report(report, sizeof(report), &frame) ==
	      SW42000_PARSE_OK);
	CHECK(frame.palm == 1);
	CHECK(frame.count == 0);
}

int main(void)
{
	test_contact_decode();
	test_release_semantics();
	test_rejects_bad_frames();
	test_ignores_non_touch_reports();
	test_palm_cancels_contacts();

	if (failures)
		return 1;

	puts("SW42000 parser checks passed");
	return 0;
}
