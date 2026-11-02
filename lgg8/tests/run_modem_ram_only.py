#!/usr/bin/env python3
"""One pinned MPSS start, read-only DMS revision query, stop, Android return."""
import base64
import re

import run_multicore_ram_only as base

CANDIDATE = base.ROOT / 'out/lgg8-modem-20261102/boot'
IMAGE_SHA = '7fd6cb0cfe4ca4c11698f5545fb676055e2e8615fbf2d69d9da9a7e19214ea35'
MANIFEST_SHA = '1b9deb33332d2be10824887c4fdf2433a76c12b7cae3df18c3aa8ae1a425c327'
_BASE_CAPTURE = base.capture_script
_BASE_COLLECT = base.collect

PREPARE = r'''set -eu
umask 077
test "$(/bin/busybox uname -r)" = 7.3.0-lgg8
test ! -e /run/lgg8-mpss-path
/bin/busybox modprobe qrtr-smd
/bin/busybox modprobe qcom_pd_mapper
/bin/busybox modprobe qcom_q6v5_pas
count=0
for r in /sys/class/remoteproc/remoteproc*; do
    test -f "$r/device/of_node/compatible" || continue
    compatible=$(/bin/busybox tr -d '\000' < "$r/device/of_node/compatible")
    test "$compatible" = qcom,sm8150-mpss-pas || continue
    count=$((count + 1))
    found=$r
done
test "$count" = 1
test "$(/bin/busybox cat "$found/firmware")" = qcom/lg/alphalm/modem.mdt
test "$(/bin/busybox cat "$found/state")" = offline
printf 'disabled\n' > "$found/recovery"
printf '%s\n' "$found" > /run/lgg8-mpss-path
printf 'MODEM_PREPARED\n'
'''
PATH_CHECK = r'''set -eu
IFS= read -r r < /run/lgg8-mpss-path
case "$r" in /sys/class/remoteproc/remoteproc[0-9]*) ;; *) exit 90 ;; esac
test "$(/bin/busybox cat "$r/firmware")" = qcom/lg/alphalm/modem.mdt
'''
START = PATH_CHECK + r'''
test "$(/bin/busybox cat "$r/state")" = offline
printf 'start\n' > "$r/state"
test "$(/bin/busybox cat "$r/state")" = running
printf 'MODEM_RUNNING\n'
'''
STATE = PATH_CHECK + r'''
/bin/busybox cat "$r/state"
'''
SETTLE = PATH_CHECK + r'''
/bin/busybox sleep 8
/bin/busybox cat "$r/state"
'''
STOP = PATH_CHECK + r'''
state=$(/bin/busybox cat "$r/state")
case "$state" in
    running|crashed) printf 'stop\n' > "$r/state" ;;
    offline) ;;
    *) exit 91 ;;
esac
test "$(/bin/busybox cat "$r/state")" = offline
printf 'MODEM_OFFLINE\n'
'''


def shell(script):
    return ['/bin/busybox', 'sh', '-c', script]


def tasks(probe_path=None):
    del probe_path
    return [('prepare', shell(PREPARE), b'MODEM_PREPARED\n'),
            ('start', shell(START), b'MODEM_RUNNING\n'),
            ('settle', shell(SETTLE), b'running\n'),
            ('control', ['/usr/bin/lgg8-modem-control-probe'], None),
            ('state', shell(STATE), b'running\n'),
            ('stop', shell(STOP), b'MODEM_OFFLINE\n'),
            ('dmesg_tail', shell('set -o pipefail; /bin/busybox dmesg | /bin/busybox tail -c 8192'), None)]


def capture_script(legacy, prefix, argv):
    commands = {base.shlex.join(command): key for key, command, _ in tasks()}
    key = commands.get(base.shlex.join(argv))
    if key is None:
        raise ValueError('command is outside modem whitelist')
    result = _BASE_CAPTURE(legacy, prefix, argv)
    duration = {'prepare': 4, 'start': 10, 'settle': 10, 'control': 4, 'stop': 17}.get(key, 1)
    timeout = b'/bin/busybox timeout -s KILL 1 '
    if result.count(timeout) != 1:
        raise ValueError('pinned timeout envelope changed')
    return result.replace(timeout, f'/bin/busybox timeout -s KILL {duration} '.encode())


def parse_control(payload, with_uim=False):
    services, count, revision = [], None, None
    uim_count, uim_states = None, []
    for line in payload.decode('ascii').splitlines():
        match = re.fullmatch(r'SERVICE (\d+) (\d+) (\d+) (\d+)', line)
        if match and count is None:
            values = list(map(int, match.groups()))
            if len(services) >= 128 or max(values) > 0xffffffff:
                raise ValueError('invalid QRTR service record')
            services.append(dict(zip(('service', 'instance', 'node', 'port'), values)))
        elif re.fullmatch(r'SERVICE_COUNT \d+', line) and count is None:
            count = int(line.split()[1])
        elif line.startswith('DMS_REVISION ') and count is not None and revision is None:
            revision = line[len('DMS_REVISION '):]
            if not 1 <= len(revision) <= 255 or any(not 32 <= ord(c) <= 126 for c in revision):
                raise ValueError('invalid revision')
        elif with_uim and revision is not None and re.fullmatch(r'UIM_CARD_COUNT [0-8]', line) and uim_count is None:
            uim_count = int(line.split()[1])
        elif with_uim and uim_count is not None and re.fullmatch(r'UIM_CARD [0-7] [0-2]', line):
            _, index, state = line.split()
            if int(index) != len(uim_states) or len(uim_states) >= uim_count:
                raise ValueError('duplicate or unordered UIM card entry')
            uim_states.append(int(state))
        else:
            raise ValueError('invalid or incomplete control record')
    if count != len(services) or revision is None or not any(s['service'] == 2 for s in services):
        raise ValueError('missing DMS service or revision response')
    report = {'services': services, 'firmware_revision': revision,
              'sim_tested': False, 'mobile_data_tested': False}
    if with_uim:
        if uim_count is None or uim_count != len(uim_states) or not any(s['service'] == 11 for s in services):
            raise ValueError('missing UIM service or incomplete card status')
        report.update(sim_status_queried=True, card_states=uim_states,
                      card_present_reported=1 in uim_states)
    return report


def collect(channel, legacy, deadline, healthy, probe_path=None, save=None):
    report = _BASE_COLLECT(channel, legacy, deadline, healthy, probe_path, save)
    rows = {row['key']: row for row in report['receipts']}
    report['mpss_started_verified'] = rows['start']['status'] == 'OK'
    report['dms_exchange_verified'] = False
    if rows['control']['status'] == 'OK':
        try:
            report['control'] = parse_control(base64.b64decode(rows['control']['stdout_b64'], validate=True))
            report['dms_exchange_verified'] = True
        except ValueError as error:
            report['control_error'] = str(error)
    if not report['dms_exchange_verified']:
        report['status'] = 'FAILED'
    return report


def configure():
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'modem'
    base.SUCCESS_KEY = 'mpss_start_dms_revision_stop_verified'
    base.REQUESTED_SCOPE = 'one MPSS start, QRTR discovery, DMS revision, MPSS stop'
    base.CAPTURE_BUDGET_SECONDS = 50
    base.COMMAND_WAIT_SECONDS = 19
    base.TRANSFER_PROBE = False
    base.tasks, base.capture_script, base.collect = tasks, capture_script, collect


if __name__ == '__main__':
    configure()
    base.main()
