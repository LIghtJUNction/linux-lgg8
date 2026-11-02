#!/usr/bin/env python3
"""Enable only the experimental Wi-Fi node; require driver, wiphy and interface."""
import base64
import re

import run_wlan_firmware_ram_only as wlan

base = wlan.base
_COLLECT = _CAPTURE = None
PREPARE = r'''set -eu
/bin/busybox modprobe ath10k_core debug_mask=0x00300000
/bin/busybox modprobe ath10k_snoc
test -d /sys/module/ath10k_snoc
printf 'WIFI_MODULE_LOADED\n'
'''
STATE = r'''set -eu
bound=0
if test "$(/bin/busybox readlink -f /sys/bus/platform/devices/18800000.wifi/driver)" = /sys/bus/platform/drivers/ath10k_snoc; then
    bound=1
fi
phys=0
for p in /sys/class/ieee80211/phy*; do
    test -d "$p" || continue
    phys=$((phys + 1))
done
interfaces=0
for p in /sys/class/net/*/phy80211; do
    test -d "$p" || continue
    interfaces=$((interfaces + 1))
done
printf 'WIFI_DRIVER_BOUND %s\nWIFI_PHY_COUNT %s\nWIFI_NET_COUNT %s\n' "$bound" "$phys" "$interfaces"
'''


def tasks(probe_path=None):
    result = []
    for row in wlan.mcfg.late.tasks(probe_path):
        if row[0] == 'start':
            result.append(('wifi_prepare', wlan.mcfg.late.tq.late.modem.shell(PREPARE),
                           b'WIFI_MODULE_LOADED\n'))
        if row[0] == 'stop':
            result.append(('wifi_state', wlan.mcfg.late.tq.late.modem.shell(STATE), None))
        result.append(row)
    return result


def collect(channel, legacy, deadline, healthy, probe_path=None, save=None):
    report = _COLLECT(channel, legacy, deadline, healthy, probe_path, save)
    row = next(r for r in report['receipts'] if r['key'] == 'wifi_state')
    data = base64.b64decode(row['stdout_b64'], validate=True)
    match = re.fullmatch(rb'WIFI_DRIVER_BOUND ([01])\nWIFI_PHY_COUNT (\d+)\nWIFI_NET_COUNT (\d+)\n', data)
    report['wifi_tested'] = True
    report['wifi_connection_tested'] = False
    report['wifi_driver_and_interface_registered'] = (
        row['status'] == 'OK' and match is not None and match.groups() == (b'1', b'1', b'1'))
    if not report['wifi_driver_and_interface_registered']:
        report['status'] = 'FAILED'
    return report


def capture_script(legacy, prefix, argv):
    result = _CAPTURE(legacy, prefix, argv)
    key = next((name for name, command, _ in tasks() if command == argv), None)
    if key in ('wifi_prepare', 'wifi_state'):
        needle = b'/bin/busybox timeout -s KILL 1 '
        if result.count(needle) != 1:
            raise ValueError('pinned timeout envelope changed')
        duration = 8 if key == 'wifi_prepare' else 2
        result = result.replace(needle, f'/bin/busybox timeout -s KILL {duration} '.encode())
    return result


def configure():
    global _COLLECT, _CAPTURE
    wlan.configure()
    _COLLECT, base.collect = base.collect, collect
    _CAPTURE, base.capture_script = base.capture_script, capture_script
    base.CANDIDATE = base.ROOT / 'out/lgg8-tqftp-20261102/private/wifi-wlan-boot'
    base.IMAGE_SHA = '6e1b5853366a41cc04672384a8e41bc1da902204c5d65e112fd43a3f9f6d6cee'
    base.MANIFEST_SHA = 'aef164ad35dd3e54d3092c977d8178c245c0d516f26ef5f740c170f61c35b8bb'
    base.RECORD_PREFIX = 'wifi'
    base.REQUESTED_SCOPE = 'experimental Wi-Fi driver, WLFW and interface registration; no network connection'
    base.SUCCESS_KEY = 'wifi_driver_and_interface_registration_verified'
    base.tasks = tasks


if __name__ == '__main__':
    configure()
    base.main()
