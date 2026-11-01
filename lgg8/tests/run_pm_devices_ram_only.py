#!/usr/bin/env python3
"""Run a bounded device-PM debug cycle; never claim real system sleep."""
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

import pm_devices_detached
import run_touch_ram_only as touch
import touch_capture_adapter
import touch_stream_capture
from touch_session import run_session

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / 'out/lgg8-pm-reconnect-20261101/boot'
IMAGE_SHA = '97bd999393bc8e034c3dffaf4acbbffbb49b285f63fb4330388fb79e2d1fc9ee'
MANIFEST_SHA = '450844d2c71800fc590a7cf5bf900c6c391677378bffb6ba16d3f0571476a51f'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def check():
    image, manifest = CANDIDATE / 'boot.img', CANDIDATE / 'manifest.json'
    if digest(manifest) != MANIFEST_SHA:
        raise ValueError('PM candidate manifest mismatch')
    data = json.loads(manifest.read_bytes())
    if (data.get('schema') != 'lgg8-boot-image-v1' or
        data.get('device_acceptance') != 'NOT_TESTED' or
        data['components']['image'] != {'sha256': IMAGE_SHA, 'size': image.stat().st_size} or
        image.stat().st_size > data['partition_size'] or digest(image) != IMAGE_SHA):
        raise ValueError('PM candidate image mismatch')
    return {'status': 'IDENTITY_MATCH', 'image_sha256': IMAGE_SHA,
            'device_acceptance': 'NOT_TESTED', 'boot_authorized': False}


def post_pm_capture(channel, event, deadline, healthy, notify_ready, capture=touch_stream_capture.capture):
    now = time.monotonic()
    if now + 24 >= deadline:
        raise RuntimeError('insufficient recovery budget for post-PM touch')
    return capture(channel, event, min(deadline - 4, now + 23), healthy, notify_ready)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-ram-only', action='store_true')
    parser.add_argument('--serial')
    parser.add_argument('--touch-after-pm', action='store_true',
                        help='request a human tap after a completed device-PM test')
    args = parser.parse_args()
    if not args.execute_ram_only:
        if args.serial is not None or args.touch_after_pm:
            parser.error('serial and touch capture require --execute-ram-only')
        print(json.dumps({'candidate': check(), 'device_execution': False,
                          'real_sleep_verified': False}, indent=2))
        return
    if not args.serial or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', args.serial):
        parser.error('execution requires an explicit device serial')
    check()
    os.umask(0o077)
    output = CANDIDATE.parent / (time.strftime('pm-devices-%Y%m%d-%H%M%S', time.gmtime()) + '-' + secrets.token_hex(4))
    output.mkdir(mode=0o700)
    # All monkey patches are local to this short-lived process. DeviceIO still
    # enforces pre/post Android, both boot hashes, slot and physical USB monitor.
    touch.CANDIDATE = CANDIDATE
    touch.check = check
    io = touch.DeviceIO(args.serial, output)
    signals = []
    def collect(channel, event, deadline, healthy, notify_ready):
        legacy, inner = io.legacy, io.inner
        plan = pm_devices_detached.plan(secrets.token_hex(12).upper())
        original = legacy.usb_snapshot()
        located_before = inner.base.acm_parent_for_port()
        if not healthy() or not located_before:
            raise RuntimeError('initial USB binding invalid')
        channel.send(plan['launch'], min(deadline, time.monotonic() + 4))
        result = {'status': 'FAILED', 'error': 'PM result unavailable',
                  'real_sleep_verified': False, 'touch_after_resume_verified': False,
                  'capture_authenticated': False}
        retry = 0
        touch_started = False
        # Give the detached process time to complete the 5 s devices test.
        time.sleep(8)
        while time.monotonic() < deadline - 8:
            if not inner.monitor.healthy():
                result['error'] = 'USB monitor stopped'
                break
            snapshot = legacy.usb_snapshot()
            located = inner.base.acm_parent_for_port()
            if not pm_devices_detached.valid_snapshot(original, snapshot) or not located:
                time.sleep(0.2)
                continue
            # Re-enumeration changes devnum/tty but must retain physical parent
            # and gadget serial, in addition to the port/VID/PID fingerprint.
            if located[1:] != located_before[1:]:
                result['error'] = 'ACM parent or gadget serial changed'
                break
            new_channel = None
            try:
                if healthy():
                    guarded, bound = channel, healthy
                else:
                    retry += 1
                    subdir = output / ('acm-reconnect-' + str(retry))
                    subdir.mkdir(mode=0o700)
                    new_channel = legacy.SerialChannel(located[0], subdir)
                    def bound():
                        return (inner.monitor.healthy() and snapshot == legacy.usb_snapshot() and
                                inner.base.acm_parent_for_port() == located)
                    guarded = touch.GuardedChannel(new_channel, bound)
                legacy.synchronize_shell(guarded, min(deadline - 5, time.monotonic() + 4))
                found = pm_devices_detached.read_record(
                    guarded, bound, plan, deadline - 5, secrets.token_hex(12).upper())
                if found is None:
                    time.sleep(0.5)
                    continue
                result = found
                result['read_after_reenumeration'] = new_channel is not None
                if args.touch_after_pm and result['status'] == 'PASS':
                    touch_started = True
                    touch_result = post_pm_capture(guarded, event, deadline, bound, notify_ready)
                    result['post_pm_touch'] = touch_result
                    if touch_result['status'] != 'PASS':
                        result['status'] = 'FAILED'
                if new_channel is not None and bound():
                    result['reboot_request'] = legacy.request_ram_reboot(
                        guarded, min(deadline, time.monotonic() + 4))
                break
            except (EOFError, TimeoutError, OSError, RuntimeError) as exc:
                result['error'] = repr(exc)
                result['status'] = 'FAILED'
                if touch_started:
                    break
                time.sleep(0.2)
            finally:
                if new_channel is not None:
                    new_channel.close()
        if result['status'] != 'PASS':
            try:
                if healthy():
                    result['fallback_reboot'] = legacy.request_ram_reboot(
                        channel, min(deadline, time.monotonic() + 4))
            except Exception as reboot_error:
                result['fallback_reboot_error'] = repr(reboot_error)
        return result
    touch_capture_adapter.capture = collect
    def interrupted(signum, frame):
        del frame
        signals.append(signum)
        if not io.inner.recovering:
            raise InterruptedError('signal ' + str(signum))
    previous = {s: signal.signal(s, interrupted) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        result = run_session(io)
        result.update(success_scope='if capture passes: pm_test selected and state write returned zero; callback execution not proven',
                      real_sleep_verified=False, touch_after_resume_verified=False,
                      charging_safety_verified=False)
        io.inner.save('pm-devices-signals', signals)
        io.inner.save('pm-devices-result', result)
        try:
            (output / 'tmp').rmdir()
        except OSError:
            pass
        print(json.dumps({'directory': str(output), **result}, indent=2))
        if not result['success']:
            sys.exit(1)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
