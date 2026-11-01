"""Bounded-session orchestration prototype. No transport or device implementation.

The caller must implement identity checks, deadlines, monitoring, and recovery.
This state machine by itself is not permission or a means to boot a phone.
"""


def run_session(io):
    result = {"capture": "NOT_ATTEMPTED", "android_return_verified": False,
              "boot_accepted": False, "success": False}
    monitor_started = False
    may_have_left_android = False
    try:
        io.candidate_gate()
        # Cleanup must tolerate a partially started monitor or acquired lock.
        monitor_started = True
        io.start_monitor()
        before = io.preflight()
        io.validate_android(before)
        io.arm_recovery_deadline()
        # Even a failed/interrupting transition may have reached the device.
        may_have_left_android = True
        io.enter_fastboot()
        io.check_fastboot()
        io.candidate_gate()
        if not io.boot_ram_only():
            raise RuntimeError("RAM boot not confirmed accepted")
        result["boot_accepted"] = True
        result["capture"] = io.capture_touch()
    except BaseException as exc:
        result["error"] = repr(exc)
    finally:
        if may_have_left_android:
            try:
                after = io.recover_android()
                io.validate_return(before, after)
                result["android_return_verified"] = True
            except BaseException as exc:
                result["recovery_error"] = repr(exc)
                result["manual_recovery_required"] = True
        if monitor_started:
            try:
                result["monitor_verified"] = bool(io.stop_and_verify_monitor())
            except BaseException as exc:
                result["monitor_verified"] = False
                result["monitor_error"] = repr(exc)
        result["success"] = (result["boot_accepted"] and result["capture"] == "PASS" and
                             result["android_return_verified"] and result.get("monitor_verified", False) and
                             "error" not in result)
    return result
