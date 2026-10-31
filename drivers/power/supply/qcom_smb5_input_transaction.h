/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _QCOM_SMB5_INPUT_TRANSACTION_H
#define _QCOM_SMB5_INPUT_TRANSACTION_H

#include <linux/types.h>

/*
 * Unwired transaction core for a future single SMB5 owner. No probe, exports,
 * work, regmap, registration or hardware backend is supplied. All public actions are
 * deliberately blocked with -EOPNOTSUPP: there is NO audited mode in this tree.
 * No string, caller verdict or callback registration can enable a backend.
 *
 * UNRESOLVED before adding an in-tree backend:
 * - Exact PM8150B revision, register ownership and cache/bus semantics.
 * - Input suspend versus battery charge disable; independent stop observation,
 *   its settling/polling bounds, and system-power implications of suspension.
 * - Complete ICL/SDP/APSD/AICL/override mode tuple and effective-limit readback;
 *   a configuration byte or suspend command echo is not sufficient evidence.
 * - Ambiguous/partial writes, autonomous mode changes and resume confirmation.
 * - One owner excluding every other software/firmware writer, runtime power,
 *   fresh 5V contract, battery/thermal protection and contract revocation.
 * - Contract generations/ABA: equal numeric limits do not identify the same
 *   contract. No generation token, revocation/cancellation barrier is present.
 * - Concurrent lifecycle: no refcount or teardown synchronization. Callers
 *   must keep the object/backend/cookie alive until ALL calls have returned,
 *   including stop callers blocked on the mutex. No callback preemption or
 *   wall-clock stop deadline is implemented. Contract lifetime is unresolved.
 *
 * Existing source: qcom_smbx.c names USBIN_CMD_IL (base+0x340), suspend bit 0,
 * and USBIN_CURRENT_LIMIT_CFG (base+0x370). It is NOT a PM8150B protocol proof.
 * lgg8/docs/CHARGING.md records downstream d4f335e13d73c4aa2af85581a6ec11b670ee5b94:
 * its ICL helper can unsuspend before a later AICL error. Do not reuse it as
 * configure-while-stopped. The 50mA unit below is a planning unit, not proof
 * that a raw register code, mode or requested limit is effective on hardware.
 */
#define QCOM_SMB5_INPUT_STEP_UA 50000U
#define QCOM_SMB5_INPUT_VOLTAGE_UV 5000000U

struct qcom_smb5_input_request {
	u64 voltage_uv;
	u64 contract_ua;
	u64 board_ua;
	u64 target_ua;
};

struct qcom_smb5_input_plan {
	u32 voltage_uv;
	u32 contract_ua;
	u32 board_ua;
	u32 target_ua;
	u32 limit_ua;
};

enum qcom_smb5_input_state {
	QCOM_SMB5_INPUT_UNKNOWN,
	QCOM_SMB5_INPUT_PREPARED,
	QCOM_SMB5_INPUT_RESUMED,
	QCOM_SMB5_INPUT_ISOLATED,
};

enum qcom_smb5_input_stop {
	QCOM_SMB5_INPUT_STOP_UNCONFIRMED,
	QCOM_SMB5_INPUT_STOP_BACKEND_CONFIRMED,
};

enum qcom_smb5_input_stage {
	QCOM_SMB5_INPUT_VALIDATE,
	QCOM_SMB5_INPUT_MODE,
	QCOM_SMB5_INPUT_STOP,
	QCOM_SMB5_INPUT_CONFIRM_STOP,
	QCOM_SMB5_INPUT_CONFIGURE,
	QCOM_SMB5_INPUT_READBACK,
	QCOM_SMB5_INPUT_RECHECK_STOP,
	QCOM_SMB5_INPUT_RESUME_VALIDATE,
	QCOM_SMB5_INPUT_RESUME_STOP,
	QCOM_SMB5_INPUT_RESUME_READBACK,
	QCOM_SMB5_INPUT_RESUME,
	QCOM_SMB5_INPUT_CONFIRM_RESUME,
	QCOM_SMB5_INPUT_CANCEL,
	QCOM_SMB5_INPUT_STOP_ONLY_MODE,
	QCOM_SMB5_INPUT_STOP_ONLY_WRITE,
	QCOM_SMB5_INPUT_STOP_ONLY_CONFIRM,
	QCOM_SMB5_INPUT_STAGE_COUNT,
};

struct qcom_smb5_input_status {
	enum qcom_smb5_input_state state;
	enum qcom_smb5_input_stop stop;
	/* First errno is sticky for this object's lifetime; no rearm/reset API. */
	int first_error;
	/* Never overwritten, even when a later stop-only retries the same stage. */
	int first_raw_result;
	enum qcom_smb5_input_stage failed_stage;
	/* Attempted stages and original callback results, including invalid >0. */
	u32 attempted;
	int raw_result[QCOM_SMB5_INPUT_STAGE_COUNT];
	/* Zero on any failure. May remain nonzero while a stop request is pending.
	 * This is not measured current, physical safety or authorization to enable.
	 */
	u32 confirmed_limit_ua;
	/* Latest stop-only outcome is separate from the sticky first error.
	 * attempted uses stage bits and describes only the latest stop-only call.
	 */
	/* Saturating diagnostic counter, never a gate preventing further stop. */
	u32 stop_only_attempts;
	u32 stop_only_attempted;
	int stop_only_error;
	/* Check FIRST, before state/confirmed_limit_ua. This permanent request can
	 * coexist with PREPARED/RESUMED and a nonzero limit while stop is pending.
	 * It does NOT mean stop was issued or confirmed, or input cannot enable.
	 */
	bool stop_requested;
};

struct qcom_smb5_input_transaction;

/* Pure arithmetic; output untouched on error. No hardware maximum is assumed.
 * Reject >u32 values, non-5V, zero/sub-step targets and target above either cap
 * BEFORE rounding down. Zero is not an implicit stop/resume command.
 */
int qcom_smb5_input_plan(const struct qcom_smb5_input_request *request,
			 struct qcom_smb5_input_plan *plan);

/* Sleepable. Allocate once per owner lifetime, before publishing the object.
 * The mutex serializes this object only, not firmware/other SMB5 writers.
 * The owner must hold its own exclusion and contract/power lifetime throughout
 * apply and the separate resume; never replace an isolated object as recovery.
 */
struct qcom_smb5_input_transaction *qcom_smb5_input_alloc(void);
/* Caller must quiesce all users first. Free performs NO hardware action. */
void qcom_smb5_input_free(struct qcom_smb5_input_transaction *transaction);
int qcom_smb5_input_apply(struct qcom_smb5_input_transaction *transaction,
			  const struct qcom_smb5_input_request *request);
/* Explicit later call; request must still match the prepared contract/plan.
 * Validation of live voltage/contract is unresolved, not caller self-attested.
 * Completion can race a stop request: success/RESUMED is not authorization
 * when stop_requested is set, nor proof that no later request can arrive.
 */
int qcom_smb5_input_resume(struct qcom_smb5_input_transaction *transaction,
			   const struct qcom_smb5_input_request *request);
/* Callable despite first_error/isolation, without a valid contract or plan.
 * After acquiring the mutex, latches isolation, invalidates the configured
 * limit, and NEVER rearms apply/resume. At most one stop + one independent
 * confirmation per call, even if stop reports failure. Explicit later calls
 * may try again regardless of old faults or attempt count; no lifetime budget
 * may block further stop.
 * The backend must separately bound each callback; no wall-clock deadline or
 * preemption of a hung callback is supplied here. This call first atomically
 * latches a permanent stop request, then WAITS for the transaction mutex;
 * it never discards a request with -EBUSY. Sleepable, non-reentrant: never
 * call from a backend callback, with this mutex held, or under a lock needed
 * by an in-flight callback. No interrupt/atomic-context use is supported.
 * apply/resume check the latch between callbacks and before publication, but
 * a zero read does not atomically exclude a later callback or publication.
 * Resume can ENTER its callback AFTER the latch and still enable input. If
 * its final check already read zero, it can publish RESUMED/nonzero limit and
 * return success AFTER the latch. Cancellation/isolation likewise does not
 * prove stopped input. Once the in-flight transaction releases the mutex,
 * this caller acquires it, isolates state, and runs stop/confirmation. This is
 * serialized eventual service ONLY IF callbacks return and callers progress,
 * not a physical stop guarantee. The latch is never reset by this API.
 *
 * Returns THIS stop-only result (0 or its error), not the sticky first error.
 * Both raw outcomes are recorded; a write error plus successful confirmation
 * still leaves stop UNCONFIRMED. Two successes record BACKEND_CONFIRMED only;
 * isolation and the original first_error/failed_stage/first_raw_result remain.
 * Public path still has no audited backend and performs no hardware access.
 */
int qcom_smb5_input_stop_only(struct qcom_smb5_input_transaction *transaction);
/* Snapshot only. Check stop_requested FIRST, before state or confirmed limit:
 * true can coexist with RESUMED/nonzero limit while stop awaits the mutex.
 * It is a request, not stop confirmation; false does not reserve permission
 * against a later request. Neither a snapshot nor a resume return authorizes
 * charging or proves physical isolation. See stop_only's service limitations.
 */
int qcom_smb5_input_get_status(struct qcom_smb5_input_transaction *transaction,
			       struct qcom_smb5_input_status *status);

/* For apply/resume/get_status, -EBUSY leaves shared state unchanged. stop_only
 * uses the persistent request latch and a blocking mutex instead. All other
 * operation failures latch isolation and invalidate stop/limit confirmation.
 * Releasing the software mutex never clears that latch. No automatic retry,
 * rollback, resume or physical-safe claim is made, even for an identical plan.
 * Explicit bounded stop-only is the sole exception to refusing further I/O
 * after a fault; it can never clear the isolation latch.
 */
#endif
