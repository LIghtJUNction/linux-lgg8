// SPDX-License-Identifier: GPL-2.0-only
/* Behavioral tests against the complete policy .c, not a translated model. */
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include "qcom_smb5_thermal_policy.h"

/* SYNTHETIC test values; none asserts physical calibration or safe pack limits. */
static const struct smb5_thermal_config fixture_config = {
	.max_sample_age_ms = 1000,
	.min_capacity_mah = 3400,
	.battery_fcc_max_ua = 3000000,
	.battery_fv_max_uv = 4430000,
	.temperature_min_decic = -400,
	.temperature_max_decic = 1000,
	.voltage_min_uv = 2500000,
	.voltage_max_uv = 4600000,
};

static unsigned int checks;

static struct smb5_thermal_input sample(int temperature, unsigned int voltage)
{
	struct smb5_thermal_input in = {
		.connected = true,
		.session_id = 1,
		.session_started_at_ms = 100,
		.now_ms = 200,
		.sample = {
			.session_id = 1,
			.captured_at_ms = 200,
			.temperature_valid = true,
			.voltage_valid = true,
		},
	};

	in.sample.temperature_decic = temperature;
	in.sample.voltage_uv = voltage;
	return in;
}

static void stopped(struct smb5_thermal_result r, enum smb5_thermal_reason reason)
{
	assert(r.stop_charging);
	assert(r.reason == reason);
	assert(r.fcc_max_ua == 0 && r.fv_max_uv == 0);
	checks++;
}

static void advised(struct smb5_thermal_result r, enum smb5_thermal_zone zone,
		    unsigned int fcc, unsigned int fv, bool chilly)
{
	assert(!r.stop_charging && r.reason == SMB5_THERMAL_OK);
	assert(r.next.zone == zone && r.chilly == chilly);
	assert(r.fcc_max_ua == fcc && r.fv_max_uv == fv);
	assert(r.next.have_sample && r.age_valid);
	checks++;
}

static void test_reference_boundaries(void)
{
	static const struct {
		int t;
		enum smb5_thermal_zone zone;
		unsigned int fcc;
		bool chilly;
	} cases[] = {
		{ -1, SMB5_THERMAL_COLD, 0, false },
		{ 0, SMB5_THERMAL_COOL, 1000000, true },
		{ 99, SMB5_THERMAL_COOL, 1000000, true },
		{ 100, SMB5_THERMAL_GOOD, 1700000, true },
		{ 150, SMB5_THERMAL_GOOD, 1700000, true },
		{ 151, SMB5_THERMAL_GOOD, 3000000, false },
		{ 449, SMB5_THERMAL_GOOD, 3000000, false },
		{ 450, SMB5_THERMAL_WARM, 1700000, false },
		{ 549, SMB5_THERMAL_WARM, 1700000, false },
		{ 550, SMB5_THERMAL_HOT, 0, false },
	};
	unsigned int i;

	for (i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
		struct smb5_thermal_input in = sample(cases[i].t, 3999999);
		struct smb5_thermal_result r =
			qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);

		if (cases[i].zone == SMB5_THERMAL_COLD)
			stopped(r, SMB5_THERMAL_STOP_COLD);
		else if (cases[i].zone == SMB5_THERMAL_HOT)
			stopped(r, SMB5_THERMAL_STOP_HOT);
		else
			advised(r, cases[i].zone, cases[i].fcc,
				cases[i].zone == SMB5_THERMAL_WARM ? 4000000 : 4430000,
				cases[i].chilly);
	}
}

static void test_hysteresis(void)
{
	static const struct {
		enum smb5_thermal_zone previous;
		int t;
		enum smb5_thermal_zone expected;
	} cases[] = {
		{ SMB5_THERMAL_COLD, 29, SMB5_THERMAL_COLD },
		{ SMB5_THERMAL_COLD, 30, SMB5_THERMAL_COOL },
		{ SMB5_THERMAL_COOL, 119, SMB5_THERMAL_COOL },
		{ SMB5_THERMAL_COOL, 120, SMB5_THERMAL_GOOD },
		{ SMB5_THERMAL_WARM, 429, SMB5_THERMAL_GOOD },
		{ SMB5_THERMAL_WARM, 430, SMB5_THERMAL_WARM },
		{ SMB5_THERMAL_HOT, 519, SMB5_THERMAL_WARM },
		{ SMB5_THERMAL_HOT, 520, SMB5_THERMAL_HOT },
		{ SMB5_THERMAL_COLD, 600, SMB5_THERMAL_HOT },
		{ SMB5_THERMAL_HOT, -10, SMB5_THERMAL_COLD },
	};
	unsigned int i;

	for (i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
		struct smb5_thermal_state state = { .zone = cases[i].previous };
		struct smb5_thermal_input in = sample(cases[i].t, 3900000);
		struct smb5_thermal_result r =
			qcom_smb5_thermal_policy_step(&fixture_config, &state, &in);

		assert(r.next.zone == cases[i].expected);
		assert(r.stop_charging == (cases[i].expected == SMB5_THERMAL_COLD ||
					  cases[i].expected == SMB5_THERMAL_HOT));
		checks++;
	}
}

static void test_voltage_and_pack_caps(void)
{
	struct smb5_thermal_input in = sample(50, 4000000);
	struct smb5_thermal_config c = fixture_config;

	advised(qcom_smb5_thermal_policy_step(&c, NULL, &in),
		SMB5_THERMAL_COOL, 500000, 4430000, true);
	in.sample.temperature_decic = 150;
	advised(qcom_smb5_thermal_policy_step(&c, NULL, &in),
		SMB5_THERMAL_GOOD, 1000000, 4430000, true);
	in.sample.temperature_decic = 450;
	c.battery_fcc_max_ua = 400000;
	c.battery_fv_max_uv = 3900000;
	advised(qcom_smb5_thermal_policy_step(&c, NULL, &in),
		SMB5_THERMAL_WARM, 400000, 3900000, false);
	c = fixture_config;
	c.min_capacity_mah = 3501;
	advised(qcom_smb5_thermal_policy_step(&c, NULL, &in),
		SMB5_THERMAL_WARM, 1750000, 4000000, false);
	c.min_capacity_mah = UINT_MAX;
	advised(qcom_smb5_thermal_policy_step(&c, NULL, &in),
		SMB5_THERMAL_WARM, 3000000, 4000000, false);
	c.min_capacity_mah = 1;
	stopped(qcom_smb5_thermal_policy_step(&c, NULL, &in),
		SMB5_THERMAL_BAD_CONFIG);
}

static void test_invalid_inputs(void)
{
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_config c = { 0 };
	struct smb5_thermal_state state = { .zone = (enum smb5_thermal_zone)-1 };

	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, NULL),
		SMB5_THERMAL_BAD_ARGUMENT);
	stopped(qcom_smb5_thermal_policy_step(NULL, NULL, &in), SMB5_THERMAL_BAD_CONFIG);
	stopped(qcom_smb5_thermal_policy_step(&c, NULL, &in), SMB5_THERMAL_BAD_CONFIG);
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &state, &in),
		SMB5_THERMAL_BAD_STATE);
	c = fixture_config;
	c.temperature_max_decic = c.temperature_min_decic;
	stopped(qcom_smb5_thermal_policy_step(&c, NULL, &in), SMB5_THERMAL_BAD_CONFIG);
	c = fixture_config;
	c.voltage_max_uv = c.battery_fv_max_uv - 1;
	stopped(qcom_smb5_thermal_policy_step(&c, NULL, &in), SMB5_THERMAL_BAD_CONFIG);
	in.sample.temperature_valid = false;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_INVALID);
	in.sample.temperature_valid = true;
	in.sample.voltage_valid = false;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_INVALID);
	in.sample.voltage_valid = true;
	in.sample.error = -5;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_ERROR);
	in.sample.error = 5;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_ERROR);
	in.sample.error = 0;
	in.sample.temperature_decic = INT_MIN;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_OUT_OF_RANGE);
	in.sample.temperature_decic = INT_MAX;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_OUT_OF_RANGE);
	in.sample.temperature_decic = 250;
	in.sample.voltage_uv = 0;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_OUT_OF_RANGE);
	in.sample.voltage_uv = UINT_MAX;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_OUT_OF_RANGE);
}

static void test_age_and_order(void)
{
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_result r;

	in.now_ms = 1199;
	r = qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);
	assert(r.sample_age_ms == 999);
	in.now_ms = 1200;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_SAMPLE_EXPIRED);
	in.now_ms = UINT64_MAX;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_SAMPLE_EXPIRED);
	in = sample(250, 3900000);
	in.sample.captured_at_ms = 201;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_FUTURE);
	in.sample.captured_at_ms = 99;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_SAMPLE_BEFORE_SESSION);
	in = sample(250, 3900000);
	r = qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	in.now_ms = 199;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_CLOCK_REGRESSED);
	in.now_ms = 201;
	in.sample.captured_at_ms = 199;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_SAMPLE_REGRESSED);
	in.sample.captured_at_ms = 201;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_GOOD, 3000000, 4430000, false);
}

static void test_errors_and_reconnect(void)
{
	struct smb5_thermal_input in = sample(550, 3900000);
	struct smb5_thermal_result r =
		qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);

	stopped(r, SMB5_THERMAL_STOP_HOT);
	in.now_ms = 201;
	in.sample.error = -5;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_SAMPLE_ERROR);
	assert(r.next.zone == SMB5_THERMAL_HOT);
	in.connected = false;
	in.now_ms = 202;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_DISCONNECTED);
	assert(r.next.zone == SMB5_THERMAL_HOT && !r.next.session_active);
	in.connected = true;
	in.sample.error = 0;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_BAD_SESSION);
	in.session_id = 2;
	in.session_started_at_ms = 202;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_SAMPLE_WRONG_SESSION);
	in.sample.session_id = 2;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_SAMPLE_BEFORE_SESSION);
	in.sample.captured_at_ms = 202;
	in.sample.temperature_decic = 530;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_STOP_HOT);
	in.sample.temperature_decic = 519;
	in.sample.captured_at_ms = ++in.now_ms;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_WARM, 1700000, 4000000, false);
	in.sample.error = -5;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_SAMPLE_ERROR);
	assert(r.next.zone == SMB5_THERMAL_WARM);
	in.sample.error = 0;
	in.now_ms += 1000;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_SAMPLE_EXPIRED);
	assert(r.next.zone == SMB5_THERMAL_WARM);
	in.sample.captured_at_ms = in.now_ms;
	in.sample.temperature_decic = 440;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_WARM, 1700000, 4000000, false);
}

static void test_session_errors(void)
{
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_result r;

	in.session_id = 0;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_BAD_SESSION);
	in.session_id = 1;
	in.session_started_at_ms = 201;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in),
		SMB5_THERMAL_BAD_SESSION);
	in = sample(250, 3900000);
	r = qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	in.session_started_at_ms = 101;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_BAD_SESSION);
	in.session_id = 2;
	in.session_started_at_ms = 99;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_BAD_SESSION);
	in = sample(250, 3900000);
	in.connected = false;
	in.now_ms = 199;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_CLOCK_REGRESSED);
	assert(!r.next.session_active);
	in.connected = true;
	in.now_ms = 200;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_BAD_SESSION);
}

static void test_cold_reconnect_and_good_failure(void)
{
	struct smb5_thermal_input in = sample(-1, 3900000);
	struct smb5_thermal_result r =
		qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);

	stopped(r, SMB5_THERMAL_STOP_COLD);
	in.connected = false;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_DISCONNECTED);
	in.connected = true;
	in.session_id = in.sample.session_id = 2;
	in.session_started_at_ms = in.sample.captured_at_ms = ++in.now_ms;
	in.sample.temperature_decic = 20;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_STOP_COLD);
	in.sample.temperature_decic = 30;
	in.sample.captured_at_ms = ++in.now_ms;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_COOL, 1000000, 4430000, true);
	in.sample.temperature_decic = 250;
	in.sample.captured_at_ms = ++in.now_ms;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);
	in.sample.temperature_valid = false;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_SAMPLE_INVALID);
	assert(r.next.zone == SMB5_THERMAL_GOOD);
	in.sample.temperature_valid = true;
	in.now_ms += 1000;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_SAMPLE_EXPIRED);
	in.sample.captured_at_ms = in.now_ms;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_GOOD, 3000000, 4430000, false);
}

static void test_required_config_fields(void)
{
	struct smb5_thermal_config cases[8];
	struct smb5_thermal_input in = sample(250, 3900000);
	unsigned int i;

	for (i = 0; i < sizeof(cases) / sizeof(cases[0]); i++)
		cases[i] = fixture_config;
	cases[0].max_sample_age_ms = 0;
	cases[1].min_capacity_mah = 0;
	cases[2].battery_fcc_max_ua = 0;
	cases[3].battery_fv_max_uv = 0;
	cases[4].voltage_min_uv = 0;
	cases[5].voltage_min_uv = cases[5].voltage_max_uv;
	cases[6].temperature_min_decic = cases[6].temperature_max_decic + 1;
	cases[7].battery_fv_max_uv = cases[7].voltage_min_uv;
	for (i = 0; i < sizeof(cases) / sizeof(cases[0]); i++)
		stopped(qcom_smb5_thermal_policy_step(&cases[i], NULL, &in),
			SMB5_THERMAL_BAD_CONFIG);
}

static void test_session_before_known_detach(void)
{
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_result r =
		qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);

	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);
	in.connected = false;
	in.now_ms = 1000;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_DISCONNECTED);
	in.connected = true;
	in.session_id = in.sample.session_id = 2;
	in.session_started_at_ms = 900;
	in.sample.captured_at_ms = 950;
	in.now_ms = 1001;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_BAD_SESSION);
}

static void test_detach_time_boundaries(void)
{
	static const u64 starts[] = { 999, 1000, 1001 };
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_result r =
		qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	struct smb5_thermal_state detached;
	unsigned int i;

	in.connected = false;
	in.now_ms = 1000;
	in.sample.error = -5;
	/* Detach recording must not depend on a usable sample or configuration. */
	r = qcom_smb5_thermal_policy_step(NULL, &r.next, &in);
	stopped(r, SMB5_THERMAL_DISCONNECTED);
	assert(r.next.session_start_floor_ms == 1000);
	assert(!r.next.session_active && !r.next.have_sample);
	detached = r.next;
	in = sample(250, 3900000);
	in.now_ms = 1001;
	in.session_id = in.sample.session_id = 2;
	in.sample.captured_at_ms = 1001;
	for (i = 0; i < sizeof(starts) / sizeof(starts[0]); i++) {
		in.session_started_at_ms = starts[i];
		r = qcom_smb5_thermal_policy_step(&fixture_config, &detached, &in);
		if (starts[i] < 1000) {
			stopped(r, SMB5_THERMAL_BAD_SESSION);
			assert(!r.next.session_active && r.next.session_id == 1);
		} else {
			advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);
		}
		assert(r.next.session_start_floor_ms == 1000);
	}
	in.session_started_at_ms = 1000;
	in.sample.captured_at_ms = 999;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &detached, &in);
	stopped(r, SMB5_THERMAL_SAMPLE_BEFORE_SESSION);
	in.sample.captured_at_ms = 1000;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_GOOD, 3000000, 4430000, false);

	in.connected = false;
	in.now_ms = 1002;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &detached, &in);
	stopped(r, SMB5_THERMAL_DISCONNECTED);
	assert(r.next.session_start_floor_ms == 1002);
	in.connected = true;
	in.session_started_at_ms = 1001;
	in.sample.captured_at_ms = 1002;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_BAD_SESSION);
	in.session_started_at_ms = 1002;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_GOOD, 3000000, 4430000, false);
}

static void test_regressed_detach_clock(void)
{
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_result r =
		qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);

	/* No previous valid detach: the last trusted active time is the floor. */
	in.connected = false;
	in.now_ms = 150;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_CLOCK_REGRESSED);
	assert(r.next.last_now_ms == 200 && r.next.session_start_floor_ms == 200);
	assert(!r.next.session_active && !r.next.have_sample);
	in.connected = true;
	in.now_ms = in.sample.captured_at_ms = 201;
	in.session_id = in.sample.session_id = 2;
	in.session_started_at_ms = 199;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_BAD_SESSION);
	in.session_started_at_ms = 200;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);

	in.connected = false;
	in.now_ms = 1000;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_DISCONNECTED);
	in.now_ms = 900;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_CLOCK_REGRESSED);
	assert(r.next.last_now_ms == 1000 && r.next.session_start_floor_ms == 1000);
	in.connected = true;
	in.now_ms = in.sample.captured_at_ms = 1001;
	in.session_id = in.sample.session_id = 3;
	in.session_started_at_ms = 999;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_BAD_SESSION);
	in.session_started_at_ms = 1000;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);

	/* A later active observation must also bound a failed detach timestamp. */
	in.now_ms = in.sample.captured_at_ms = 1100;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);
	in.connected = false;
	in.now_ms = 800;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_CLOCK_REGRESSED);
	assert(r.next.last_now_ms == 1100 && r.next.session_start_floor_ms == 1100);
	assert(!r.next.session_active && !r.next.have_sample);
	in.now_ms = 700;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_CLOCK_REGRESSED);
	assert(r.next.last_now_ms == 1100 && r.next.session_start_floor_ms == 1100);
	in.connected = true;
	in.now_ms = in.sample.captured_at_ms = 1101;
	in.session_id = in.sample.session_id = 4;
	in.session_started_at_ms = 1099;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_BAD_SESSION);
	in.session_started_at_ms = 1100;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_GOOD, 3000000, 4430000, false);
}

static void test_detach_time_extremes(void)
{
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_result r;

	in.connected = false;
	in.now_ms = 0;
	r = qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	stopped(r, SMB5_THERMAL_DISCONNECTED);
	assert(r.next.have_now && r.next.session_start_floor_ms == 0);
	in.connected = true;
	in.session_started_at_ms = in.sample.captured_at_ms = 0;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);
	in.connected = false;
	in.now_ms = UINT64_MAX;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_DISCONNECTED);
	assert(r.next.session_start_floor_ms == UINT64_MAX);
	in.connected = true;
	in.session_id = in.sample.session_id = 2;
	in.session_started_at_ms = UINT64_MAX - 1;
	in.sample.captured_at_ms = UINT64_MAX;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_BAD_SESSION);
	in.session_started_at_ms = UINT64_MAX;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_GOOD, 3000000, 4430000, false);
}

static void test_active_session_replacement(void)
{
	static const u64 starts[] = { 150, 199, 200, 201 };
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_result r =
		qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	struct smb5_thermal_state active = r.next;
	unsigned int i;

	/* A larger session ID must not admit data from the previous active window. */
	in.session_id = in.sample.session_id = 2;
	in.now_ms = 201;
	for (i = 0; i < sizeof(starts) / sizeof(starts[0]); i++) {
		in.session_started_at_ms = starts[i];
		in.sample.captured_at_ms = starts[i] == 150 ? 190 : 201;
		r = qcom_smb5_thermal_policy_step(&fixture_config, &active, &in);
		if (starts[i] < 200) {
			stopped(r, SMB5_THERMAL_BAD_SESSION);
			assert(r.next.session_id == 1 && r.next.session_active);
			assert(r.next.last_sample_at_ms == 200 && r.next.last_now_ms == 201);
		} else {
			advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);
		}
	}

	/* Replacing the session must not clear HOT or COLD recovery hysteresis. */
	in = sample(550, 3900000);
	r = qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	in.session_id = in.sample.session_id = 2;
	in.session_started_at_ms = 200;
	in.now_ms = in.sample.captured_at_ms = 201;
	in.sample.temperature_decic = 530;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_STOP_HOT);
	in = sample(-1, 3900000);
	r = qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	in.session_id = in.sample.session_id = 2;
	in.session_started_at_ms = 200;
	in.now_ms = in.sample.captured_at_ms = 201;
	in.sample.temperature_decic = 20;
	stopped(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_STOP_COLD);
}

static void test_replacement_retries_and_clock(void)
{
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_result r =
		qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);

	in.session_id = in.sample.session_id = 2;
	in.session_started_at_ms = 150;
	in.sample.captured_at_ms = 190;
	in.now_ms = 201;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_BAD_SESSION);
	/* Adopt failed next: its clock watermark advances, but the old active
	 * observation is still 200. Correcting to that boundary must succeed.
	 */
	in.session_started_at_ms = in.sample.captured_at_ms = 200;
	in.now_ms = 202;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);

	/* A regressed clock neither installs the proposed session nor lowers the
	 * previous observation. A rejected retry must not poison the next one.
	 */
	in.session_id = in.sample.session_id = 3;
	in.session_started_at_ms = in.sample.captured_at_ms = in.now_ms = 201;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_CLOCK_REGRESSED);
	assert(r.next.session_id == 2 && r.next.last_now_ms == 202);
	in.now_ms = in.sample.captured_at_ms = 203;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_BAD_SESSION);
	in.session_started_at_ms = in.sample.captured_at_ms = 202;
	in.now_ms = 204;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);

	/* A clock error on a later call also cannot lower the established bound. */
	in.now_ms = in.sample.captured_at_ms = 203;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_CLOCK_REGRESSED);
	in.session_id = in.sample.session_id = 4;
	in.session_started_at_ms = 203;
	in.now_ms = in.sample.captured_at_ms = 205;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_BAD_SESSION);
	in.session_started_at_ms = in.sample.captured_at_ms = 204;
	in.now_ms = 206;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_GOOD, 3000000, 4430000, false);
}

static void test_replacement_after_observation_errors(void)
{
	unsigned int i;

	for (i = 0; i < 2; i++) {
		struct smb5_thermal_input in = sample(250, 3900000);
		struct smb5_thermal_result r =
			qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);

		/* Connection identity and clock are valid independently of config or
		 * sensor errors: a later session must start after this observation.
		 */
		in.now_ms = 300;
		in.sample.error = i ? -5 : 0;
		r = qcom_smb5_thermal_policy_step(i ? &fixture_config : NULL, &r.next, &in);
		stopped(r, i ? SMB5_THERMAL_SAMPLE_ERROR : SMB5_THERMAL_BAD_CONFIG);
		in.sample.error = 0;
		in.session_id = in.sample.session_id = 2;
		in.session_started_at_ms = 299;
		in.now_ms = in.sample.captured_at_ms = 301;
		r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
		stopped(r, SMB5_THERMAL_BAD_SESSION);
		in.session_started_at_ms = in.sample.captured_at_ms = 300;
		in.now_ms = 302;
		r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
		advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);

		/* A replacement admitted before a config/sample error can retry with
		 * the same ID and start, even though its observation has advanced.
		 */
		in.session_id = in.sample.session_id = 3;
		in.session_started_at_ms = 302;
		in.now_ms = in.sample.captured_at_ms = 303;
		in.sample.error = i ? -5 : 0;
		r = qcom_smb5_thermal_policy_step(i ? &fixture_config : NULL, &r.next, &in);
		stopped(r, i ? SMB5_THERMAL_SAMPLE_ERROR : SMB5_THERMAL_BAD_CONFIG);
		in.sample.error = 0;
		in.now_ms = 304;
		advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
			SMB5_THERMAL_GOOD, 3000000, 4430000, false);
	}
}

static void test_replacement_time_extremes(void)
{
	struct smb5_thermal_input in = sample(250, 3900000);
	struct smb5_thermal_result r;

	in.session_started_at_ms = in.now_ms = in.sample.captured_at_ms = 0;
	r = qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	in.session_id = in.sample.session_id = 2;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_GOOD, 3000000, 4430000, false);
	in = sample(250, 3900000);
	in.now_ms = in.sample.captured_at_ms = UINT64_MAX - 1;
	r = qcom_smb5_thermal_policy_step(&fixture_config, NULL, &in);
	in.session_id = in.sample.session_id = 2;
	in.session_started_at_ms = UINT64_MAX - 2;
	in.now_ms = in.sample.captured_at_ms = UINT64_MAX;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	stopped(r, SMB5_THERMAL_BAD_SESSION);
	in.session_started_at_ms = UINT64_MAX - 1;
	r = qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in);
	advised(r, SMB5_THERMAL_GOOD, 3000000, 4430000, false);
	in.session_id = in.sample.session_id = 3;
	in.session_started_at_ms = UINT64_MAX;
	advised(qcom_smb5_thermal_policy_step(&fixture_config, &r.next, &in),
		SMB5_THERMAL_GOOD, 3000000, 4430000, false);
}

static void test_global_invariants(void)
{
	int zone, t;
	unsigned int v;

	for (zone = SMB5_THERMAL_UNKNOWN; zone <= SMB5_THERMAL_HOT; zone++) {
		for (t = -401; t <= 1001; t++) {
			for (v = 3999999; v <= 4000001; v++) {
				struct smb5_thermal_state state = {
					.zone = (enum smb5_thermal_zone)zone,
				};
				struct smb5_thermal_input in = sample(t, v);
				struct smb5_thermal_result r =
					qcom_smb5_thermal_policy_step(&fixture_config,
								    &state, &in);

				assert(r.fcc_max_ua <= 3000000 && r.fv_max_uv <= 4430000);
				if (t < 0 || t >= 550)
					assert(r.stop_charging);
				if (r.stop_charging)
					assert(!r.fcc_max_ua && !r.fv_max_uv);
				if (!r.stop_charging && r.next.zone == SMB5_THERMAL_WARM)
					assert(r.fv_max_uv <= 4000000);
				checks++;
			}
		}
	}
}

int smb5_thermal_policy_tests(void)
{
	checks = 0;
	test_reference_boundaries();
	test_hysteresis();
	test_voltage_and_pack_caps();
	test_invalid_inputs();
	test_age_and_order();
	test_errors_and_reconnect();
	test_session_errors();
	test_cold_reconnect_and_good_failure();
	test_required_config_fields();
	test_session_before_known_detach();
	test_detach_time_boundaries();
	test_regressed_detach_clock();
	test_detach_time_extremes();
	test_active_session_replacement();
	test_replacement_retries_and_clock();
	test_replacement_after_observation_errors();
	test_replacement_time_extremes();
	test_global_invariants();
	printf("SMB5 thermal policy: %u behavioral cases passed (offline only)\n", checks);
	fflush(stdout);
	return 0;
}
