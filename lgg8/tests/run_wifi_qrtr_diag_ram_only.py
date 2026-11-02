#!/usr/bin/env python3
"""Observe QRTR HELLO drops and PD queries without changing protocol behavior."""
import base64
import re

import run_wifi_host_inputs_ram_only as host

wifi = host.delayed.bdf.wifi
base = wifi.base
rmtfs = wifi.wlan.mcfg.late.tq.late
modem = rmtfs.modem
_PREPARE = rmtfs.PREPARE
_SETTLE = modem.SETTLE
_CAPTURE = _COLLECT = None
EARLY = 'set -o pipefail; /bin/busybox dmesg | /bin/busybox tail -c 4096'


def tasks(probe_path=None):
    result = []
    for row in wifi.tasks(probe_path):
        if row[0] == 'settle':
            result.append(('qrtr_early', modem.shell(EARLY), None))
        result.append(row)
    return result


def capture_script(legacy, prefix, argv):
    result = _CAPTURE(legacy, prefix, argv)
    key = next((name for name, command, _ in tasks() if command == argv), None)
    if key == 'settle':
        needle = b'/bin/busybox timeout -s KILL 10 '
        if result.count(needle) != 1:
            raise ValueError('pinned settle timeout changed')
        result = result.replace(needle, b'/bin/busybox timeout -s KILL 32 ')
    return result


def collect(channel, legacy, deadline, healthy, probe_path=None, save=None):
    report = _COLLECT(channel, legacy, deadline, healthy, probe_path, save)
    log = '\n'.join(base64.b64decode(r['stdout_b64'], validate=True).decode('ascii')
                    for r in report['receipts']
                    if r['key'] in ('qrtr_early', 'dmesg_tail') and r['status'] == 'OK')
    report['qrtr_diagnostic_observed'] = 'LGG8_QRTR_ANN' in log and 'LGG8_QRTR_TX' in log
    report['qrtr_prehello_drops'] = [list(map(int, values)) for values in
        re.findall(r'LGG8_QRTR_BLOCK nid=(\d+) type=(\d+) hello=0', log)]
    report['qrtr_announcements'] = [list(map(int, values)) for values in re.findall(
        r'LGG8_QRTR_ANN svc=(\d+) inst=(\d+) owner=(\d+):(\d+) dst=(\d+):(\d+) rc=(-?\d+)', log)]
    report['pd_query_observed'] = 'LGG8_PD_QUERY' in log
    if not report['qrtr_diagnostic_observed']:
        report['status'] = 'FAILED'
    return report


def configure():
    global _CAPTURE, _COLLECT
    host.configure()
    token = '/bin/busybox modprobe qcom_pd_mapper\n'
    if _PREPARE.count(token) != 1 or _SETTLE.count('/bin/busybox sleep 8\n') != 1:
        raise ValueError('pinned MPSS preparation changed')
    rmtfs.PREPARE = ('set -eu\ntest ! -d /sys/module/qrtr\n'
                     '/bin/busybox insmod /opt/lgg8-qrtr-diag/qrtr.ko\n' +
                     _PREPARE.replace(token, '/bin/busybox insmod /opt/lgg8-qrtr-diag/qcom_pd_mapper.ko\n'))
    modem.SETTLE = _SETTLE.replace('/bin/busybox sleep 8\n', '/bin/busybox sleep 30\n')
    _CAPTURE, _COLLECT = base.capture_script, base.collect
    base.tasks, base.capture_script, base.collect = tasks, capture_script, collect
    base.CANDIDATE = base.ROOT / 'out/lgg8-tqftp-20261102/private/qrtr-diag-boot'
    base.IMAGE_SHA = '3f46f5cf09806fc0e790906c3a69346e12905866418ab48ee4890329adf87a5a'
    base.MANIFEST_SHA = '0672072208c5d7ced1a65ffe8c9b4825d88090aad162fa1a340dcae153d57692'
    base.COMMAND_WAIT_SECONDS = 37
    base.RECORD_PREFIX = 'wifi-qrtr-diag'
    base.REQUESTED_SCOPE = 'QRTR HELLO/announcement and PD-query observation, 30-second MPSS window, Wi-Fi registration'


if __name__ == '__main__':
    configure()
    base.main()
