// SPDX-License-Identifier: GPL-2.0-only
/* Host-only shell-supervisor test: no tty, real fork, USB, or PID 1. */
#define fork fake_fork
#define waitpid fake_waitpid
#define alarm fake_alarm
#define nanosleep fake_nanosleep
#define main supervisor_unused_main
#include "supervisor.c"
#undef main
#include <assert.h>

static int forks, waits, sleeps, alarms, fail_at, interrupt_wait, interrupt_sleep;
pid_t fake_fork(void)
{
    forks++;
    if (forks == fail_at) { errno = EAGAIN; return -1; }
    return 42;
}
pid_t fake_waitpid(pid_t pid, int *status, int flags)
{
    assert(pid == 42 && flags == 0);
    if (interrupt_wait) { interrupt_wait = 0; errno = EINTR; return -1; }
    waits++;
    *status = 0;
    return pid;
}
unsigned int fake_alarm(unsigned int seconds)
{
    assert(seconds == 0);
    alarms++;
    return 0;
}
int fake_nanosleep(const struct timespec *request, struct timespec *remaining)
{
    assert(request->tv_sec == 1 && request->tv_nsec == 0);
    if (interrupt_sleep) {
        interrupt_sleep = 0;
        *remaining = *request;
        errno = EINTR;
        return -1;
    }
    sleeps++;
    return 0;
}
int main(void)
{
    fail_at = 4;
    interrupt_wait = interrupt_sleep = 1;
    usb_shell_session();
    assert(forks == 4 && waits == 3 && sleeps == 3 && alarms == 1);
    forks = waits = sleeps = alarms = 0;
    fail_at = 0;
    usb_shell_session();
    assert(forks == 90 && waits == 90 && sleeps == 90 && alarms == 1);
    puts("shell restart, backoff, interruption, fork failure and retry cap passed");
    return 0;
}
