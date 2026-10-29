/* SPDX-License-Identifier: GPL-2.0-only */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static int console_fd = -1, kmsg_fd = -1;
static void message(const char *fmt, ...)
{
    char line[1024];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(line, sizeof(line) - 2, fmt, ap);
    va_end(ap);
    if (n < 0) return;
    if (n > (int)sizeof(line) - 3) n = sizeof(line) - 3;
    line[n++] = '\n';
    if (console_fd >= 0) (void)write(console_fd, line, n);
    if (kmsg_fd >= 0) (void)write(kmsg_fd, line, n);
}
static void until(struct timespec deadline)
{
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL) == EINTR) {}
}
static void reset_now(void)
{
    /* Known diagnostic path first: normal reboot can block in shutdown. */
    int fd = open("/proc/sysrq-trigger", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd >= 0) { (void)write(fd, "b", 1); close(fd); }
    (void)reboot(RB_AUTOBOOT);
    for (;;) pause();
}
static void mount_ram(const char *type, const char *at, unsigned long flags, const char *options)
{
    (void)mkdir(at, 0755);
    if (mount(type, at, type, flags, options) && errno != EBUSY)
        message("LGG8_MOUNT path=%s errno=%d", at, errno);
}
static void mirror_kmsg(const char *path, const char *text, size_t length)
{
    /* /dev/console writes do not enter printk. Each nonblocking kmsg write
     * is one bounded record, including its prefix and newline. Long lines
     * are split; kernel rate limits/EAGAIN can still lose diagnostics. */
    if (kmsg_fd < 0) return;
    while (length) {
        char record[960];
        int prefix = snprintf(record, sizeof(record), "<6>lgg8 %s: ", path);
        if (prefix < 0 || prefix >= (int)sizeof(record) - 1) return;
        size_t amount = sizeof(record) - (size_t)prefix - 1;
        if (amount > length) amount = length;
        const char *newline = memchr(text, '\n', amount);
        if (newline) amount = (size_t)(newline - text);
        memcpy(record + prefix, text, amount);
        record[prefix + amount] = '\n';
        (void)write(kmsg_fd, record, (size_t)prefix + amount + 1);
        size_t consumed = amount + (newline != NULL);
        text += consumed;
        length -= consumed;
    }
}
static void forward_logs(void)
{
    static const char *paths[] = {"/run/desktop-events.log", "/run/weston.log",
        "/run/client.log", "/run/seatd.log", "/run/udev.log"};
    static off_t offsets[5];
    char buf[4096];
    for (unsigned i = 0; i < 5; ++i) {
        int fd = open(paths[i], O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) continue;
        ssize_t n;
        /* Bound work even if a child is writing continuously. */
        for (int chunks = 0; chunks < 16 && (n = pread(fd, buf, sizeof(buf), offsets[i])) > 0; ++chunks) {
            if (console_fd >= 0) (void)write(console_fd, buf, n);
            mirror_kmsg(paths[i], buf, (size_t)n);
            offsets[i] += n;
        }
        close(fd);
    }
}
int main(void)
{
    if (getpid() != 1) return 91;
    struct timespec start;
    if (clock_gettime(CLOCK_MONOTONIC, &start)) return 92;
    /* Fork independent 90-second recovery before mounts, console or other I/O. */
    pid_t guardian = fork();
    if (!guardian) {
        struct timespec deadline = start;
        deadline.tv_sec += 90;
        until(deadline);
        reset_now();
    }
    if (guardian < 0) reset_now();
    mount_ram("proc", "/proc", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL);
    mount_ram("sysfs", "/sys", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL);
    mount_ram("devtmpfs", "/dev", MS_NOSUID, "mode=0755");
    mount_ram("tmpfs", "/run", MS_NOSUID | MS_NODEV, "mode=0755,size=32m");
    (void)mkdir("/dev/pts", 0755);
    mount_ram("devpts", "/dev/pts", MS_NOSUID | MS_NOEXEC, "mode=0620,ptmxmode=0666");
    (void)chmod("/dev/ptmx", 0666);
    console_fd = open("/dev/console", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    kmsg_fd = open("/dev/kmsg", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    char cmdline[4096] = {0};
    int fd = open("/proc/cmdline", O_RDONLY | O_CLOEXEC);
    if (fd >= 0) { (void)read(fd, cmdline, sizeof(cmdline) - 1); close(fd); }
    const char *backend = "drm";
    int seconds = 0;
    char *save = NULL;
    for (char *arg = strtok_r(cmdline, " \n", &save); arg; arg = strtok_r(NULL, " \n", &save)) {
        if (!strcmp(arg, "lgg8.desktop_backend=headless")) backend = "headless";
        if (!strcmp(arg, "lgg8.desktop_timeout=20")) seconds = 20;
    }
    if (strcmp(backend, "headless")) seconds = 0;
    message("LGG8_SUPERVISOR pid=1 backend=%s recovery=90 test_timeout=%d", backend, seconds);
    pid_t guest = fork();
    if (!guest) {
        (void)setsid();
        int output = open("/run/desktop-events.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
        if (output >= 0) { (void)dup2(output, 1); (void)dup2(output, 2); close(output); }
        int input = open("/dev/null", O_RDONLY);
        if (input >= 0) { (void)dup2(input, 0); close(input); }
        char *env[] = {"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "HOME=/root", "LANG=C", "LC_ALL=C", NULL};
        char *args[] = {"/bin/sh", "/usr/local/bin/desktop-start", (char *)backend, NULL};
        execve(args[0], args, env);
        _exit(127);
    }
    if (guest < 0) message("LGG8_GUEST fork errno=%d", errno);
    for (;;) {
        int status;
        pid_t child;
        while ((child = waitpid(-1, &status, WNOHANG)) > 0)
            message("LGG8_REAP pid=%ld status=%d", (long)child, status);
        forward_logs();
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        if (seconds && now.tv_sec - start.tv_sec >= seconds) {
            message("LGG8_QEMU_TIMEOUT seconds=20");
            if (guest > 0) (void)kill(-guest, SIGTERM);
            forward_logs();
            reset_now();
        }
        struct timespec tick = {.tv_sec = 1};
        (void)nanosleep(&tick, NULL);
    }
}
