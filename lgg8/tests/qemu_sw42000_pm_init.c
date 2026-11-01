// SPDX-License-Identifier: GPL-2.0-only
/* PID 1 for the diskless QEMU test. No phone or host device is exposed. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define BASE "/sys/kernel/sw42000-pm-qemu/"

static void finish(const char *message)
{
	printf("SW42000_QEMU_GUEST: %s\n", message);
	fflush(stdout);
	reboot(RB_POWER_OFF);
	_exit(1);
}

static void fail(const char *message)
{
	printf("SW42000_QEMU_GUEST: FAIL %s errno=%d\n", message, errno);
	finish("failed");
}

static void write_file(const char *path, const char *value)
{
	int fd = open(path, O_WRONLY | O_CLOEXEC);
	size_t n = strlen(value);

	if (fd < 0 || write(fd, value, n) != (ssize_t)n || close(fd))
		fail(path);
}

static void read_bus_counts(int *stop, int *active)
{
	char buf[128];
	int fd = open(BASE "bus_counts", O_RDONLY | O_CLOEXEC);
	ssize_t n;

	if (fd < 0 || (n = read(fd, buf, sizeof(buf) - 1)) <= 0 || close(fd))
		fail("bus counts read");
	buf[n] = '\0';
	if (sscanf(buf, "%d %d", stop, active) != 2)
		fail("bus counts parse");
}

int main(void)
{
	char cmdline[4096], status[128];
	bool reject, negative, system_pm;
	int fd, ret, saved_errno, result = -EINPROGRESS, starts = 0, ends = 0;
	unsigned int cases = 0;
	ssize_t n;
	struct timespec pause = { .tv_nsec = 10000000 };

	setvbuf(stdout, NULL, _IONBF, 0);
	if (mount("proc", "/proc", "proc", 0, NULL) ||
	    mount("sysfs", "/sys", "sysfs", 0, NULL))
		fail("mount");
	fd = open("/proc/cmdline", O_RDONLY | O_CLOEXEC);
	if (fd < 0 || (n = read(fd, cmdline, sizeof(cmdline) - 1)) <= 0)
		fail("cmdline");
	cmdline[n] = '\0';
	close(fd);
	reject = strstr(cmdline, "sw42000.expect_reject=1") != NULL;
	negative = strstr(cmdline, "sw42000.negative=1") != NULL;
	system_pm = strstr(cmdline, "sw42000.system_pm=1") != NULL;
	/* Deterministic PM ordering, using the real kernel PM dispatcher. */
	write_file("/sys/power/pm_async", "0\n");
	fd = open("/sw42000_pm_fixture.ko", O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		fail("module open");
	ret = syscall(SYS_finit_module, fd, negative ? "skip_pm=1" : "", 0);
	saved_errno = errno;
	close(fd);
	if (reject) {
		if (!ret || saved_errno != ENODEV || access(BASE "status", F_OK) == 0)
			fail("non-virt guard");
		finish("non-virt rejection passed");
	}
	if (ret)
		fail("module load");
	if (system_pm) {
		int stop_before, active_before, stop_after, active_after;

		write_file("/sys/power/pm_test", "devices\n");
		for (int cycle = 0; cycle < 2; cycle++) {
			read_bus_counts(&stop_before, &active_before);
			write_file("/sys/power/state", "freeze\n");
			read_bus_counts(&stop_after, &active_after);
			printf("SW42000_QEMU_GUEST: system PM bus deltas cycle=%d stop=%d active=%d\n",
			       cycle, stop_after - stop_before, active_after - active_before);
			if (negative ? (stop_after != stop_before || active_after != active_before) :
			    (stop_after <= stop_before || active_after <= active_before))
				fail("system PM callback assertions");
		}
		if (syscall(SYS_delete_module, "sw42000_pm_fixture", O_NONBLOCK))
			fail("system PM module unload");
		finish(negative ? "system PM negative passed" : "system PM devices passed");
	}
	write_file(BASE "run", "1\n");
	for (int i = 0; i < 3000; i++) {
		fd = open(BASE "status", O_RDONLY | O_CLOEXEC);
		if (fd < 0 || (n = read(fd, status, sizeof(status) - 1)) <= 0)
			fail("status read");
		close(fd);
		status[n] = '\0';
		if (sscanf(status, "%d %u %d %d", &result, &cases, &starts, &ends) != 4)
			fail("status parse");
		if (result != -EINPROGRESS)
			break;
		nanosleep(&pause, NULL);
	}
	printf("SW42000_QEMU_GUEST: result=%d cases=%u starts=%d ends=%d\n",
	       result, cases, starts, ends);
	if (starts != ends || starts != (negative ? 1 : 7) ||
	    (negative ? (result != -EUCLEAN || cases != 0) : (result || cases != 127)))
		fail("PM assertions");
	if (syscall(SYS_delete_module, "sw42000_pm_fixture", O_NONBLOCK))
		fail("module unload");
	if (access(BASE "status", F_OK) == 0)
		fail("sysfs survived unload");
	finish(negative ? "missing-PM negative control passed" : "device PM integration passed");
	return 0;
}
