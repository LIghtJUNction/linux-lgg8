/* SPDX-License-Identifier: GPL-2.0-only */
/* Read-only QRTR queries: DMS revision, optionally UIM card presence. */
#define _GNU_SOURCE
#include <endian.h>
#include <errno.h>
#include <linux/qrtr.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static uint16_t le16(const unsigned char *p)
{
	return p[0] | ((uint16_t)p[1] << 8);
}

static int revision_reply(const unsigned char *p, size_t n, char *revision,
			  size_t capacity)
{
	int result_seen = 0, revision_seen = 0;
	size_t cursor = 7;

	if (n < 7 || p[0] != 2 || le16(p + 1) != 1 ||
	    le16(p + 3) != 0x23 || le16(p + 5) != n - 7)
		return -1;
	while (cursor < n) {
		unsigned int kind, size;

		if (n - cursor < 3)
			return -1;
		kind = p[cursor];
		size = le16(p + cursor + 1);
		cursor += 3;
		if (size > n - cursor)
			return -1;
		if (kind == 2) {
			if (result_seen++ || size != 4 || le16(p + cursor) ||
			    le16(p + cursor + 2))
				return -1;
		} else if (kind == 1) {
			if (revision_seen++ || !size || size >= capacity)
				return -1;
			for (unsigned int i = 0; i < size; i++)
				if (p[cursor + i] < 32 || p[cursor + i] > 126)
					return -1;
			memcpy(revision, p + cursor, size);
			revision[size] = 0;
		}
		cursor += size;
	}
	return result_seen == 1 && revision_seen == 1 ? 0 : -1;
}

static long milliseconds(void)
{
	struct timespec now;

	if (clock_gettime(CLOCK_MONOTONIC, &now))
		return -1;
	return now.tv_sec * 1000L + now.tv_nsec / 1000000;
}

static int card_status(const unsigned char *p, size_t n,
		       unsigned char states[8], unsigned int *count)
{
	size_t cursor = 9;

	if (n < cursor || p[8] > 8)
		return -1;
	*count = p[8];
	for (unsigned int card = 0; card < *count; card++) {
		unsigned int apps;

		if (n - cursor < 6 || p[cursor] > 2)
			return -1;
		states[card] = p[cursor];
		apps = p[cursor + 5];
		cursor += 6;
		for (unsigned int app = 0; app < apps; app++) {
			unsigned int aid;

			if (n - cursor < 7)
				return -1;
			aid = p[cursor + 6];
			cursor += 7;
			if (n - cursor < aid + 7)
				return -1;
			cursor += aid + 7;
		}
	}
	return cursor == n ? 0 : -1;
}

static int uim_reply(const unsigned char *p, size_t n,
		     unsigned char states[8], unsigned int *count)
{
	int result_seen = 0, status_seen = 0;
	size_t cursor = 7;

	if (n < 7 || p[0] != 2 || le16(p + 1) != 2 ||
	    le16(p + 3) != 0x2f || le16(p + 5) != n - 7)
		return -1;
	while (cursor < n) {
		unsigned int kind, size;

		if (n - cursor < 3)
			return -1;
		kind = p[cursor];
		size = le16(p + cursor + 1);
		cursor += 3;
		if (size > n - cursor)
			return -1;
		if (kind == 2) {
			if (result_seen++ || size != 4 || le16(p + cursor) ||
			    le16(p + cursor + 2))
				return -1;
		} else if (kind == 0x10) {
			if (status_seen++ || card_status(p + cursor, size, states, count))
				return -1;
		}
		cursor += size;
	}
	return result_seen == 1 && status_seen == 1 ? 0 : -1;
}

static int query_uim(int fd, const struct sockaddr_qrtr *uim)
{
	const unsigned char request[] = {0, 2, 0, 0x2f, 0, 0, 0};
	struct pollfd wait = {.fd = fd, .events = POLLIN};
	long end = milliseconds() + 1200;

	if (!uim->sq_family) {
		puts("UIM_NOT_FOUND");
		return 20;
	}
	if (sendto(fd, request, sizeof(request), 0,
		   (const struct sockaddr *)uim, sizeof(*uim)) != sizeof(request))
		return 21;
	while (milliseconds() < end) {
		unsigned char buffer[4096], states[8];
		struct sockaddr_qrtr from;
		socklen_t length = sizeof(from);
		unsigned int count;
		ssize_t received;

		if (poll(&wait, 1, 100) <= 0)
			continue;
		received = recvfrom(fd, buffer, sizeof(buffer), MSG_TRUNC,
				    (struct sockaddr *)&from, &length);
		if (received < 7 || (size_t)received > sizeof(buffer) ||
		    from.sq_node != uim->sq_node || from.sq_port != uim->sq_port ||
		    buffer[0] != 2 || le16(buffer + 1) != 2 || le16(buffer + 3) != 0x2f)
			continue;
		if (uim_reply(buffer, received, states, &count)) {
			puts("UIM_INVALID_REPLY");
			return 22;
		}
		printf("UIM_CARD_COUNT %u\n", count);
		for (unsigned int card = 0; card < count; card++)
			printf("UIM_CARD %u %u\n", card, states[card]);
		return 0;
	}
	puts("UIM_REPLY_TIMEOUT");
	return 23;
}

int main(int argc, char **argv)
{
	struct sockaddr_qrtr local = {0}, dms = {0}, uim = {0}, from;
	struct qrtr_ctrl_pkt lookup = {.cmd = htole32(QRTR_TYPE_NEW_LOOKUP)};
	struct pollfd wait;
	socklen_t length = sizeof(local);
	unsigned int services = 0;
	unsigned char buffer[2048];
	long end;
	int want_uim = argc == 2 && !strcmp(argv[1], "--uim-status");
	int fd;

	if (argc != 1 && !want_uim)
		return 2;
	fd = socket(AF_QIPCRTR, SOCK_DGRAM | SOCK_CLOEXEC, 0);

	if (fd < 0 || getsockname(fd, (struct sockaddr *)&local, &length)) {
		perror("qrtr socket");
		return 10;
	}
	local.sq_port = QRTR_PORT_CTRL;
	if (sendto(fd, &lookup, sizeof(lookup), 0,
		   (struct sockaddr *)&local, sizeof(local)) != sizeof(lookup)) {
		perror("qrtr lookup");
		return 11;
	}
	wait = (struct pollfd){.fd = fd, .events = POLLIN};
	end = milliseconds() + 1200;
	while (milliseconds() < end && services < 128) {
		struct qrtr_ctrl_pkt packet;
		ssize_t received;
		uint32_t service, instance, node, port;

		if (poll(&wait, 1, 100) <= 0)
			continue;
		length = sizeof(from);
		received = recvfrom(fd, &packet, sizeof(packet), MSG_TRUNC,
				    (struct sockaddr *)&from, &length);
		if (received != sizeof(packet) || from.sq_node != local.sq_node ||
		    from.sq_port != QRTR_PORT_CTRL ||
		    le32toh(packet.cmd) != QRTR_TYPE_NEW_SERVER)
			continue;
		service = le32toh(packet.server.service);
		instance = le32toh(packet.server.instance);
		node = le32toh(packet.server.node);
		port = le32toh(packet.server.port);
		if (!service && !instance && !node && !port)
			continue;
		printf("SERVICE %u %u %u %u\n", service, instance, node, port);
		services++;
		if (service == 2 && node != local.sq_node)
			dms = (struct sockaddr_qrtr){.sq_family = AF_QIPCRTR,
				.sq_node = node, .sq_port = port};
		if (service == 11 && node != local.sq_node)
			uim = (struct sockaddr_qrtr){.sq_family = AF_QIPCRTR,
				.sq_node = node, .sq_port = port};
	}
	printf("SERVICE_COUNT %u\n", services);
	if (!dms.sq_family) {
		puts("DMS_NOT_FOUND");
		close(fd);
		return 12;
	}
	/* QMI request header: type, transaction 1, Get Revision, zero TLV bytes. */
	const unsigned char request[] = {0, 1, 0, 0x23, 0, 0, 0};
	if (sendto(fd, request, sizeof(request), 0,
		   (struct sockaddr *)&dms, sizeof(dms)) != sizeof(request))
		return 13;
	end = milliseconds() + 1200;
	while (milliseconds() < end) {
		char revision[256];
		ssize_t received;

		if (poll(&wait, 1, 100) <= 0)
			continue;
		length = sizeof(from);
		received = recvfrom(fd, buffer, sizeof(buffer), MSG_TRUNC,
				    (struct sockaddr *)&from, &length);
		if (received < 0 || (size_t)received > sizeof(buffer) ||
		    from.sq_node != dms.sq_node || from.sq_port != dms.sq_port)
			continue;
		if (revision_reply(buffer, received, revision, sizeof(revision))) {
			puts("DMS_INVALID_REPLY");
			return 14;
		}
		printf("DMS_REVISION %s\n", revision);
		int ret = want_uim ? query_uim(fd, &uim) : 0;
		close(fd);
		return ret;
	}
	puts("DMS_REPLY_TIMEOUT");
	close(fd);
	return 15;
}
