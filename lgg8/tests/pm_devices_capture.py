"""Device-PM diagnostic only; a successful result is not real system sleep."""
import re
import time


def command(nonce):
    if re.fullmatch(r"[A-F0-9]{24}", nonce) is None:
        raise ValueError("invalid nonce")
    # Only freeze when the kernel reports devices as the active test level.
    # Marker names are printed as whole lines, never accepted from shell echo.
    prefix = "PMDEV_" + nonce
    script = (
        "if printf 'devices\\n' > /sys/power/pm_test && "
        "/bin/busybox grep -q '\\[devices\\]' /sys/power/pm_test; then "
        f"printf '\\n{prefix}_SELECTED\\n'; "
        "printf 'freeze\\n' > /sys/power/state; r=$?; "
        f"printf '\\n{prefix}_RETURN_%s\\n' \"$r\"; "
        "else " + f"printf '\\n{prefix}_SELECT_FAILED\\n'; fi; "
        "printf 'none\\n' > /sys/power/pm_test; r=$?; "
        f"printf '\\n{prefix}_RESET_%s\\n' \"$r\"\n"
    )
    return script.encode(), prefix


def parse(data, prefix):
    lines = data.replace(b"\r", b"").split(b"\n")[:-1]
    selected = (prefix + "_SELECTED").encode() in lines
    select_failed = (prefix + "_SELECT_FAILED").encode() in lines
    ret = [x for x in lines if re.fullmatch(re.escape(prefix.encode()) + rb"_RETURN_[0-9]+", x)]
    reset = [x for x in lines if re.fullmatch(re.escape(prefix.encode()) + rb"_RESET_[0-9]+", x)]
    if not reset:
        return None
    selected_line = (prefix + "_SELECTED").encode()
    return_line = (prefix + "_RETURN_0").encode()
    reset_line = (prefix + "_RESET_0").encode()
    success = (lines.count(selected_line) == 1 and not select_failed and
               ret == [return_line] and reset == [reset_line] and
               lines.index(selected_line) < lines.index(return_line) < lines.index(reset_line))
    begin, end = (prefix + "_LOG_BEGIN").encode(), (prefix + "_LOG_END").encode()
    log = []
    if lines.count(begin) == lines.count(end) == 1:
        start, stop = lines.index(begin), lines.index(end)
        if start < stop and stop - start <= 81:
            log = [line[:512].decode('utf-8', errors='replace') for line in lines[start + 1:stop]]
    return {"status": "PASS" if success else "FAILED", "selected": selected,
            "state_returns": [x.decode() for x in ret], "reset_returns": [x.decode() for x in reset],
            "timing_enabled": (prefix + "_TIMING_ENABLED").encode() in lines,
            "touch_pm_log": log,
            "real_sleep_verified": False, "touch_after_resume_verified": False,
            "capture_authenticated": False}


def capture(channel, healthy, deadline, nonce):
    data, prefix = command(nonce)
    if not healthy():
        raise RuntimeError("USB binding or monitor invalid before PM test")
    offset = len(channel.buffer)
    channel.send(data, deadline)
    def receipt(buffer):
        if not healthy():
            raise RuntimeError("USB binding or monitor lost during PM test")
        return parse(buffer[offset:], prefix)
    return channel.until(receipt, min(deadline, time.monotonic() + 45))
