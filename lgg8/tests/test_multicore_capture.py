"""CPU receipt validation and fail-closed transport tests, without a phone."""
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_multicore_ram_only as runner


class Channel:
    def __init__(self):
        self.sent = 0

    def send(self, data, deadline):
        self.sent += 1

    def until(self, predicate, deadline):
        return predicate(b'frame')


class Legacy:
    def __init__(self, bad=None):
        self.bad = bad

    def capture_script(self, prefix, argv):
        self.index = int(prefix.rsplit('_', 1)[1])
        return b'/bin/busybox cat /proc/cmdline'

    def parse_frame(self, data, prefix):
        name, _, expected = runner.tasks()[self.index]
        frame = {'payload_integrity_verified': True, 'exit_code': 0,
                 'stdout': expected if expected is not None else b'log\n', 'stderr': b''}
        if self.bad and self.bad[0] == name:
            frame.update(self.bad[1])
        return frame


class MulticoreTest(unittest.TestCase):
    @unittest.skipUnless(runner.touch.LEGACY.is_file(), 'requires retained C234 helper')
    def test_real_framing_helper_and_busybox_receipts(self):
        legacy = runner.touch.pinned_legacy()
        prefix = 'C234_' + 'A' * 24 + '_cpu'
        for _, argv, _ in runner.tasks():
            command = runner.capture_script(legacy, prefix, argv)
            subprocess.run(['/bin/busybox', 'sh', '-n'], input=command, check=True)
        with self.assertRaises(ValueError):
            runner.capture_script(legacy, prefix, ['/bin/busybox', 'reboot'])
        with tempfile.TemporaryDirectory(prefix='multicore-frame-') as temp:
            selected = [('online', runner.tasks()[0][1])]
            for name, argv in selected:
                command = runner.capture_script(legacy, prefix, argv)
                command = command.replace(('/run/' + prefix).encode(),
                                          str(Path(temp) / 'capture').encode())
                output = subprocess.check_output(['/bin/busybox', 'sh', '-c', command], timeout=5)
                receipt = legacy.parse_frame(output, prefix)
                self.assertTrue(receipt['payload_integrity_verified'])
                self.assertEqual(receipt['exit_code'], 0)
                self.assertEqual(receipt['stderr'], b'')
                expected = Path('/sys/devices/system/cpu/online').read_bytes()
                self.assertEqual(receipt['stdout'], expected)

    def test_all_cpus_must_execute_and_receipts_must_be_intact(self):
        report = runner.collect(Channel(), Legacy(), 10**20, lambda: True)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(len(report['receipts']), 7)
        for bad in [('online', {'stdout': b'0\n'}),
                    ('cpu_execution', {'stdout': runner.PROBE_OUTPUT.replace(b'CPU7_OK\n', b'')}),
                    ('cpu_execution', {'payload_integrity_verified': False}),
                    ('cpu_execution', {'stderr': b'affinity failed\n'}),
                    ('cpu_execution', {'exit_code': 1})]:
            with self.subTest(bad=bad):
                self.assertEqual(runner.collect(Channel(), Legacy(bad), 10**20,
                                                lambda: True)['status'], 'FAILED')

    def test_lost_binding_prevents_commands(self):
        channel = Channel()
        with self.assertRaises(RuntimeError):
            runner.collect(channel, Legacy(), 10**20, lambda: False)
        self.assertEqual(channel.sent, 0)

    @unittest.skipUnless(runner.touch.LEGACY.is_file(), 'requires retained C234 helper')
    def test_diagnostic_tail_bounds_output_and_preserves_read_failure(self):
        legacy = runner.touch.pinned_legacy()
        prefix = 'C234_' + 'C' * 24 + '_log'
        argv = runner.tasks()[-1][1]
        for replacement, expected_rc, expected in [
                ('/bin/busybox head -c 50000 /dev/zero', 0, b'\0' * 8192),
                ('/bin/busybox false', 1, b'')]:
            with tempfile.TemporaryDirectory(prefix='multicore-log-') as temp:
                command = runner.capture_script(legacy, prefix, argv)
                command = command.replace(b'/bin/busybox dmesg', replacement.encode())
                command = command.replace(('/run/' + prefix).encode(),
                                          str(Path(temp) / 'capture').encode())
                output = subprocess.check_output(['/bin/busybox', 'sh', '-c', command], timeout=5)
                receipt = legacy.parse_frame(output, prefix)
                self.assertTrue(receipt['payload_integrity_verified'])
                self.assertEqual(receipt['exit_code'], expected_rc)
                self.assertEqual(receipt['stdout'], expected)

    def test_partial_receipts_survive_diagnostic_failure(self):
        class BrokenLog(Legacy):
            def parse_frame(self, data, prefix):
                if self.index == 6:
                    raise ValueError('invalid diagnostic payload')
                return super().parse_frame(data, prefix)
        saved = []
        with self.assertRaisesRegex(ValueError, 'invalid diagnostic payload'):
            runner.collect(Channel(), BrokenLog(), 10**20, lambda: True, save=saved.append)
        self.assertEqual(saved[-1]['status'], 'INCOMPLETE')
        self.assertEqual(len(saved[-1]['receipts']), 6)
        self.assertEqual(saved[-1]['receipts'][3]['status'], 'OK')

    def test_default_and_invalid_serial_never_touch_device(self):
        with patch.object(runner.touch, 'DeviceIO') as device, \
                patch.object(runner, 'check', return_value={'device_execution': False}), \
                patch('sys.argv', ['runner']), contextlib.redirect_stdout(io.StringIO()):
            runner.main()
            device.assert_not_called()
        for args in (['--execute-ram-only'], ['--serial', 'phone'],
                     ['--execute-ram-only', '--serial', 'bad;serial']):
            with patch.object(runner.touch, 'DeviceIO') as device, \
                    patch('sys.argv', ['runner'] + args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    runner.main()
                device.assert_not_called()


if __name__ == '__main__':
    unittest.main()
