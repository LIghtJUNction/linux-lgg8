#!/usr/bin/env python3
"""Repeat the DMS/UIM acceptance using the rebuilt connectivity kernel."""
import run_uim_ram_only as uim

base = uim.late.base
CANDIDATE = base.ROOT / 'out/lgg8-connectivity-20261102/private/radio-baseline-boot'
IMAGE_SHA = '643f38db45124a072ecca767397fdd536a9a2a3192e0466df7cff24da8806ec7'
MANIFEST_SHA = '1d51c002dda5b4f7a9491c27f15f59310b4654dcc8df159abf300b06b0c00a78'


def configure():
    uim.configure()
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'uim-connectivity'
    base.REQUESTED_SCOPE = 'new connectivity kernel with matching modules, DMS/UIM and private EFS shadow'
    base.SUCCESS_KEY = 'rebuilt_kernel_dms_and_uim_card_status_verified'


if __name__ == '__main__':
    configure()
    base.main()
