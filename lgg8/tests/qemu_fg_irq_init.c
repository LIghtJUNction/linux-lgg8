// SPDX-License-Identifier: GPL-2.0-only
/* QEMU-only init: verify a simulated FG IRQ reaches a real power-supply uevent. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/netlink.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define BASE "/sys/kernel/lgg8-fg-irqtest/"
#define TEST_NAME "POWER_SUPPLY_NAME=lgg8-fg-irq-test"
#define TEST_DEVPATH "DEVPATH=/devices/lgg8-fg-irq-fixture/power_supply/lgg8-fg-irq-test"

static void fail(const char *what)
{
	printf("LGG8_QEMU_IRQ: FAIL %s errno=%d\n", what, errno);
	fflush(stdout);
	reboot(RB_POWER_OFF);
	_exit(1);
}

static void mount_or_fail(const char *source, const char *target, const char *type)
{
	if (mount(source, target, type, 0, NULL) && errno != EBUSY)
		fail(target);
}

static void write_attr(const char *name, const char *value)
{
	char path[256];
	int fd;
	size_t size = strlen(value);

	if (snprintf(path, sizeof(path), BASE "%s", name) >= (int)sizeof(path))
		fail("attribute path too long");
	fd = open(path, O_WRONLY | O_CLOEXEC);
	if (fd < 0)
		fail(path);
	if (write(fd, value, size) != (ssize_t)size)
		fail("attribute write");
	if (close(fd))
		fail("attribute close");
}

static unsigned int read_count(const char *attribute)
{
	char path[256];
	char value[32];
	unsigned long count;
	char *end;
	int fd;
	ssize_t n;

	if (snprintf(path, sizeof(path), BASE "%s", attribute) >= (int)sizeof(path))
		fail("counter path too long");
	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		fail("counter open");
	n = read(fd, value, sizeof(value) - 1);
	if (n <= 0)
		fail("counter read");
	value[n] = '\0';
	errno = 0;
	count = strtoul(value, &end, 10);
	if (errno || end == value || (*end != '\n' && *end != '\0') ||
	    count > UINT_MAX || close(fd))
		fail("counter parse");
	return (unsigned int)count;
}

static void wait_count(const char *attribute, unsigned int expected)
{
	struct timespec pause = { .tv_nsec = 10000000 };

	for (int i = 0; i < 300; i++) {
		if (read_count(attribute) >= expected)
			return;
		nanosleep(&pause, NULL);
	}
	fail("counter did not advance");
}

/* 0: unrelated; 1: present with measurements; 2: absent; -1: malformed. */
static int target_event(const char *data, ssize_t len)
{
	bool action = false, subsystem = false, name = false, devpath = false;
	bool voltage = false, current = false, capacity = false;
	bool any_measurement = false;
	int present = -1;

	for (ssize_t pos = 0; pos < len;) {
		size_t remaining = (size_t)(len - pos);
		size_t size = strnlen(data + pos, remaining);

		if (size == remaining)
			return -1;
		if (!strcmp(data + pos, "ACTION=change"))
			action = true;
		if (!strcmp(data + pos, "SUBSYSTEM=power_supply"))
			subsystem = true;
		if (!strcmp(data + pos, TEST_NAME))
			name = true;
		if (!strcmp(data + pos, TEST_DEVPATH))
			devpath = true;
		if (!strcmp(data + pos, "POWER_SUPPLY_PRESENT=1"))
			present = 1;
		if (!strcmp(data + pos, "POWER_SUPPLY_PRESENT=0"))
			present = 0;
		if (!strncmp(data + pos, "POWER_SUPPLY_VOLTAGE_NOW=", 25) ||
		    !strncmp(data + pos, "POWER_SUPPLY_CURRENT_NOW=", 25) ||
		    !strncmp(data + pos, "POWER_SUPPLY_CAPACITY=", 22))
			any_measurement = true;
		if (!strcmp(data + pos, "POWER_SUPPLY_VOLTAGE_NOW=3999989"))
			voltage = true;
		if (!strcmp(data + pos, "POWER_SUPPLY_CURRENT_NOW=499999"))
			current = true;
		if (!strcmp(data + pos, "POWER_SUPPLY_CAPACITY=50"))
			capacity = true;
		pos += (ssize_t)size + 1;
	}
	if (!name && !devpath)
		return 0;
	if (!action || !subsystem || !name || !devpath)
		return -1;
	if (present == 1 && voltage && current && capacity)
		return 1;
	if (present == 0 && !any_measurement)
		return 2;
	return -1;
}

static int wait_event(int fd, int timeout_ms)
{
	struct timespec start, now;
	char data[8192];

	if (clock_gettime(CLOCK_MONOTONIC, &start))
		fail("clock");
	for (;;) {
		struct pollfd pfd = { .fd = fd, .events = POLLIN };
		long elapsed;
		int ret;

		if (clock_gettime(CLOCK_MONOTONIC, &now))
			fail("clock");
		elapsed = (now.tv_sec - start.tv_sec) * 1000 +
			  (now.tv_nsec - start.tv_nsec) / 1000000;
		if (elapsed >= timeout_ms)
			return 0;
		ret = poll(&pfd, 1, timeout_ms - (int)elapsed);
		if (ret < 0 && errno == EINTR)
			continue;
		if (ret < 0 || (ret && !(pfd.revents & POLLIN)))
			fail("uevent poll");
		if (ret) {
			struct sockaddr_nl sender = {};
			struct iovec iov = { .iov_base = data, .iov_len = sizeof(data) };
			struct msghdr msg = { .msg_name = &sender, .msg_namelen = sizeof(sender),
					      .msg_iov = &iov, .msg_iovlen = 1 };
			ssize_t n = recvmsg(fd, &msg, 0);

			if (n < 0 && errno == EINTR)
				continue;
			if (n <= 0)
				fail("uevent receive");
			if ((msg.msg_flags & MSG_TRUNC) || msg.msg_namelen != sizeof(sender) ||
			    sender.nl_family != AF_NETLINK || sender.nl_pid != 0)
				fail("uevent sender or truncation");
			ret = target_event(data, n);
			if (ret)
				return ret;
		}
	}
}

int main(void)
{
	struct sockaddr_nl addr = { .nl_family = AF_NETLINK, .nl_groups = 1 };
	char cmdline[512];
	bool expect_reject;
	int module_fd, sock, fd, rc;
	ssize_t n;

	setvbuf(stdout, NULL, _IONBF, 0);
	mount_or_fail("proc", "/proc", "proc");
	mount_or_fail("sysfs", "/sys", "sysfs");
	mount_or_fail("devtmpfs", "/dev", "devtmpfs");
	fd = open("/proc/cmdline", O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		fail("cmdline open");
	n = read(fd, cmdline, sizeof(cmdline) - 1);
	if (n < 0 || close(fd))
		fail("cmdline read");
	cmdline[n] = '\0';
	expect_reject = strstr(cmdline, "lgg8.expect_reject=1") != NULL;
	module_fd = open("/fg_irq_fixture.ko", O_RDONLY | O_CLOEXEC);
	if (module_fd < 0)
		fail("module open");
	rc = syscall(SYS_finit_module, module_fd, "", 0);
	if (expect_reject) {
		if (rc != -1 || errno != ENODEV)
			fail("non-virt module was not rejected");
		printf("LGG8_QEMU_IRQ: non-virt module rejection passed\n");
		close(module_fd);
		reboot(RB_POWER_OFF);
		fail("power off");
	}
	if (rc)
		fail("module load");
	if (close(module_fd))
		fail("module close");
	sock = socket(AF_NETLINK, SOCK_DGRAM | SOCK_CLOEXEC, NETLINK_KOBJECT_UEVENT);
	if (sock < 0 || bind(sock, (struct sockaddr *)&addr, sizeof(addr)))
		fail("uevent socket");
	write_attr("mode", "0\n");
	write_attr("trigger", "1\n");
	wait_count("handler_count", 1);
	if (wait_event(sock, 1000) != 0)
		fail("negative control emitted a power-supply event");
	printf("LGG8_QEMU_IRQ: negative control passed\n");
	write_attr("mode", "1\n");
	write_attr("trigger", "1\n");
	wait_count("handler_count", 2);
	if (wait_event(sock, 5000) != 1)
		fail("missing power-supply change uevent");
	printf("LGG8_QEMU_IRQ: IRQ -> FG callback -> power_supply uevent passed\n");
	write_attr("mode", "2\n");
	write_attr("trigger", "1\n");
	wait_count("handler_count", 3);
	if (wait_event(sock, 5000) != 2)
		fail("missing battery-absent event");
	printf("LGG8_QEMU_IRQ: battery-absent event passed\n");
	write_attr("mode", "3\n");
	write_attr("trigger", "1\n");
	wait_count("handler_count", 4);
	wait_count("io_error_count", 1);
	if (wait_event(sock, 1000) != 0)
		fail("unexpected uevent on injected read error");
	printf("LGG8_QEMU_IRQ: read error dropped uevent\n");
	write_attr("mode", "1\n");
	write_attr("trigger", "1\n");
	wait_count("handler_count", 5);
	if (wait_event(sock, 5000) != 1)
		fail("uevent did not recover after read error");
	printf("LGG8_QEMU_IRQ: recovery event passed\n");
	close(sock);
	if (syscall(SYS_delete_module, "lgg8_fg_irq_fixture", 0))
		fail("module unload");
	printf("LGG8_QEMU_IRQ: cleanup passed\n");
	reboot(RB_POWER_OFF);
	fail("power off");
}
