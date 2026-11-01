// SPDX-License-Identifier: GPL-2.0-only
/*
 * Preparation only: an intentionally destructive-to-uptime watchdog test.
 * Never run without the guarded RAM-only supervisor, USB monitor and recovery.
 * Open starts the watchdog, even before WDIOC_GETSUPPORT is called.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <linux/watchdog.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

struct probe_ops {
	int (*open_device)(void);
	int (*get_info)(int, struct watchdog_info *);
	int (*set_timeout)(int, int *);
	int (*wait_seconds)(int);
	ssize_t (*magic_close)(int);
	int (*close_device)(int);
};

static int do_probe(const struct probe_ops *ops)
{
	struct watchdog_info info = {0};
	int fd, seconds = 10, ret = 1;

	fd = ops->open_device();
	if (fd < 0) {
		puts("OPEN_FAILED");
		return 1;
	}
	/* From this point, all exits attempt magic close, even on ioctl failure.
	 * That is only an attempt: failure or nowayout may leave it running.
	 */
	if (ops->get_info(fd, &info) ||
	    strncmp((const char *)info.identity, "qcom_wdt", sizeof(info.identity)) ||
	    (info.options & (WDIOF_SETTIMEOUT | WDIOF_MAGICCLOSE)) !=
		(WDIOF_SETTIMEOUT | WDIOF_MAGICCLOSE)) {
		puts("IDENTITY_OR_CAPABILITY_MISMATCH");
		goto out;
	}
	if (ops->set_timeout(fd, &seconds) || seconds < 5 || seconds > 20) {
		puts("TIMEOUT_UNSUPPORTED");
		goto out;
	}
	printf("ARMED timeout_seconds=%d\n", seconds);
	fflush(stdout);
	if (ops->wait_seconds(seconds + 10)) {
		puts("WAIT_FAILED");
		goto out;
	}
	/* Reaching this line means this test did not observe a timely reset. */
	puts("NO_RESET_OBSERVED");
	ret = 2;
out:
	if (ops->magic_close(fd) != 1) {
		puts("MAGIC_CLOSE_WRITE_FAILED_WATCHDOG_MAY_STILL_RUN");
		ret = 1;
	}
	if (ops->close_device(fd)) {
		puts("CLOSE_FAILED_WATCHDOG_MAY_STILL_RUN");
		ret = 1;
	}
	return ret;
}

#ifndef QCOM_WATCHDOG_PROBE_TEST
static int open_device(void) { return open("/dev/watchdog0", O_WRONLY | O_CLOEXEC); }
static int get_info(int fd, struct watchdog_info *info) { return ioctl(fd, WDIOC_GETSUPPORT, info); }
static int set_timeout(int fd, int *seconds) { return ioctl(fd, WDIOC_SETTIMEOUT, seconds); }
static int wait_seconds(int seconds)
{
	struct timespec end;
	int ret;

	if (clock_gettime(CLOCK_MONOTONIC, &end))
		return -1;
	end.tv_sec += seconds;
	do {
		ret = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &end, NULL);
	} while (ret == EINTR);
	return ret;
}
static ssize_t magic_close(int fd) { return write(fd, "V", 1); }
static int close_device(int fd) { return close(fd); }

int main(int argc, char **argv)
{
	static const struct probe_ops ops = {
		open_device, get_info, set_timeout, wait_seconds, magic_close, close_device,
	};

	if (argc != 2 || strcmp(argv[1], "--arm-and-expect-reset")) {
		fprintf(stderr, "Refusing: this test arms a watchdog and expects a device reset.\n");
		return 64;
	}
	setvbuf(stdout, NULL, _IONBF, 0);
	return do_probe(&ops);
}
#endif
