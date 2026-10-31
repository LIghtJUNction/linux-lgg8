/* SPDX-License-Identifier: GPL-2.0-only */
/* Offline only. Include the complete production source, including private
 * executor, with host kernel-API shims. The fake backend has abstract state,
 * NOT PM8150B registers, audited modes, measured currents or safety evidence.
 * Public entry points remain blocked even if tests forge private fields.
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sched.h>
#include <time.h>

#include "../../drivers/power/supply/qcom_smb5_input_transaction.c"

enum test_op { STOP, CONFIRM_STOP, CONFIGURE, READBACK, RESUME, CONFIRM_RESUME };
enum test_mode { UNCONFIGURED, LIMITED };

struct interleave;
struct fixture {
	struct qcom_smb5_input_transaction *transaction;
	struct qcom_smb5_input_request request;
	int calls, fail_at, error;
	bool after, stopped, ignore_stop, ignore_resume, configure_unstops;
	bool corrupt_limit, reenter;
	bool resume_entry_stop_requested;
	unsigned int configure_mask;
	u32 limit;
	enum test_mode mode;
	enum test_op log[32];
	struct interleave *interleave;
};

static unsigned int scenarios;
static void callback_gate(struct fixture *f, bool after);

static int begin(struct fixture *f, enum test_op op)
{
	assert(f->calls < 32);
	f->log[f->calls++] = op;
	callback_gate(f, false);
	if (f->calls == f->fail_at && !f->after)
		return f->error;
	return 0;
}

static int finish(struct fixture *f, int ret)
{
	callback_gate(f, true);
	return f->calls == f->fail_at && f->after ? f->error : ret;
}

static int fake_stop(void *cookie)
{
	struct fixture *f = cookie;
	int ret = begin(f, STOP);

	if (ret)
		return ret;
	if (f->reenter) {
		struct qcom_smb5_input_status status;

		assert(qcom_smb5_input_apply(f->transaction, &f->request) == -EBUSY);
		assert(qcom_smb5_input_get_status(f->transaction, &status) == -EBUSY);
	}
	if (!f->ignore_stop)
		f->stopped = true;
	return finish(f, 0);
}

static int fake_confirm_stop(void *cookie)
{
	struct fixture *f = cookie;
	int ret = begin(f, CONFIRM_STOP);

	if (ret)
		return ret;
	return finish(f, f->stopped ? 0 : -EAGAIN);
}

static int fake_configure(void *cookie, const struct qcom_smb5_input_plan *plan)
{
	struct fixture *f = cookie;
	int ret = begin(f, CONFIGURE);

	if (ret)
		return ret;
	assert(f->stopped);
	if (f->configure_mask & 1)
		f->limit = plan->limit_ua + (f->corrupt_limit ? QCOM_SMB5_INPUT_STEP_UA : 0);
	if (f->configure_mask & 2)
		f->mode = LIMITED;
	if (f->configure_unstops)
		f->stopped = false;
	return finish(f, 0);
}

static int fake_readback(void *cookie, const struct qcom_smb5_input_plan *plan)
{
	struct fixture *f = cookie;
	int ret = begin(f, READBACK);

	if (ret)
		return ret;
	return finish(f, f->mode == LIMITED && f->limit == plan->limit_ua ? 0 : -EUCLEAN);
}

static int fake_resume(void *cookie)
{
	struct fixture *f = cookie;
	int ret;

	f->resume_entry_stop_requested = atomic_read_acquire(&f->transaction->stop_requested);
	ret = begin(f, RESUME);

	if (ret)
		return ret;
	assert(f->stopped);
	if (!f->ignore_resume)
		f->stopped = false;
	return finish(f, 0);
}

static int fake_confirm_resume(void *cookie, const struct qcom_smb5_input_plan *plan)
{
	struct fixture *f = cookie;
	int ret = begin(f, CONFIRM_RESUME);

	if (ret)
		return ret;
	return finish(f, !f->stopped && f->mode == LIMITED &&
		      f->limit == plan->limit_ua ? 0 : -EUCLEAN);
}

static const struct smb5_input_backend backend = {
	.stop = fake_stop,
	.confirm_stop = fake_confirm_stop,
	.configure = fake_configure,
	.readback = fake_readback,
	.resume = fake_resume,
	.confirm_resume = fake_confirm_resume,
};

static struct fixture setup(void)
{
	struct fixture f = {
		.transaction = qcom_smb5_input_alloc(),
		.request = { 5000000, 1500000, 1400000, 1249999 },
		.limit = 500000,
		.configure_mask = 3,
	};

	assert(f.transaction);
	return f;
}

static int apply(struct fixture *f)
{
	return smb5_input_apply(f->transaction, &backend, f, &f->request);
}

static int resume_input(struct fixture *f)
{
	return smb5_input_resume(f->transaction, &backend, &f->request);
}

static int stop_only(struct fixture *f)
{
	return smb5_input_stop_only(f->transaction, &backend, f);
}

static struct qcom_smb5_input_status status(struct fixture *f)
{
	struct qcom_smb5_input_status result;

	assert(!qcom_smb5_input_get_status(f->transaction, &result));
	return result;
}

static void isolated(struct fixture *f, int error, enum qcom_smb5_input_stage stage)
{
	struct qcom_smb5_input_status s = status(f);
	int calls = f->calls;
	int expected = error < 0 ? error : -EPROTO;

	assert(s.state == QCOM_SMB5_INPUT_ISOLATED);
	assert(s.first_error == expected && s.failed_stage == stage);
	assert(s.first_raw_result == error);
	assert(s.stop == QCOM_SMB5_INPUT_STOP_UNCONFIRMED && !s.confirmed_limit_ua);
	assert((s.attempted & (1U << stage)) && s.raw_result[stage] == error);
	/* Same-value retries, even after removing the injected fault, cannot
	 * clear isolation or issue any callback. Preserve the original error.
	 */
	f->fail_at = 0;
	assert(apply(f) == expected);
	assert(resume_input(f) == expected);
	assert(qcom_smb5_input_apply(f->transaction, &f->request) == expected);
	assert(qcom_smb5_input_resume(f->transaction, &f->request) == expected);
	assert(f->calls == calls);
	assert(!memcmp(&s, &f->transaction->status, sizeof(s)));
}

static void plan_tests(void)
{
	struct qcom_smb5_input_request r = { 5000000, U32_MAX, U32_MAX, U32_MAX };
	struct qcom_smb5_input_plan plan, previous;
	unsigned int i;
	const u64 invalid[][4] = {
		{ 9000000, 1500000, 1400000, 1000000 },
		{ 5000000, 1500000, 1400000, 0 },
		{ 5000000, 1500000, 1400000, 49999 },
		{ 5000000, 999999, 1400000, 1000000 },
		{ 5000000, 1500000, 999999, 1000000 },
		{ 5000000, 0, 1400000, 50000 },
		{ 5000000, 1500000, 0, 50000 },
		{ 5000000, 1000000, 1400000, 1000001 },
		{ 5000000, 1500000, 1000000, 1000001 },
		{ (u64)U32_MAX + 1, 1500000, 1400000, 1000000 },
		{ 5000000, (u64)U32_MAX + 1, 1400000, 1000000 },
		{ 5000000, 1500000, (u64)U32_MAX + 1, 1000000 },
		{ 5000000, 1500000, 1400000, (u64)U32_MAX + 1 },
		{ 5000000, ~(u64)0, ~(u64)0, ~(u64)0 },
	};

	memset(&plan, 0xa5, sizeof(plan));
	previous = plan;
	assert(qcom_smb5_input_plan(NULL, &plan) == -EINVAL);
	assert(!memcmp(&plan, &previous, sizeof(plan)));
	assert(qcom_smb5_input_plan(&r, NULL) == -EINVAL);
	for (i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
		r = (struct qcom_smb5_input_request) {
			invalid[i][0], invalid[i][1], invalid[i][2], invalid[i][3]
		};
		assert(qcom_smb5_input_plan(&r, &plan) ==
		       (i >= 9 ? -EOVERFLOW : i == 0 ? -EOPNOTSUPP : -ERANGE));
		assert(!memcmp(&plan, &previous, sizeof(plan)));
		scenarios++;
	}
	/* Includes exact 50mA/one-unit-above and the highest u32 input. No raw
	 * register encoding or hardware maximum is inferred from this arithmetic.
	 */
	r = (struct qcom_smb5_input_request) { 5000000, U32_MAX, U32_MAX, 50000 };
	for (i = 0; i < 1000; i++) {
		r.target_ua = i < 2 ? 50000 + i : U32_MAX - i * 173;
		assert(!qcom_smb5_input_plan(&r, &plan));
		assert(plan.limit_ua && !(plan.limit_ua % 50000));
		assert(plan.limit_ua <= r.target_ua && r.target_ua - plan.limit_ua < 50000);
		assert(plan.limit_ua <= r.contract_ua && plan.limit_ua <= r.board_ua);
		scenarios++;
	}
}

static void public_and_lock_tests(void)
{
	struct fixture f = setup();
	struct qcom_smb5_input_status before = status(&f), out;
	struct smb5_input_backend incomplete = backend;

	assert(mutex_trylock(&f.transaction->lock));
	assert(apply(&f) == -EBUSY);
	assert(resume_input(&f) == -EBUSY);
	assert(qcom_smb5_input_apply(f.transaction, &f.request) == -EBUSY);
	assert(qcom_smb5_input_resume(f.transaction, &f.request) == -EBUSY);
	assert(qcom_smb5_input_get_status(f.transaction, &out) == -EBUSY);
	assert(!f.calls && !memcmp(&before, &f.transaction->status, sizeof(before)));
	mutex_unlock(&f.transaction->lock);
	assert(qcom_smb5_input_apply(NULL, &f.request) == -EINVAL);
	assert(qcom_smb5_input_resume(NULL, &f.request) == -EINVAL);
	assert(qcom_smb5_input_stop_only(NULL) == -EINVAL);
	assert(qcom_smb5_input_get_status(NULL, &out) == -EINVAL);
	assert(qcom_smb5_input_get_status(f.transaction, NULL) == -EINVAL);
	assert(qcom_smb5_input_apply(f.transaction, &f.request) == -EOPNOTSUPP);
	assert(!f.calls);
	isolated(&f, -EOPNOTSUPP, QCOM_SMB5_INPUT_MODE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	f = setup();
	/* Even forging all private prepared/backend fields cannot enable the
	 * public path. There is no caller-supplied evidence/callback parameter.
	 */
	f.transaction->backend = &backend;
	f.transaction->cookie = &f;
	f.transaction->status.state = QCOM_SMB5_INPUT_PREPARED;
	f.transaction->status.stop = QCOM_SMB5_INPUT_STOP_BACKEND_CONFIRMED;
	assert(!qcom_smb5_input_plan(&f.request, &f.transaction->prepared));
	assert(qcom_smb5_input_resume(f.transaction, &f.request) == -EOPNOTSUPP);
	assert(!f.calls);
	isolated(&f, -EOPNOTSUPP, QCOM_SMB5_INPUT_MODE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	f = setup();
	incomplete.confirm_resume = NULL;
	assert(smb5_input_apply(f.transaction, &incomplete, &f, &f.request) == -EOPNOTSUPP);
	assert(!f.calls);
	isolated(&f, -EOPNOTSUPP, QCOM_SMB5_INPUT_MODE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	f = setup();
	f.request.target_ua = 49999;
	assert(apply(&f) == -ERANGE && !f.calls);
	isolated(&f, -ERANGE, QCOM_SMB5_INPUT_VALIDATE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;
	f = setup();
	assert(resume_input(&f) == -ESTALE && !f.calls);
	isolated(&f, -ESTALE, QCOM_SMB5_INPUT_RESUME_VALIDATE);
	qcom_smb5_input_free(f.transaction);
	qcom_smb5_input_free(NULL);
	scenarios++;
}

static void fault_tests(void)
{
	const int errors[] = { -EIO, -ETIMEDOUT, -EOPNOTSUPP, 7 };
	const enum qcom_smb5_input_stage stages[] = {
		QCOM_SMB5_INPUT_STOP, QCOM_SMB5_INPUT_CONFIRM_STOP, QCOM_SMB5_INPUT_CONFIGURE,
		QCOM_SMB5_INPUT_READBACK, QCOM_SMB5_INPUT_RECHECK_STOP,
		QCOM_SMB5_INPUT_RESUME_STOP, QCOM_SMB5_INPUT_RESUME_READBACK,
		QCOM_SMB5_INPUT_RESUME, QCOM_SMB5_INPUT_CONFIRM_RESUME,
	};
	const enum test_op operations[] = {
		STOP, CONFIRM_STOP, CONFIGURE, READBACK, CONFIRM_STOP,
		CONFIRM_STOP, READBACK, RESUME, CONFIRM_RESUME,
	};
	unsigned int step, after, e, i;

	for (step = 0; step < 9; step++) for (after = 0; after < 2; after++)
	for (e = 0; e < 4; e++) {
		struct fixture f = setup();
		unsigned int offset = step >= 5 ? 5 : 0;
		int expected = errors[e] < 0 ? errors[e] : -EPROTO;

		if (offset) {
			assert(!apply(&f) && f.stopped);
			f.calls = 0;
		}
		f.fail_at = step - offset + 1;
		f.after = after;
		f.error = errors[e];
		assert((offset ? resume_input(&f) : apply(&f)) == expected);
		assert(f.calls == f.fail_at);
		for (i = 0; i < (unsigned int)f.calls; i++)
			assert(f.log[i] == operations[offset + i]);
		if (step == 0)
			assert(f.stopped == !!after);
		if (step == 2)
			assert(f.limit == (after ? 1200000U : 500000U));
		if (step == 7)
			assert(f.stopped == !after);
		isolated(&f, errors[e], stages[step]);
		qcom_smb5_input_free(f.transaction);
		scenarios++;
	}
}

static void sequence_tests(void)
{
	struct fixture f = setup();
	struct qcom_smb5_input_status s;
	unsigned int i;

	f.reenter = true;
	assert(!apply(&f));
	s = status(&f);
	assert(f.stopped && f.calls == 5 && s.state == QCOM_SMB5_INPUT_PREPARED);
	assert(s.stop == QCOM_SMB5_INPUT_STOP_BACKEND_CONFIRMED && s.confirmed_limit_ua == 1200000);
	assert(!apply(&f)); /* Identical success retries still stop/confirm/rewrite. */
	assert(f.stopped && f.calls == 10);
	assert(!resume_input(&f));
	assert(!f.stopped && f.calls == 14 && status(&f).state == QCOM_SMB5_INPUT_RESUMED);
	assert(!apply(&f)); /* Same value while resumed must stop again. */
	assert(f.stopped && f.calls == 19 && status(&f).state == QCOM_SMB5_INPUT_PREPARED);
	assert(!resume_input(&f) && f.calls == 23);
	assert(resume_input(&f) == -ESTALE && f.calls == 23);
	isolated(&f, -ESTALE, QCOM_SMB5_INPUT_RESUME_VALIDATE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	for (i = 0; i < 4; i++) {
		f = setup();
		assert(!apply(&f));
		if (i == 0)
			f.request.contract_ua--;
		if (i == 1)
			f.request.board_ua--;
		if (i == 2)
			f.request.target_ua--; /* Same quantized limit, different intent. */
		if (i == 3)
			f.request.voltage_uv = 9000000;
		assert(resume_input(&f) == (i == 3 ? -EOPNOTSUPP : -ESTALE));
		assert(f.calls == 5 && f.stopped);
		isolated(&f, i == 3 ? -EOPNOTSUPP : -ESTALE, QCOM_SMB5_INPUT_RESUME_VALIDATE);
		qcom_smb5_input_free(f.transaction);
		scenarios++;
	}
	for (i = 0; i < 3; i++) {
		f = setup();
		assert(!apply(&f));
		if (i == 0)
			f.stopped = false;
		if (i == 1)
			f.mode = UNCONFIGURED;
		if (i == 2)
			f.limit += 50000;
		assert(resume_input(&f) == (i ? -EUCLEAN : -EAGAIN));
		assert(f.calls == (i ? 7 : 6)); /* Never reach resume. */
		isolated(&f, i ? -EUCLEAN : -EAGAIN,
			 i ? QCOM_SMB5_INPUT_RESUME_READBACK : QCOM_SMB5_INPUT_RESUME_STOP);
		qcom_smb5_input_free(f.transaction);
		scenarios++;
	}
	f = setup(); f.ignore_stop = true;
	assert(apply(&f) == -EAGAIN && f.calls == 2 && !f.stopped);
	isolated(&f, -EAGAIN, QCOM_SMB5_INPUT_CONFIRM_STOP);
	qcom_smb5_input_free(f.transaction);
	scenarios++;
	f = setup(); f.corrupt_limit = true;
	assert(apply(&f) == -EUCLEAN && f.calls == 4);
	isolated(&f, -EUCLEAN, QCOM_SMB5_INPUT_READBACK);
	qcom_smb5_input_free(f.transaction);
	scenarios++;
	f = setup(); f.configure_unstops = true;
	assert(apply(&f) == -EAGAIN && f.calls == 5 && !f.stopped);
	isolated(&f, -EAGAIN, QCOM_SMB5_INPUT_RECHECK_STOP);
	qcom_smb5_input_free(f.transaction);
	scenarios++;
	f = setup(); f.configure_unstops = true; f.fail_at = 3; f.after = true; f.error = -EIO;
	assert(apply(&f) == -EIO && f.calls == 3 && !f.stopped);
	isolated(&f, -EIO, QCOM_SMB5_INPUT_CONFIGURE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;
	/* Multi-write configuration can stop after changing only the abstract
	 * limit or only the abstract mode. Neither outcome permits a same-value
	 * retry or publication, regardless of what actually took effect.
	 */
	for (i = 0; i < 4; i++) {
		f = setup();
		f.configure_mask = i; f.fail_at = 3; f.after = true; f.error = -EIO;
		assert(apply(&f) == -EIO && f.calls == 3);
		assert(f.limit == ((i & 1) ? 1200000U : 500000U));
		assert(f.mode == ((i & 2) ? LIMITED : UNCONFIGURED));
		isolated(&f, -EIO, QCOM_SMB5_INPUT_CONFIGURE);
		qcom_smb5_input_free(f.transaction);
		scenarios++;
	}
	f = setup(); assert(!apply(&f)); f.ignore_resume = true;
	assert(resume_input(&f) == -EUCLEAN && f.calls == 9 && f.stopped);
	isolated(&f, -EUCLEAN, QCOM_SMB5_INPUT_CONFIRM_RESUME);
	qcom_smb5_input_free(f.transaction);
	scenarios++;
}

static void assert_latched_after_stop(struct fixture *f, int first, int raw,
				      enum qcom_smb5_input_stage stage)
{
	struct qcom_smb5_input_status s = status(f);
	int calls = f->calls;
	int expected = first ? first : -ESHUTDOWN;

	assert(s.state == QCOM_SMB5_INPUT_ISOLATED && !s.confirmed_limit_ua);
	assert(s.first_error == first && s.first_raw_result == raw);
	if (first)
		assert(s.failed_stage == stage);
	assert(apply(f) == expected && resume_input(f) == expected);
	assert(qcom_smb5_input_apply(f->transaction, &f->request) == expected);
	assert(qcom_smb5_input_resume(f->transaction, &f->request) == expected);
	assert(f->calls == calls);
	assert(!memcmp(&s, &f->transaction->status, sizeof(s)));
}

static void resume_failed_after_effect(struct fixture *f)
{
	assert(!apply(f));
	f->calls = 0;
	f->fail_at = 3; f->after = true; f->error = -EIO;
	assert(resume_input(f) == -EIO);
	assert(!f->stopped && f->calls == 3); /* Resume DID apply before error. */
	f->calls = 0; f->fail_at = 0;
	assert(status(f).stop == QCOM_SMB5_INPUT_STOP_UNCONFIRMED);
}

static void stop_only_tests(void)
{
	const int errors[] = { -ETIMEDOUT, -EOPNOTSUPP, 9 };
	struct fixture f;
	struct qcom_smb5_input_status s;
	struct smb5_input_backend stop_backend = {
		.stop = fake_stop, .confirm_stop = fake_confirm_stop,
	};
	unsigned int step, after, e, i;

	/* The regression: sticky resume error must NOT prevent a subsequent
	 * stop + independent confirmation. Success must NOT clear isolation.
	 */
	f = setup(); resume_failed_after_effect(&f);
	assert(!stop_only(&f));
	assert(f.stopped && f.calls == 2 && f.log[0] == STOP && f.log[1] == CONFIRM_STOP);
	s = status(&f);
	assert(!s.stop_only_error && s.stop_only_attempts == 1);
	assert(s.stop == QCOM_SMB5_INPUT_STOP_BACKEND_CONFIRMED);
	assert_latched_after_stop(&f, -EIO, -EIO, QCOM_SMB5_INPUT_RESUME);
	assert(!stop_only(&f) && f.calls == 4); /* Explicit retry never skips I/O. */
	assert_latched_after_stop(&f, -EIO, -EIO, QCOM_SMB5_INPUT_RESUME);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	/* Fault isolation must not prevent stopping after a partially completed
	 * configuration which also unexpectedly re-enabled the abstract input.
	 */
	for (i = 0; i < 4; i++) {
		f = setup();
		f.configure_mask = i; f.configure_unstops = true;
		f.fail_at = 3; f.after = true; f.error = -ETIMEDOUT;
		assert(apply(&f) == -ETIMEDOUT && !f.stopped && f.calls == 3);
		f.fail_at = 0;
		assert(!stop_only(&f) && f.stopped && f.calls == 5);
		assert(f.log[3] == STOP && f.log[4] == CONFIRM_STOP);
		assert_latched_after_stop(&f, -ETIMEDOUT, -ETIMEDOUT, QCOM_SMB5_INPUT_CONFIGURE);
		qcom_smb5_input_free(f.transaction);
		scenarios++;
	}

	for (step = 0; step < 2; step++) for (after = 0; after < 2; after++)
	for (e = 0; e < 3; e++) {
		int expected = errors[e] > 0 ? -EPROTO : errors[e];

		f = setup(); resume_failed_after_effect(&f);
		f.fail_at = step + 1; f.after = after; f.error = errors[e];
		assert(stop_only(&f) == expected);
		/* Even if the stop write fails, still do exactly one confirmation. */
		assert(f.calls == 2 && f.log[0] == STOP && f.log[1] == CONFIRM_STOP);
		s = status(&f);
		assert(s.stop_only_attempts == 1 && s.stop_only_error == expected);
		assert(s.stop == QCOM_SMB5_INPUT_STOP_UNCONFIRMED);
		assert(s.raw_result[step ? QCOM_SMB5_INPUT_STOP_ONLY_CONFIRM :
					   QCOM_SMB5_INPUT_STOP_ONLY_WRITE] == errors[e]);
		if (!step) {
			assert(f.stopped == !!after);
			/* Failed write before effect also causes an independent stop
			 * mismatch: preserve both errors, not just the returned one.
			 */
			assert(s.raw_result[QCOM_SMB5_INPUT_STOP_ONLY_CONFIRM] ==
			       (after ? 0 : -EAGAIN));
		}
		assert_latched_after_stop(&f, -EIO, -EIO, QCOM_SMB5_INPUT_RESUME);
		f.fail_at = 0;
		assert(!stop_only(&f) && f.stopped && f.calls == 4);
		assert(status(&f).stop == QCOM_SMB5_INPUT_STOP_BACKEND_CONFIRMED);
		assert_latched_after_stop(&f, -EIO, -EIO, QCOM_SMB5_INPUT_RESUME);
		qcom_smb5_input_free(f.transaction);
		scenarios++;
	}

	/* Backend stop success with no effect must fail independent confirmation. */
	f = setup(); resume_failed_after_effect(&f); f.ignore_stop = true;
	assert(stop_only(&f) == -EAGAIN && f.calls == 2 && !f.stopped);
	assert(status(&f).stop == QCOM_SMB5_INPUT_STOP_UNCONFIRMED);
	assert_latched_after_stop(&f, -EIO, -EIO, QCOM_SMB5_INPUT_RESUME);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	f = setup(); assert(!apply(&f)); assert(!resume_input(&f));
	assert(!f.stopped && f.calls == 9);
	assert(!stop_only(&f) && f.stopped && f.calls == 11);
	assert_latched_after_stop(&f, 0, 0, QCOM_SMB5_INPUT_VALIDATE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	/* Each call is bounded, with no implicit retry loop. Repeated failures
	 * and a saturated diagnostic count must never prevent a later explicit
	 * stop. Confirm on each failed write; never rearm apply/resume.
	 */
	f = setup(); resume_failed_after_effect(&f);
	for (i = 0; i < 8; i++) {
		f.fail_at = f.calls + 1; f.after = false; f.error = -ETIMEDOUT;
		assert(stop_only(&f) == -ETIMEDOUT);
		assert(f.calls == (int)(2 * (i + 1)));
		s = status(&f);
		assert(s.stop_only_attempts == i + 1);
		assert(s.stop_only_error == -ETIMEDOUT && s.stop == QCOM_SMB5_INPUT_STOP_UNCONFIRMED);
		assert(s.stop_only_attempted & (1U << QCOM_SMB5_INPUT_STOP_ONLY_WRITE));
		assert(s.stop_only_attempted & (1U << QCOM_SMB5_INPUT_STOP_ONLY_CONFIRM));
		assert_latched_after_stop(&f, -EIO, -EIO, QCOM_SMB5_INPUT_RESUME);
	}
	f.fail_at = 0;
	f.transaction->status.stop_only_attempts = U32_MAX - 1;
	for (i = 0; i < 2; i++) {
		assert(!stop_only(&f) && f.stopped && f.calls == (int)(18 + 2 * i));
		assert(status(&f).stop_only_attempts == U32_MAX);
		assert_latched_after_stop(&f, -EIO, -EIO, QCOM_SMB5_INPUT_RESUME);
	}
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	f = setup(); f.fail_at = 2; f.after = true; f.error = 9;
	assert(stop_only(&f) == -EPROTO && f.stopped && f.calls == 2);
	assert_latched_after_stop(&f, -EPROTO, 9, QCOM_SMB5_INPUT_STOP_ONLY_CONFIRM);
	f.fail_at = 0;
	assert(!stop_only(&f) && f.calls == 4);
	assert(!status(&f).raw_result[QCOM_SMB5_INPUT_STOP_ONLY_CONFIRM]);
	assert_latched_after_stop(&f, -EPROTO, 9, QCOM_SMB5_INPUT_STOP_ONLY_CONFIRM);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	/* Stop-only works before prepare, with no contract/plan/configure/resume
	 * callbacks. It still locks the object, even if there is no first errno.
	 */
	f = setup(); f.request.voltage_uv = 0;
	assert(!smb5_input_stop_only(f.transaction, &stop_backend, &f));
	assert(f.stopped && f.calls == 2);
	assert_latched_after_stop(&f, 0, 0, QCOM_SMB5_INPUT_VALIDATE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	/* A first stop-only error remains intact when that same stage later
	 * succeeds. Latest raw_result may change; first_raw_result must not.
	 */
	f = setup(); f.fail_at = 1; f.after = true; f.error = 9;
	assert(stop_only(&f) == -EPROTO && f.stopped && f.calls == 2);
	assert_latched_after_stop(&f, -EPROTO, 9, QCOM_SMB5_INPUT_STOP_ONLY_WRITE);
	f.fail_at = 0;
	assert(!stop_only(&f) && f.calls == 4);
	assert(!status(&f).raw_result[QCOM_SMB5_INPUT_STOP_ONLY_WRITE]);
	assert_latched_after_stop(&f, -EPROTO, 9, QCOM_SMB5_INPUT_STOP_ONLY_WRITE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	/* Public stop-only must remain blocked even with forged private backend
	 * fields and a sticky resume fault. It must report the stop error while
	 * preserving the resume error, without calling the forged backend.
	 */
	f = setup(); resume_failed_after_effect(&f);
	assert(qcom_smb5_input_stop_only(f.transaction) == -EOPNOTSUPP);
	assert(!f.calls && !f.stopped && !status(&f).stop_only_attempts);
	assert_latched_after_stop(&f, -EIO, -EIO, QCOM_SMB5_INPUT_RESUME);
	qcom_smb5_input_free(f.transaction);
	scenarios++;

	f = setup();
	stop_backend.confirm_stop = NULL;
	assert(smb5_input_stop_only(f.transaction, &stop_backend, &f) == -EOPNOTSUPP);
	assert(!f.calls && !status(&f).stop_only_attempts);
	assert_latched_after_stop(&f, -EOPNOTSUPP, -EOPNOTSUPP, QCOM_SMB5_INPUT_STOP_ONLY_MODE);
	qcom_smb5_input_free(f.transaction);
	scenarios++;
}

struct interleave {
	struct fixture *f;
	pthread_mutex_t gate;
	pthread_cond_t condition;
	pthread_t owner;
	bool reached, released, apply, pause_after, pause_unlock, unlock_gated;
	bool load_gated, stop_parked, stop_released;
	int pause_load_call;
	int pause_call, operation_result, stop_result;
	atomic_bool stop_done;
};

static struct interleave *active_interleave;

static void block_operation(struct interleave *c)
{
	assert(!pthread_mutex_lock(&c->gate));
	c->reached = true;
	assert(!pthread_cond_broadcast(&c->condition));
	while (!c->released)
		assert(!pthread_cond_wait(&c->condition, &c->gate));
	assert(!pthread_mutex_unlock(&c->gate));
}

static void callback_gate(struct fixture *f, bool after)
{
	struct interleave *c = f->interleave;

	if (c && !c->pause_unlock && pthread_equal(pthread_self(), c->owner) &&
	    c->pause_call == f->calls && c->pause_after == after)
		block_operation(c);
}

/* Host mutex instrumentation creates the otherwise tiny final-check/unlock
 * window without inserting hooks or alternate logic into the kernel core.
 */
static void final_unlock_gate(struct mutex *lock)
{
	struct interleave *c = active_interleave;

	if (c && lock == &c->f->transaction->lock && c->pause_unlock &&
	    pthread_equal(pthread_self(), c->owner) && !c->unlock_gated) {
		c->unlock_gated = true;
		block_operation(c);
	}
}

/* Pause AFTER a real acquire load of zero, not before the cancellation check.
 * The host shim returns that same value once released, matching preemption
 * between the load instruction and the subsequent callback/publication.
 */
static void latch_load_gate(const atomic_t *v, int value)
{
	struct interleave *c = active_interleave;

	if (c && v == &c->f->transaction->stop_requested && !value &&
	    pthread_equal(pthread_self(), c->owner) && !c->load_gated &&
	    c->f->calls == c->pause_load_call) {
		c->load_gated = true;
		block_operation(c);
	}
}

/* Hold the stop thread after its exchange, before it acquires the mutex.
 * This exposes pending-request status without racing the stop callbacks.
 */
static void stop_lock_gate(struct mutex *lock)
{
	struct interleave *c = active_interleave;

	if (!c || lock != &c->f->transaction->lock)
		return;
	assert(!pthread_mutex_lock(&c->gate));
	c->stop_parked = true;
	assert(!pthread_cond_broadcast(&c->condition));
	while (!c->stop_released)
		assert(!pthread_cond_wait(&c->condition, &c->gate));
	assert(!pthread_mutex_unlock(&c->gate));
}

static void *operation_thread(void *cookie)
{
	struct interleave *c = cookie;

	c->owner = pthread_self();
	c->operation_result = c->apply ? apply(c->f) : resume_input(c->f);
	return NULL;
}

static void *stop_thread(void *cookie)
{
	struct interleave *c = cookie;

	c->stop_result = stop_only(c->f);
	atomic_store_explicit(&c->stop_done, true, memory_order_release);
	return NULL;
}

static void wait_for_stop_latch(struct qcom_smb5_input_transaction *transaction)
{
	struct timespec start, now;

	assert(!clock_gettime(CLOCK_MONOTONIC, &start));
	while (!atomic_read_acquire(&transaction->stop_requested)) {
		assert(!clock_gettime(CLOCK_MONOTONIC, &now));
		assert(now.tv_sec - start.tv_sec < 3);
		sched_yield();
	}
}

static void threaded_tests(void)
{
	const struct {
		bool apply;
		int pause_call;
		bool after, unlock;
		int callback_error, stop_error;
	} cases[] = {
		{ false, 1, true, false, 0, 0 }, /* Before resume readback. */
		{ false, 2, true, false, 0, 0 }, /* Before entering resume callback. */
		{ false, 3, false, false, 0, 0 }, /* Entered callback, before effect. */
		{ false, 3, true, false, 0, 0 }, /* Resume has already enabled input. */
		{ false, 4, false, false, 0, 0 },
		{ false, 4, true, false, 0, 0 }, /* Before success publication. */
		{ false, 4, true, true, 0, 0 }, /* AFTER final check/publication. */
		{ false, 3, true, false, -EIO, 0 }, /* Enable then return error. */
		{ false, 3, true, false, 0, 1 }, /* Subsequent stop write fails. */
		{ false, 3, true, false, 0, 2 }, /* Subsequent confirmation fails. */
		{ true, 3, true, false, 0, 0 }, /* Stop during configuration. */
		{ true, 5, true, false, 0, 0 }, /* Stop before prepare publication. */
		{ true, 3, true, false, -EIO, 0 },
	};
	unsigned int i, repeat;

	for (repeat = 0; repeat < 16; repeat++)
	for (i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
		struct fixture f = setup();
		struct interleave c = {
			.f = &f, .apply = cases[i].apply, .pause_call = cases[i].pause_call,
			.pause_after = cases[i].after, .pause_unlock = cases[i].unlock,
		};
		struct qcom_smb5_input_status s;
		pthread_t operation, stopper;
		int original_calls = cases[i].pause_call;
		int first = cases[i].unlock ? 0 : cases[i].callback_error ? -EIO : -ECANCELED;

		if (!c.apply)
			assert(!apply(&f));
		f.calls = 0;
		if (cases[i].callback_error) {
			f.fail_at = original_calls; f.after = true; f.error = -EIO;
		}
		if (cases[i].stop_error) {
			f.fail_at = original_calls + cases[i].stop_error;
			f.after = cases[i].stop_error == 2; f.error = -ETIMEDOUT;
		}
		assert(!pthread_mutex_init(&c.gate, NULL));
		assert(!pthread_cond_init(&c.condition, NULL));
		atomic_init(&c.stop_done, false);
		f.interleave = &c;
		active_interleave = &c;
		host_before_unlock = final_unlock_gate;
		assert(!pthread_create(&operation, NULL, operation_thread, &c));
		assert(!pthread_mutex_lock(&c.gate));
		while (!c.reached)
			assert(!pthread_cond_wait(&c.condition, &c.gate));
		assert(!pthread_mutex_unlock(&c.gate));
		assert(!pthread_create(&stopper, NULL, stop_thread, &c));
		wait_for_stop_latch(f.transaction);
		/* Operation is still holding its mutex. Stop did not return EBUSY,
		 * and its request is visible BEFORE the blocked callback returns.
		 */
		assert(!atomic_load_explicit(&c.stop_done, memory_order_acquire));
		assert(!pthread_mutex_lock(&c.gate));
		c.released = true;
		assert(!pthread_cond_broadcast(&c.condition));
		assert(!pthread_mutex_unlock(&c.gate));
		assert(!pthread_join(operation, NULL));
		assert(!pthread_join(stopper, NULL));
		host_before_unlock = NULL;
		active_interleave = NULL;
		f.interleave = NULL;
		assert(c.operation_result == first);
		assert(c.stop_result == (cases[i].stop_error ? -ETIMEDOUT : 0));
		assert(f.calls == original_calls + 2);
		assert(f.log[original_calls] == STOP && f.log[original_calls + 1] == CONFIRM_STOP);
		s = status(&f);
		assert(s.stop_requested && s.state == QCOM_SMB5_INPUT_ISOLATED);
		assert(s.first_error == first && !s.confirmed_limit_ua);
		assert(s.stop_only_attempts == 1);
		if (!cases[i].stop_error) {
			assert(f.stopped && s.stop == QCOM_SMB5_INPUT_STOP_BACKEND_CONFIRMED);
		} else {
			assert(s.stop == QCOM_SMB5_INPUT_STOP_UNCONFIRMED);
			assert(f.stopped == (cases[i].stop_error == 2));
			f.fail_at = 0;
			assert(!stop_only(&f) && f.stopped && f.calls == original_calls + 4);
			assert(status(&f).first_error == first);
		}
		/* A permanent latch survives publication races and repeated calls. */
		assert_latched_after_stop(&f, first, first, cases[i].callback_error ?
					  (c.apply ? QCOM_SMB5_INPUT_CONFIGURE : QCOM_SMB5_INPUT_RESUME) :
					  QCOM_SMB5_INPUT_CANCEL);
		assert(!pthread_cond_destroy(&c.condition));
		assert(!pthread_mutex_destroy(&c.gate));
		qcom_smb5_input_free(f.transaction);
		scenarios++;
	}
}

static void stop_latch_window_tests(void)
{
	unsigned int publish, repeat;

	for (repeat = 0; repeat < 16; repeat++)
	for (publish = 0; publish < 2; publish++) {
		struct fixture f = setup();
		struct interleave c = {
			.f = &f, .pause_call = -1,
			.pause_load_call = publish ? 4 : 2,
		};
		struct qcom_smb5_input_status s;
		pthread_t operation, stopper;
		int first = publish ? 0 : -ECANCELED;
		int pending_calls = publish ? 4 : 3;

		assert(!apply(&f));
		f.calls = 0;
		assert(!pthread_mutex_init(&c.gate, NULL));
		assert(!pthread_cond_init(&c.condition, NULL));
		atomic_init(&c.stop_done, false);
		f.interleave = &c;
		active_interleave = &c;
		host_after_atomic_read = latch_load_gate;
		host_before_lock = stop_lock_gate;
		assert(!pthread_create(&operation, NULL, operation_thread, &c));
		assert(!pthread_mutex_lock(&c.gate));
		while (!c.reached)
			assert(!pthread_cond_wait(&c.condition, &c.gate));
		assert(!pthread_mutex_unlock(&c.gate));
		assert(!pthread_create(&stopper, NULL, stop_thread, &c));
		assert(!pthread_mutex_lock(&c.gate));
		while (!c.stop_parked)
			assert(!pthread_cond_wait(&c.condition, &c.gate));
		assert(atomic_read_acquire(&f.transaction->stop_requested));
		assert(!atomic_load_explicit(&c.stop_done, memory_order_acquire));
		c.released = true;
		assert(!pthread_cond_broadcast(&c.condition));
		assert(!pthread_mutex_unlock(&c.gate));
		assert(!pthread_join(operation, NULL));

		/* The request is permanent, but stop has not run. Neither a software
		 * isolation state nor a successful resume return proves stopped input.
		 */
		assert(!atomic_load_explicit(&c.stop_done, memory_order_acquire));
		assert(c.operation_result == first && f.calls == pending_calls);
		s = status(&f);
		assert(s.stop_requested && !f.stopped && !s.stop_only_attempts);
		assert(s.stop == QCOM_SMB5_INPUT_STOP_UNCONFIRMED);
		assert(s.first_error == first);
		if (publish) {
			/* Latch after the final zero load, before publishing RESUMED.
			 * Readers MUST give stop_requested priority over these fields.
			 */
			assert(!f.resume_entry_stop_requested);
			assert(s.state == QCOM_SMB5_INPUT_RESUMED);
			assert(s.confirmed_limit_ua == 1200000);
		} else {
			/* Latch after the pre-resume zero load, before callback entry:
			 * the callback starts AFTER the request and still enables input.
			 * The next check isolates software state, without undoing enable.
			 */
			assert(f.resume_entry_stop_requested && f.log[2] == RESUME);
			assert(s.state == QCOM_SMB5_INPUT_ISOLATED);
			assert(!s.confirmed_limit_ua);
		}

		assert(!pthread_mutex_lock(&c.gate));
		c.stop_released = true;
		assert(!pthread_cond_broadcast(&c.condition));
		assert(!pthread_mutex_unlock(&c.gate));
		assert(!pthread_join(stopper, NULL));
		host_after_atomic_read = NULL;
		host_before_lock = NULL;
		active_interleave = NULL;
		f.interleave = NULL;
		assert(!c.stop_result && f.stopped && f.calls == pending_calls + 2);
		assert(f.log[pending_calls] == STOP && f.log[pending_calls + 1] == CONFIRM_STOP);
		s = status(&f);
		assert(s.stop_only_attempts == 1 && !s.stop_only_error);
		assert(s.stop == QCOM_SMB5_INPUT_STOP_BACKEND_CONFIRMED);
		assert_latched_after_stop(&f, first, first, QCOM_SMB5_INPUT_CANCEL);
		assert(!pthread_cond_destroy(&c.condition));
		assert(!pthread_mutex_destroy(&c.gate));
		qcom_smb5_input_free(f.transaction);
		scenarios++;
	}
}

int main(void)
{
	plan_tests();
	public_and_lock_tests();
	fault_tests();
	sequence_tests();
	stop_only_tests();
	threaded_tests();
	stop_latch_window_tests();
	printf("SMB5 actual-source offline scenarios: %u passed\n", scenarios);
	return 0;
}
