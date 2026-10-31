// SPDX-License-Identifier: GPL-2.0-only
/*
 * LG d4f335e13d73c4aa2af85581a6ec11b670ee5b94 BTP reference thresholds.
 * Calibration, physical pack limits and hardware shutdown remain unverified.
 * This file is deliberately not connected to the kernel build or any device.
 */
#include "qcom_smb5_thermal_policy.h"

static bool config_valid(const struct smb5_thermal_config *c)
{
	return c && c->max_sample_age_ms && c->min_capacity_mah &&
		c->battery_fcc_max_ua && c->battery_fv_max_uv &&
		c->temperature_min_decic < c->temperature_max_decic &&
		c->voltage_min_uv && c->voltage_min_uv < c->voltage_max_uv &&
		c->battery_fv_max_uv > c->voltage_min_uv &&
		c->battery_fv_max_uv <= c->voltage_max_uv;
}

/* Boundaries are deci-degrees C, with strict '<' recovery comparisons. */
static enum smb5_thermal_zone next_zone(enum smb5_thermal_zone previous, int t)
{
	if (t < 0 || (previous == SMB5_THERMAL_COLD && t < 30))
		return SMB5_THERMAL_COLD;
	if (t < 100 || (previous == SMB5_THERMAL_COOL && t < 120))
		return SMB5_THERMAL_COOL;
	if (t >= 550 || (previous == SMB5_THERMAL_HOT && t >= 520))
		return SMB5_THERMAL_HOT;
	if (t >= 450 || (previous == SMB5_THERMAL_WARM && t >= 430))
		return SMB5_THERMAL_WARM;
	return SMB5_THERMAL_GOOD;
}

static unsigned int lower_limit(unsigned int a, unsigned int b)
{
	return a < b ? a : b;
}

/* LG rounds a percentage of minimum capacity DOWN to 50 mA, in battery units. */
static unsigned int percent_limit(const struct smb5_thermal_config *c,
				  unsigned int percent)
{
	u64 ua = (u64)c->min_capacity_mah * percent / 5000 * 50000;

	return ua < c->battery_fcc_max_ua ? (unsigned int)ua :
		c->battery_fcc_max_ua;
}

struct smb5_thermal_result
qcom_smb5_thermal_policy_step(const struct smb5_thermal_config *config,
			    const struct smb5_thermal_state *state,
			    const struct smb5_thermal_input *input)
{
	struct smb5_thermal_result r = {
		.reason = SMB5_THERMAL_BAD_ARGUMENT,
		.stop_charging = true,
	};
	const struct smb5_thermal_sample *s;

	if (state)
		r.next = *state;
	if (!input)
		return r;
	if ((unsigned int)r.next.zone > SMB5_THERMAL_HOT ||
	    (r.next.session_active && !r.next.session_id) ||
	    (r.next.have_sample && !r.next.session_active)) {
		r.reason = SMB5_THERMAL_BAD_STATE;
		return r;
	}

	/* Observing detach revokes authorization even if its clock is invalid. */
	if (!input->connected) {
		r.next.session_active = false;
		r.next.have_sample = false;
		if (r.next.have_now &&
		    r.next.session_start_floor_ms < r.next.last_now_ms)
			r.next.session_start_floor_ms = r.next.last_now_ms;
	}
	if (r.next.have_now && input->now_ms < r.next.last_now_ms) {
		r.reason = SMB5_THERMAL_CLOCK_REGRESSED;
		return r;
	}
	r.next.last_now_ms = input->now_ms;
	r.next.have_now = true;
	if (!input->connected) {
		if (r.next.session_start_floor_ms < input->now_ms)
			r.next.session_start_floor_ms = input->now_ms;
		r.reason = SMB5_THERMAL_DISCONNECTED;
		return r;
	}
	if (!input->session_id || input->session_started_at_ms > input->now_ms ||
	    input->session_started_at_ms < r.next.session_start_floor_ms ||
	    input->session_id < r.next.session_id ||
	    (input->session_id == r.next.session_id &&
	     (!r.next.session_active || input->session_started_at_ms !=
						 r.next.session_started_at_ms)) ||
	    (input->session_id > r.next.session_id && r.next.session_active &&
	     input->session_started_at_ms < r.next.last_connected_at_ms) ||
	    (input->session_id > r.next.session_id && r.next.session_id &&
	     input->session_started_at_ms < r.next.session_started_at_ms)) {
		r.reason = SMB5_THERMAL_BAD_SESSION;
		return r;
	}
	if (input->session_id != r.next.session_id) {
		r.next.session_id = input->session_id;
		r.next.session_started_at_ms = input->session_started_at_ms;
		r.next.have_sample = false;
	}
	r.next.session_active = true;
	/*
	 * Keep the previous connection observation until session validation passes.
	 * last_now_ms also advances on bad sessions and cannot supply this bound.
	 */
	r.next.last_connected_at_ms = input->now_ms;
	if (!config_valid(config)) {
		r.reason = SMB5_THERMAL_BAD_CONFIG;
		return r;
	}

	s = &input->sample;
	if (s->error) {
		r.reason = SMB5_THERMAL_SAMPLE_ERROR;
		return r;
	}
	if (!s->temperature_valid || !s->voltage_valid) {
		r.reason = SMB5_THERMAL_SAMPLE_INVALID;
		return r;
	}
	if (s->session_id != input->session_id) {
		r.reason = SMB5_THERMAL_SAMPLE_WRONG_SESSION;
		return r;
	}
	if (s->captured_at_ms > input->now_ms) {
		r.reason = SMB5_THERMAL_SAMPLE_FUTURE;
		return r;
	}
	r.age_valid = true;
	r.sample_age_ms = input->now_ms - s->captured_at_ms;
	if (s->captured_at_ms < input->session_started_at_ms) {
		r.reason = SMB5_THERMAL_SAMPLE_BEFORE_SESSION;
		return r;
	}
	if (r.next.have_sample && s->captured_at_ms < r.next.last_sample_at_ms) {
		r.reason = SMB5_THERMAL_SAMPLE_REGRESSED;
		return r;
	}
	/* At the deadline the sample is already expired. */
	if (r.sample_age_ms >= config->max_sample_age_ms) {
		r.reason = SMB5_THERMAL_SAMPLE_EXPIRED;
		return r;
	}
	if (s->temperature_decic < config->temperature_min_decic ||
	    s->temperature_decic > config->temperature_max_decic ||
	    s->voltage_uv < config->voltage_min_uv ||
	    s->voltage_uv > config->voltage_max_uv) {
		r.reason = SMB5_THERMAL_SAMPLE_OUT_OF_RANGE;
		return r;
	}

	r.next.last_sample_at_ms = s->captured_at_ms;
	r.next.have_sample = true;
	r.next.zone = next_zone(r.next.zone, s->temperature_decic);
	if (r.next.zone == SMB5_THERMAL_COLD) {
		r.reason = SMB5_THERMAL_STOP_COLD;
		return r;
	}
	if (r.next.zone == SMB5_THERMAL_HOT) {
		r.reason = SMB5_THERMAL_STOP_HOT;
		return r;
	}
	r.fcc_max_ua = config->battery_fcc_max_ua;
	r.fv_max_uv = config->battery_fv_max_uv;
	if (r.next.zone == SMB5_THERMAL_COOL)
		r.fcc_max_ua = s->voltage_uv >= 4000000 ?
			lower_limit(r.fcc_max_ua, 500000) : percent_limit(config, 30);
	if (r.next.zone == SMB5_THERMAL_WARM) {
		r.fcc_max_ua = percent_limit(config, 50);
		r.fv_max_uv = lower_limit(r.fv_max_uv, 4000000);
	}
	r.chilly = s->temperature_decic >= 0 && s->temperature_decic <= 150;
	if (r.chilly)
		r.fcc_max_ua = lower_limit(r.fcc_max_ua,
			s->voltage_uv >= 4000000 ? 1000000 : percent_limit(config, 50));
	if (!r.fcc_max_ua) {
		r.fv_max_uv = 0;
		r.reason = SMB5_THERMAL_BAD_CONFIG;
		return r;
	}
	r.stop_charging = false;
	r.reason = SMB5_THERMAL_OK;
	return r;
}
