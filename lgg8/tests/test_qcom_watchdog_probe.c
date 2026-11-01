// SPDX-License-Identifier: GPL-2.0-only
#define QCOM_WATCHDOG_PROBE_TEST
#include "qcom_watchdog_probe.c"
#include <assert.h>

static int calls[6], scenario, reported_seconds;
static int f_open(void) { calls[0]++; return scenario == 1 ? -1 : 42; }
static int f_info(int fd, struct watchdog_info *info)
{
	assert(fd == 42); calls[1]++;
	if (scenario == 2) return -1;
	strcpy((char *)info->identity, scenario == 3 ? "other" : "qcom_wdt");
	info->options = scenario == 4 ? 0 : WDIOF_SETTIMEOUT | WDIOF_MAGICCLOSE;
	return 0;
}
static int f_timeout(int fd, int *seconds)
{
	assert(fd == 42 && *seconds == 10); calls[2]++;
	if (scenario == 5) return -1;
	if (scenario == 6) *seconds = 21;
	return 0;
}
static int f_wait(int seconds)
{
	calls[3]++; reported_seconds = seconds;
	return scenario == 7 ? -1 : 0;
}
static ssize_t f_magic(int fd) { assert(fd == 42); calls[4]++; return scenario == 8 ? -1 : 1; }
static int f_close(int fd) { assert(fd == 42); calls[5]++; return scenario == 9 ? -1 : 0; }

int main(void)
{
	const struct probe_ops ops = {f_open, f_info, f_timeout, f_wait, f_magic, f_close};

	for (scenario = 0; scenario <= 9; scenario++) {
		int result;
		memset(calls, 0, sizeof(calls)); reported_seconds = 0;
		result = do_probe(&ops);
		assert(calls[0] == 1);
		if (scenario == 1) {
			assert(result == 1 && calls[1] == 0 && calls[4] == 0 && calls[5] == 0);
			continue;
		}
		assert(calls[1] == 1 && calls[4] == 1 && calls[5] == 1);
		assert(calls[2] == (scenario >= 2 && scenario <= 4 ? 0 : 1));
		assert(calls[3] == (scenario == 0 || scenario >= 7 ? 1 : 0));
		if (calls[3]) assert(reported_seconds == 20);
		assert(result == (scenario == 0 ? 2 : 1));
	}
	puts("watchdog probe fake scenarios: 10 passed");
}
