#!/usr/bin/env python3
"""Observe modem TFTP requests with an explicitly bounded RAM write directory."""
import base64
import re

import run_rmtfs_late_ram_only as late

base = late.base
CANDIDATE = base.ROOT / 'out/lgg8-tqftp-20261102/private/boot'
IMAGE_SHA = '4e8f80d137b0a1ca71bc23588b261d9f8836e05203d7a13ec1f51c165e79e438'
MANIFEST_SHA = '79d5ea3356d620cb3e0bbd02a31b1475ad726041d932ced8c77d911a6324f6e3'
_COLLECT = _CAPTURE = None
START = r'''set -eu
test ! -e /run/lgg8-tqftp.pid
test ! -e /var/lib/tqftpserv
test "$(/bin/busybox wc -c < /sys/module/firmware_class/parameters/path)" -eq 1
test -z "$(/bin/busybox cat /sys/module/firmware_class/parameters/path)"
/bin/busybox mkdir -p -m 700 /var/lib/tqftpserv
/bin/busybox mount -t tmpfs -o size=8m,mode=700,nosuid,nodev,noexec tqftp-ram /var/lib/tqftpserv
/usr/bin/tqftpserv -d > /run/lgg8-tqftp.log 2>&1 &
pid=$!
printf '%s\n' "$pid" > /run/lgg8-tqftp.pid
/bin/busybox sleep 1
test "$(/bin/busybox readlink /proc/$pid/exe)" = /usr/bin/tqftpserv
printf 'TQFTP_READY\n'
'''
STOP = late.experiment.DAEMON_STOP.replace('rmtfs', 'tqftp').replace(
    '/usr/bin/tqftp', '/usr/bin/tqftpserv').replace('RMTFS_STOPPED', 'TQFTP_STOPPED')
MOUNT = "/bin/busybox grep '^tqftp-ram /var/lib/tqftpserv tmpfs ' /proc/mounts"
LOG = ("set -eu; /bin/busybox head -c 4096 /run/lgg8-tqftp.log; "
       "printf '\\nLGG8_TQFTP_LOG_TAIL\\n'; /bin/busybox tail -c 4096 /run/lgg8-tqftp.log")


def tasks(probe_path=None):
    original = late.tasks(probe_path)
    shell = late.modem.shell
    return [original[0], ('tqftp_start', shell(START), b'TQFTP_READY\n'),
            ('tqftp_mount', shell(MOUNT), None), *original[1:-1],
            ('tqftp_stop', shell(STOP), b'TQFTP_STOPPED\n'),
            ('tqftp_log', shell(LOG), None), original[-1]]


def capture_script(legacy, prefix, argv):
    result = _CAPTURE(legacy, prefix, argv)
    key = next((name for name, command, _ in tasks() if command == argv), None)
    if key in ('tqftp_start', 'tqftp_stop', 'tqftp_log'):
        needle = b'/bin/busybox timeout -s KILL 1 '
        if result.count(needle) != 1:
            raise ValueError('pinned timeout envelope changed')
        duration = {'tqftp_start': 5, 'tqftp_stop': 3, 'tqftp_log': 2}[key]
        result = result.replace(needle, f'/bin/busybox timeout -s KILL {duration} '.encode())
    return result


def collect(channel, legacy, deadline, healthy, probe_path=None, save=None):
    report = _COLLECT(channel, legacy, deadline, healthy, probe_path, save)
    rows = {row['key']: row for row in report['receipts']}

    def payload(key):
        row = rows[key]
        return (base64.b64decode(row['stdout_b64'], validate=True).decode('ascii')
                if row['status'] == 'OK' else '')

    report['tqftp_service_published'] = any(
        s['service'] == 4096 and s['instance'] == 1
        for s in report.get('control', {}).get('services', []))
    mount = payload('tqftp_mount').split()
    report['tqftp_ram_storage_verified'] = (
        len(mount) == 6 and mount[:3] == ['tqftp-ram', '/var/lib/tqftpserv', 'tmpfs'] and
        {'size=8192k', 'mode=700', 'nosuid', 'nodev', 'noexec'} <= set(mount[3].split(',')))
    found = re.findall(r'^(read|write) request for (\S+) \([^)]*\) from \d+:\d+$',
                       payload('tqftp_log'), re.M)
    report['tqftp_unique_requests'] = [{'operation': op, 'path': path}
                                        for op, path in dict.fromkeys(found)]
    report['wifi_tested'] = False
    if not (report['tqftp_service_published'] and report['tqftp_ram_storage_verified'] and found):
        report['status'] = 'FAILED'
    return report


def configure():
    global _COLLECT, _CAPTURE
    late.configure()
    _COLLECT, _CAPTURE = base.collect, base.capture_script
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'tqftp'
    base.REQUESTED_SCOPE = 'TFTP requests, DMS revision and private EFS shadow; writes only on bounded RAM tmpfs'
    base.SUCCESS_KEY = 'tftp_requests_ram_storage_and_dms_verified'
    base.CAPTURE_BUDGET_SECONDS = 70
    base.tasks, base.capture_script, base.collect = tasks, capture_script, collect


if __name__ == '__main__':
    configure()
    base.main()
