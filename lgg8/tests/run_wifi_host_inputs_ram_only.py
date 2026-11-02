#!/usr/bin/env python3
"""Same timing control with upstream ath10k metadata and signed regdb inputs."""
import run_wifi_bdf_delay_ram_only as delayed


def configure():
    delayed.configure()
    base = delayed.bdf.wifi.base
    base.CANDIDATE = base.ROOT / 'out/lgg8-tqftp-20261102/private/wifi-host-inputs-boot'
    base.IMAGE_SHA = 'cbe59fec688d5204c7e7e4b2770c083c445ac1436f756f3b5e24f354e3851d87'
    base.MANIFEST_SHA = '8442e33b97f5fe9045cdae32bb498736e0d03c849de383a38e691d48e4883f42'
    base.RECORD_PREFIX = 'wifi-host-inputs'
    base.REQUESTED_SCOPE = 'Wi-Fi registration with stock firmware/BDF, upstream metadata and signed regdb'


if __name__ == '__main__':
    configure()
    delayed.bdf.wifi.base.main()
