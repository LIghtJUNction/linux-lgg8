#!/usr/bin/env python3
"""Same verified EFS input and raw archive, with CRC32 XZ encoding."""
import run_rmtfs_nv_ram_only as nv

CANDIDATE = nv.experiment.base.ROOT / 'out/lgg8-rmtfs-20261102/private/xz-boot'
IMAGE_SHA = '293eac6dd6b48ef89be032b60ec7809d4e9e72cc3f7544edd0aa9b551e3fda78'
MANIFEST_SHA = '43d1f8c094835403c875cec538bbdf85356c6499252b283252f0efd2357cd975'


def configure():
    nv.configure()
    base = nv.experiment.base
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'rmtfs-xz'


if __name__ == '__main__':
    configure()
    nv.experiment.base.main()
