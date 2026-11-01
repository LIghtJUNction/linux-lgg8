#!/usr/bin/env python3
"""Candidate touch session. Default is read-only review; execution is explicit.

The Linux capture is not authenticated and does not prove physical origin or
suspend. USB power can inherit charging; no charge safety is established.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time

from check_touch_candidate import CANDIDATE, check
from touch_capture_adapter import collect
from touch_session import run_session

ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / "out/lgg8-c234-integration-20261101/run-c234-observe.py"
LEGACY_SHA = "22b4ec2e1b246a62a604ffe9d5e47fbddd4fae3ff303dea88a8d4359f64aaed3"


def pinned_legacy():
    data = LEGACY.read_bytes()
    if hashlib.sha256(data).hexdigest() != LEGACY_SHA:
        raise RuntimeError("C234 runner changed; review required")
    spec = importlib.util.spec_from_file_location("touch_c234_reference", LEGACY)
    module = importlib.util.module_from_spec(spec)
    # Compile the exact bytes hashed above, not a second read of the path.
    exec(compile(data, str(LEGACY), "exec"), module.__dict__)
    return module


def review():
    candidate = check()
    if hashlib.sha256(LEGACY.read_bytes()).hexdigest() != LEGACY_SHA:
        raise RuntimeError("C234 runner hash mismatch")
    return {"candidate": candidate, "legacy_sha256": LEGACY_SHA,
            "device_execution": False, "physical_touch_verified": False,
            "suspend_verified": False, "charging_safety_verified": False}


def notify_user(title, message):
    """Best-effort desktop notification; never block device recovery."""
    try:
        return subprocess.run(["notify-send", title, message], timeout=1,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class GuardedChannel:
    """Recheck physical binding and monitor before sends and while receiving."""
    def __init__(self, channel, healthy):
        self.channel, self.healthy = channel, healthy

    def __getattr__(self, name):
        return getattr(self.channel, name)

    def send(self, data, deadline):
        if not self.healthy():
            raise RuntimeError("USB binding or monitor lost before serial send")
        return self.channel.send(data, deadline)

    def until(self, predicate, deadline):
        def guarded(buffer):
            if not self.healthy():
                raise RuntimeError("USB binding or monitor lost during serial receive")
            return predicate(buffer)
        return self.channel.until(guarded, deadline)


class DeviceIO:
    def __init__(self, serial, output):
        legacy = pinned_legacy()
        # Only these globals differ from C234. The legacy helper and recovery
        # checks remain pinned; candidate review is repeated before fastboot.
        legacy.IMAGE = CANDIDATE / "boot.img"
        legacy.review = check
        self.legacy = legacy
        self.inner = legacy.LiveIO(serial, output)
        self.inner.manifest = json.loads((CANDIDATE / "manifest.json").read_text())
        self.output = output
        self.session_start_ns = None

    def candidate_gate(self): return review()
    def start_monitor(self):
        self.session_start_ns = time.monotonic_ns()
        self.inner.start_monitor()
    def preflight(self): return self.inner.preflight()
    def validate_android(self, before): return self.legacy.validate_android(before)
    def arm_recovery_deadline(self): return self.inner.arm_recovery()
    def enter_fastboot(self): return self.inner.enter_fastboot()
    def check_fastboot(self): return self.inner.check_fastboot()
    def boot_ram_only(self): return self.inner.boot()

    def capture_touch(self):
        inner, legacy = self.inner, self.legacy
        end = min(inner.deadline, inner.boot_time + 180)
        while time.monotonic() < end:
            if not inner.monitor.healthy():
                raise RuntimeError("USB monitor stopped while waiting for ACM")
            located = inner.base.acm_parent_for_port()
            if located:
                node, parent, serial = located
                fingerprint = legacy.usb_snapshot()
                try:
                    channel = legacy.SerialChannel(node, self.output)
                except (PermissionError, FileNotFoundError):
                    time.sleep(0.1)
                    continue
                try:
                    def healthy():
                        return (inner.monitor.healthy() and fingerprint == legacy.usb_snapshot() and
                                inner.base.acm_parent_for_port() == located)
                    if not healthy():
                        raise RuntimeError("ACM identity changed while opening")
                    notification = {"attempted": False, "sent": False}
                    def ready():
                        print("READY: 请在手机屏幕轻触并抬起，限时 20 秒。", flush=True)
                        notification["attempted"] = True
                        notification["sent"] = notify_user(
                            "LG G8 触摸测试", "请现在轻触手机屏幕并抬起，限时 20 秒。")
                    guarded = GuardedChannel(channel, healthy)
                    result = collect(guarded, legacy, inner.manifest, healthy, ready, end)
                    result["desktop_notification"] = notification
                    result["usb_binding"] = {"tty": str(node), "parent": str(parent),
                                             "gadget_serial": serial, "snapshot": fingerprint}
                    if result["status"] == "PASS" and healthy():
                        result["reboot_request"] = legacy.request_ram_reboot(
                            guarded, min(inner.deadline, time.monotonic() + 4))
                    inner.save("touch-capture", result)
                    return result["status"]
                finally:
                    channel.close()
            snap = legacy.usb_snapshot()
            if snap.get("vid") == "1004" and snap.get("serial") == inner.serial:
                raise RuntimeError("Android returned before ACM capture")
            if ((snap.get("vid"), snap.get("pid"), snap.get("serial")) ==
                    ("18d1", "4ee0", inner.serial) and time.monotonic() - inner.boot_time >= 30):
                raise RuntimeError("fastboot still present after 30 seconds")
            time.sleep(0.2)
        raise TimeoutError("ACM capture deadline reached")

    def recover_android(self):
        self.inner.recovering = True
        return self.inner.recover()
    def validate_return(self, before, after): return self.legacy.validate_return(before, after)
    def stop_and_verify_monitor(self):
        data = self.inner.stop_monitor(self.session_start_ns, time.monotonic_ns())
        self.inner.save("touch-usb-monitor", data)
        return bool(data.get("exit_code") == 0 and data.get("sampling_verified") and
                    data.get("session_coverage_verified") and data.get("log_integrity_verified") and
                    data.get("observation_verified") and not data.get("forced") and not data.get("premature"))


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
    os.umask(0o077)
    output = CANDIDATE.parent / (time.strftime("touch-run-%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(4))
    output.mkdir(mode=0o700)
    io = DeviceIO(args.serial, output)
    signals = []

    def interrupted(signum, frame):
        signals.append(signum)
        if not io.inner.recovering:
            raise InterruptedError("signal " + str(signum))

    previous = {s: signal.signal(s, interrupted) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        result = run_session(io)
        result.update(success_scope="capture and recovery only; not physical-origin verification",
                      physical_touch_verified=False, suspend_verified=False,
                      charging_safety_verified=False)
        io.inner.save("touch-signals", signals)
        io.inner.save("touch-result", result)
        try:
            (output / "tmp").rmdir()  # Never remove unknown/nonempty files.
        except OSError:
            pass
        print(json.dumps(result, indent=2))
        if not result["success"]:
            sys.exit(1)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    main()
