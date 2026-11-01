"""Safety gates for the manual-wake runner; no phone interaction."""
import contextlib
import io
import sys
import unittest
from pathlib import Path
import tempfile
import time
from unittest.mock import Mock, patch

import run_system_freeze_ram_only as runner


class FreezeRunnerGateTest(unittest.TestCase):
    def test_execute_needs_serial_and_present_operator_before_device_io(self):
        for args in (['--execute-ram-only'],
                     ['--execute-ram-only', '--serial', 'test-device'],
                     ['--execute-ram-only', '--operator-present'],
                     ['--serial', 'test-device'],
                     ['--operator-present']):
            with self.subTest(args=args), patch.object(sys, 'argv', ['runner'] + args), \
                 patch.object(runner.touch, 'DeviceIO', side_effect=AssertionError('device access')), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    runner.main()

    def test_notification_failure_prevents_freeze_launch(self):
        root = Path(__file__).resolve().parents[2] / 'out/lgg8-pairing-audit-20261101'
        with tempfile.TemporaryDirectory(prefix='freeze-runner-test-', dir=root) as temp:
            fake_io = Mock()
            fake_io.inner.recovering = False
            fake_io.inner.base.acm_parent_for_port.return_value = ('/dev/fake', 'parent', 'serial')
            channel = Mock()
            def run_session(_io):
                with self.assertRaisesRegex(RuntimeError, 'notification failed'):
                    runner.touch_capture_adapter.capture(channel, '/dev/event',
                        time.monotonic() + 30, lambda: True, lambda: None)
                return {'success': False}
            with patch.object(sys, 'argv', ['runner', '--execute-ram-only',
                    '--serial', 'test-device', '--operator-present']), \
                 patch.object(runner, 'CANDIDATE', Path(temp) / 'boot'), \
                 patch.object(runner, 'check'), \
                 patch.object(runner.touch, 'DeviceIO', return_value=fake_io), \
                 patch.object(runner.touch, 'notify_user', return_value=False), \
                 patch.object(runner.touch_capture_adapter, 'capture'), \
                 patch.object(runner, 'run_session', side_effect=run_session), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    runner.main()
            channel.send.assert_not_called()

    def test_preflight_mode_never_instantiates_device_io(self):
        with patch.object(sys, 'argv', ['runner']), \
             patch.object(runner, 'check', return_value={'status': 'test'}), \
             patch.object(runner.touch, 'DeviceIO', side_effect=AssertionError('device access')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            runner.main()
        self.assertIn('"device_execution": false', output.getvalue())
        self.assertIn('"real_sleep_verified": false', output.getvalue())


if __name__ == '__main__':
    unittest.main()
