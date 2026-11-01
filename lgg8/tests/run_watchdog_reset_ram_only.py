#!/usr/bin/env python3
"""Supervised RAM-only awake watchdog experiment; default is review only.

It intentionally arms a watchdog and may reset the phone. A timed USB detach
is not reset-cause proof and this test does not enter or validate suspend.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import time

import run_touch_ram_only as touch
import run_watchdog_registration_ram_only as registration
import touch_capture_adapter
import watchdog_reset_capture
import watchdog_transfer
from touch_session import run_session

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "out/lgg8-watchdog-probe-20261101/qcom-watchdog-probe"
BINARY_SHA = "ea41d2b1fda68264998ec826222ffe66ac719efb79f8509367d3b2a5716f0108"
DEVICE = "/sys/devices/platform/soc@0/17c10000.watchdog\n"
DRIVER = "/sys/bus/platform/drivers/qcom_wdt\n"


def review():
    result = touch.review()
    binary = BINARY.read_bytes()
    if hashlib.sha256(binary).hexdigest() != BINARY_SHA:
        raise RuntimeError("watchdog binary hash mismatch")
    return {"candidate": result, "binary_sha256": BINARY_SHA, "device_execution": False,
            "watchdog_reset_verified": False, "suspend_verified": False}


def perform(channel, io, healthy, deadline, binary):
    """Run only after the adapter validates /run, cmdline and touchscreen."""
    legacy, inner = io.legacy, io.inner
    capture = {"status": "FAILED", "watchdog_reset_verified": False,
               "suspend_verified": False, "capture_authenticated": False}
    try:
        if hashlib.sha256(binary).hexdigest() != BINARY_SHA:
            raise RuntimeError("watchdog binary changed before transfer")
        if deadline - time.monotonic() < 75:
            raise RuntimeError("insufficient fixed recovery deadline")
        receipts = registration.inventory(channel, legacy, healthy, deadline)
        capture["binding_receipts"] = receipts
        if any(receipts[k]["exit_code"] for k in ("device", "driver")) or \
                receipts["device"]["stdout"] != DEVICE or receipts["driver"]["stdout"] != DRIVER:
            raise RuntimeError("watchdog binding mismatch")
        plan = watchdog_transfer.upload(binary, secrets.token_hex(12).upper())
        capture["transfer"] = watchdog_transfer.send_batches(
            channel, plan, healthy, min(deadline - 35, time.monotonic() + 90))

        def state():
            if healthy():
                return "same"
            snap = legacy.usb_snapshot()
            return "absent" if snap.get("status") == "absent" else "other"

        capture["probe"] = watchdog_reset_capture.capture(
            channel, plan["path"], healthy, inner.monitor.healthy, state, deadline - 5)
        if capture["probe"]["outcome"] == "TIMED_DISCONNECT_ONLY":
            capture["status"] = "PASS"
    except Exception as exc:
        capture["error"] = repr(exc)
    finally:
        # If a reset did not already remove the Linux gadget, request ordinary
        # RAM reboot while the binding and monitor are valid. Do not assume the
        # probe's magic close stopped a watchdog. /run is volatile.
        try:
            if healthy():
                # The interactive shell can be left inside an unterminated
                # command after a truncated transfer. Ctrl-U only clears the
                # current line; attempt an interrupt before resyncing. Signal
                # delivery is not guaranteed; Android verification remains
                # the only evidence of successful recovery.
                channel.send(b"\x03\n", min(deadline, time.monotonic() + 1))
                capture["fallback_reboot"] = legacy.request_ram_reboot(
                    channel, min(deadline, time.monotonic() + 4))
        except Exception as exc:
            capture["fallback_reboot_error"] = repr(exc)
            capture["status"] = "FAILED"
    return capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-ram-only", action="store_true")
    parser.add_argument("--serial")
    args = parser.parse_args()
    if not args.execute_ram_only:
        if args.serial is not None:
            parser.error("serial requires explicit --execute-ram-only")
        print(json.dumps(review(), indent=2))
        return
    if not args.serial or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", args.serial) is None:
        parser.error("execution requires one explicit well-formed serial")
    review()
    binary = BINARY.read_bytes()
    os.umask(0o077)
    output = touch.CANDIDATE.parent / (time.strftime("watchdog-reset-%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(4))
    output.mkdir(mode=0o700)
    io = touch.DeviceIO(args.serial, output)
    signals = []

    def capture(channel, event, deadline, healthy, notify_ready):
        del event, notify_ready
        return perform(channel, io, healthy, deadline, binary)

    old_capture = touch_capture_adapter.capture
    touch_capture_adapter.capture = capture

    def interrupted(signum, frame):
        del frame
        signals.append(signum)
        if not io.inner.recovering:
            raise InterruptedError("signal " + str(signum))

    previous = {s: signal.signal(s, interrupted) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        result = run_session(io)
        result.update(success_scope="timed USB disconnect and Android recovery only; no reset causality",
                      watchdog_reset_verified=False, suspend_verified=False,
                      charging_safety_verified=False)
        io.inner.save("watchdog-reset-signals", signals)
        io.inner.save("watchdog-reset-result", result)
        try:
            (output / "tmp").rmdir()
        except OSError:
            pass
        print(json.dumps({"directory": str(output), **result}, indent=2))
        if not result["success"]:
            sys.exit(1)
    finally:
        touch_capture_adapter.capture = old_capture
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    main()
