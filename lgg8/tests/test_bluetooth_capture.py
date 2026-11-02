"""Controller acceptance requires power-on/off evidence and intact transport."""
import subprocess
import unittest
from unittest.mock import patch

import run_bluetooth_ram_only as bt
from test_multicore_capture import Channel

GOOD = (b'BT_CONTROLLER_COUNT 1\nBT_INDEX 0\nBT_VERSION 9\n'
        b'BT_MANUFACTURER 29\nBT_POWERED 1\nBT_POWERED_OFF 1\n')


class Legacy:
    def __init__(self, corrupt=False):
        self.corrupt = corrupt

    def capture_script(self, prefix, argv):
        self.index = int(prefix.rsplit('_', 1)[1])
        return b'/bin/busybox timeout -s KILL 1 /bin/busybox cat /proc/cmdline'

    def parse_frame(self, data, prefix):
        key, _, expected = bt.base.tasks()[self.index]
        if key == 'bt_controller':
            stdout = GOOD
        else:
            stdout = expected or b'log\n'
        return {'payload_integrity_verified': not (self.corrupt and key == 'bt_controller'),
                'exit_code': 0, 'stderr': b'', 'stdout': stdout}


class CaptureTest(unittest.TestCase):
    def test_power_off_and_intact_frame_required(self):
        self.assertEqual(bt.parse_controller(GOOD)['BT_POWERED_OFF'], 1)
        for bad in (GOOD.replace(b'BT_POWERED_OFF 1', b'BT_POWERED_OFF 0'),
                    GOOD.replace(b'BT_CONTROLLER_COUNT 1', b'BT_CONTROLLER_COUNT 2'),
                    GOOD + b'BT_INDEX 0\n', GOOD + b'address 00:00\n'):
            with self.assertRaises(ValueError):
                bt.parse_controller(bad)
        with patch.dict(bt.base.__dict__):
            bt.configure()
            good = bt.base.collect(Channel(), Legacy(), 10**20, lambda: True)
            self.assertEqual(good['status'], 'PASS')
            self.assertTrue(good['bluetooth_controller_cycle_verified'])
            bad = bt.base.collect(Channel(), Legacy(True), 10**20, lambda: True)
            self.assertEqual(bad['status'], 'FAILED')
            self.assertFalse(bad['bluetooth_controller_cycle_verified'])

    @unittest.skipUnless(bt.base.touch.LEGACY.is_file(), 'requires retained framing helper')
    def test_bounded_commands_and_reject_unplanned_reboot(self):
        with patch.dict(bt.base.__dict__):
            bt.configure()
            helper = bt.base.touch.pinned_legacy()
            prefix = 'C234_' + 'B' * 24 + '_bt'
            for key, argv, _ in bt.base.tasks():
                command = bt.base.capture_script(helper, prefix, argv)
                subprocess.run(['/bin/busybox', 'sh', '-n'], input=command, check=True)
                if key == 'bt_controller':
                    self.assertIn(b'timeout -s KILL 35 ', command)
            with self.assertRaises(ValueError):
                bt.base.capture_script(helper, prefix, ['/bin/busybox', 'reboot'])


if __name__ == '__main__':
    unittest.main()
