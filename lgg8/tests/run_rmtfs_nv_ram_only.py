#!/usr/bin/env python3
"""Pinned private EFS-copy experiment; all modem writes stay in memory."""
import run_rmtfs_ram_only as experiment

CANDIDATE = experiment.base.ROOT / 'out/lgg8-rmtfs-20261102/private/seed-boot'
IMAGE_SHA = '04fcb32e88d8ea5103c7d02757ff59fb7a71ec708e0fddea6f11ff8beea61579'
MANIFEST_SHA = '1181ea9dc75b1581b0c91fb8175d2bd9f327a26f76f05661d80dfa4832a0a07a'


def configure():
    experiment.PREPARE = experiment.PREPARE.replace(
        '/bin/busybox mkdir /run/lgg8-rmtfs-empty',
        'test -d /opt/lgg8-rmtfs-input').replace(
        '-o /run/lgg8-rmtfs-empty', '-o /opt/lgg8-rmtfs-input')
    experiment.configure()
    base = experiment.base
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'rmtfs-nv'
    base.REQUESTED_SCOPE = 'private verified EFS copies; RMTFS writes stay in RAM; DMS revision'
    original_collect = experiment.collect

    def collect(*args, **kwargs):
        report = original_collect(*args, **kwargs)
        report['empty_storage_experiment'] = False
        report['private_efs_shadow_experiment'] = True
        return report

    base.collect = collect


if __name__ == '__main__':
    configure()
    experiment.base.main()
