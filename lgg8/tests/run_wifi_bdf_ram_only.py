#!/usr/bin/env python3
"""Wi-Fi registration with the exact board file selected by stock Android."""
import run_wifi_ram_only as wifi


def configure():
    wifi.configure()
    base = wifi.base
    base.CANDIDATE = base.ROOT / 'out/lgg8-tqftp-20261102/private/wifi-bdf-boot'
    base.IMAGE_SHA = '80afa12598f7bbcfbfe3a7613aa66dae8c1c022f26dde7e010470bf9333c1a9c'
    base.MANIFEST_SHA = 'd85b5916f9b3a45db463cfff388f9f40a2f93abf91d28d0150b03d3a5cc2b8a2'
    base.RECORD_PREFIX = 'wifi-bdf'
    base.REQUESTED_SCOPE = 'Wi-Fi registration using stock Android-selected bdwlan.bin; no connection'


if __name__ == '__main__':
    configure()
    wifi.base.main()
