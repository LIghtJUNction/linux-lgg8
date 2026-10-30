/* SPDX-License-Identifier: GPL-2.0-only */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/mman.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/vfs.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifndef LGG8_PMSG_PATH
#define LGG8_PMSG_PATH "/dev/pmsg0"
#endif
static int console_fd = -1, kmsg_fd = -1;
enum { PMSG_OFF, PMSG_PENDING, PMSG_OK, PMSG_SHORT, PMSG_ERROR, PMSG_FORMAT_ERROR };
struct pmsg_receipt {
    int open_state, open_errno;
    int write_state, write_errno, write_bytes, write_expected;
};
static struct pmsg_receipt *pmsg_result;
static int pmsg_spawn_errno;
static char pmsg_tag[25] = "NA";
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
static void pmsg_probe(struct pmsg_receipt *result)
{
    char record[128];
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    int length = snprintf(record, sizeof(record),
        "LGG8_USER_PMSG_PROBE tag=%s uptime_ns=%lld\n", pmsg_tag,
        (long long)now.tv_sec * 1000000000LL + now.tv_nsec);
    if (length <= 0 || length >= (int)sizeof(record)) {
        __atomic_store_n(&result->open_state, PMSG_FORMAT_ERROR, __ATOMIC_RELEASE);
        message("LGG8_USER_PMSG_PROBE format_failed");
        return;
    }
    __atomic_store_n(&result->open_state, PMSG_PENDING, __ATOMIC_RELEASE);
#ifdef LGG8_PMSG_TEST_HANG_OPEN
    for (;;) pause();
#endif
    int fd = open(LGG8_PMSG_PATH, O_WRONLY | O_CLOEXEC);
    if (fd < 0) {
        int error = errno;
        __atomic_store_n(&result->open_errno, error, __ATOMIC_RELAXED);
        __atomic_store_n(&result->open_state, PMSG_ERROR, __ATOMIC_RELEASE);
        message("LGG8_USER_PMSG_PROBE open_errno=%d", error);
        return;
    }
    __atomic_store_n(&result->write_expected, length, __ATOMIC_RELAXED);
    __atomic_store_n(&result->open_state, PMSG_OK, __ATOMIC_RELEASE);
    __atomic_store_n(&result->write_state, PMSG_PENDING, __ATOMIC_RELEASE);
#ifdef LGG8_PMSG_TEST_HANG_WRITE
    for (;;) pause();
#endif
#ifdef LGG8_PMSG_TEST_SHORT_WRITE
    ssize_t written = length / 2;
#else
    ssize_t written = write(fd, record, (size_t)length);
#endif
    int write_errno = written < 0 ? errno : 0;
    if (written < 0) {
        __atomic_store_n(&result->write_errno, write_errno, __ATOMIC_RELAXED);
        __atomic_store_n(&result->write_state, PMSG_ERROR, __ATOMIC_RELEASE);
        message("LGG8_USER_PMSG_PROBE write_errno=%d bytes=-1 expected=%d",
                write_errno, length);
    } else if (written != length) {
        __atomic_store_n(&result->write_bytes, (int)written, __ATOMIC_RELAXED);
        __atomic_store_n(&result->write_state, PMSG_SHORT, __ATOMIC_RELEASE);
        message("LGG8_USER_PMSG_PROBE short_write bytes=%zd expected=%d", written, length);
    } else {
        __atomic_store_n(&result->write_bytes, (int)written, __ATOMIC_RELAXED);
        __atomic_store_n(&result->write_state, PMSG_OK, __ATOMIC_RELEASE);
        message("LGG8_USER_PMSG_PROBE written bytes=%d", length);
    }
    close(fd);
}
static void start_pmsg_probe(void)
{
    pmsg_result = mmap(NULL, sizeof(*pmsg_result), PROT_READ | PROT_WRITE,
                       MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (pmsg_result == MAP_FAILED) {
        pmsg_result = NULL;
        pmsg_spawn_errno = errno;
        message("LGG8_USER_PMSG_PROBE state_errno=%d", pmsg_spawn_errno);
        return;
    }
    memset(pmsg_result, 0, sizeof(*pmsg_result));
    pid_t worker = fork();
    if (!worker) {
        pmsg_probe(pmsg_result);
        _exit(0);
    }
    if (worker < 0) {
        pmsg_spawn_errno = errno;
        message("LGG8_USER_PMSG_PROBE fork_errno=%d", pmsg_spawn_errno);
    } else {
        message("LGG8_USER_PMSG_PROBE worker=%ld", (long)worker);
    }
}
static void freeze_pmsg_receipt(char serial[126])
{
    if (!pmsg_result && !pmsg_spawn_errno) {
        snprintf(serial, 126, "LGG8" "-RAM");
        return;
    }
    int open_state = PMSG_OFF, open_errno = 0;
    int write_state = PMSG_OFF, write_errno = 0, bytes = 0, expected = 0;
    if (pmsg_result) {
        open_state = __atomic_load_n(&pmsg_result->open_state, __ATOMIC_ACQUIRE);
        open_errno = __atomic_load_n(&pmsg_result->open_errno, __ATOMIC_RELAXED);
        write_state = __atomic_load_n(&pmsg_result->write_state, __ATOMIC_ACQUIRE);
        write_errno = __atomic_load_n(&pmsg_result->write_errno, __ATOMIC_RELAXED);
        bytes = __atomic_load_n(&pmsg_result->write_bytes, __ATOMIC_RELAXED);
        expected = __atomic_load_n(&pmsg_result->write_expected, __ATOMIC_RELAXED);
    }
    if (pmsg_spawn_errno) {
        snprintf(serial, 126, "LGG8-RAM;T=%s;P=START-ERR-%d", pmsg_tag, pmsg_spawn_errno);
        return;
    }
    if (open_state == PMSG_OK && write_state == PMSG_OFF)
        write_state = PMSG_PENDING;
    const char *o = open_state == PMSG_OK ? "OK" :
                    open_state == PMSG_ERROR ? "ERR" :
                    open_state == PMSG_FORMAT_ERROR ? "FORMAT" :
                    open_state == PMSG_OFF ? "OFF" : "PEND";
    const char *w = write_state == PMSG_OK ? "OK" :
                    write_state == PMSG_SHORT ? "SHORT" :
                    write_state == PMSG_ERROR ? "ERR" :
                    write_state == PMSG_OFF ? "NA" : "PEND";
    if (write_state == PMSG_SHORT)
        snprintf(serial, 126, "LGG8-RAM;T=%s;O=%s;W=%s-%d/%d", pmsg_tag, o, w, bytes, expected);
    else if (write_state == PMSG_ERROR)
        snprintf(serial, 126, "LGG8-RAM;T=%s;O=%s;W=%s-%d", pmsg_tag, o, w, write_errno);
    else if (open_state == PMSG_ERROR)
        snprintf(serial, 126, "LGG8-RAM;T=%s;O=%s-%d;W=%s", pmsg_tag, o, open_errno, w);
    else if (open_state == PMSG_FORMAT_ERROR)
        snprintf(serial, 126, "LGG8-RAM;T=%s;O=FORMAT;W=NA", pmsg_tag);
    else
        snprintf(serial, 126, "LGG8-RAM;T=%s;O=%s;W=%s", pmsg_tag, o, w);
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
static int read_short(const char *path, char *buf, size_t size)
{
    int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = read(fd, buf, size - 1);
    int error = errno;
    close(fd);
    if (n <= 0) { errno = n < 0 ? error : EIO; return -1; }
    buf[n] = 0;
    while (n && (buf[n-1] == '\n' || buf[n-1] == '\r')) buf[--n] = 0;
    return 0;
}
static int exists_guest(const char *path, int socket_only)
{
    struct stat st;
    if (!stat(path, &st)) return !socket_only || S_ISSOCK(st.st_mode);
    return errno == ENOENT ? 0 : -1;
}
static int weston_live(void)
{
    char value[256], path[80], *end;
    if (read_short("/run/desktop-weston.pid", value, sizeof(value)))
        return errno == ENOENT ? 0 : -1;
    long pid = strtol(value, &end, 10);
    if (*end || pid <= 1 || pid > 4194304) return -1;
    snprintf(path, sizeof(path), "/proc/%ld/comm", pid);
    if (read_short(path, value, sizeof(value))) return errno == ENOENT ? 0 : -1;
    if (strcmp(value, "weston")) return 0;
    snprintf(path, sizeof(path), "/proc/%ld/stat", pid);
    if (read_short(path, value, sizeof(value))) return errno == ENOENT ? 0 : -1;
    end = strrchr(value, ')');
    if (!end || end[1] != ' ' || !end[2]) return -1;
    return end[2] != 'Z' && end[2] != 'X' && !kill((pid_t)pid, 0);
}
static int script_stage(void)
{
    char value[24], *end;
    if (read_short("/run/desktop-stage", value, sizeof(value))) return -1;
    long stage = strtol(value, &end, 10);
    return *end || stage < 1 || stage > 99 ? -1 : (int)stage;
}
static void drm_snapshot(int *cards, int *connected)
{
    *cards = *connected = 0;
    DIR *dir = opendir("/sys/class/drm");
    if (!dir) { *cards = *connected = -1; return; }
    struct dirent *entry;
    unsigned seen = 0;
    for (;;) {
        errno = 0; /* The loop body may change errno between directory reads. */
        entry = readdir(dir);
        if (!entry) {
            if (errno) *cards = *connected = -1;
            break;
        }
        if (++seen > 128) { *cards = *connected = -1; break; }
        const char *suffix = entry->d_name;
        if (strncmp(suffix, "card", 4)) continue;
        suffix += 4;
        if (*suffix < '0' || *suffix > '9') continue;
        while (*suffix >= '0' && *suffix <= '9') ++suffix;
        if (!*suffix) { ++*cards; continue; }
        if (*suffix == '-' && suffix[1]) {
            char path[512], state[32];
            snprintf(path, sizeof(path), "/sys/class/drm/%s/status", entry->d_name);
            if (read_short(path, state, sizeof(state))) *connected = -1;
            else if (*connected >= 0 && !strcmp(state, "connected")) ++*connected;
        }
    }
    closedir(dir);
}
static int beacon_mkdir(const char *path)
{
    if (!mkdir(path, 0755)) return 0;
    message("LGG8_BEACON mkdir path=%s errno=%d", path, errno);
    return -1;
}
static int beacon_write(const char *path, const char *value)
{
    int fd = open(path, O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) { message("LGG8_BEACON open path=%s errno=%d", path, errno); return -1; }
    size_t length = strlen(value);
    ssize_t n = write(fd, value, length);
    int error = n < 0 ? errno : EIO;
    close(fd);
    if (n == (ssize_t)length) return 0;
    message("LGG8_BEACON write path=%s errno=%d", path, error);
    return -1;
}
static void save_snapshot(const char *product, int udc_count)
{
    /* Publish a complete RAM file, including unknown UDC before enumeration. */
    const char *tmp = "/run/usb-beacon-snapshot.tmp";
    char text[256];
    int length = snprintf(text, sizeof(text), "%s\nUDC=%d\n", product, udc_count);
    int fd = open(tmp, O_WRONLY | O_CREAT | O_EXCL | O_NONBLOCK | O_CLOEXEC, 0600);
    if (fd < 0) { message("LGG8_BEACON snapshot_open errno=%d", errno); return; }
    ssize_t n = write(fd, text, (size_t)length);
    int error = n < 0 ? errno : EIO;
    if (close(fd) && n == length) { n = -1; error = errno; }
    if (n != length || rename(tmp, "/run/usb-beacon-snapshot")) {
        if (n == length) error = errno;
        (void)unlink(tmp);
        message("LGG8_BEACON snapshot_publish errno=%d", error);
    }
}
static const char *ram_fields[] = {"DRM", "CON", "FB0", "SEATSOCK", "WPROC", "ST", "UDC", "CAL0", "CAL15"};
static int ram_code(const char *field)
{
    char text[512];
    int failed = read_short("/run/usb-beacon-snapshot", text, sizeof(text));
    /* Calibration codes are fixed, independent of snapshot availability. */
    if (!strcmp(field, "CAL0")) return 0;
    if (!strcmp(field, "CAL15")) return 15;
    if (failed || strlen(text) == sizeof(text) - 1) return 16;
    char *save = NULL, *token = strtok_r(text, " \n", &save);
    if (!token || strcmp(token, "LGG8-RAM")) return 16;
    long selected = -1;
    for (unsigned i = 0; i < 7; ++i) {
        token = strtok_r(NULL, " \n", &save);
        if (!token) return 16;
        char *value = strchr(token, '=');
        if (!value) return 16;
        *value++ = 0;
        if (strcmp(token, ram_fields[i]) || !*value) return 16;
        char *end;
        errno = 0;
        long n = strtol(value, &end, 10);
        if (errno || *end) return 16;
        if (!strcmp(token, field)) selected = n;
    }
    if (strtok_r(NULL, " \n", &save)) return 16;
    if (!strcmp(field, "ST")) {
        if (selected >= 1 && selected <= 8) return (int)selected;
        if (selected >= 90 && selected <= 94) return (int)selected - 81;
        return 16;
    }
    return selected >= 0 && selected <= 15 ? (int)selected : 16;
}
static int reached(struct timespec now, struct timespec start, int seconds)
{
    return now.tv_sec > start.tv_sec + seconds ||
        (now.tv_sec == start.tv_sec + seconds && now.tv_nsec >= start.tv_nsec);
}
static void usb_beacon(const char *serial)
{
    /* This separate worker cannot stall desktop supervision. Alarm bounds
     * interruptible work; an uninterruptible UDC bind still needs guardian90. */
    alarm(3);
    int cards, connected;
    drm_snapshot(&cards, &connected);
    char product[126];
    snprintf(product, sizeof(product),
        "LGG8-RAM DRM=%d CON=%d FB0=%d SEATSOCK=%d WPROC=%d ST=%d",
        cards, connected, exists_guest("/sys/class/graphics/fb0", 0),
        exists_guest("/run/seatd.sock", 1), weston_live(), script_stage());
    message("LGG8_BEACON snapshot %s", product);
    save_snapshot(product, -1);
    DIR *dir = opendir("/sys/class/udc");
    if (!dir) { message("LGG8_BEACON no_udc errno=%d", errno); return; }
    struct dirent *entry;
    char udc[128] = {0};
    unsigned count = 0, seen = 0;
    for (;;) {
        errno = 0;
        entry = readdir(dir);
        if (!entry) {
            if (errno) {
                int error = errno;
                closedir(dir);
                save_snapshot(product, -1);
                message("LGG8_BEACON udc_readdir errno=%d", error);
                return;
            }
            break;
        }
        if (++seen > 64) {
            closedir(dir);
            save_snapshot(product, -1);
            message("LGG8_BEACON udc_scan_limit");
            return;
        }
        if (entry->d_name[0] == '.') continue;
        ++count;
        if (strlen(entry->d_name) >= sizeof(udc)) {
            closedir(dir);
            save_snapshot(product, -1);
            message("LGG8_BEACON udc_name_limit");
            return;
        }
        if (count == 1) strcpy(udc, entry->d_name);
    }
    closedir(dir);
    save_snapshot(product, (int)count); /* Before any configfs action or bind. */
    if (count != 1) { message("LGG8_BEACON skip udc_count=%u", count); return; }
    struct statfs fs;
    if (statfs("/sys/kernel/config", &fs)) {
        message("LGG8_BEACON configfs_stat errno=%d", errno); return;
    }
    if (fs.f_type != 0x62656570 && mount("configfs", "/sys/kernel/config", "configfs",
                                      MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL)) {
        message("LGG8_BEACON configfs_mount errno=%d", errno); return;
    }
    const char *base = "/sys/kernel/config/usb_gadget/lgg8-beacon";
    if (beacon_mkdir(base)) return; /* Never modify an existing gadget. */
    char path[256];
    const char *dirs[] = {"strings/0x409", "configs/c.1", "configs/c.1/strings/0x409", "functions/acm.usb0"};
    for (unsigned i = 0; i < sizeof(dirs)/sizeof(dirs[0]); ++i) {
        snprintf(path, sizeof(path), "%s/%s", base, dirs[i]);
        if (beacon_mkdir(path)) return;
    }
    const char *attrs[][2] = {{"idVendor", "0x18d1"}, {"idProduct", "0x4ee7"},
        {"strings/0x409/serialnumber", serial},
        {"strings/0x409/manufacturer", "LGG8 RAM diagnostic"},
        {"strings/0x409/product", product},
        {"configs/c.1/strings/0x409/configuration", "RAM descriptor beacon"},
        {"configs/c.1/MaxPower", "120"}};
    for (unsigned i = 0; i < sizeof(attrs)/sizeof(attrs[0]); ++i) {
        snprintf(path, sizeof(path), "%s/%s", base, attrs[i][0]);
        if (beacon_write(path, attrs[i][1])) return;
    }
    snprintf(path, sizeof(path), "%s/configs/c.1/acm.usb0", base);
    char function_path[256];
    snprintf(function_path, sizeof(function_path), "%s/functions/acm.usb0", base);
    if (symlink(function_path, path)) {
        message("LGG8_BEACON symlink path=%s errno=%d", path, errno); return;
    }
    snprintf(path, sizeof(path), "%s/UDC", base);
    message("LGG8_BEACON bind_once");
    if (!beacon_write(path, udc)) message("LGG8_BEACON bound %s", product);
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
    int seconds = 0, beacon = 0, beacon_attempted = 0, beacon_delay = 8, ram_sampled = 0;
    int pmsg_probe_requested = 0;
    const char *ram_field = NULL;
    char *save = NULL;
    for (char *arg = strtok_r(cmdline, " \n", &save); arg; arg = strtok_r(NULL, " \n", &save)) {
        if (!strcmp(arg, "lgg8.desktop_backend=headless")) backend = "headless";
        if (!strcmp(arg, "lgg8.desktop_timeout=20")) seconds = 20;
        if (!strncmp(arg, "lgg8.pmsg_tag=", 14)) {
            size_t n = strnlen(arg + 14, sizeof(pmsg_tag));
            if (n > 0 && n < sizeof(pmsg_tag)) {
                int valid = 1;
                for (size_t i = 0; i < n; ++i)
                    if (!((arg[14+i] >= 'a' && arg[14+i] <= 'z') ||
                          (arg[14+i] >= 'A' && arg[14+i] <= 'Z') ||
                          (arg[14+i] >= '0' && arg[14+i] <= '9') ||
                          arg[14+i] == '-' || arg[14+i] == '_')) valid = 0;
                if (valid) { memcpy(pmsg_tag, arg + 14, n); pmsg_tag[n] = 0; }
            }
        }
        if (!strcmp(arg, "lgg8.pmsg_probe=1")) pmsg_probe_requested = 1;
        if (!strncmp(arg, "lgg8.usb_beacon=", 16)) beacon = !strcmp(arg, "lgg8.usb_beacon=1");
        if (!strncmp(arg, "lgg8.usb_beacon_delay=", 22))
            beacon_delay = !strcmp(arg, "lgg8.usb_beacon_delay=12") ? 12 : 8;
        if (!strncmp(arg, "lgg8.ram_field=", 15)) {
            ram_field = NULL;
            for (unsigned i = 0; i < sizeof(ram_fields)/sizeof(ram_fields[0]); ++i)
                if (!strcmp(arg + 15, ram_fields[i])) ram_field = ram_fields[i];
        }
    }
    if (ram_field && (!beacon || seconds != 20)) {
        message("LGG8_RAM_FIELD disabled requires_usb_beacon_and_timeout20");
        ram_field = NULL;
    }
    if (pmsg_probe_requested) start_pmsg_probe();
    message("LGG8_SUPERVISOR pid=1 backend=%s recovery=90 test_timeout=%d usb_beacon=%d", backend, seconds, beacon);
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
        if (beacon && !beacon_attempted && reached(now, start, beacon_delay)) {
            beacon_attempted = 1;
            char serial[126];
            freeze_pmsg_receipt(serial);
            pid_t worker = fork();
            if (!worker) { usb_beacon(serial); _exit(0); }
            if (worker < 0) message("LGG8_BEACON fork errno=%d", errno);
            else message("LGG8_BEACON worker pid=%ld alarm=3", (long)worker);
        }
        if (ram_field && !ram_sampled && reached(now, start, 16)) {
            ram_sampled = 1;
            int code = ram_code(ram_field);
            seconds = 20 + 2 * code;
            message("LGG8_RAM_FIELD field=%s code=%d deadline=%d", ram_field, code, seconds);
        }
        if (seconds && reached(now, start, seconds)) {
            message("LGG8_DESKTOP_TIMEOUT seconds=%d backend=%s", seconds, backend);
            if (!strcmp(backend, "headless")) message("LGG8_QEMU_TIMEOUT seconds=%d", seconds);
            if (guest > 0) (void)kill(-guest, SIGTERM);
            forward_logs();
            reset_now();
        }
        struct timespec tick = {.tv_sec = 1};
        (void)nanosleep(&tick, NULL);
    }
}
