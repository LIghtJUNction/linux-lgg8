"""TFTP evidence needs intact traffic and RAM storage, without a phone."""
import subprocess
import unittest
from unittest.mock import patch

import run_tqftp_ram_only as tq
import run_tqftp_late_ram_only as late
from test_multicore_capture import Channel

CONTROL = (b'SERVICE 2 1 0 8\nSERVICE 14 1 1 14\nSERVICE 4096 1 1 100\n'
           b'SERVICE_COUNT 3\nDMS_REVISION HE.test\n')
MOUNT = b'tqftp-ram /var/lib/tqftpserv tmpfs rw,nosuid,nodev,noexec,size=8192k,mode=700 0 0\n'


class Legacy:
    def __init__(self, corrupt=None, mount=MOUNT, request_log=None):
        self.corrupt, self.mount = corrupt, mount
        self.request_log = (b'write request for /readwrite/server_check.txt (octet) from 0:100\n'
                            if request_log is None else request_log)

    def capture_script(self, prefix, argv):
        self.index = int(prefix.rsplit('_', 1)[1])
        return b'/bin/busybox timeout -s KILL 1 /bin/busybox cat /proc/cmdline'

    def parse_frame(self, data, prefix):
        key, _, expected = tq.base.tasks()[self.index]
        stdout = {
            'control': CONTROL,
            'rmtfs_log': b'[RMTFS] open /boot/modem_fs1 => 0 (0:0)\n',
            'tqftp_log': self.request_log,
            'tqftp_mount': self.mount}.get(key, expected or b'log\n')
        return {'payload_integrity_verified': key != self.corrupt,
                'exit_code': 0, 'stderr': b'', 'stdout': stdout}


class CaptureTest(unittest.TestCase):
    def test_require_real_requests_intact_control_and_ram_mount(self):
        with patch.dict(tq.base.__dict__), patch.dict(tq.late.experiment.__dict__):
            tq.configure()
            good = tq.base.collect(Channel(), Legacy(), 10**20, lambda: True)
            self.assertEqual(good['status'], 'PASS')
            self.assertTrue(good['tqftp_ram_storage_verified'])
            self.assertTrue(good['private_efs_shadow_experiment'])
            for bad in [Legacy('control'), Legacy('tqftp_log'),
                        Legacy(mount=MOUNT.replace(b'tmpfs', b'ext4')),
                        Legacy(request_log=b'got del_client for 0:8\n')]:
                report = tq.base.collect(Channel(), bad, 10**20, lambda: True)
                self.assertEqual(report['status'], 'FAILED')

    @unittest.skipUnless(tq.base.touch.LEGACY.is_file(), 'requires retained framing helper')
    def test_real_framing_shell_syntax_and_whitelist(self):
        for runner in (tq, late):
            with self.subTest(runner=runner.__name__), patch.dict(tq.base.__dict__), patch.dict(tq.late.experiment.__dict__):
                runner.configure()
                helper = tq.base.touch.pinned_legacy()
                names = [key for key, _, _ in tq.base.tasks()]
                self.assertEqual(names.index('start') < names.index('tqftp_start'), runner is late)
                for key, argv, _ in tq.base.tasks():
                    command = tq.base.capture_script(helper, 'C234_' + 'F' * 24 + '_tq', argv)
                    subprocess.run(['/bin/busybox', 'sh', '-n'], input=command, check=True)
                    if key == 'tqftp_start':
                        self.assertIn(b'timeout -s KILL 5 ', command)
                with self.assertRaises(ValueError):
                    tq.base.capture_script(helper, 'C234_' + 'F' * 24 + '_tq', ['/bin/busybox', 'reboot'])


if __name__ == '__main__':
    unittest.main()
