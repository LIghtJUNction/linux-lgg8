"""Require actual WLFW discovery and intact Wi-Fi registration evidence."""
import subprocess
import unittest
from unittest.mock import patch

import run_wifi_ram_only as wifi
import run_wifi_qrtr_fixed_ram_only as fixed
import run_wlan_firmware_ram_only as wlan
import test_tqftp_capture as tqtest
from test_multicore_capture import Channel

REQUEST = b'read request for /readonly/firmware/image/wlanmdsp.mbn (mode: octet, rsize: 0, seek: -1) from 0:68\n'
CONTROL = tqtest.CONTROL.replace(b'SERVICE_COUNT 3\n', b'SERVICE 69 1 0 68\nSERVICE_COUNT 4\n')
STATE = b'WIFI_DRIVER_BOUND 1\nWIFI_PHY_COUNT 1\nWIFI_NET_COUNT 1\n'


class Legacy(tqtest.Legacy):
    def __init__(self, state=STATE, **kwargs):
        super().__init__(request_log=REQUEST, **kwargs)
        self.state = state

    def parse_frame(self, data, prefix):
        result = super().parse_frame(data, prefix)
        if wifi.base.tasks()[self.index][0] == 'wifi_state':
            result['stdout'] = self.state
        return result


class WifiCaptureTest(unittest.TestCase):
    def test_production_profile_needs_registration_without_diagnostic_logs(self):
        observed = fixed.observed
        with patch.dict(wifi.base.__dict__), patch.dict(observed.modem.__dict__), \
                patch.dict(observed.rmtfs.__dict__), patch.dict(tqtest.tq.__dict__), \
                patch.dict(tqtest.tq.late.experiment.__dict__), patch.object(tqtest, 'CONTROL', CONTROL):
            fixed.configure()
            good = wifi.base.collect(Channel(), Legacy(), 10**20, lambda: True)
            self.assertEqual(good['status'], 'PASS')
            self.assertFalse(good['wifi_connection_tested'])
            bad = Legacy(state=STATE.replace(b'PHY_COUNT 1', b'PHY_COUNT 0'))
            self.assertEqual(wifi.base.collect(Channel(), bad, 10**20, lambda: True)['status'], 'FAILED')

    def test_wlfw_and_firmware_request_both_required(self):
        with patch.dict(wlan.base.__dict__), patch.dict(tqtest.tq.late.experiment.__dict__):
            wlan.configure()
            absent = wlan.base.collect(Channel(), Legacy(), 10**20, lambda: True)
            self.assertEqual(absent['status'], 'FAILED')
            with patch.object(tqtest, 'CONTROL', CONTROL):
                good = wlan.base.collect(Channel(), Legacy(), 10**20, lambda: True)
                self.assertEqual(good['status'], 'PASS')
                no_request = wlan.base.collect(Channel(), tqtest.Legacy(), 10**20, lambda: True)
                self.assertEqual(no_request['status'], 'FAILED')

    def test_interface_registration_requires_intact_complete_evidence(self):
        with patch.dict(wifi.base.__dict__), patch.dict(tqtest.tq.late.experiment.__dict__), patch.object(tqtest, 'CONTROL', CONTROL):
            wifi.configure()
            good = wifi.base.collect(Channel(), Legacy(), 10**20, lambda: True)
            self.assertEqual(good['status'], 'PASS')
            self.assertTrue(good['wifi_tested'])
            self.assertFalse(good['wifi_connection_tested'])
            for bad in (Legacy(corrupt='wifi_state'),
                        Legacy(state=STATE.replace(b'BOUND 1', b'BOUND 0')),
                        Legacy(state=STATE.replace(b'PHY_COUNT 1', b'PHY_COUNT 0')),
                        Legacy(state=STATE.replace(b'NET_COUNT 1', b'NET_COUNT 0'))):
                self.assertEqual(wifi.base.collect(Channel(), bad, 10**20, lambda: True)['status'], 'FAILED')

    @unittest.skipUnless(wifi.base.touch.LEGACY.is_file(), 'requires retained framing helper')
    def test_pinned_framing_and_driver_loading_timeout(self):
        with patch.dict(wifi.base.__dict__), patch.dict(tqtest.tq.late.experiment.__dict__):
            wifi.configure()
            helper = wifi.base.touch.pinned_legacy()
            for key, argv, _ in wifi.base.tasks():
                command = wifi.base.capture_script(helper, 'C234_' + 'F' * 24 + '_wifi', argv)
                subprocess.run(['/bin/busybox', 'sh', '-n'], input=command, check=True)
                if key == 'wifi_prepare':
                    self.assertIn(b'timeout -s KILL 8 ', command)


if __name__ == '__main__':
    unittest.main()
