/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef QCOM_SMB5_THERMAL_POLICY_H
#define QCOM_SMB5_THERMAL_POLICY_H

#ifdef __KERNEL__
#include <linux/types.h>
#else
#include <stdbool.h>
#include <stdint.h>
typedef uint64_t u64;
#endif

/* Pure advisory policy only: no clocks, allocation, I/O or charger ownership. */
enum smb5_thermal_zone {
	SMB5_THERMAL_UNKNOWN,
	SMB5_THERMAL_COLD,
	SMB5_THERMAL_COOL,
	SMB5_THERMAL_GOOD,
	SMB5_THERMAL_WARM,
	SMB5_THERMAL_HOT,
};

enum smb5_thermal_reason {
	SMB5_THERMAL_OK,
	SMB5_THERMAL_BAD_ARGUMENT,
	SMB5_THERMAL_BAD_CONFIG,
	SMB5_THERMAL_BAD_STATE,
	SMB5_THERMAL_DISCONNECTED,
	SMB5_THERMAL_BAD_SESSION,
	SMB5_THERMAL_CLOCK_REGRESSED,
	SMB5_THERMAL_SAMPLE_ERROR,
	SMB5_THERMAL_SAMPLE_INVALID,
	SMB5_THERMAL_SAMPLE_WRONG_SESSION,
	SMB5_THERMAL_SAMPLE_FUTURE,
	SMB5_THERMAL_SAMPLE_BEFORE_SESSION,
	SMB5_THERMAL_SAMPLE_REGRESSED,
	SMB5_THERMAL_SAMPLE_EXPIRED,
	SMB5_THERMAL_SAMPLE_OUT_OF_RANGE,
	SMB5_THERMAL_STOP_COLD,
	SMB5_THERMAL_STOP_HOT,
};

/*
 * All fields are required; there is no charge-permitting default config.
 * These limits require pack identification, calibration and real-device evidence.
 * max_sample_age_ms must include sensor latency, scheduling and suspend behavior.
 * min_capacity_mah feeds the LG percentage rules, not the USB input-current limit.
 */
struct smb5_thermal_config {
	u64 max_sample_age_ms;
	unsigned int min_capacity_mah;
	unsigned int battery_fcc_max_ua;
	unsigned int battery_fv_max_uv;
	int temperature_min_decic;
	int temperature_max_decic;
	unsigned int voltage_min_uv;
	unsigned int voltage_max_uv;
};

/* TEMP and voltage must belong to one coherent, calibrated acquisition. */
struct smb5_thermal_sample {
	u64 session_id;
	u64 captured_at_ms;
	bool temperature_valid;
	bool voltage_valid;
	int error; /* Any nonzero provider error vetoes the entire sample. */
	int temperature_decic; /* Signed 0.1 degrees C; -1 is a real temperature. */
	unsigned int voltage_uv; /* Battery voltage, not VBUS and not OCV. */
};

struct smb5_thermal_input {
	bool connected;
	u64 session_id; /* Nonzero, strictly increasing on every attach; never wrap. */
	u64 session_started_at_ms;
	u64 now_ms; /* Monotonic elapsed time INCLUDING suspend, same clock as sample. */
	struct smb5_thermal_sample sample;
};

/* Zero-initialize once. Preserve across errors, detach and reconnect. */
struct smb5_thermal_state {
	enum smb5_thermal_zone zone;
	u64 session_id;
	u64 session_started_at_ms;
	/* Valid detach time, or last trusted time when the detach clock failed. */
	u64 session_start_floor_ms;
	u64 last_sample_at_ms;
	u64 last_now_ms;
	/*
	 * Last connected observation with a valid clock and session identity.
	 * Config/sample errors still record it; bad sessions and clock rollback do not.
	 */
	u64 last_connected_at_ms;
	bool session_active;
	bool have_sample;
	bool have_now;
};

struct smb5_thermal_result {
	struct smb5_thermal_state next;
	enum smb5_thermal_reason reason;
	bool stop_charging;
	bool chilly;
	bool age_valid;
	u64 sample_age_ms;
	unsigned int fcc_max_ua;
	unsigned int fv_max_uv;
};

/*
 * state may be NULL for the initial evaluation; config/input must not be NULL.
 * Caller serializes evaluations and adopts next even when stop_charging is true.
 * Repeated samples are usable only until their original timestamp expires.
 * Failure preserves thermal hysteresis. Disconnect revokes the session, while
 * retaining COLD/HOT hysteresis so replug cannot bypass recovery thresholds.
 * A new session must start at or after the retained detach-time lower bound.
 * A regressed detach clock still revokes the session and raises that bound to
 * the last trusted time, never the invalid timestamp; last_now_ms is unchanged.
 * Replacing an active session also requires a start at/after its last connected
 * observation, captured before this call. A rejected session may advance the
 * clock watermark, but never this observation, so a corrected retry can succeed.
 *
 * stop_charging=false means only "no thermal veto", NEVER hardware authorization.
 * A stop result with zero limits supplies no FV/FCC programming instruction.
 * Apply stop unconditionally; matching previous advice is not proof of hardware
 * state. An eventual executor needs independent fault latching/write verification.
 */
struct smb5_thermal_result
qcom_smb5_thermal_policy_step(const struct smb5_thermal_config *config,
			    const struct smb5_thermal_state *state,
			    const struct smb5_thermal_input *input);

#endif /* QCOM_SMB5_THERMAL_POLICY_H */
