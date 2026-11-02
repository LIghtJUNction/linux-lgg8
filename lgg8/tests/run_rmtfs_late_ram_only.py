#!/usr/bin/env python3
"""Publish RMTFS after MPSS is running, using the same private XZ image."""
import run_rmtfs_xz_ram_only as xz

experiment = xz.nv.experiment
modem = experiment.modem
base = experiment.base
PREPARE = modem.PREPARE + r'''
test -c /dev/qcom_rmtfs_mem1
test -r /opt/lgg8-rmtfs-input/modem_fs1
'''
DAEMON_START = r'''set -eu
/usr/bin/rmtfs -r -v -o /opt/lgg8-rmtfs-input > /run/lgg8-rmtfs.log 2>&1 &
pid=$!
printf '%s\n' "$pid" > /run/lgg8-rmtfs.pid
/bin/busybox sleep 1
test "$(/bin/busybox readlink /proc/$pid/exe)" = /usr/bin/rmtfs
printf 'RMTFS_READY\n'
'''


def tasks(probe_path=None):
    original = experiment.tasks(probe_path)
    return [('prepare', modem.shell(PREPARE), b'MODEM_PREPARED\n'),
            ('start', modem.shell(modem.START), b'MODEM_RUNNING\n'),
            ('daemon_start', modem.shell(DAEMON_START), b'RMTFS_READY\n'),
            *original[2:]]


def configure():
    xz.configure()
    base.RECORD_PREFIX = 'rmtfs-late'
    base.REQUESTED_SCOPE = 'publish RMTFS after MPSS running, with private RAM shadow copies'
    base.tasks = tasks


if __name__ == '__main__':
    configure()
    base.main()
