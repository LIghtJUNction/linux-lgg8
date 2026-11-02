#!/usr/bin/env python3
"""Timing control: same BDF image, publish TFTP one second after MPSS ready."""
import run_wifi_bdf_ram_only as bdf


def configure():
    bdf.configure()
    tq = bdf.wifi.wlan.mcfg.late.tq
    delay = '/bin/busybox sleep 1\n'
    if not tq.START.startswith(delay):
        tq.START = delay + tq.START
    bdf.wifi.base.RECORD_PREFIX = 'wifi-bdf-delay'
    bdf.wifi.base.REQUESTED_SCOPE = 'same BDF image with TFTP delayed one second after MPSS running'


if __name__ == '__main__':
    configure()
    bdf.wifi.base.main()
