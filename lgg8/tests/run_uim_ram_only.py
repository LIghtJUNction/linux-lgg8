#!/usr/bin/env python3
"""Read DMS revision and UIM card presence through the validated late RMTFS order."""
from functools import partial

import run_rmtfs_late_ram_only as late

CANDIDATE = late.base.ROOT / 'out/lgg8-rmtfs-20261102/private/uim-boot'
IMAGE_SHA = '4008a255e307bbb0f03e4342fe83ec26f11444355f3fd65f310b009e5fe9d5c1'
MANIFEST_SHA = 'd27589cddc760cfac2e169622f557b1f0575596b33dcdf271a386ea9d0265a07'
_PARSE = late.modem.parse_control


def tasks(probe_path=None):
    return [(key, argv + ['--uim-status'] if key == 'control' else argv, expected)
            for key, argv, expected in late.tasks(probe_path)]


def configure():
    late.configure()
    base = late.base
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'uim'
    base.REQUESTED_SCOPE = 'DMS revision and UIM Get Card Status; private EFS shadow'
    base.SUCCESS_KEY = 'dms_and_uim_card_status_verified'
    base.tasks = tasks
    late.modem.parse_control = partial(_PARSE, with_uim=True)


if __name__ == '__main__':
    configure()
    late.base.main()
