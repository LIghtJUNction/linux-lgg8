#!/usr/bin/env python3
"""Test deferred service announcements with the diagnostic control's inputs."""
import run_wifi_qrtr_diag_ram_only as observed


def configure():
    observed.configure()
    base = observed.base
    base.CANDIDATE = base.ROOT / 'out/lgg8-tqftp-20261102/private/qrtr-retry-boot'
    base.IMAGE_SHA = 'b3b48a8f638e22c717d5d565347680a767b6c8f0efebdfad5a2907f120f24922'
    base.MANIFEST_SHA = '2d3bdf1df2fd416aff53ed56d952f401138f6d969ee031263196131447c6bfa1'
    base.RECORD_PREFIX = 'wifi-qrtr-retry'
    base.REQUESTED_SCOPE = 'QRTR announcement retry, same 30-second diagnostic window, Wi-Fi registration'


if __name__ == '__main__':
    configure()
    observed.base.main()
