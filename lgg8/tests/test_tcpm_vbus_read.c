// SPDX-License-Identifier: GPL-2.0-only
/* Offline API boundaries. No kernel scheduling, physical IRQ or PMIC access. */
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef uint32_t u32;
#define BIT(n) (1U << (n))
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
/* STATES */
enum typec_cc_status { TYPEC_CC_OPEN, TYPEC_CC_RD, TYPEC_CC_RP_DEF };
enum { FAST_ROLE_SWAP, PD_MSG_NONE };
struct mutex {
	bool held;
};
struct kthread_work {
	int unused;
};
struct tcpc_dev {
	int (*get_vbus)(struct tcpc_dev *);
	int (*get_cc)(struct tcpc_dev *, enum typec_cc_status *,
		      enum typec_cc_status *);
	bool (*is_vbus_vsafe0v)(struct tcpc_dev *);
};
struct tcpm_port {
	struct tcpc_dev *tcpc;
	struct mutex lock;
	int pd_event_lock;
	struct kthread_work event_work;
	u32 pd_events;
	enum tcpm_state state, upcoming_state;
	bool init_pending, vbus_present, vbus_vsafe0v, vbus_never_low;
	bool vbus_source, vbus_charge;
	int vbus_control_error, queued_message;
	unsigned int init_status_attempts, vbus_reset_attempts;
	enum typec_cc_status cc1, cc2;
};
static int result, cc_result, logged_error;
static unsigned int reads, cc_reads, cc_events, on_events, off_events,
	safe_events;
static unsigned int safe_reads, error_logs, clean_logs, port_error_logs,
	hard_resets;
static unsigned int frs_starts, cases;
static bool safe_value, append_event;
static struct tcpm_port *current;
static void mutex_lock(struct mutex *m)
{
	assert(!m->held);
	m->held = true;
}
static void mutex_unlock(struct mutex *m)
{
	assert(m->held);
	m->held = false;
}
#define spin_lock(p) ((void)(p))
#define spin_unlock(p) ((void)(p))
static void log_note(const char *s)
{
	if (!strcmp(s, "port clean"))
		clean_logs++;
	if (!strcmp(s, "port triggering error recovery"))
		port_error_logs++;
}
static void log_error(const char *fmt, ...)
{
	va_list ap;
	assert(!strcmp(fmt, "Failed to read VBUS status: %d"));
	va_start(ap, fmt);
	logged_error = va_arg(ap, int);
	va_end(ap);
	error_logs++;
}
#define tcpm_log(p, fmt, ...) log_note(fmt)
#define tcpm_log_force(p, fmt, ...) log_error(fmt, ##__VA_ARGS__)
static void _tcpm_pd_vbus_on(struct tcpm_port *p)
{
	p->vbus_present = p->vbus_never_low = true;
	p->vbus_vsafe0v = false;
	on_events++;
}
static void _tcpm_pd_vbus_off(struct tcpm_port *p)
{
	p->vbus_present = false;
	off_events++;
}
static void _tcpm_pd_vbus_vsafe0v(struct tcpm_port *p)
{
	p->vbus_vsafe0v = true;
	safe_events++;
}
static void _tcpm_cc_change(struct tcpm_port *p, enum typec_cc_status a,
			    enum typec_cc_status b)
{
	p->cc1 = a;
	p->cc2 = b;
	cc_events++;
}
static void _tcpm_pd_hard_reset(struct tcpm_port *p)
{
	(void)p;
	hard_resets++;
}
static void tcpm_set_state(struct tcpm_port *p, enum tcpm_state s,
			   unsigned int delay)
{
	assert(!delay);
	p->state = s;
}
static int tcpm_ams_start(struct tcpm_port *p, int ams)
{
	(void)p;
	(void)ams;
	frs_starts++;
	return -EAGAIN;
}
static bool tcpm_port_is_source(struct tcpm_port *p)
{
	(void)p;
	return false;
}
static bool tcpm_port_is_debug_source(struct tcpm_port *p)
{
	(void)p;
	return false;
}
static bool tcpm_start_toggling(struct tcpm_port *p, enum typec_cc_status c)
{
	(void)p;
	(void)c;
	return false;
}
static enum typec_cc_status tcpm_rp_cc(struct tcpm_port *p)
{
	(void)p;
	return TYPEC_CC_RP_DEF;
}
static enum tcpm_state tcpm_default_state(struct tcpm_port *p)
{
	(void)p;
	return SNK_UNATTACHED;
}
/* PRODUCTION */
static int get_vbus(struct tcpc_dev *t)
{
	(void)t;
	reads++;
	return result;
}
static int get_cc(struct tcpc_dev *t, enum typec_cc_status *a,
		  enum typec_cc_status *b)
{
	(void)t;
	cc_reads++;
	*a = TYPEC_CC_RD;
	*b = TYPEC_CC_OPEN;
	if (append_event) {
		current->pd_events |= TCPM_VBUS_EVENT | TCPM_CC_EVENT;
		append_event = false;
	}
	return cc_result;
}
static bool get_safe(struct tcpc_dev *t)
{
	(void)t;
	safe_reads++;
	return safe_value;
}
static struct tcpc_dev tcpc;
static void setup(struct tcpm_port *p, unsigned int flags)
{
	memset(p, 0, sizeof(*p));
	tcpc = (struct tcpc_dev){ get_vbus, get_cc, get_safe };
	p->tcpc = &tcpc;
	current = p;
	p->state = SNK_READY;
	p->queued_message = 7;
	p->vbus_present = flags & 1;
	p->vbus_vsafe0v = flags & 2;
	p->vbus_never_low = flags & 4;
	p->init_pending = flags & 8;
	p->vbus_control_error = -ETIMEDOUT;
	p->init_status_attempts = 2;
	p->vbus_reset_attempts = 1;
	result = 1;
	cc_result = 0;
	reads = cc_reads = cc_events = on_events = off_events = safe_events = 0;
	safe_reads = error_logs = clean_logs = port_error_logs = hard_resets =
		frs_starts = 0;
	safe_value = append_event = false;
	logged_error = 0;
}
static void event(struct tcpm_port *p, u32 events)
{
	p->pd_events |= events;
	tcpm_pd_event_handler(&p->event_work);
	assert(!p->pd_events && !p->lock.held);
}
unsigned int tcpm_vbus_read_tests(void)
{
	/* Exercise every negative Linux errno and every combination of old flags. */
	for (int err = -1; err >= -4095; err--) {
		for (unsigned int flags = 0; flags < 16; flags++) {
			struct tcpm_port p;
			setup(&p, flags);
			struct tcpm_port before = p;
			result = err;
			event(&p, TCPM_VBUS_EVENT);
			assert(!memcmp(&p, &before, sizeof(p)));
			assert(reads == 1 && error_logs == 1 &&
			       logged_error == err);
			assert(!on_events && !off_events && !safe_events &&
			       !safe_reads);
			cases++;
		}
	}
	const int errors[] = { -EIO,	-ETIMEDOUT, -EAGAIN,
			       -ENODEV, -ENODATA,   -EINVAL };
	for (unsigned int i = 0; i < sizeof(errors) / sizeof(errors[0]); i++) {
		for (unsigned int flags = 0; flags < 16; flags++) {
			struct tcpm_port p;
			setup(&p, flags);
			struct tcpm_port before = p;
			result = errors[i];
			event(&p, TCPM_VBUS_EVENT | TCPM_CC_EVENT);
			before.cc1 = TYPEC_CC_RD;
			before.cc2 = TYPEC_CC_OPEN;
			assert(!memcmp(&p, &before, sizeof(p)));
			assert(cc_reads == 1 && cc_events == 1 &&
			       logged_error == errors[i]);
			assert(!on_events && !off_events && !safe_events &&
			       !safe_reads);
			cases++;
		}
	}
	for (int present = 0; present <= 2; present++) {
		for (int safe = 0; safe <= 1; safe++) {
			for (unsigned int fallback = 0; fallback < 2;
			     fallback++) {
				struct tcpm_port p;
				setup(&p, 0);
				result = present;
				safe_value = safe;
				if (fallback)
					tcpc.is_vbus_vsafe0v = NULL;
				event(&p, TCPM_VBUS_EVENT | TCPM_CC_EVENT);
				assert(cc_reads == 1 && cc_events == 1 &&
				       !error_logs);
				assert(on_events == (unsigned int)!!present);
				assert(off_events == (unsigned int)!present);
				assert(safe_reads ==
				       (unsigned int)(!present && !fallback));
				assert(safe_events ==
				       (unsigned int)(!present &&
						      (safe || fallback)));
				assert(p.vbus_present == !!present);
				cases++;
			}
		}
	}
	struct tcpm_port p;
	setup(&p, 5);
	result = -EIO;
	event(&p, TCPM_VBUS_EVENT | TCPM_CC_EVENT | TCPM_RESET_EVENT |
			  TCPM_FRS_EVENT | TCPM_PORT_CLEAN | TCPM_PORT_ERROR);
	assert(logged_error == -EIO && hard_resets == 1 && frs_starts == 1);
	assert(cc_events == 1 && clean_logs == 1 && port_error_logs == 1);
	assert(p.vbus_present && !p.vbus_vsafe0v && !on_events && !off_events &&
	       !safe_events);
	assert(p.state ==
	       ERROR_RECOVERY); /* Other events keep their existing effects. */
	cases++;
	setup(&p, 5);
	result = -ETIMEDOUT;
	append_event = true;
	event(&p, TCPM_VBUS_EVENT | TCPM_CC_EVENT);
	assert(reads == 2 && error_logs == 2 && cc_events == 2);
	assert(p.vbus_present && !p.vbus_vsafe0v && p.state == SNK_READY);
	cases++;
	setup(&p, 5);
	result = -EIO;
	event(&p, TCPM_VBUS_EVENT);
	result = 0;
	safe_value = true;
	event(&p, TCPM_VBUS_EVENT);
	assert(!p.vbus_present && p.vbus_vsafe0v && off_events == 1 &&
	       safe_events == 1);
	result = 1;
	event(&p, TCPM_VBUS_EVENT);
	assert(p.vbus_present && !p.vbus_vsafe0v && on_events == 1);
	cases++;
	return cases;
}
