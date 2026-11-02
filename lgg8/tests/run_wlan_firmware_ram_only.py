#!/usr/bin/env python3
"""Deliver stock WLAN DSP firmware and require its WLFW service announcement."""
import run_tqftp_mcfg_ram_only as mcfg

base = mcfg.late.tq.base
_COLLECT = None


def collect(channel, legacy, deadline, healthy, probe_path=None, save=None):
    report = _COLLECT(channel, legacy, deadline, healthy, probe_path, save)
    report['wlfw_service_published'] = any(
        s['service'] == 69 for s in report.get('control', {}).get('services', []))
    report['wlan_firmware_requested'] = {
        'operation': 'read', 'path': '/readonly/firmware/image/wlanmdsp.mbn'
    } in report.get('tqftp_unique_requests', [])
    if not (report['wlfw_service_published'] and report['wlan_firmware_requested']):
        report['status'] = 'FAILED'
    return report


def configure():
    global _COLLECT
    mcfg.configure()
    _COLLECT, base.collect = base.collect, collect
    base.CANDIDATE = base.ROOT / 'out/lgg8-tqftp-20261102/private/wlan-boot'
    base.IMAGE_SHA = '6f8f9dcf702e0c677ab7dd68f8dbd3bf205185b0831a0291aa5e38c40841c13b'
    base.MANIFEST_SHA = '5220ef3026d41451617772defb2ab539930a27adbfe72c747b442f00b99d3697'
    base.RECORD_PREFIX = 'wlan-firmware'
    base.REQUESTED_SCOPE = 'stock WLAN firmware TFTP request and WLFW service 69; Wi-Fi device disabled'
    base.SUCCESS_KEY = 'wlan_firmware_request_and_wlfw_service_verified'


if __name__ == '__main__':
    configure()
    base.main()
