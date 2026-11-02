"""Service-order experiments retain command bounds and require intact evidence."""
import subprocess
import unittest
from unittest.mock import patch

import run_rmtfs_late_ram_only as late
from test_multicore_capture import Channel

GOOD = b'SERVICE 2 1 0 8\nSERVICE 14 1 1 14\nSERVICE_COUNT 2\nDMS_REVISION HE.test\n'


class Legacy:
    def __init__(self, corrupt=False):
        self.corrupt = corrupt

    def capture_script(self, prefix, argv):
        self.index = int(prefix.rsplit('_', 1)[1])
        return b'/bin/busybox timeout -s KILL 1 /bin/busybox cat /proc/cmdline'

    def parse_frame(self, data, prefix):
        key, _, expected = late.base.tasks()[self.index]
        stdout = GOOD if key == 'control' else expected or b'log\n'
        if key == 'rmtfs_log':
            stdout = b'[RMTFS] open /boot/modem_fs1 => 0 (0:0)\n'
        return {'payload_integrity_verified': not (self.corrupt and key == 'control'),
                'exit_code': 0, 'stderr': b'', 'stdout': stdout}


class CaptureTest(unittest.TestCase):
    def test_late_publish_and_corrupt_service_receipt_rejection(self):
        with patch.dict(late.base.__dict__), patch.dict(late.experiment.__dict__):
            late.configure()
            keys = [key for key, _, _ in late.base.tasks()]
            self.assertLess(keys.index('start'), keys.index('daemon_start'))
            self.assertLess(keys.index('stop'), keys.index('daemon_stop'))
            good = late.base.collect(Channel(), Legacy(), 10**20, lambda: True)
            self.assertEqual(good['status'], 'PASS')
            self.assertTrue(good['rmtfs_service_published'])
            self.assertEqual(good['rmtfs_open_requests'], ['/boot/modem_fs1'])
            bad = late.base.collect(Channel(), Legacy(True), 10**20, lambda: True)
            self.assertEqual(bad['status'], 'FAILED')
            self.assertFalse(bad['rmtfs_service_published'])

    @unittest.skipUnless(late.base.touch.LEGACY.is_file(), 'requires retained framing helper')
    def test_real_helper_shell_syntax_and_out_of_scope_command_rejection(self):
        with patch.dict(late.base.__dict__), patch.dict(late.experiment.__dict__):
            late.configure()
            helper = late.base.touch.pinned_legacy()
            prefix = 'C234_' + 'D' * 24 + '_rfs'
            for key, argv, _ in late.base.tasks():
                command = late.base.capture_script(helper, prefix, argv)
                subprocess.run(['/bin/busybox', 'sh', '-n'], input=command, check=True)
                if key == 'stop':
                    self.assertIn(b'timeout -s KILL 23 ', command)
            with self.assertRaises(ValueError):
                late.base.capture_script(helper, prefix, ['/bin/busybox', 'reboot'])


if __name__ == '__main__':
    unittest.main()
