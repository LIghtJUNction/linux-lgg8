"""Bounded modem commands and evidence validation without a phone."""
import subprocess
import unittest
from unittest.mock import patch

import run_modem_ram_only as modem
from test_multicore_capture import Channel

GOOD = b'SERVICE 2 1 0 8\nSERVICE 11 1 0 9\nSERVICE_COUNT 2\nDMS_REVISION HE.test\n'


class Legacy:
    def __init__(self, bad=False):
        self.bad = bad
        self.visited = []

    def capture_script(self, prefix, argv):
        self.index = int(prefix.rsplit('_', 1)[1])
        return b'/bin/busybox timeout -s KILL 1 /bin/busybox cat /proc/cmdline'

    def parse_frame(self, data, prefix):
        key, _, expected = modem.tasks()[self.index]
        self.visited.append(key)
        return {'payload_integrity_verified': not (self.bad and key == 'control'),
                'exit_code': 0, 'stderr': b'',
                'stdout': GOOD if key == 'control' else expected or b'log\n'}


class ModemTest(unittest.TestCase):
    def test_uim_status_requires_every_card_and_service_and_is_opt_in(self):
        data = GOOD + b'UIM_CARD_COUNT 1\nUIM_CARD 0 0\n'
        report = modem.parse_control(data, with_uim=True)
        self.assertEqual(report['card_states'], [0])
        self.assertTrue(report['sim_status_queried'])
        self.assertFalse(report['card_present_reported'])
        self.assertFalse(report['sim_tested'])
        for invalid in (data.replace(b'UIM_CARD 0 0\n', b''),
                        data.replace(b'SERVICE 11 ', b'SERVICE 12 '),
                        data.replace(b'UIM_CARD 0 0', b'UIM_CARD 0 3'),
                        data + b'UIM_CARD 0 0\n'):
            with self.subTest(payload=invalid), self.assertRaises(ValueError):
                modem.parse_control(invalid, with_uim=True)
        with self.assertRaises(ValueError):
            modem.parse_control(data)

    def test_control_requires_matching_service_count_and_revision(self):
        self.assertEqual(modem.parse_control(GOOD)['firmware_revision'], 'HE.test')
        for invalid in (GOOD.replace(b'COUNT 2', b'COUNT 3'),
                        GOOD.replace(b'SERVICE 2 ', b'SERVICE 4 '),
                        GOOD.replace(b'DMS_REVISION HE.test\n', b''),
                        GOOD + b'extra\n', GOOD + b'DMS_REVISION HE.test\n',
                        GOOD.replace(b'HE.test', b'\x00'),
                        GOOD.replace(b'SERVICE 11', b'SERVICE 4294967296')):
            with self.subTest(payload=invalid), self.assertRaises(ValueError):
                modem.parse_control(invalid)

    def test_invalid_control_still_runs_shutdown_and_cannot_pass(self):
        with patch.dict(modem.base.__dict__):
            modem.configure()
            good = modem.collect(Channel(), Legacy(), 10**20, lambda: True)
            self.assertEqual(good['status'], 'PASS')
            self.assertTrue(good['mpss_started_verified'])
            self.assertTrue(good['dms_exchange_verified'])
            legacy = Legacy(bad=True)
            bad = modem.collect(Channel(), legacy, 10**20, lambda: True)
            self.assertEqual(bad['status'], 'FAILED')
            self.assertFalse(bad['dms_exchange_verified'])
            self.assertIn('stop', legacy.visited)
            self.assertFalse(modem.base.TRANSFER_PROBE)

    @unittest.skipUnless(modem.base.touch.LEGACY.is_file(), 'requires retained C234 helper')
    def test_real_helper_bounded_timeouts_shell_syntax_and_whitelist(self):
        legacy = modem.base.touch.pinned_legacy()
        with patch.dict(modem.base.__dict__):
            modem.configure()
            prefix = 'C234_' + 'A' * 24 + '_modem'
            for key, argv, _ in modem.tasks():
                command = modem.capture_script(legacy, prefix, argv)
                subprocess.run(['/bin/busybox', 'sh', '-n'], input=command, check=True)
                if key == 'start':
                    self.assertIn(b'timeout -s KILL 10 ', command)
            with self.assertRaises(ValueError):
                modem.capture_script(legacy, prefix, ['/bin/busybox', 'reboot'])
            with self.assertRaises(ValueError):
                modem.capture_script(legacy, prefix, ['/run/wdt-' + 'A' * 24])


if __name__ == '__main__':
    unittest.main()
