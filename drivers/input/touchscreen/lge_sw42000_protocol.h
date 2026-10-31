/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LGE_SW42000_PROTOCOL_H
#define _LGE_SW42000_PROTOCOL_H

#ifdef __KERNEL__
#include <linux/types.h>
typedef u8 sw42000_u8;
typedef u16 sw42000_u16;
typedef u32 sw42000_u32;
#else
#include <stddef.h>
#include <stdint.h>
typedef uint8_t sw42000_u8;
typedef uint16_t sw42000_u16;
typedef uint32_t sw42000_u32;
#endif

#define SW42000_REPORT_SIZE 132
#define SW42000_REPORT_CONTACTS 10

#define SW42000_PARSE_OK 0
#define SW42000_PARSE_IGNORE 1
#define SW42000_PARSE_INVALID (-1)

#define SW42000_EVENT_DOWN 1
#define SW42000_EVENT_MOVE 2
#define SW42000_EVENT_UP 3

struct sw42000_contact {
	sw42000_u8 id;
	sw42000_u8 event;
	sw42000_u8 pressure;
	sw42000_u16 x;
	sw42000_u16 y;
	sw42000_u16 major;
	sw42000_u16 minor;
};

struct sw42000_frame {
	sw42000_u8 count;
	sw42000_u8 palm;
	struct sw42000_contact contacts[SW42000_REPORT_CONTACTS];
};

static inline sw42000_u32 sw42000_get_le32(const sw42000_u8 *p)
{
	return (sw42000_u32)p[0] | ((sw42000_u32)p[1] << 8) |
	       ((sw42000_u32)p[2] << 16) | ((sw42000_u32)p[3] << 24);
}

/* The vendor ABI is a little-endian, 132-byte structure with 12-byte records. */
static inline int sw42000_parse_report(const sw42000_u8 *buf, size_t len,
				       struct sw42000_frame *frame)
{
	sw42000_u32 tc_status, header;
	sw42000_u16 seen = 0;
	sw42000_u8 touch_count;
	unsigned int i;

	if (!buf || !frame || len != SW42000_REPORT_SIZE)
		return SW42000_PARSE_INVALID;

	frame->count = 0;
	frame->palm = 0;

	tc_status = sw42000_get_le32(buf + 4);
	if (((tc_status >> 16) & 0xf) != 5)
		return SW42000_PARSE_IGNORE;

	header = sw42000_get_le32(buf + 8);
	if ((header & 0xff) != 0) /* ABS_MODE */
		return SW42000_PARSE_IGNORE;

	touch_count = (header >> 8) & 0x1f;
	/* The controller's own driver rejects zero; it is not release-all. */
	if (!touch_count || touch_count > SW42000_REPORT_CONTACTS)
		return SW42000_PARSE_INVALID;

	for (i = 0; i < touch_count; i++) {
		const sw42000_u8 *record = buf + 12 + i * 12;
		sw42000_u32 word0 = sw42000_get_le32(record);
		sw42000_u32 word1 = sw42000_get_le32(record + 4);
		sw42000_u32 word2 = sw42000_get_le32(record + 8);
		struct sw42000_contact *contact;
		sw42000_u8 id = word0 & 0x1f;
		sw42000_u8 event = (word0 >> 16) & 0x3;

		if (id == 15) {
			frame->palm = 1;
			continue;
		}

		/* Match the vendor path: records outside its ten slots are skipped. */
		if (id >= SW42000_REPORT_CONTACTS ||
		    (event != SW42000_EVENT_DOWN && event != SW42000_EVENT_MOVE))
			continue;

		if (seen & (1U << id))
			return SW42000_PARSE_INVALID;
		seen |= 1U << id;

		contact = &frame->contacts[frame->count++];
		contact->id = id;
		contact->event = event;
		contact->x = (word0 >> 18) & 0x3fff;
		contact->y = word1 & 0x3fff;
		contact->pressure = (word1 >> 14) & 0xff;
		contact->major = (word2 >> 4) & 0x3fff;
		contact->minor = (word2 >> 18) & 0x3fff;
	}

	/* A palm packet cancels active contacts instead of reporting coordinates. */
	if (frame->palm)
		frame->count = 0;

	return SW42000_PARSE_OK;
}

#endif /* _LGE_SW42000_PROTOCOL_H */
