/* SPDX-License-Identifier: GPL-2.0-only */
/* Own controller only: list, power on, read version/settings, power off. */
#define _GNU_SOURCE
#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static uint16_t get16(const unsigned char *p)
{
	return p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t get32(const unsigned char *p)
{
	return get16(p) | ((uint32_t)get16(p + 2) << 16);
}

static long milliseconds(void)
{
	struct timespec now;
	if (clock_gettime(CLOCK_MONOTONIC, &now))
		return -1;
	return now.tv_sec * 1000L + now.tv_nsec / 1000000;
}

static int complete_reply(const unsigned char *p, size_t n,
			 unsigned int opcode, unsigned int index)
{
	if (n < 6 || get16(p + 4) != n - 6)
		return -EPROTO;
	if ((get16(p) != 1 && get16(p) != 2) || get16(p + 2) != index)
		return -EAGAIN;
	if (n < 9)
		return -EPROTO;
	if (get16(p + 6) != opcode)
		return -EAGAIN;
	if (p[8])
		return -EIO;
	return get16(p) == 1 ? (int)n - 9 : -EAGAIN;
}

static int exchange(int fd, unsigned int opcode, unsigned int index,
		    int value, unsigned char reply[512])
{
	unsigned char request[7] = {opcode, opcode >> 8, index, index >> 8,
		value >= 0, 0, value >= 0 ? value : 0};
	struct pollfd ready = {.fd = fd, .events = POLLIN};
	size_t request_size = value >= 0 ? 7 : 6;
	long end = milliseconds() + 15000;

	if (send(fd, request, request_size, 0) != (ssize_t)request_size)
		return -errno;
	while (milliseconds() < end) {
		ssize_t n;
		int ret;

		if (poll(&ready, 1, 100) <= 0)
			continue;
		n = recv(fd, reply, 512, MSG_TRUNC);
		if (n < 0 || n > 512)
			return -EMSGSIZE;
		ret = complete_reply(reply, n, opcode, index);
		if (ret != -EAGAIN)
			return ret;
	}
	return -ETIMEDOUT;
}

int main(void)
{
	struct { sa_family_t family; uint16_t device, channel; } address = {
		.family = AF_BLUETOOTH, .device = 0xffff, .channel = 3};
	unsigned char reply[512];
	unsigned int count, index, version, manufacturer, settings;
	int fd = socket(AF_BLUETOOTH, SOCK_RAW | SOCK_CLOEXEC, 1), n, ret = 1;

	if (fd < 0 || bind(fd, (struct sockaddr *)&address, sizeof(address))) {
		perror("Bluetooth management socket");
		return 10;
	}
	n = exchange(fd, 3, 0xffff, -1, reply);
	if (n < 2 || n != 2 + 2 * get16(reply + 9))
		goto done;
	count = get16(reply + 9);
	printf("BT_CONTROLLER_COUNT %u\n", count);
	if (count != 1)
		goto done;
	index = get16(reply + 11);
	printf("BT_INDEX %u\n", index);
	n = exchange(fd, 5, index, 1, reply);
	if (n != 4 || !(get32(reply + 9) & 1))
		goto poweroff;
	n = exchange(fd, 4, index, -1, reply);
	/* Kernel mgmt_rp_read_info is exactly 280 bytes. Omit address/names. */
	if (n != 280)
		goto poweroff;
	version = reply[9 + 6];
	manufacturer = get16(reply + 9 + 7);
	settings = get32(reply + 9 + 13);
	if (!(settings & 1))
		goto poweroff;
	printf("BT_VERSION %u\nBT_MANUFACTURER %u\nBT_POWERED 1\n",
	       version, manufacturer);
	ret = 0;
poweroff:
	n = exchange(fd, 5, index, 0, reply);
	if (n != 4 || (get32(reply + 9) & 1))
		ret = 1;
	else
		puts("BT_POWERED_OFF 1");
done:
	if (ret)
		printf("BT_MGMT_FAILURE %d\n", n);
	close(fd);
	return ret;
}
