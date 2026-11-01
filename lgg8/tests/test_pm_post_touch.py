#!/usr/bin/env python3
"""Offline tests; no phone, USB, or suspend operations."""
import unittest
from unittest.mock import patch

from run_pm_devices_ram_only import post_pm_capture


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


if __name__ == '__main__':
    unittest.main()
