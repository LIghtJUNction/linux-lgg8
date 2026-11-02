#!/usr/bin/env python3
"""Verify Wi-Fi registration without temporary QRTR/PD protocol logging."""
import run_wifi_qrtr_diag_ram_only as observed


def configure():
    observed.configure()
    base = observed.base
    base.collect = observed._COLLECT
    base.CANDIDATE = base.ROOT / 'out/lgg8-tqftp-20261102/private/qrtr-retry-normal-boot'
    base.IMAGE_SHA = '4603381794d5f3a5ee1d3e38f9d0aba5322dd411e6d712a4548ffa1e673a19c5'
    base.MANIFEST_SHA = '0280ccd5868054105b718c073e1411ed6eee469fda55d28e99c36ae22c563d33'
    base.RECORD_PREFIX = 'wifi-qrtr-fixed'
    base.REQUESTED_SCOPE = 'QRTR retry without diagnostic logging, same 30-second window, Wi-Fi registration'


if __name__ == '__main__':
    configure()
    observed.base.main()
