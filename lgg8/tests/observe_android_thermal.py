#!/usr/bin/env python3
"""Bounded read-only Android temperature observation; not freshness or safety proof."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import time

from run_touch_ram_only import pinned_legacy

ROOT = Path(__file__).resolve().parents[2]
SERIAL = "LMG820UM13c10bc9"
READ = """for p in bms battery; do for f in temp voltage_now current_now status; do
printf '%s/%s=' "$p" "$f"; if [ -r "/sys/class/power_supply/$p/$f" ]; then
cat "/sys/class/power_supply/$p/$f" || exit 1; else printf 'unavailable\\n'; fi; done; done"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-read-only", action="store_true")
    if not parser.parse_args().execute_read_only:
        print("Review only; no device operation. Use --execute-read-only for the fixed phone.")
        return
    os.umask(0o077)
    directory = ROOT / "out/lgg8-touch-candidate-20261101" / (
        time.strftime("android-thermal-%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(4))
    directory.mkdir(mode=0o700, parents=True)
    legacy = pinned_legacy()
    io = legacy.LiveIO(SERIAL, directory)
    start = time.monotonic_ns()
    report = {"scope": "Android sysfs only; no independent calibration or freshness proof",
              "samples": [], "unchanged_android": False, "monitor_verified": False}
    before = None
    try:
        io.start_monitor()
        before = io.preflight()
        for index in range(12):
            if not io.monitor.healthy() or legacy.usb_snapshot().get("serial") != SERIAL:
                raise RuntimeError("monitor or USB identity lost")
            start_sample = time.monotonic_ns()
            result = io.base.command(f"temperature-{index:02d}",
                                     ["adb", "-s", SERIAL, "shell", "su -c " + shlex.quote(READ)],
                                     timeout=5, check=False)
            report["samples"].append({"index": index, "start_ns": start_sample,
                                      "end_ns": time.monotonic_ns(), "exit_code": result["exit_code"],
                                      "timed_out": result["timed_out"]})
            if result["exit_code"] or result["timed_out"]:
                raise RuntimeError("temperature observation failed")
            if index < 11:
                time.sleep(2)
    except Exception as error:
        report["error"] = repr(error)
    finally:
        if before is not None:
            try:
                io.base.require_adb("postflight-adb")
                after = io.base.android("post-android")
                legacy.validate_android(after)
                report["unchanged_android"] = before == after
            except Exception as error:
                report["postflight_error"] = repr(error)
        try:
            monitor = io.stop_monitor(start, time.monotonic_ns())
            report["monitor"] = monitor
            report["monitor_verified"] = bool(monitor.get("exit_code") == 0 and
                monitor.get("sampling_verified") and monitor.get("session_coverage_verified") and
                monitor.get("log_integrity_verified") and monitor.get("observation_verified") and
                not monitor.get("forced") and not monitor.get("premature"))
        except Exception as error:
            report["monitor_error"] = repr(error)
        io.save("thermal-observation", report)
        try:
            (directory / "tmp").rmdir()
        except OSError:
            pass
    print(json.dumps({"directory": str(directory), **report}, indent=2))
    if (report.get("error") or not report["unchanged_android"] or
            not report["monitor_verified"] or len(report["samples"]) != 12):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
