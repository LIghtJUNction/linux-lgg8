#!/usr/bin/env python3
"""Pinned RMTFS experiment; empty storage first, with full Android recovery."""
import base64
import json
import re

import run_modem_ram_only as modem

base = modem.base
CANDIDATE = base.ROOT / 'out/lgg8-rmtfs-20261102/empty-boot'
IMAGE_SHA = 'b77c8333bdf992aa9db77d50eef1254fd1b2da420bc1c3708e5a4e655a496f3d'
MANIFEST_SHA = '67961c72ce380f6792b9b32ed198e7710478a14d13b12d3db483df5b48d5924c'

PREPARE = modem.PREPARE + r'''
test -c /dev/qcom_rmtfs_mem1
test "$(/bin/busybox cat /sys/class/rmtfs/qcom_rmtfs_mem1/phys_addr)" = 0x00000000fa601000
test "$(/bin/busybox cat /sys/class/rmtfs/qcom_rmtfs_mem1/size)" = 0x0000000000200000
/bin/busybox mkdir /run/lgg8-rmtfs-empty
/usr/bin/rmtfs -r -v -o /run/lgg8-rmtfs-empty > /run/lgg8-rmtfs.log 2>&1 &
pid=$!
printf '%s\n' "$pid" > /run/lgg8-rmtfs.pid
/bin/busybox sleep 1
test "$(/bin/busybox readlink /proc/$pid/exe)" = /usr/bin/rmtfs
printf 'RMTFS_READY\n'
'''
DAEMON_STOP = r'''set -eu
IFS= read -r pid < /run/lgg8-rmtfs.pid
case "$pid" in ''|*[!0-9]*) exit 90 ;; esac
test "$pid" -gt 1
test "$(/bin/busybox readlink /proc/$pid/exe)" = /usr/bin/rmtfs
/bin/busybox kill -TERM "$pid"
for try in 0 1 2 3 4 5 6 7 8 9; do
    test -e /proc/$pid/exe || break
    /bin/busybox sleep 0.1
done
test ! -e /proc/$pid/exe
printf 'RMTFS_STOPPED\n'
'''
START = r'''set -eu
IFS= read -r pid < /run/lgg8-rmtfs.pid
case "$pid" in ''|*[!0-9]*) exit 90 ;; esac
test "$pid" -gt 1
test "$(/bin/busybox readlink /proc/$pid/exe)" = /usr/bin/rmtfs
''' + modem.START


def tasks(probe_path=None):
    del probe_path
    return [('prepare', modem.shell(PREPARE), b'MODEM_PREPARED\nRMTFS_READY\n'),
            ('start', modem.shell(START), b'MODEM_RUNNING\n'),
            ('settle', modem.shell(modem.SETTLE), b'running\n'),
            ('control', ['/usr/bin/lgg8-modem-control-probe'], None),
            ('state', modem.shell(modem.STATE), b'running\n'),
            ('stop', modem.shell(modem.STOP), b'MODEM_OFFLINE\n'),
            ('daemon_stop', modem.shell(DAEMON_STOP), b'RMTFS_STOPPED\n'),
            ('rmtfs_log', modem.shell("set -eu; /bin/busybox head -c 4096 /run/lgg8-rmtfs.log; "
                                     "printf '\\nLGG8_RMTFS_LOG_TAIL\\n'; "
                                     "/bin/busybox tail -c 4096 /run/lgg8-rmtfs.log"), None),
            modem.tasks()[-1]]


def capture_script(legacy, prefix, argv):
    names = {base.shlex.join(command): name for name, command, _ in base.tasks()}
    name = names.get(base.shlex.join(argv))
    if name is None:
        raise ValueError('command outside RMTFS whitelist')
    result = modem._BASE_CAPTURE(legacy, prefix, argv)
    needle = b'/bin/busybox timeout -s KILL 1 '
    if result.count(needle) != 1:
        raise ValueError('pinned timeout envelope changed')
    duration = {'prepare': 6, 'daemon_start': 6, 'start': 10, 'settle': 10, 'control': 5,
                'stop': 23, 'daemon_stop': 3}.get(name, 1)
    return result.replace(needle, f'/bin/busybox timeout -s KILL {duration} '.encode())


def collect(channel, legacy, deadline, healthy, probe_path=None, save=None):
    report = modem.collect(channel, legacy, deadline, healthy, probe_path, save)
    rows = {row['key']: row for row in report['receipts']}
    log = (base64.b64decode(rows['rmtfs_log']['stdout_b64'], validate=True).decode('ascii')
           if rows['rmtfs_log']['status'] == 'OK' else '')
    report['rmtfs_open_requests'] = list(dict.fromkeys(re.findall(r'\[RMTFS\] open ([^\s]+) =>', log)))
    report['empty_storage_experiment'] = True
    control = base64.b64decode(rows['control']['stdout_b64'], validate=True).decode('ascii')
    report['rmtfs_service_published'] = (rows['control']['payload_integrity_verified'] and
        not rows['control']['stderr_b64'] and bool(re.search(r'^SERVICE 14 1 1 14$', control, re.M)))
    if not report['rmtfs_service_published']:
        report['status'] = 'FAILED'
    return report


def configure():
    modem.configure()
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'rmtfs'
    base.SUCCESS_KEY = 'rmtfs_dms_revision_verified'
    base.REQUESTED_SCOPE = 'RMTFS with empty RAM storage; one MPSS start and DMS revision query'
    base.CAPTURE_BUDGET_SECONDS = 65
    base.COMMAND_WAIT_SECONDS = 25
    base.tasks, base.capture_script, base.collect = tasks, capture_script, collect


if __name__ == '__main__':
    configure()
    base.main()
