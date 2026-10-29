// SPDX-License-Identifier: GPL-2.0-only
/* Bounded diagnostic PID 1. All mounts are memory-backed pseudo-filesystems. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static int logfd = -1;

static void logline(const char *message)
{
	if (logfd >= 0)
		dprintf(logfd, "<6>LGG8-SOURCE-INIT: %s\n", message);
	dprintf(STDOUT_FILENO, "LGG8-SOURCE-INIT: %s\n", message);
}

static void sleep_until(time_t deadline)
{
	struct timespec target = { .tv_sec = deadline };
	while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &target, NULL) == EINTR)
		;
}

static void reset(void)
{
	int fd = open("/proc/sysrq-trigger", O_WRONLY | O_CLOEXEC);
	if (fd >= 0) {
		(void)write(fd, "b", 1);
		close(fd);
	}
	(void)reboot(RB_AUTOBOOT);
	for (;;)
		pause();
}

static void mount_view(const char *type, const char *path, unsigned long flags)
{
	char line[256];
	if (mount(type, path, type, flags, NULL) < 0) {
		snprintf(line, sizeof(line), "mount %s: %s", path, strerror(errno));
		logline(line);
	}
}

static void inspect(const char *path)
{
	DIR *dir = opendir(path);
	struct dirent *entry;
	char line[512];
	int count = 0;
	if (!dir) {
		snprintf(line, sizeof(line), "%s: %s", path, strerror(errno));
		logline(line);
		return;
	}
	while ((entry = readdir(dir))) {
		if (entry->d_name[0] == '.')
			continue;
		snprintf(line, sizeof(line), "%s/%s", path, entry->d_name);
		logline(line);
		count++;
	}
	closedir(dir);
	if (!count) {
		snprintf(line, sizeof(line), "%s: empty", path);
		logline(line);
	}
}

int main(void)
{
	struct timespec start;
	pid_t fallback;
	int fd;

	/* Host/QEMU verification may execute this binary without touching devices. */
	if (getpid() != 1)
		return 91;
	clock_gettime(CLOCK_MONOTONIC, &start);
	fallback = fork();
	if (fallback == 0) {
		sleep_until(start.tv_sec + 50);
		reset();
	}
	/* Nodes already exist in the CPIO; mark entry before potentially blocking I/O. */
	logfd = open("/dev/kmsg", O_WRONLY | O_CLOEXEC | O_NONBLOCK);
	logline("PID1 entry; before mounts and console open");
	mkdir("/proc", 0755);
	mkdir("/sys", 0755);
	mkdir("/dev", 0755);
	mount_view("proc", "/proc", MS_NOSUID | MS_NODEV | MS_NOEXEC);
	mount_view("sysfs", "/sys", MS_NOSUID | MS_NODEV | MS_NOEXEC);
	mount_view("devtmpfs", "/dev", MS_NOSUID);
	(void)mknod("/dev/console", S_IFCHR | 0600, makedev(5, 1));
	(void)mknod("/dev/kmsg", S_IFCHR | 0600, makedev(1, 11));
	fd = open("/dev/console", O_RDWR | O_CLOEXEC);
	if (fd >= 0) {
		dup2(fd, STDIN_FILENO);
		dup2(fd, STDOUT_FILENO);
		dup2(fd, STDERR_FILENO);
		if (fd > STDERR_FILENO)
			close(fd);
	}
	if (logfd < 0)
		logfd = open("/dev/kmsg", O_WRONLY | O_CLOEXEC | O_NONBLOCK);
	logline("PID1 reached; diagnostic initramfs; automatic reset after 45 seconds");
	if (fallback < 0)
		logline("fallback fork failed; primary reset timer remains active");
	for (int tick = 0; tick < 9; tick++) {
		inspect("/sys/class/udc");
		inspect("/sys/class/drm");
		inspect("/sys/class/graphics");
		while (waitpid(-1, NULL, WNOHANG) > 0)
			;
		sleep_until(start.tv_sec + (tick + 1) * 5);
	}
	logline("diagnostic deadline reached; rebooting");
	reset();
	return 0;
}
