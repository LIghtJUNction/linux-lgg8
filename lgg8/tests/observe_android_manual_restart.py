#!/usr/bin/env python3
"""Observe a user-performed Android restart; no reset command or partition write.

This cannot prove a key combination can reset an unresponsive Linux kernel.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import time

from run_touch_ram_only import notify_user, pinned_legacy

ROOT = Path(__file__).resolve().parents[2]
SERIAL = "LMG820UM13c10bc9"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observe-manual-restart", action="store_true")
    if not parser.parse_args().observe_manual_restart:
        print("Review only; explicit --observe-manual-restart is required.")
        return
    os.umask(0o077)
    directory = ROOT / "out/lgg8-touch-candidate-20261101" / (
        time.strftime("manual-restart-%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(4))
    directory.mkdir(mode=0o700, parents=True)
    legacy = pinned_legacy()
    io = legacy.LiveIO(SERIAL, directory)
    start = time.monotonic_ns()
    result = {"scope": "Android restart observation; not unresponsive Linux recovery",
              "notification_sent": False, "disconnect_observed": False,
              "android_return_verified": False, "monitor_verified": False}
    before = None
    try:
        io.start_monitor()
        before = io.preflight()
        result["notification_sent"] = notify_user(
            "LG G8：请协助验证人工重启",
            "请同时长按电源键和音量下键，手机开始重启或出现 LG 标志时松开；请不要拔线。")
        print("请同时长按电源键和音量下键，手机开始重启或出现 LG 标志时松开；请不要拔线。", flush=True)
        deadline = time.monotonic() + 180
        attempts = 0
        while time.monotonic() < deadline:
            if not io.monitor.healthy():
                raise RuntimeError("USB monitor lost")
            snap = legacy.usb_snapshot()
            if snap.get("status") == "absent":
                result["disconnect_observed"] = True
            if (result["disconnect_observed"] and snap.get("serial") == SERIAL and
                    snap.get("vid") == "1004" and snap.get("pid") in ("631f", "633e")):
                attempts += 1
                cmd = io.base.command(f"boot-completed-{attempts:03d}",
                                      ["adb", "-s", SERIAL, "shell", "getprop", "sys.boot_completed"],
                                      timeout=5, check=False)
                if cmd["exit_code"] == 0 and cmd["stdout"].strip() == b"1":
                    io.base.require_adb("postflight-adb")
                    after = io.base.android("post-android")
                    legacy.validate_return(before, after)
                    result["android_return_verified"] = True
                    break
            time.sleep(0.5)
        else:
            result["error"] = "Restart/Android return not observed before deadline"
    except Exception as error:
        result["error"] = repr(error)
    finally:
        try:
            monitor = io.stop_monitor(start, time.monotonic_ns())
            result["monitor"] = monitor
            result["monitor_verified"] = bool(monitor.get("exit_code") == 0 and
                monitor.get("sampling_verified") and monitor.get("session_coverage_verified") and
                monitor.get("log_integrity_verified") and monitor.get("observation_verified") and
                not monitor.get("forced") and not monitor.get("premature"))
        except Exception as error:
            result["monitor_error"] = repr(error)
        io.save("manual-restart", result)
        try:
            (directory / "tmp").rmdir()
        except OSError:
            pass
    print(json.dumps({"directory": str(directory), **result}, indent=2))
    if result.get("error") or not result["android_return_verified"] or not result["monitor_verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
