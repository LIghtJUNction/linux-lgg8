// SPDX-License-Identifier: GPL-2.0-only
/* Bounded read-only evdev observer; not a suspend or hardware safety test. */
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

struct contact { int x, y; bool x_seen, y_seen, down; };
struct sample { struct contact slots[32]; int slot, x, y; bool pending, complete, dropped; };

static void feed(struct sample *s, const struct input_event *e)
{
	struct contact *c;

	if (e->type == EV_SYN && e->code == SYN_DROPPED) { s->dropped = true; return; }
	if (e->type == EV_SYN && e->code == SYN_REPORT) { s->complete |= s->pending; s->pending = false; return; }
	if (e->type != EV_ABS) return;
	if (e->code == ABS_MT_SLOT) {
		if (e->value < 0 || e->value >= 32) { s->dropped = true; return; }
		s->slot = e->value;
		return;
	}
	c = &s->slots[s->slot];
	switch (e->code) {
	case ABS_MT_TRACKING_ID:
		if (e->value >= 0) { *c = (struct contact){ .down = true }; }
		else if (c->down) {
			if (c->x_seen && c->y_seen) { s->x = c->x; s->y = c->y; s->pending = true; }
			c->down = false;
		}
		break;
	case ABS_MT_POSITION_X: if (c->down) { c->x = e->value; c->x_seen = true; } break;
	case ABS_MT_POSITION_Y: if (c->down) { c->y = e->value; c->y_seen = true; } break;
	}
}

static int selftest(void)
{
	struct sample s = {0};
	struct input_event e = { .type = EV_ABS, .code = ABS_MT_TRACKING_ID, .value = 3 };
	feed(&s, &e);
	e.code = ABS_MT_POSITION_X; e.value = 50; feed(&s, &e);
	e.code = ABS_MT_POSITION_Y; e.value = 90; feed(&s, &e);
	e.code = ABS_MT_TRACKING_ID; e.value = -1; feed(&s, &e);
	if (s.complete || !s.pending) return 1;
	e.type = EV_SYN; e.code = SYN_REPORT; feed(&s, &e);
	if (!s.complete || s.x != 50 || s.y != 90) return 1;
	/* A stale coordinate from a previous contact must not validate the next. */
	s = (struct sample){0};
	e.type = EV_ABS; e.code = ABS_MT_POSITION_X; e.value = 50; feed(&s, &e);
	e.code = ABS_MT_TRACKING_ID; e.value = 4; feed(&s, &e);
	e.code = ABS_MT_POSITION_Y; e.value = 90; feed(&s, &e);
	e.code = ABS_MT_TRACKING_ID; e.value = -1; feed(&s, &e);
	if (s.complete || s.pending) return 1;
	/* Coordinates and releases from another slot must not form a contact. */
	s = (struct sample){0};
	e.code = ABS_MT_TRACKING_ID; e.value = 1; feed(&s, &e);
	e.code = ABS_MT_SLOT; e.value = 1; feed(&s, &e);
	e.code = ABS_MT_POSITION_X; e.value = 50; feed(&s, &e);
	e.code = ABS_MT_POSITION_Y; e.value = 90; feed(&s, &e);
	e.code = ABS_MT_TRACKING_ID; e.value = -1; feed(&s, &e);
	if (s.complete || s.pending) return 1;
	e.type = EV_SYN; e.code = SYN_DROPPED; feed(&s, &e);
	if (!s.dropped) return 1;
	s = (struct sample){0};
	e.type = EV_ABS; e.code = ABS_MT_SLOT; e.value = 32; feed(&s, &e);
	return !s.dropped;
}

int main(int argc, char **argv)
{
	struct input_absinfo x, y;
	struct sample s = {0};
	struct timespec start, now;
	char name[128] = {0};
	int fd;

	if (argc == 2 && !strcmp(argv[1], "--self-test"))
		return selftest();
	if (argc != 2 || strncmp(argv[1], "/dev/input/event", 16)) {
		fprintf(stderr, "usage: %s /dev/input/eventN\n", argv[0]);
		return 2;
	}
	fd = open(argv[1], O_RDONLY | O_NONBLOCK | O_CLOEXEC);
	if (fd < 0) { perror("open"); return 1; }
	if (ioctl(fd, EVIOCGNAME(sizeof(name)), name) < 0 ||
	    strcmp(name, "LG SW42000 Touchscreen") ||
	    ioctl(fd, EVIOCGABS(ABS_MT_POSITION_X), &x) < 0 ||
	    ioctl(fd, EVIOCGABS(ABS_MT_POSITION_Y), &y) < 0) {
		fprintf(stderr, "wrong device or missing MT axes\n"); close(fd); return 1;
	}
	printf("DEVICE %s X=%d..%d Y=%d..%d\n", name, x.minimum, x.maximum, y.minimum, y.maximum);
	puts("READY: tap and release within 20 seconds"); fflush(stdout);
	if (clock_gettime(CLOCK_MONOTONIC, &start)) { perror("clock_gettime"); close(fd); return 1; }
	for (;;) {
		struct pollfd p = { .fd = fd, .events = POLLIN };
		struct input_event events[32];
		int n = poll(&p, 1, 200);
		if (n < 0 && errno != EINTR) { perror("poll"); break; }
		if (n > 0 && p.revents & (POLLERR | POLLHUP | POLLNVAL)) break;
		if (n > 0 && p.revents & POLLIN) {
			ssize_t bytes = read(fd, events, sizeof(events));
			if (bytes < 0 && errno != EAGAIN && errno != EINTR) { perror("read"); break; }
			if (bytes == 0 || (bytes > 0 && bytes % (ssize_t)sizeof(events[0]))) break;
			for (ssize_t i = 0; i < bytes / (ssize_t)sizeof(events[0]); i++)
				feed(&s, &events[i]);
		}
		if (s.dropped) { fprintf(stderr, "SYN_DROPPED: invalid capture\n"); break; }
		if (s.complete) {
			if (s.x < x.minimum || s.x > x.maximum || s.y < y.minimum || s.y > y.maximum) {
				fprintf(stderr, "Coordinate outside reported range\n"); break;
			}
			printf("EVENTS contact release x=%d y=%d\n", s.x, s.y);
			close(fd); return 0;
		}
		if (clock_gettime(CLOCK_MONOTONIC, &now) || now.tv_sec - start.tv_sec >= 20) break;
	}
	fprintf(stderr, "No complete contact/position/release observed\n");
	close(fd); return 1;
}
