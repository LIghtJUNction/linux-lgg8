#!/usr/bin/env python3
"""Pinned eight-CPU idle-counter experiment; explicit RAM-only execution."""
import base64
import json
import re

import run_multicore_ram_only as base

CANDIDATE = base.ROOT / 'out/lgg8-cpuidle-20261102/boot'
IMAGE_SHA = 'f800d267f21073ffce43c5c86984cbe4e2b4f91d5e37cd8653a8bac26420ea91'
MANIFEST_SHA = '798f492b7893e8ca3c20e6cc7bf6b0d51b0239803a7fb5604731566915ff915c'
_BASE_CHECK = base.check
_BASE_TASKS = base.tasks
_BASE_CAPTURE = base.capture_script
_BASE_COLLECT = base.collect

# All reads are sysfs/procfs; the sleep creates a sampling interval, not suspend.
IDLE_SCRIPT = '''set -eu
for sample in 0 1; do
    printf 'SAMPLE|%s\n' "$sample"
    IFS= read -r driver < /sys/devices/system/cpu/cpuidle/current_driver
    printf 'DRIVER|%s\n' "$driver"
    read -r uptime rest < /proc/uptime
    printf 'UPTIME|%s\n' "$uptime"
    for cpu in 0 1 2 3 4 5 6 7; do
        for state in /sys/devices/system/cpu/cpu$cpu/cpuidle/state*; do
            IFS= read -r name < "$state/name"
            IFS= read -r usage < "$state/usage"
            IFS= read -r duration < "$state/time"
            IFS= read -r disabled < "$state/disable"
            printf 'STATE|%s|%s|%s|%s|%s|%s\n' "$cpu" "${state##*/}" "$name" "$usage" "$duration" "$disabled"
        done
    done
    if [ "$sample" = 0 ]; then /bin/busybox sleep 1; fi
done
printf 'END\n'
'''
IDLE_ARGV = ['/bin/busybox', 'sh', '-c', IDLE_SCRIPT]


def tasks(probe_path='/run/wdt-' + 'A' * 24):
    original = _BASE_TASKS(probe_path)
    # Pin and execute on every core after the idle interval, checking return.
    return original[:3] + [('idle_pair', IDLE_ARGV, None)] + original[3:]


def capture_script(legacy, prefix, argv):
    command = _BASE_CAPTURE(legacy, prefix, argv)
    if argv == IDLE_ARGV:
        timeout = b'/bin/busybox timeout -s KILL 1 '
        if command.count(timeout) != 1:
            raise ValueError('pinned timeout envelope changed')
        command = command.replace(timeout, b'/bin/busybox timeout -s KILL 3 ')
    return command


def parse_idle(payload):
    samples = []
    ended = False
    for line in payload.decode('ascii').splitlines():
        if ended:
            raise ValueError('data after idle terminator')
        fields = line.split('|')
        if fields[0] == 'SAMPLE':
            if fields != ['SAMPLE', str(len(samples))] or len(samples) >= 2:
                raise ValueError('invalid sample sequence')
            samples.append({'states': {}})
        elif not samples:
            raise ValueError('missing sample')
        elif fields[0] in ('DRIVER', 'UPTIME'):
            key = fields[0].lower()
            if len(fields) != 2 or key in samples[-1]:
                raise ValueError('invalid or duplicate sample metadata')
            if key == 'uptime' and re.fullmatch(r'\d+\.\d+', fields[1]) is None:
                raise ValueError('invalid uptime')
            samples[-1][key] = fields[1]
        elif fields[0] == 'STATE':
            if (len(fields) != 7 or re.fullmatch(r'[0-7]', fields[1]) is None or
                    re.fullmatch(r'state[0-9]+', fields[2]) is None or
                    re.fullmatch(r'[-A-Za-z0-9_]{1,64}', fields[3]) is None or
                    any(re.fullmatch(r'\d{1,20}', value) is None for value in fields[4:]) or
                    fields[6] not in ('0', '1')):
                raise ValueError('invalid state record')
            key = (int(fields[1]), fields[2])
            if key in samples[-1]['states']:
                raise ValueError('duplicate state')
            samples[-1]['states'][key] = (fields[3], *map(int, fields[4:]))
        elif fields == ['END']:
            ended = True
        else:
            raise ValueError('unknown idle record')
    if not ended or len(samples) != 2:
        raise ValueError('incomplete idle samples')
    before, after = samples
    if any(s.get('driver') != 'psci_idle' or 'uptime' not in s for s in samples):
        raise ValueError('PSCI idle driver or uptime missing')
    interval = float(after['uptime']) - float(before['uptime'])
    if not 0.5 <= interval <= 4:
        raise ValueError('idle sample interval outside bounds')
    if before['states'].keys() != after['states'].keys():
        raise ValueError('idle topology changed between samples')
    cores = []
    for cpu in range(8):
        states = []
        for key, previous in before['states'].items():
            if key[0] != cpu:
                continue
            current = after['states'][key]
            if previous[0] != current[0] or previous[3] or current[3]:
                raise ValueError('state renamed or disabled')
            usage, duration = current[1] - previous[1], current[2] - previous[2]
            if min(usage, duration) < 0:
                raise ValueError('idle counter moved backward')
            states.append({'state': key[1], 'name': current[0],
                           'usage_delta': usage, 'time_us_delta': duration})
        if not any(s['state'] == 'state0' for s in states) or len(states) < 2:
            raise ValueError('CPU missing idle states')
        deep = any(s['name'] != 'WFI' and s['state'] != 'state0' and
                   s['usage_delta'] > 0 and s['time_us_delta'] > 0 for s in states)
        cores.append({'cpu': cpu, 'deeper_than_wfi_observed': deep, 'states': states})
    passed = all(core['deeper_than_wfi_observed'] for core in cores)
    return {'status': 'PASS' if passed else 'FAILED', 'driver': 'psci_idle',
            'interval_seconds': round(interval, 3), 'cores': cores,
            'measured_power_savings': False, 'system_suspend_tested': False}


def collect(channel, legacy, deadline, healthy, probe_path='/run/wdt-' + 'A' * 24, save=None):
    report = _BASE_COLLECT(channel, legacy, deadline, healthy, probe_path, save)
    idle = next(row for row in report['receipts'] if row['key'] == 'idle_pair')
    if idle['status'] == 'OK':
        try:
            report['idle_verification'] = parse_idle(base64.b64decode(idle['stdout_b64'], validate=True))
        except ValueError as error:
            report['idle_verification'] = {'status': 'FAILED', 'error': str(error)}
    else:
        report['idle_verification'] = {'status': 'FAILED', 'error': 'idle read command failed'}
    if report['idle_verification']['status'] != 'PASS':
        report['status'] = 'FAILED'
    return report


def check():
    report = _BASE_CHECK()
    args = json.loads((CANDIDATE / 'manifest.json').read_text())['bootargs'].split()
    if [arg for arg in args if arg.startswith('cpuidle.off=')] != ['cpuidle.off=0']:
        raise ValueError('CPU idle candidate argument mismatch')
    return report


def configure():
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'cpuidle'
    base.SUCCESS_KEY = 'eight_cpu_idle_and_execution_verified'
    base.REQUESTED_SCOPE = 'PSCI idle counters advance on every CPU, then each CPU executes the probe'
    base.tasks, base.capture_script, base.collect, base.check = tasks, capture_script, collect, check


if __name__ == '__main__':
    configure()
    base.main()
