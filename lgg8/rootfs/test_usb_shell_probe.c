/* SPDX-License-Identifier: GPL-2.0-only */
#define _DEFAULT_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

static long long monotonic_ms(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return -1;
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

int main(void)
{
    int fd = -1;
    for (unsigned i = 0; i < 180; ++i) {
        fd = open("/dev/ttyACM0", O_RDWR | O_NOCTTY | O_NONBLOCK);
        if (fd >= 0) break;
        if (errno != ENOENT && errno != ENODEV) break;
        usleep(100000);
    }
    if (fd < 0) {
        printf("HOST_SHELL_PROBE open_failed errno=%d\n", errno);
        return 1;
    }

    struct termios settings;
    if (tcgetattr(fd, &settings)) {
        printf("HOST_SHELL_PROBE tcgetattr_failed errno=%d\n", errno);
        close(fd);
        return 1;
    }
    cfmakeraw(&settings);
    settings.c_cflag |= CLOCAL | CREAD;
    settings.c_cc[VMIN] = 0;
    settings.c_cc[VTIME] = 1;
    if (tcsetattr(fd, TCSANOW, &settings)) {
        printf("HOST_SHELL_PROBE tcsetattr_failed errno=%d\n", errno);
        close(fd);
        return 1;
    }
    (void)tcflush(fd, TCIOFLUSH);

    static const char command[] = "echo LGG8_SHELL_ROUNDTRIP\n";
    size_t sent = 0;
    while (sent < sizeof(command) - 1) {
        ssize_t n = write(fd, command + sent, sizeof(command) - 1 - sent);
        if (n > 0) { sent += (size_t)n; continue; }
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            struct pollfd ready = {.fd = fd, .events = POLLOUT};
            (void)poll(&ready, 1, 500);
            continue;
        }
        printf("HOST_SHELL_PROBE write_failed errno=%d\n", errno);
        close(fd);
        return 1;
    }

    char received[2048];
    size_t used = 0;
    long long deadline = monotonic_ms() + 6000;
    while (monotonic_ms() < deadline && used < sizeof(received) - 1) {
        struct pollfd ready = {.fd = fd, .events = POLLIN};
        int remaining = (int)(deadline - monotonic_ms());
        int result = poll(&ready, 1, remaining > 250 ? 250 : remaining);
        if (result < 0 && errno == EINTR) continue;
        if (result < 0) break;
        if (!result) continue;
        ssize_t n = read(fd, received + used, sizeof(received) - used - 1);
        if (n > 0) {
            used += (size_t)n;
            received[used] = 0;
            if (strstr(received, "LGG8_SHELL_ROUNDTRIP")) {
                puts("HOST_SHELL_PROBE PASS byte_roundtrip=1");
                close(fd);
                return 0;
            }
        } else if (n < 0 && errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) {
            break;
        }
    }
    received[used] = 0;
    printf("HOST_SHELL_PROBE timeout received=%s\n", received);
    close(fd);
    return 1;
}
