#!/usr/bin/env python3
"""Offline tests; no phone, USB, or suspend operations."""
import unittest
from unittest.mock import patch

from run_pm_devices_ram_only import post_pm_capture, reconnect_error_recovery


class PostPmTouchTest(unittest.TestCase):
    def test_capture_receives_bounded_deadline_and_callbacks(self):
        channel, healthy, ready = object(), object(), object()
        calls = []
        def capture(*args):
            calls.append(args)
            return {'status': 'PASS', 'physical_origin_verified': False}
        with patch('run_pm_devices_ram_only.time.monotonic', return_value=100):
            result = post_pm_capture(channel, '/dev/input/event2', 130, healthy, ready, capture)
        self.assertEqual(calls, [(channel, '/dev/input/event2', 123, healthy, ready)])
        self.assertEqual(result, {'status': 'PASS', 'physical_origin_verified': False})

    def test_insufficient_budget_never_captures(self):
        calls = []
        with patch('run_pm_devices_ram_only.time.monotonic', return_value=100):
            with self.assertRaises(RuntimeError):
                post_pm_capture(None, '/dev/input/event2', 124, None, None,
                                lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_failure_requests_reboot_only_on_healthy_reconnected_channel(self):
        class Legacy:
            def __init__(self): self.calls = []
            def request_ram_reboot(self, channel, deadline):
                self.calls.append((channel, deadline))
                return {'line_fully_sent': True}
        legacy, channel = Legacy(), object()
        with patch('run_pm_devices_ram_only.time.monotonic', return_value=100):
            self.assertEqual(reconnect_error_recovery(None, lambda: True, legacy, channel, 110), {})
            self.assertEqual(reconnect_error_recovery(object(), lambda: False, legacy, channel, 110), {})
            self.assertEqual(reconnect_error_recovery(object(), lambda: True, legacy, channel, 103),
                             {'capture_error_reboot': {'line_fully_sent': True}})
        self.assertEqual(legacy.calls, [(channel, 103)])

    def test_reboot_exception_is_recorded(self):
        class Broken:
            def request_ram_reboot(self, channel, deadline):
                raise OSError('offline')
        result = reconnect_error_recovery(object(), lambda: True, Broken(), object(), 1000)
        self.assertIn('offline', result['capture_error_reboot_error'])


if __name__ == '__main__':
    unittest.main()
