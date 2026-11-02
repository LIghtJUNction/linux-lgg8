#!/usr/bin/env python3
"""One pinned eight-CPU RAM boot; verify CPU inventory and execution affinity."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import sys
import time

import run_touch_ram_only as touch
import touch_capture_adapter
import watchdog_transfer
from touch_session import run_session

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / 'out/lgg8-multicore-20261102/boot'
IMAGE_SHA = 'c46540fcba4d6c37ab3ddd579e480a9e1e76c6add15233fa0ceb133a53959cad'
MANIFEST_SHA = '396c9e088cbf62645b6e684780c8d4af14ddb20b08ea223d9539a473c4e61b7f'
PROBE = ROOT / 'out/lgg8-multicore-20261102/cpu-probe'
PROBE_SHA = '2fb29cb5db468cc4688fd231746fb12cc683487a078662563ad8bcd5f4aac4b8'
PROBE_OUTPUT = b''.join(f'CPU{cpu}_OK\n'.encode() for cpu in range(8))


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def check():
    image, manifest = CANDIDATE / 'boot.img', CANDIDATE / 'manifest.json'
    if digest(manifest) != MANIFEST_SHA:
        raise ValueError('multicore manifest mismatch')
    if digest(PROBE) != PROBE_SHA:
        raise ValueError('multicore probe mismatch')
    data = json.loads(manifest.read_bytes())
    if (data.get('schema') != 'lgg8-boot-image-v1' or
            data['components']['image'] != {'sha256': IMAGE_SHA, 'size': image.stat().st_size} or
            image.stat().st_size > data['partition_size'] or digest(image) != IMAGE_SHA or
            [word for word in data['bootargs'].split() if word.startswith('maxcpus=')] != ['maxcpus=8']):
        raise ValueError('multicore image mismatch')
    return {'status': 'IDENTITY_MATCH', 'image_sha256': IMAGE_SHA,
            'device_execution': False}


def tasks(probe_path='/run/wdt-' + 'A' * 24):
    if re.fullmatch(r'/run/wdt-[A-F0-9]{24}', probe_path) is None:
        raise ValueError('invalid RAM probe path')
    cpu = '/sys/devices/system/cpu/'
    result = [(name, ['/bin/busybox', 'cat', cpu + name], b'0-7\n')
              for name in ('online', 'present', 'possible')]
    result += [('cpu_execution', [probe_path], PROBE_OUTPUT)]
    result += [('cpuinfo', ['/bin/busybox', 'cat', '/proc/cpuinfo'], None),
               ('interrupts', ['/bin/busybox', 'cat', '/proc/interrupts'], None),
               ('dmesg_tail', ['/bin/busybox', 'sh', '-c',
                               'set -o pipefail; /bin/busybox dmesg | /bin/busybox tail -c 8192'], None)]
    return result


def capture_script(legacy, prefix, argv):
    """Reuse pinned framing, with a separate explicit CPU-command whitelist."""
    probe = len(argv) == 1 and re.fullmatch(r'/run/wdt-[A-F0-9]{24}', argv[0])
    if not probe and argv not in [command for _, command, _ in tasks()]:
        raise ValueError('command is outside multicore whitelist')
    original = ['/bin/busybox', 'cat', '/proc/cmdline']
    envelope = legacy.capture_script(prefix, original)
    needle = shlex.join(original).encode('ascii')
    if envelope.count(needle) != 1:
        raise ValueError('pinned capture envelope changed')
    return envelope.replace(needle, shlex.join(argv).encode('ascii'))


def collect(channel, legacy, deadline, healthy, probe_path='/run/wdt-' + 'A' * 24, save=None):
    stop = min(deadline - 5, time.monotonic() + 20)
    nonce = secrets.token_hex(12).upper()
    rows = []
    for index, (name, argv, expected) in enumerate(tasks(probe_path)):
        if not healthy() or time.monotonic() >= stop:
            raise RuntimeError('multicore capture lost binding or budget')
        prefix = f'C234_{nonce}_{index:02d}'
        channel.send(capture_script(legacy, prefix, argv), stop)
        frame = channel.until(lambda data: legacy.parse_frame(data, prefix),
                              min(stop, time.monotonic() + 4))
        valid = (frame.get('payload_integrity_verified') is True and
                 frame['exit_code'] == 0 and not frame['stderr'] and
                 (expected is None or frame['stdout'] == expected))
        rows.append({'key': name, 'status': 'OK' if valid else 'FAILED',
                     'stdout_b64': base64.b64encode(frame['stdout']).decode(),
                     'stderr_b64': base64.b64encode(frame['stderr']).decode(),
                     'exit_code': frame['exit_code'],
                     'payload_integrity_verified': frame.get('payload_integrity_verified') is True})
        if save is not None:
            save({'status': 'INCOMPLETE', 'receipts': rows})
    return {'status': 'PASS' if all(row['status'] == 'OK' for row in rows) else 'FAILED',
            'receipts': rows, 'long_term_stability_verified': False,
            'charging_safety_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-ram-only', action='store_true')
    parser.add_argument('--serial')
    args = parser.parse_args()
    if not args.execute_ram_only:
        if args.serial is not None:
            parser.error('serial requires --execute-ram-only')
        print(json.dumps(check(), indent=2))
        return
    if not args.serial or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', args.serial):
        parser.error('execution requires an explicit device serial')
    check()
    # Validate the actual pinned helper contract before any device transition.
    legacy = touch.pinned_legacy()
    for index, (_, argv, _) in enumerate(tasks()):
        capture_script(legacy, f'C234_{"A" * 24}_{index:02d}', argv)
    os.umask(0o077)
    output = CANDIDATE.parent / (time.strftime('run-%Y%m%d-%H%M%S', time.gmtime()) + '-' + secrets.token_hex(4))
    output.mkdir(mode=0o700)
    touch.CANDIDATE, touch.check = CANDIDATE, check
    io = touch.DeviceIO(args.serial, output)

    def capture(channel, event, deadline, healthy, notify_ready):
        del event, notify_ready
        try:
            binary = PROBE.read_bytes()
            if hashlib.sha256(binary).hexdigest() != PROBE_SHA:
                raise ValueError('probe changed before transfer')
            plan = watchdog_transfer.upload(binary, secrets.token_hex(12).upper())
            transfer = watchdog_transfer.send_batches(channel, plan, healthy,
                                                      min(deadline - 10, time.monotonic() + 10))
            io.inner.save('multicore-transfer', transfer)
            report = collect(channel, io.legacy, deadline, healthy, plan['path'],
                             lambda value: io.inner.save('multicore-capture', value))
        except Exception:
            if healthy():
                io.legacy.request_ram_reboot(channel, min(deadline, time.monotonic() + 4))
            raise
        io.inner.save('multicore-capture', report)
        return report

    touch_capture_adapter.capture = capture
    signals = []

    def interrupted(signum, frame):
        del frame
        signals.append(signum)
        if not io.inner.recovering:
            raise InterruptedError('signal ' + str(signum))

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        result = run_session(io)
        result.update(image_sha256=IMAGE_SHA,
                      eight_cpu_execution_verified=result.get('capture') == 'PASS',
                      requested_scope='eight CPUs online and each executed a pinned process',
                      long_term_stability_verified=False, charging_safety_verified=False)
        io.inner.save('multicore-signals', signals)
        io.inner.save('multicore-result', result)
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
