#!/usr/bin/env python3
"""Pinned rebuilt kernel: own Bluetooth controller cycle and eight-CPU execution."""
import base64
import re

import run_multicore_ram_only as base

CANDIDATE = base.ROOT / 'out/lgg8-connectivity-20261102/bt-wcn3998-boot'
IMAGE_SHA = 'ca1bfb12f4ba2ec3f5ae0cd0a8adde2fb3948ecb351a247a6469c800260f5b34'
MANIFEST_SHA = '3d8714f76710cf8bcb526ca9ae8ff475cd4b944e30891d0eddeaa09f1884f8c9'
_TASKS, _CAPTURE, _COLLECT = base.tasks, base.capture_script, base.collect
PREPARE = r'''set -eu
/bin/busybox modprobe hci_uart
/bin/busybox sleep 20
test -d /sys/class/bluetooth/hci0
printf 'BT_DRIVER_READY\n'
'''


def tasks(probe_path='/run/wdt-' + 'A' * 24):
    original = _TASKS(probe_path)
    return original[:3] + [
        ('bt_prepare', ['/bin/busybox', 'sh', '-c', PREPARE], b'BT_DRIVER_READY\n'),
        ('bt_controller', ['/usr/bin/lgg8-bluetooth-probe'], None)] + original[3:]


def capture_script(legacy, prefix, argv):
    result = _CAPTURE(legacy, prefix, argv)
    name = next((key for key, command, _ in tasks() if command == argv), None)
    if name in ('bt_prepare', 'bt_controller'):
        needle = b'/bin/busybox timeout -s KILL 1 '
        if result.count(needle) != 1:
            raise ValueError('pinned timeout envelope changed')
        duration = 24 if name == 'bt_prepare' else 35
        result = result.replace(needle, f'/bin/busybox timeout -s KILL {duration} '.encode())
    return result


def parse_controller(payload):
    fields = {}
    for line in payload.decode('ascii').splitlines():
        match = re.fullmatch(r'(BT_[A-Z_]+) ([0-9]+)', line)
        if not match or match[1] in fields:
            raise ValueError('invalid Bluetooth controller receipt')
        fields[match[1]] = int(match[2])
    expected = {'BT_CONTROLLER_COUNT', 'BT_INDEX', 'BT_VERSION', 'BT_MANUFACTURER',
                'BT_POWERED', 'BT_POWERED_OFF'}
    if (set(fields) != expected or fields['BT_CONTROLLER_COUNT'] != 1 or
            fields['BT_POWERED'] != 1 or fields['BT_POWERED_OFF'] != 1 or
            fields['BT_INDEX'] > 65534 or fields['BT_VERSION'] > 255 or
            fields['BT_MANUFACTURER'] > 65535):
        raise ValueError('Bluetooth power/version/off evidence incomplete')
    return fields


def collect(channel, legacy, deadline, healthy, probe_path='/run/wdt-' + 'A' * 24, save=None):
    report = _COLLECT(channel, legacy, deadline, healthy, probe_path, save)
    row = next(row for row in report['receipts'] if row['key'] == 'bt_controller')
    report['bluetooth_controller_cycle_verified'] = False
    if row['status'] == 'OK':
        try:
            report['bluetooth'] = parse_controller(base64.b64decode(row['stdout_b64'], validate=True))
            report['bluetooth_controller_cycle_verified'] = True
        except ValueError as error:
            report['bluetooth_error'] = str(error)
    if not report['bluetooth_controller_cycle_verified']:
        report['status'] = 'FAILED'
    report['pairing_tested'] = False
    return report


def configure():
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'bluetooth'
    base.SUCCESS_KEY = 'bluetooth_controller_and_eight_cpu_execution_verified'
    base.REQUESTED_SCOPE = 'rebuilt connectivity kernel, Bluetooth power/version/off, eight CPUs'
    base.CAPTURE_BUDGET_SECONDS, base.COMMAND_WAIT_SECONDS = 70, 37
    base.TRANSFER_PROBE = True
    base.tasks, base.capture_script, base.collect = tasks, capture_script, collect


if __name__ == '__main__':
    configure()
    base.main()
