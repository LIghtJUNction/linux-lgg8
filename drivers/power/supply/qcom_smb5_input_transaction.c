// SPDX-License-Identifier: GPL-2.0-only
#include <linux/atomic.h>
#include <linux/errno.h>
#include <linux/limits.h>
#include <linux/mutex.h>
#include <linux/slab.h>

#include "qcom_smb5_input_transaction.h"

/* Private operation boundary for a FUTURE compiled-in, reviewed mode. There
 * is intentionally no public setter for these operations. Each confirmation
 * must make independent live observations; register/cache echoes do not meet
 * the contract. All operations are sleepable, bounded, non-reentrant, and use
 * 0/-errno. configure must never resume input, even transiently.
 *
 * Offline tests replace only this boundary and compile this exact source.
 * Their callbacks establish no SMB5 register semantics or safety evidence.
 */
struct smb5_input_backend {
	int (*stop)(void *cookie);
	int (*confirm_stop)(void *cookie);
	int (*configure)(void *cookie, const struct qcom_smb5_input_plan *plan);
	int (*readback)(void *cookie, const struct qcom_smb5_input_plan *plan);
	int (*resume)(void *cookie);
	int (*confirm_resume)(void *cookie, const struct qcom_smb5_input_plan *plan);
};

struct qcom_smb5_input_transaction {
	/* Permanent request, published before waiting for lock. A zero check does
	 * not atomically exclude a later enable or success publication; the waiting
	 * stop caller services the request after the in-flight transaction.
	 */
	atomic_t stop_requested;
	/* Serializes state, diagnostics and the complete sleepable transaction. */
	struct mutex lock;
	struct qcom_smb5_input_status status;
	struct qcom_smb5_input_plan prepared;
	const struct smb5_input_backend *backend;
	void *cookie;
};

int qcom_smb5_input_plan(const struct qcom_smb5_input_request *request,
			 struct qcom_smb5_input_plan *plan)
{
	struct qcom_smb5_input_plan next;

	if (!request || !plan)
		return -EINVAL;
	if (request->voltage_uv > U32_MAX || request->contract_ua > U32_MAX ||
	    request->board_ua > U32_MAX || request->target_ua > U32_MAX)
		return -EOVERFLOW;
	if (request->voltage_uv != QCOM_SMB5_INPUT_VOLTAGE_UV)
		return -EOPNOTSUPP;
	if (request->target_ua < QCOM_SMB5_INPUT_STEP_UA ||
	    request->target_ua > request->contract_ua ||
	    request->target_ua > request->board_ua)
		return -ERANGE;

	next.voltage_uv = request->voltage_uv;
	next.contract_ua = request->contract_ua;
	next.board_ua = request->board_ua;
	next.target_ua = request->target_ua;
	next.limit_ua = next.target_ua / QCOM_SMB5_INPUT_STEP_UA * QCOM_SMB5_INPUT_STEP_UA;
	*plan = next;
	return 0;
}

struct qcom_smb5_input_transaction *qcom_smb5_input_alloc(void)
{
	struct qcom_smb5_input_transaction *transaction;

	transaction = kzalloc_obj(*transaction);
	if (transaction) {
		atomic_set(&transaction->stop_requested, 0);
		mutex_init(&transaction->lock);
	}
	return transaction;
}

void qcom_smb5_input_free(struct qcom_smb5_input_transaction *transaction)
{
	if (!transaction)
		return;
	mutex_destroy(&transaction->lock);
	kfree(transaction);
}

static int smb5_input_record(struct qcom_smb5_input_transaction *transaction,
			     enum qcom_smb5_input_stage stage, int ret)
{
	struct qcom_smb5_input_status *status = &transaction->status;

	status->attempted |= 1U << stage;
	status->raw_result[stage] = ret;
	if (!ret)
		return 0;
	if (!status->first_error) {
		status->first_error = ret < 0 ? ret : -EPROTO;
		status->first_raw_result = ret;
		status->failed_stage = stage;
	}
	status->state = QCOM_SMB5_INPUT_ISOLATED;
	status->stop = QCOM_SMB5_INPUT_STOP_UNCONFIRMED;
	status->confirmed_limit_ua = 0;
	/* Do not issue compensating writes or treat an error as non-application. */
	return status->first_error;
}

static bool smb5_input_backend_complete(const struct smb5_input_backend *backend)
{
	return backend && backend->stop && backend->confirm_stop && backend->configure &&
		backend->readback && backend->resume && backend->confirm_resume;
}

static bool smb5_input_same_plan(const struct qcom_smb5_input_plan *a,
				 const struct qcom_smb5_input_plan *b)
{
	return a->voltage_uv == b->voltage_uv && a->contract_ua == b->contract_ua &&
		a->board_ua == b->board_ua && a->target_ua == b->target_ua &&
		a->limit_ua == b->limit_ua;
}

static int smb5_input_cancelled(struct qcom_smb5_input_transaction *transaction)
{
	if (!atomic_read_acquire(&transaction->stop_requested))
		return 0;
	transaction->status.stop_requested = true;
	/* The waiting stop caller owns the stop/confirmation operation. Do not
	 * hide an earlier callback error or initiate another enable on its behalf.
	 */
	return smb5_input_record(transaction, QCOM_SMB5_INPUT_CANCEL, -ECANCELED);
}

/* This is the actual transaction executor, not a parallel testing model. A
 * future owner integration must add an audited backend here in source; the
 * current public path always supplies NULL and cannot reach any callback.
 */
static int smb5_input_apply(struct qcom_smb5_input_transaction *transaction,
			    const struct smb5_input_backend *backend, void *cookie,
			    const struct qcom_smb5_input_request *request)
{
	struct qcom_smb5_input_plan plan;
	int ret;

	if (!transaction)
		return -EINVAL;
	if (!mutex_trylock(&transaction->lock))
		return -EBUSY;
	ret = transaction->status.first_error;
	if (!ret && transaction->status.state == QCOM_SMB5_INPUT_ISOLATED)
		ret = -ESHUTDOWN;
	if (ret)
		goto out;
	transaction->status = (struct qcom_smb5_input_status) { };
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_VALIDATE,
				qcom_smb5_input_plan(request, &plan));
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_MODE,
				smb5_input_backend_complete(backend) ? 0 : -EOPNOTSUPP);
	if (ret)
		goto out;

	/* Do the full stop/configuration sequence even for an identical request.
	 * Invalidate observations before the very first potentially effective write.
	 */
	transaction->backend = backend;
	transaction->cookie = cookie;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_STOP, backend->stop(cookie));
	if (ret)
		goto out;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_CONFIRM_STOP,
				backend->confirm_stop(cookie));
	if (ret)
		goto out;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_CONFIGURE,
				backend->configure(cookie, &plan));
	if (ret)
		goto out;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_READBACK,
				backend->readback(cookie, &plan));
	if (ret)
		goto out;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_RECHECK_STOP,
				backend->confirm_stop(cookie));
	if (ret)
		goto out;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	transaction->prepared = plan;
	transaction->status.state = QCOM_SMB5_INPUT_PREPARED;
	transaction->status.stop = QCOM_SMB5_INPUT_STOP_BACKEND_CONFIRMED;
	transaction->status.confirmed_limit_ua = plan.limit_ua;
out:
	mutex_unlock(&transaction->lock);
	return ret;
}

int qcom_smb5_input_apply(struct qcom_smb5_input_transaction *transaction,
			  const struct qcom_smb5_input_request *request)
{
	/* No audited PM8150B mode exists. Never take a caller's audit verdict. */
	return smb5_input_apply(transaction, NULL, NULL, request);
}

static int smb5_input_resume(struct qcom_smb5_input_transaction *transaction,
			     const struct smb5_input_backend *backend,
			     const struct qcom_smb5_input_request *request)
{
	struct qcom_smb5_input_plan plan;
	int ret;

	if (!transaction)
		return -EINVAL;
	if (!mutex_trylock(&transaction->lock))
		return -EBUSY;
	ret = transaction->status.first_error;
	if (!ret && transaction->status.state == QCOM_SMB5_INPUT_ISOLATED)
		ret = -ESHUTDOWN;
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_MODE,
				smb5_input_backend_complete(backend) ? 0 : -EOPNOTSUPP);
	if (ret)
		goto out;
	ret = qcom_smb5_input_plan(request, &plan);
	if (!ret && (transaction->status.state != QCOM_SMB5_INPUT_PREPARED ||
		     transaction->backend != backend ||
		     !smb5_input_same_plan(&plan, &transaction->prepared)))
		ret = -ESTALE;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_RESUME_VALIDATE, ret);
	if (ret)
		goto out;
	transaction->status.stop = QCOM_SMB5_INPUT_STOP_UNCONFIRMED;
	transaction->status.confirmed_limit_ua = 0;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_RESUME_STOP,
				backend->confirm_stop(transaction->cookie));
	if (ret)
		goto out;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_RESUME_READBACK,
				backend->readback(transaction->cookie, &plan));
	if (ret)
		goto out;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_RESUME,
				backend->resume(transaction->cookie));
	if (ret)
		goto out;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	ret = smb5_input_record(transaction, QCOM_SMB5_INPUT_CONFIRM_RESUME,
				backend->confirm_resume(transaction->cookie, &plan));
	if (ret)
		goto out;
	ret = smb5_input_cancelled(transaction);
	if (ret)
		goto out;
	transaction->status.state = QCOM_SMB5_INPUT_RESUMED;
	transaction->status.confirmed_limit_ua = plan.limit_ua;
out:
	mutex_unlock(&transaction->lock);
	return ret;
}

int qcom_smb5_input_resume(struct qcom_smb5_input_transaction *transaction,
			   const struct qcom_smb5_input_request *request)
{
	/* Do not trust even a forged prepared state/backend in caller memory. */
	return smb5_input_resume(transaction, NULL, request);
}

static int smb5_input_stop_record(struct qcom_smb5_input_transaction *transaction,
				  enum qcom_smb5_input_stage stage, int raw)
{
	transaction->status.stop_only_attempted |= 1U << stage;
	smb5_input_record(transaction, stage, raw);
	/* Report this action's error independently of the sticky first error. */
	return raw > 0 ? -EPROTO : raw;
}

static int smb5_input_stop_only(struct qcom_smb5_input_transaction *transaction,
				const struct smb5_input_backend *backend, void *cookie)
{
	struct qcom_smb5_input_status *status;
	int ret, confirm, stage;

	if (!transaction)
		return -EINVAL;
	/* Latch first, then wait so the request is serviced after the in-flight
	 * transaction. Resume may still start a callback or publish success AFTER
	 * the latch if its preceding check read zero. Waiting preserves eventual
	 * stop service; it does not close those enable/publication windows.
	 * Must not be called by a backend callback or while holding this lock.
	 */
	atomic_xchg(&transaction->stop_requested, 1);
	mutex_lock(&transaction->lock);
	status = &transaction->status;
	status->stop_requested = true;
	/* Deliberately do not gate stop-only on first_error or the old state. */
	status->state = QCOM_SMB5_INPUT_ISOLATED;
	status->stop = QCOM_SMB5_INPUT_STOP_UNCONFIRMED;
	status->confirmed_limit_ua = 0;
	status->stop_only_attempted = 0;
	for (stage = QCOM_SMB5_INPUT_STOP_ONLY_MODE; stage < QCOM_SMB5_INPUT_STAGE_COUNT; stage++)
		status->raw_result[stage] = 0;

	ret = smb5_input_stop_record(transaction, QCOM_SMB5_INPUT_STOP_ONLY_MODE,
				     backend && backend->stop && backend->confirm_stop ?
				     0 : -EOPNOTSUPP);
	if (ret)
		goto out;
	/* Bound each call, not the lifetime ability to attempt another stop. */
	if (status->stop_only_attempts < U32_MAX)
		status->stop_only_attempts++;
	ret = smb5_input_stop_record(transaction, QCOM_SMB5_INPUT_STOP_ONLY_WRITE,
				     backend->stop(cookie));
	/* An ambiguous write may have applied. Always make the independent
	 * observation, record BOTH outcomes, and preserve the write error.
	 */
	confirm = smb5_input_stop_record(transaction, QCOM_SMB5_INPUT_STOP_ONLY_CONFIRM,
					 backend->confirm_stop(cookie));
	if (!ret)
		ret = confirm;
	if (!ret)
		status->stop = QCOM_SMB5_INPUT_STOP_BACKEND_CONFIRMED;
out:
	status->stop_only_error = ret;
	mutex_unlock(&transaction->lock);
	return ret;
}

int qcom_smb5_input_stop_only(struct qcom_smb5_input_transaction *transaction)
{
	/* No backend selection from caller memory, even when already isolated. */
	return smb5_input_stop_only(transaction, NULL, NULL);
}

int qcom_smb5_input_get_status(struct qcom_smb5_input_transaction *transaction,
			       struct qcom_smb5_input_status *status)
{
	if (!transaction || !status)
		return -EINVAL;
	if (!mutex_trylock(&transaction->lock))
		return -EBUSY;
	*status = transaction->status;
	/* A pending request may coexist with RESUMED and a nonzero limit.
	 * Readers must give this latch priority; the snapshot is not authorization.
	 */
	status->stop_requested = atomic_read_acquire(&transaction->stop_requested);
	mutex_unlock(&transaction->lock);
	return 0;
}
