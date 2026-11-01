#!/usr/bin/env python3
"""Read-only watchdog registration inventory during a supervised RAM-only boot.

Does not open a watchdog device, arm a timer, enter suspend, or prove recovery.
Default invocation is review-only. This reuses the guarded touch-session transport.
"""
import argparse
import json
import os
import re
import secrets
import signal
import sys
import time

import touch_capture_adapter
import run_touch_ram_only as touch
from touch_session import run_session

FIELDS = (
    ("misc", "/proc/misc", "cat"),
    ("device", "/sys/class/watchdog/watchdog0/device", "readlink"),
    ("driver", "/sys/class/watchdog/watchdog0/device/driver", "readlink"),
)


def inventory(channel, legacy, healthy, deadline):
    """Capture fixed read-only commands with the existing integrity framing."""
    legacy.METADATA.append(("watchdog_misc", FIELDS[0][1], "inventory"))
    legacy.NODE_LINKS.extend((f"watchdog_{name}", path, "inventory")
                             for name, path, kind in FIELDS if kind == "readlink")
    nonce = secrets.token_hex(12).upper()
    receipts = {}
    for index, (name, path, kind) in enumerate(FIELDS):
        if not healthy():
            raise RuntimeError("USB monitor or binding invalid")
        prefix = f"C234_{nonce}_{index:02d}"
        argv = ["/bin/busybox", "cat", path] if kind == "cat" else ["/bin/busybox", "readlink", "-f", path]
        channel.send(legacy.capture_script(prefix, argv), deadline)

        def complete(buffer):
            if not healthy():
                raise RuntimeError("USB monitor or binding lost during capture")
            return legacy.parse_frame(buffer, prefix)

        frame = channel.until(complete, min(deadline, time.monotonic() + 4))
        if frame.get("payload_integrity_verified") is not True:
            raise RuntimeError("unverified capture frame")
        # A missing watchdog path is a valid observation, not a success claim.
        receipts[name] = {"exit_code": frame["exit_code"],
                          "stdout": frame["stdout"].decode("utf-8", "replace"),
                          "stderr": frame["stderr"].decode("utf-8", "replace"),
                          "payload_integrity_verified": True}
    return receipts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute-ram-only", action="store_true")
    p.add_argument("--serial")
    args = p.parse_args()
    if not args.execute_ram_only:
        if args.serial is not None:
            p.error("serial requires explicit --execute-ram-only")
        print(json.dumps({"candidate": touch.review(), "device_execution": False,
                          "opens_watchdog": False, "enters_suspend": False}, indent=2))
        return
    if not args.serial or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", args.serial) is None:
        p.error("execution requires one explicit well-formed serial")
    touch.review()
    os.umask(0o077)
    output = touch.CANDIDATE.parent / (time.strftime("watchdog-registration-%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(4))
    output.mkdir(mode=0o700)
    io = touch.DeviceIO(args.serial, output)
    signals = []

    def capture(channel, event, deadline, healthy, notify_ready):
        del event, notify_ready
        return {"status": "PASS", "scope": "read-only registration only; no watchdog open or suspend",
                "receipts": inventory(channel, io.legacy, healthy, deadline)}

    previous_capture = touch_capture_adapter.capture
    touch_capture_adapter.capture = capture

    def interrupted(signum, frame):
        del frame
        signals.append(signum)
        if not io.inner.recovering:
            raise InterruptedError("signal " + str(signum))

    previous = {s: signal.signal(s, interrupted) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        result = run_session(io)
        result.update(success_scope="read-only registration capture and Android recovery only",
                      watchdog_reset_verified=False, suspend_verified=False,
                      charging_safety_verified=False)
        io.inner.save("watchdog-signals", signals)
        io.inner.save("watchdog-result", result)
        try:
            (output / "tmp").rmdir()
        except OSError:
            pass
        print(json.dumps(result, indent=2))
        if not result["success"]:
            sys.exit(1)
    finally:
        touch_capture_adapter.capture = previous_capture
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    main()
