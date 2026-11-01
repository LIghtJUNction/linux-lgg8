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

import pm_devices_capture
import run_touch_ram_only as touch
import touch_capture_adapter
from touch_session import run_session

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / 'out/lgg8-pm-test-20261101/boot'
IMAGE_SHA = '23164971072af58164312e6e4796f4e20f7d6c6c13a04a2319edffc200650426'
MANIFEST_SHA = '85870f71b735ac9cdee15edff6fdde89e5b13cca4989e04f291d9806b674f373'


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-ram-only', action='store_true')
    parser.add_argument('--serial')
    args = parser.parse_args()
    if not args.execute_ram_only:
        if args.serial is not None:
            parser.error('serial requires --execute-ram-only')
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
        del event, notify_ready
        try:
            result = pm_devices_capture.capture(channel, healthy, deadline - 5, secrets.token_hex(12).upper())
        except Exception as exc:
            result = {'status': 'FAILED', 'error': repr(exc), 'real_sleep_verified': False,
                      'touch_after_resume_verified': False, 'capture_authenticated': False}
        if result['status'] != 'PASS':
            try:
                if healthy():
                    result['fallback_reboot'] = io.legacy.request_ram_reboot(
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
        result.update(success_scope='pm_test selection and state write returned zero with Android recovery; callback execution not proven',
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
