"""Offline-only tests; these never write real power sysfs attributes."""
import subprocess
import tempfile
import time
from pathlib import Path
import unittest

import system_sleep_capture as capture


class SystemSleepCaptureTest(unittest.TestCase):
    nonce = '0123456789ABCDEF01234567'

    def test_nonce_and_shell_syntax(self):
        for nonce in ('', 'A' * 23, 'a' * 24, 'A' * 23 + ';', None):
            with self.subTest(nonce=nonce), self.assertRaises(ValueError):
                capture.plan(nonce)
        plan = capture.plan(self.nonce)
        launch = plan['launch'].decode('ascii')
        subprocess.run(['sh', '-n'], input=launch, text=True, check=True)
        self.assertIn('/sys/power/pm_test', launch)
        self.assertIn('/sys/power/state', launch)
        self.assertNotIn('> /sys/power/pm_test', launch)
        self.assertEqual(plan['path'], '/run/system-freeze-' + self.nonce)

    def test_success_is_only_a_return_receipt(self):
        p = 'SYSFREEZE_' + self.nonce
        data = ('\n'.join([p + '_READY', p + '_RETURN_0', p + '_LOG_BEGIN',
                           '[ 1] PM: suspend entry (s2idle)', p + '_LOG_END', p + '_DONE']) + '\n').encode()
        result = capture.parse(data, self.nonce)
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['write_returned_zero'])
        self.assertFalse(result['real_sleep_verified'])
        self.assertFalse(result['touch_after_resume_verified'])
        self.assertFalse(result['capture_authenticated'])

    def test_shell_precheck_with_fake_sysfs(self):
        root = Path(__file__).resolve().parents[2] / 'out/lgg8-pairing-audit-20261101'
        with tempfile.TemporaryDirectory(prefix='freeze-fixture-', dir=root) as temp:
            temp = Path(temp)
            state, pm_test = temp / 'state', temp / 'pm_test'
            for selection in ('[devices] none', 'devices [none]'):
                with self.subTest(selection=selection):
                    state.write_text('freeze mem\n')
                    pm_test.write_text(selection + '\n')
                    record = temp / ('record-' + selection[1])
                    command = capture.plan(self.nonce)['launch'].decode()
                    command = command.replace('/sys/power/state', str(state))
                    command = command.replace('/sys/power/pm_test', str(pm_test))
                    command = command.replace('/run/system-freeze-' + self.nonce, str(record))
                    command = command.replace('/bin/busybox dmesg', '/bin/busybox echo PM:suspend-fake')
                    self.assertNotIn('/sys/power/', command)
                    subprocess.run(['sh', '-c', command], check=True, timeout=5)
                    deadline = time.monotonic() + 5
                    result = None
                    while time.monotonic() < deadline:
                        if record.exists():
                            result = capture.parse(record.read_bytes(), self.nonce)
                            if result is not None:
                                break
                        time.sleep(0.01)
                    self.assertIsNotNone(result)
                    self.assertEqual(result['status'], 'PASS' if '[none]' in selection else 'FAILED')
                    self.assertEqual(state.read_text(), 'freeze\n' if '[none]' in selection else 'freeze mem\n')
                    self.assertEqual(pm_test.read_text(), selection + '\n')

    def test_read_record_checks_identity_and_complete_frames(self):
        nonce = self.nonce
        prefix = ('SYSFREEZE_' + nonce).encode()
        body = b'\n'.join([prefix + b'_READY', prefix + b'_RETURN_0',
                           prefix + b'_LOG_BEGIN', prefix + b'_LOG_END', prefix + b'_DONE']) + b'\n'

        class Channel:
            buffer = b'old\n'
            def __init__(self, payload):
                self.payload = payload
            def send(self, command, deadline):
                self.command = command
            def until(self, predicate, deadline):
                return predicate(self.buffer + self.command + self.payload +
                                 b'\nSYSREAD_' + b'B' * 24 + b'\n')

        result = capture.read_record(Channel(body), lambda: True, nonce, 10**9, 'B' * 24)
        self.assertEqual(result['status'], 'PASS')
        self.assertIsNone(capture.read_record(Channel(prefix + b'_READY\n'), lambda: True,
                                              nonce, 10**9, 'B' * 24))
        with self.assertRaises(RuntimeError):
            capture.read_record(Channel(body), lambda: False, nonce, 10**9, 'B' * 24)
        for bad in ('', 'A' * 23 + ';'):
            with self.assertRaises(ValueError):
                capture.read_record(Channel(body), lambda: True, nonce, 10**9, bad)

    def test_fail_closed_and_whole_lines(self):
        p = ('SYSFREEZE_' + self.nonce).encode()
        ready, ret, begin, end, done = [p + suffix for suffix in
            (b'_READY', b'_RETURN_0', b'_LOG_BEGIN', b'_LOG_END', b'_DONE')]
        for lines in ([ret, ready, begin, end, done],
                      [ready, ret, ret, begin, end, done],
                      [ready, p + b'_RETURN_1', begin, end, done],
                      [ready, ret, begin, end, done, done],
                      [ready, ret, begin, end, p + b'_PRECHECK_FAILED', done],
                      [b'echo ' + ready, ret, begin, end, done],
                      [ready, ret, begin] + [b'x'] * 101 + [end, done]):
            with self.subTest(lines=lines):
                self.assertEqual(capture.parse(b'\n'.join(lines) + b'\n', self.nonce)['status'], 'FAILED')
        self.assertIsNone(capture.parse(b'\n'.join([ready, ret, begin, end, done]), self.nonce))


if __name__ == '__main__':
    unittest.main()
