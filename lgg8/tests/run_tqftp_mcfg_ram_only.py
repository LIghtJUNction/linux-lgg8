#!/usr/bin/env python3
"""Late TFTP publication with verified stock modem_pr configuration files."""
import run_tqftp_late_ram_only as late


def configure():
    late.configure()
    base = late.tq.base
    base.CANDIDATE = base.ROOT / 'out/lgg8-tqftp-20261102/private/mcfg-boot'
    base.IMAGE_SHA = '6075912ee33d0567d56c1e08ad02eab361cd9f8a892ab89adec5921ffebd7f54'
    base.MANIFEST_SHA = '52d94a55d1eabc887a5ea8cf4966e2164c49115f7b07efbc8cfc74175d07a14a'
    base.RECORD_PREFIX = 'tqftp-mcfg'
    base.REQUESTED_SCOPE = 'late TFTP with verified stock modem_pr; RAM writes and private EFS shadow'


if __name__ == '__main__':
    configure()
    late.tq.base.main()
