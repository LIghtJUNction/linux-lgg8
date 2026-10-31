"""Exercise actual TCPM functions with controlled callback outcomes."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CurrentLimitTest(unittest.TestCase):
    def compile_and_run(self, harness):
        with tempfile.TemporaryDirectory(prefix="test-tcpm-", dir=ROOT / "lgg8/tests") as tmp:
            directory = Path(tmp)
            test_source = directory / "test.c"
            binary = directory / "test"
            test_source.write_text(harness)
            env = {**os.environ, "TMPDIR": str(directory)}
            subprocess.run(["cc", "-pipe", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(test_source), "-o", str(binary)], check=True, env=env)
            subprocess.run([str(binary)], check=True, timeout=10)

    def test_callback_outcomes(self):
        source = (ROOT / "drivers/usb/typec/tcpm/tcpm.c").read_text()
        start = source.index("static int tcpm_set_current_limit(")
        end = source.index("\nstatic int tcpm_set_charge(", start)
        setter = source[start:end]
        harness = r'''
#include <assert.h>
#include <errno.h>
typedef unsigned int u32;
struct tcpc_dev { int (*set_current_limit)(struct tcpc_dev *, u32, u32); };
struct tcpm_port { u32 supply_voltage, current_limit; void *psy; struct tcpc_dev *tcpc; };
static int notifications;
#define tcpm_log(...) ((void)0)
static void power_supply_changed(void *p) { (void)p; notifications++; }
static int accept(struct tcpc_dev *t, u32 a, u32 b)
{ (void)t; (void)a; (void)b; return 0; }
static int reject(struct tcpc_dev *t, u32 a, u32 b)
{ (void)t; (void)a; (void)b; return -EIO; }
'''+ setter + r'''
int main(void)
{
    struct tcpc_dev t = { reject };
    struct tcpm_port p = { 5000, 500, 0, &t };
    assert(tcpm_set_current_limit(&p, 3000, 9000) == -EIO);
    assert(p.current_limit == 500 && p.supply_voltage == 5000 && notifications == 0);
    t.set_current_limit = accept;
    assert(tcpm_set_current_limit(&p, 3000, 9000) == 0);
    assert(p.current_limit == 3000 && p.supply_voltage == 9000 && notifications == 1);
    t.set_current_limit = 0;
    assert(tcpm_set_current_limit(&p, 500, 5000) == -EOPNOTSUPP);
    assert(p.current_limit == 500 && p.supply_voltage == 5000 && notifications == 2);
    return 0;
}
'''
        self.compile_and_run(harness)

    def test_vbus_recovery_state_machine(self):
        source = (ROOT / "drivers/usb/typec/tcpm/tcpm.c").read_text()

        def function(name):
            match = re.search(r"^static (?:int|void|bool) " + re.escape(name) +
                              r"\([^;{}]*\)\n\{", source, re.MULTILINE)
            self.assertIsNotNone(match, name)
            end = source.index("\n}\n", match.start()) + 3
            return source[match.start():end]

        # Copy callback declarations from the kernel header so the harness
        # cannot invent an errno channel for a bool/void callback.
        header = (ROOT / "include/linux/usb/tcpm.h").read_text()
        callbacks = ("set_vbus", "set_current_limit", "set_pd_rx", "init", "get_vbus",
                     "get_cc", "set_cc", "is_vbus_vsafe0v", "set_bist_data", "enable_frs")
        declarations = []
        for name in callbacks:
            match = re.search(r"^\s*(?:int|bool|void) \(\*" + name + r"\)\([^;]+;",
                              header, re.MULTILINE)
            self.assertIsNotNone(match, name)
            declarations.append(match[0].strip())
        tcpc_callbacks = "\n".join(declarations)

        # Whole actual functions, including cleanup, init and the timer worker.
        names = ("tcpm_set_cc", "tcpm_set_state", "tcpm_vbus_error", "tcpm_set_vbus",
                 "tcpm_set_charge", "tcpm_init_vbus", "tcpm_retry_vbus_reset", "tcpm_src_attach",
                 "tcpm_set_current_limit", "tcpm_set_sink_current_limit",
                 "tcpm_reset_port", "tcpm_detach", "tcpm_init_port_status", "tcpm_init",
                 "tcpm_psy_get_online", "tcpm_send_queued_message")
        functions = "\n".join(function(n) for n in names)
        states = source[source.index("#define FOREACH_STATE(S)"):
                        source.index("#define GENERATE_ENUM")]
        constants = re.search(r"^#define TCPM_VBUS_RESET_ATTEMPTS .*", source, re.MULTILINE)[0]
        pd = (ROOT / "include/linux/usb/pd.h").read_text()
        for name in ("PD_T_ERROR_RECOVERY", "PD_T_SRC_RECOVER", "PD_T_PS_SOURCE_ON",
                     "PD_T_SRCSWAPSTDBY", "PD_T_NEWSRC", "PD_T_SENDER_RESPONSE"):
            constants += "\n" + re.search(r"^#define " + name + r"\s.*", pd, re.MULTILINE)[0]
        messages = source[source.index("enum pd_msg_request {"):source.index("enum adev_actions {")]
        cc = function("_tcpm_cc_change")
        cc_case = cc[cc.index("\tcase SNK_UNATTACHED:"):cc.index("\tcase SNK_ATTACH_WAIT:")]
        cc_handler = ("\nstatic void _tcpm_cc_change(struct tcpm_port *port, "
                      "enum typec_cc_status cc1, enum typec_cc_status cc2)\n{\n"
                      "port->cc1 = cc1; port->cc2 = cc2; switch (port->state) {\n" +
                      cc_case + "default: break; }\n}\n")
        functions = functions.replace(function("tcpm_set_state"), function("tcpm_set_state") + cc_handler)

        def cases_between(first, after):
            body = function("run_state_machine")
            return body[body.index("\tcase " + first + ":"):
                        body.index("\tcase " + after + ":")]

        # Unchanged selected cases from the real large dispatcher; other
        # states/platform operations are outside this harness's boundary.
        reset_cases = cases_between("PORT_RESET", "AMS_START")
        discovery_case = cases_between("SNK_DISCOVERY", "SNK_DISCOVERY_DEBOUNCE")
        sink_cases = (cases_between("SNK_HARD_RESET_SINK_OFF", "SNK_HARD_RESET_WAIT_VBUS") +
                      cases_between("SNK_HARD_RESET_SINK_ON", "SOFT_RESET") +
                      cases_between("PR_SWAP_SNK_SRC_SINK_OFF", "PR_SWAP_SNK_SRC_SOURCE_ON"))
        source_cases = (cases_between("SRC_HARD_RESET_VBUS_OFF", "SNK_HARD_RESET_SINK_OFF") +
                        cases_between("PR_SWAP_SRC_SNK_TRANSITION_OFF", "PR_SWAP_SRC_SNK_SOURCE_OFF") +
                        cases_between("PR_SWAP_SNK_SRC_SOURCE_ON", "PR_SWAP_SNK_SRC_SOURCE_ON_VBUS_RAMPED_UP"))
        body = function("run_state_machine")
        guard = body[body.index("\t/* Also fence delayed transitions"):
                     body.index("\tif (port->tcpc->check_contaminant")]
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef unsigned int u32;
''' + states + r'''
#define GENERATE_ENUM(e) e
enum tcpm_state { FOREACH_STATE(GENERATE_ENUM) };
''' + constants + "\n" + messages + r'''
#define TYPEC_PORT_DRP 2
#define PD_P_SNK_STDBY_MW 2500
#define PD_T_DB_DETECT 10
#define PD_T_NO_RESPONSE 10
#define PD_T_SAFE_0V 650
#define PD_T_SRC_RECOVER_MAX 1000
#define TYPEC_PWR_MODE_USB 0
#define TYPEC_STATE_USB 0
#define TYPEC_SINK 0
#define TYPEC_SOURCE 1
#define TCPC_TX_SOP 0
#define PD_CTRL_WAIT 0
#define PD_CTRL_REJECT 1
#define PD_CTRL_NOT_SUPP 2
#define HARD_RESET 1
#define VSAFE5V 5000
#define NONE_AMS 0
#define VDM_DISCOVERY_UNKNOWN 0
#define TYPEC_POLARITY_CC1 0
#define TYPEC_STATE_SAFE 0
#define USB_ROLE_NONE 0
#define TYPEC_ORIENTATION_NONE 0
#define POWER_SUPPLY_USB_TYPE_C 0
#define TCPM_PSY_PPS_ONLINE 2
#define TCPM_PSY_SPR_AVS_ONLINE 3
#define TCPM_PSY_FIXED_ONLINE 1
#define TCPM_PSY_OFFLINE 0
#define tcpm_log(...) ((void)0)
#define tcpm_log_force(...) ((void)0)
#define tcpm_enable_auto_vbus_discharge(...) ((void)0)
#define tcpm_set_auto_vbus_discharge_threshold(...) ((void)0)
#define tcpm_ams_finish(...) ((void)0)
#define tcpm_update_vdm_discovery_state(...) ((void)0)
#define mod_vdm_discovery_cancel_delayed_work(...) ((void)0)
#define tcpm_unregister_altmodes(...) ((void)0)
#define tcpm_typec_disconnect(...) ((void)0)
#define tcpm_set_partner_usb_comm_capable(...) ((void)0)
#define tcpm_init_vconn(...) ((void)0)
#define tcpm_mux_set(...) ((void)0)
#define usb_power_delivery_unregister_capabilities(...) ((void)0)
#define tcpm_partner_source_caps_reset(...) ((void)0)
#define usb_power_delivery_unregister(...) ((void)0)
#define tcpm_port_is_disconnected(...) true
#define mutex_lock(...) ((void)0)
#define mutex_unlock(...) ((void)0)
#define container_of(w, t, m) ((w)->port)
#define ms_to_ktime(m) (m)
#define ktime_add(a, b) ((a) + (b))
#define ktime_get() 0
#define ktime_after(a,b) ((a) > (b))
#define ktime_to_ms(a) (a)
#define ktime_sub(a,b) ((a) - (b))
#define pdo_max_current(p) (p)
#define TYPEC_POLARITY_CC2 1
struct tcpm_port;
struct kthread_work { struct tcpm_port *port; };
enum typec_cc_polarity { POLARITY_UNUSED };
enum typec_cc_status {
    TYPEC_CC_OPEN, TYPEC_CC_RD, TYPEC_CC_RP_DEF, TYPEC_CC_RP_1_5, TYPEC_CC_RP_3_0, TYPEC_CC_RA
};
#define tcpm_port_is_debug_sink(p) false
#define tcpm_port_is_audio(p) false
#define tcpm_port_is_sink(p) ((p)->cc1 >= TYPEC_CC_RP_DEF || (p)->cc2 >= TYPEC_CC_RP_DEF)
union power_supply_propval { int intval; };
struct tcpc_dev {
''' + tcpc_callbacks + r'''
};
struct tcpm_port {
    struct tcpc_dev *tcpc;
    bool vbus_source, vbus_charge, state_machine_running, self_powered;
    int vbus_control_error;
    unsigned int vbus_reset_attempts;
    enum typec_cc_status cc_req, cc1, cc2;
    bool init_pending, explicit_contract;
    unsigned int init_status_attempts;
    int pwr_role;
    enum tcpm_state state, prev_state, delayed_state;
    long delayed_runtime, delay_ms;
    u32 supply_voltage, current_limit;
    void *psy;
    bool in_ams, vdm_sm_running, attached, pd_capable, sink_cap_done;
    bool vbus_present, vbus_never_low, vbus_vsafe0v, pd_supported, slow_charger_loop;
    struct { bool supported, active; } pps_data;
    struct { bool active; } spr_avs_data;
    struct { unsigned int ps_src_off_time; } timings;
    int ams, rx_msgid, rx_msgid_prime, try_src_count, try_snk_count, usb_type;
    int hard_reset_count, port_type, snk_pdo[1], queued_message, lock;
    unsigned int nr_sink_caps;
    void *partner_sink_caps, *partner_pd, *partner;
    struct kthread_work state_machine;
};
static int calls, get_vbus_calls, get_cc_calls, notifications, ready_entries;
static unsigned int schedules, last_delay;
static bool physical_source, physical_sink;
static int results[16];
static unsigned int applied[16];
static int cc_error, cc_read_error, vbus_read_error;
static int vsafe_calls, pd_tx_calls, pd_rx_on_calls, roles_calls, attached_on_calls;
static bool external_vbus, cable_rp, bus_failed, vsafe_sample;
static int post_failure_pd_rx_calls;
static unsigned int cc_calls;
static enum typec_cc_status physical_cc;
static int callback(struct tcpc_dev *t, bool source, bool sink)
{
    int index = calls++;
    (void)t;
    assert(index < 16);
    if (!results[index] || (applied[index] & 1)) physical_source = source;
    if (!results[index] || (applied[index] & 2)) physical_sink = sink;
    bus_failed = results[index] < 0;
    return results[index];
}
static int current_cb(struct tcpc_dev *t, u32 a, u32 b)
{ (void)t; (void)a; (void)b; return 0; }
static int pd_rx(struct tcpc_dev *t, bool on) { (void)t; pd_rx_on_calls += on; post_failure_pd_rx_calls += bus_failed; return 0; }
static int init_cb(struct tcpc_dev *t) { (void)t; return 0; }
static int get_vbus(struct tcpc_dev *t)
{ (void)t; get_vbus_calls++; return vbus_read_error ? vbus_read_error : external_vbus || physical_source; }
static bool get_vsafe(struct tcpc_dev *t) { (void)t; vsafe_calls++; return vsafe_sample; }
static int get_cc(struct tcpc_dev *t, enum typec_cc_status *a, enum typec_cc_status *b)
{
    (void)t; get_cc_calls++;
    if (cc_read_error) return cc_read_error;
    *a = cable_rp ? TYPEC_CC_RP_DEF : TYPEC_CC_OPEN;
    *b = TYPEC_CC_OPEN;
    return 0;
}
static int set_cc(struct tcpc_dev *t, enum typec_cc_status cc)
{
    (void)t;
    cc_calls++;
    if (cc_error) return cc_error;
    physical_cc = cc;
    return 0;
}
static struct tcpc_dev tcpc = {
    .set_vbus = callback, .set_current_limit = current_cb, .set_pd_rx = pd_rx,
    .init = init_cb, .get_vbus = get_vbus, .get_cc = get_cc,
    .set_cc = set_cc,
};
static void power_supply_changed(void *p) { (void)p; notifications++; }
static int tcpm_set_roles(struct tcpm_port *p, bool attached, int state, int role, int data)
{ (void)p; (void)attached; (void)state; (void)role; (void)data; roles_calls++; return 0; }
static int tcpm_set_polarity(struct tcpm_port *p, enum typec_cc_polarity polarity)
{ (void)p; (void)polarity; return 0; }
static int tcpm_set_vconn(struct tcpm_port *p, bool enable)
{ (void)p; (void)enable; return 0; }
static int tcpm_set_attached_state(struct tcpm_port *p, bool attached)
{ (void)p; attached_on_calls += attached; return 0; }
#define tcpm_data_role_for_source(p) 0
#define tcpm_data_role_for_sink(p) 0
static int test_pd_send(struct tcpm_port *p) { (void)p; pd_tx_calls++; return 0; }
#define tcpm_pd_send_control(p, type, sop) test_pd_send(p)
#define tcpm_pd_send_sink_caps(p) test_pd_send(p)
#define tcpm_pd_send_source_caps(p) test_pd_send(p)
#define tcpm_pd_send_revision(p) test_pd_send(p)
#define tcpm_pd_send_sink_cap_ext(p) test_pd_send(p)
#define tcpm_pd_send_batt_status(p) test_pd_send(p)
#define tcpm_pd_send_batt_cap(p) test_pd_send(p)
static void mod_tcpm_delayed_work(struct tcpm_port *p, unsigned int ms)
{ (void)p; schedules++; last_delay = ms; }
static enum tcpm_state tcpm_default_state(struct tcpm_port *p) { (void)p; return SNK_UNATTACHED; }
static int tcpm_rp_cc(struct tcpm_port *p) { (void)p; return 2; }
static unsigned int tcpm_get_current_limit(struct tcpm_port *p) { (void)p; return 500; }
static enum tcpm_state hard_reset_state(struct tcpm_port *p) { (void)p; return PORT_RESET; }
''' + functions + r'''
static void run_selected_state(struct tcpm_port *port)
{
    int __attribute__((unused)) ret;
''' + guard + r'''
    switch (port->state) {
''' + reset_cases + discovery_case + sink_cases + source_cases + r'''
    default:
        if (port->state == SNK_READY || port->state == SRC_READY) ready_entries++;
        break;
    }
}
/* The entire real worker body, with only its large dispatcher substituted
 * by the exact source cases above. Timer firing is driven deterministically.
 */
#define run_state_machine run_selected_state
''' + function("tcpm_state_machine_work") + r'''
#undef run_state_machine
static void setup(struct tcpm_port *p, unsigned int flags)
{
    memset(p, 0, sizeof(*p));
    memset(results, 0, sizeof(results));
    memset(applied, 0, sizeof(applied));
    p->tcpc = &tcpc;
    p->vbus_source = physical_source = !!(flags & 1);
    p->vbus_charge = physical_sink = !!(flags & 2);
    p->state = PORT_RESET;
    p->state_machine.port = p;
    p->snk_pdo[0] = 500;
    calls = get_vbus_calls = get_cc_calls = notifications = ready_entries = 0;
    schedules = last_delay = 0;
    cc_error = cc_read_error = vbus_read_error = 0;
    vsafe_sample = true;
    vsafe_calls = pd_tx_calls = pd_rx_on_calls = roles_calls = attached_on_calls = 0;
    external_vbus = cable_rp = bus_failed = false;
    post_failure_pd_rx_calls = 0;
    tcpc.is_vbus_vsafe0v = NULL;
    cc_calls = 0;
    physical_cc = TYPEC_CC_RD;
}
static void work(struct tcpm_port *p) { tcpm_state_machine_work(&p->state_machine); }
static void assert_fault(struct tcpm_port *p, int rc)
{
    union power_supply_propval v = { .intval = 99 };
    assert(p->vbus_control_error == rc && !ready_entries);
    assert(tcpm_psy_get_online(p, &v) == rc && v.intval == 99);
}
int main(void)
{
    struct tcpm_port p;
    const int errors[] = { -EIO, -ETIMEDOUT, -EOPNOTSUPP };
    unsigned int flags, effect, e, n = 0;
    for (flags = 0; flags < 4; flags++)
    for (effect = 0; effect < 4; effect++)
    for (e = 0; e < 3; e++) {
        unsigned int before;
        setup(&p, flags);
        results[0] = errors[e]; applied[0] = effect;
        work(&p); /* Actual PORT_RESET cleanup and actual timer worker. */
        assert_fault(&p, errors[e]);
        assert(calls == 1 && p.vbus_reset_attempts == 1);
        assert(p.vbus_source == !!(flags & 1) && p.vbus_charge == !!(flags & 2));
        assert(p.delayed_state == PORT_RESET && last_delay == PD_T_ERROR_RECOVERY);
        assert(physical_source == ((effect & 1) ? false : !!(flags & 1)));
        assert(physical_sink == ((effect & 2) ? false : !!(flags & 2)));
        before = schedules;
        tcpm_set_state(&p, SNK_DISCOVERY, 0);
        tcpm_set_state(&p, SNK_READY, 1);
        tcpm_set_state(&p, SRC_READY, 0);
        assert(schedules == before && p.delayed_state == PORT_RESET);
        assert(tcpm_set_charge(&p, true) == errors[e] && calls == 1);
        work(&p); /* Timer retry succeeds: only complete off clears fault. */
        assert(calls == 2 && !p.vbus_control_error && !p.vbus_reset_attempts);
        assert(!p.vbus_source && !p.vbus_charge && !physical_source && !physical_sink);
        assert(p.delayed_state == PORT_RESET_WAIT_OFF && !ready_entries);
        work(&p);
        assert(p.state == SNK_UNATTACHED && !ready_entries);
        p.vbus_present = true;
        tcpm_set_state(&p, SNK_DISCOVERY, 0);
        work(&p);
        assert(p.state == SNK_READY && p.vbus_charge && physical_sink && ready_entries == 1);
        n++;
    }
    /* The actual void tcpm_set_cc drops callback errors and still updates
     * cc_req. A failed CC-open cannot be detected here or block VBUS retries.
     * All three VBUS failures park without spontaneous fourth attempts. */
    setup(&p, 3);
    results[0] = -EIO; results[1] = -ETIMEDOUT; results[2] = -EOPNOTSUPP;
    applied[0] = 1; applied[1] = 2; applied[2] = 3; cc_error = -EIO;
    work(&p); work(&p); work(&p);
    assert(calls == 3 && p.state == PORT_RESET_FAILED && !p.delayed_state);
    assert(cc_calls == 3 && p.cc_req == TYPEC_CC_OPEN && physical_cc == TYPEC_CC_RD);
    assert_fault(&p, -EOPNOTSUPP);
    tcpm_set_state(&p, PORT_RESET, 0);
    tcpm_set_state(&p, SNK_READY, 0);
    tcpm_set_state(&p, ERROR_RECOVERY, 0);
    work(&p); work(&p);
    assert(calls == 3 && p.state == PORT_RESET_FAILED && !p.delayed_state);
    /* Explicit TCPC reset (the actual init function) rearms the budget. */
    cc_error = 0;
    tcpm_init(&p);
    assert(calls == 4 && !p.vbus_control_error && p.state == PORT_RESET);
    work(&p); work(&p);
    assert(p.state == SNK_UNATTACHED && calls == 5);
    n++;
    /* Startup failure must not read CC/VBUS or enter discovery. */
    setup(&p, 0); p.state = INVALID_STATE; results[0] = -EIO; applied[0] = 3;
    tcpm_init(&p);
    assert(calls == 1 && !get_vbus_calls && !get_cc_calls);
    assert_fault(&p, -EIO);
    assert(p.delayed_state == PORT_RESET);
    work(&p);
    assert(!p.vbus_control_error && calls == 2);
    n++;
    /* Detach still runs cleanup and returns its failed shutdown to recovery. */
    setup(&p, 2); p.attached = true; p.state = SNK_UNATTACHED; results[0] = -EIO;
    tcpm_detach(&p);
    assert(!p.attached && p.delayed_state == PORT_RESET);
    assert_fault(&p, -EIO);
    work(&p);
    assert(calls == 2 && !p.vbus_control_error);
    n++;
    /* A sink-on failure may have physically enabled input, despite cached
     * false flags. Never enter ready; recovery MUST issue complete off. */
    for (effect = 0; effect < 4; effect++) {
        setup(&p, 0); p.state = SNK_DISCOVERY; p.vbus_present = true;
        results[0] = -EIO; applied[0] = effect;
        work(&p);
        assert(!ready_entries && calls == 2 && !physical_sink);
        assert(!p.vbus_control_error && p.delayed_state == PORT_RESET_WAIT_OFF);
        n++;
    }
    /* Source-on and sink-off callback failures latch even if software state
     * would otherwise suppress another attempt. Old queued ready is fenced. */
    setup(&p, 0); p.state = SRC_UNATTACHED; results[0] = -EIO; applied[0] = 1;
    assert(tcpm_set_vbus(&p, true) == -EIO && physical_source && !p.vbus_source);
    p.delayed_state = SRC_READY;
    work(&p);
    assert(!ready_entries && !physical_source && !p.vbus_control_error && calls == 2);
    n++;
    setup(&p, 2); p.state = SNK_READY; results[0] = -EIO; applied[0] = 2;
    assert(tcpm_set_charge(&p, false) == -EIO && p.vbus_charge && !physical_sink);
    assert(tcpm_set_charge(&p, false) == -EIO && calls == 1);
    work(&p);
    assert(!p.vbus_charge && !p.vbus_control_error && calls == 2 && !ready_entries);
    n++;
    /* Success is never skipped just because cached flags were already off. */
    setup(&p, 0);
    assert(tcpm_init_vbus(&p) == 0 && calls == 1);
    assert(tcpm_init_vbus(&p) == 0 && calls == 2);
    n++;
    /* Real hard-reset and role-swap cases must stop at failed sink writes. */
    {
        const enum tcpm_state paths[] = {
            SNK_HARD_RESET_SINK_OFF, SNK_HARD_RESET_SINK_ON, PR_SWAP_SNK_SRC_SINK_OFF
        };
        unsigned int path;
        for (path = 0; path < 3; path++) for (effect = 0; effect < 4; effect++) {
            setup(&p, path == 1 ? 0 : 2);
            p.state = paths[path]; p.pd_capable = true; p.attached = true;
            results[0] = -EIO; applied[0] = effect;
            work(&p);
            assert(calls == 2 && !ready_entries && !p.attached);
            assert(!physical_sink && !p.vbus_control_error);
            assert(p.delayed_state == PORT_RESET_WAIT_OFF);
            n++;
        }
    }

    /* Stale PD messages: exercise the actual sender (not a no-op substitute).
     * Both fault recovery and an ordinary reset must discard them BEFORE tx.
     */
    {
        const int stale[] = { PD_MSG_DATA_SOURCE_CAP, PD_MSG_DATA_SINK_CAP, PD_MSG_CTRL_WAIT };
        unsigned int msg;
        for (msg = 0; msg < 3; msg++) {
            setup(&p, 2); p.queued_message = stale[msg];
            results[0] = -EIO;
            work(&p);
            assert(!pd_tx_calls && p.queued_message == PD_MSG_NONE);
            work(&p); work(&p);
            assert(!pd_tx_calls && !p.vbus_control_error && p.state == SNK_UNATTACHED);
            setup(&p, 0); p.queued_message = stale[msg];
            work(&p); work(&p);
            assert(!pd_tx_calls && p.queued_message == PD_MSG_NONE);
            n += 2;
        }
        setup(&p, 0); p.state = SNK_READY; p.queued_message = PD_MSG_CTRL_WAIT;
        assert(!tcpm_send_queued_message(&p));
        assert(pd_tx_calls == 1 && p.queued_message == PD_MSG_NONE);
        n++;
    }
    setup(&p, 0); p.state = SNK_READY; p.queued_message = PD_MSG_DATA_SOURCE_CAP;
    tcpm_set_state(&p, PORT_RESET, PD_T_ERROR_RECOVERY);
    assert(p.queued_message == PD_MSG_NONE);
    work(&p); work(&p);
    assert(!pd_tx_calls && p.state == SNK_UNATTACHED);
    n++;
    /* A plugged adapter cannot be assumed to generate another IRQ after the
     * first shutdown fails. Real init completion must re-read and replay CC.
     */
    setup(&p, 0); p.state = INVALID_STATE; results[0] = -EIO;
    external_vbus = cable_rp = true;
    tcpc.is_vbus_vsafe0v = get_vsafe;
    tcpm_init(&p);
    assert(p.init_pending && !get_vbus_calls && !get_cc_calls);
    tcpm_set_state(&p, SNK_DISCOVERY, 0);
    assert(p.delayed_state == PORT_RESET && p.init_pending);
    work(&p); /* Off retry succeeded, wait for reset recovery before reads. */
    assert(p.init_pending && !get_vbus_calls && !get_cc_calls);
    work(&p); /* No synthetic IRQ is injected anywhere. */
    assert(!p.init_pending && get_vbus_calls == 1 && get_cc_calls == 1);
    assert(p.vbus_present && p.vbus_never_low && !p.vbus_vsafe0v && !vsafe_calls);
    assert(p.cc1 == TYPEC_CC_RP_DEF && p.state == SNK_ATTACH_WAIT);
    assert(!ready_entries);
    n++;
    /* Optional bool callback: absent fallback, true and false are distinct
     * observations. False is not an errno and must not trigger read retries.
     */
    for (effect = 0; effect < 3; effect++) {
        setup(&p, 0); p.state = INVALID_STATE;
        tcpc.is_vbus_vsafe0v = effect ? get_vsafe : NULL;
        vsafe_sample = effect != 2;
        tcpm_init(&p); work(&p); work(&p);
        assert(!p.init_pending && !p.vbus_present && p.vbus_vsafe0v == (effect != 2));
        assert(!p.init_status_attempts && !p.vbus_control_error);
        assert(vsafe_calls == (effect ? 1 : 0));
        assert(get_cc_calls == 1 && p.state == SNK_UNATTACHED);
        n++;
    }
    /* Only the int-returning get_vbus/get_cc callbacks can report errno.
     * Preserve their errors and bound observation retries.
     */
    for (effect = 0; effect < 2; effect++) for (e = 0; e < 3; e++) {
        setup(&p, 0); p.state = INVALID_STATE; tcpc.is_vbus_vsafe0v = get_vsafe;
        if (effect == 0) vbus_read_error = errors[e];
        else cc_read_error = errors[e];
        tcpm_init(&p); work(&p); work(&p);
        assert(p.init_pending && p.init_status_attempts == 1 && !ready_entries);
        assert(p.delayed_state == PORT_RESET_WAIT_OFF);
        work(&p); work(&p);
        assert(p.state == PORT_RESET_FAILED && p.init_pending && !ready_entries);
        assert_fault(&p, errors[e]);
        n++;
    }
    setup(&p, 0); p.state = INVALID_STATE; external_vbus = cable_rp = true;
    cc_read_error = -EIO;
    tcpm_init(&p); work(&p); work(&p);
    assert(p.init_pending && p.init_status_attempts == 1);
    cc_read_error = 0;
    work(&p);
    assert(!p.init_pending && p.state == SNK_ATTACH_WAIT && p.vbus_present);
    n++;
    /* Stop the exact source cases immediately after a failed VBUS operation,
     * before reset cleanup, so reset cannot hide an unintended hardware call.
     */
    {
        const enum tcpm_state paths[] = {
            SRC_HARD_RESET_VBUS_OFF, SRC_HARD_RESET_VBUS_ON,
            PR_SWAP_SRC_SNK_TRANSITION_OFF, PR_SWAP_SNK_SRC_SOURCE_ON
        };
        unsigned int path;
        for (path = 0; path < 4; path++) for (effect = 0; effect < 4; effect++) {
            setup(&p, path == 0 || path == 2 ? 1 : 0);
            p.state = paths[path]; p.pd_supported = true; p.ams = HARD_RESET;
            p.explicit_contract = true;
            results[0] = -EIO; applied[0] = effect;
            run_selected_state(&p);
            assert(p.state == PORT_RESET && p.vbus_control_error == -EIO);
            assert(calls == 1 && !pd_rx_on_calls && !roles_calls && !attached_on_calls);
            assert(!post_failure_pd_rx_calls);
            assert(p.explicit_contract && !pd_tx_calls && !ready_entries);
            work(&p);
            assert(!physical_source && !physical_sink && calls == 2);
            assert(!pd_rx_on_calls && !roles_calls && !attached_on_calls);
            n++;
        }
        /* Positive control: normal source-on still enables PD RX/attached. */
        setup(&p, 0); p.state = SRC_HARD_RESET_VBUS_ON; p.pd_supported = true;
        run_selected_state(&p);
        assert(calls == 1 && pd_rx_on_calls == 1 && attached_on_calls == 1);
        assert(p.delayed_state == SRC_UNATTACHED && !p.vbus_control_error);
        n++;
        for (effect = 0; effect < 4; effect++) {
            setup(&p, 0); p.state = SRC_ATTACHED; p.pd_supported = true;
            results[0] = -EIO; applied[0] = effect;
            assert(tcpm_src_attach(&p) == -EIO);
            assert(calls == 1 && !pd_rx_on_calls && !roles_calls && !attached_on_calls);
            assert(!post_failure_pd_rx_calls);
            work(&p);
            assert(calls == 2 && !physical_source && !ready_entries);
            n++;
        }
    }
    printf("VBUS recovery: %u actual-source scenarios passed\n", n);
    return 0;
}
'''
        self.compile_and_run(harness)


if __name__ == "__main__":
    unittest.main()
