"""Offline tests for the explicit, read-only Android observation gate."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import observe_android_thermal as observation


class TestObservation(unittest.TestCase):
    def test_default_does_not_construct_device(self):
        with patch.object(observation, "pinned_legacy") as legacy, \
             patch.object(sys, "argv", ["observe"]), contextlib.redirect_stdout(io.StringIO()):
            observation.main()
            legacy.assert_not_called()

    def test_success_reads_only_and_checks_monitor(self):
        class FakeIO:
            def __init__(self, serial, output):
                self.output = output
                (output / "tmp").mkdir()
                self.monitor = types.SimpleNamespace(healthy=lambda: True)
                self.base = types.SimpleNamespace(command=self.command, require_adb=lambda _: None,
                                                  android=lambda _: ["same"])
                self.calls = 0
            def start_monitor(self): pass
            def preflight(self): return ["same"]
            def command(self, name, args, **kwargs):
                self.calls += 1
                self_test.assertEqual(args[:4], ["adb", "-s", observation.SERIAL, "shell"])
                self_test.assertNotIn(" >", observation.READ)
                self_test.assertNotIn("reboot", observation.READ)
                return {"exit_code": 0, "timed_out": False}
            def stop_monitor(self, start, end):
                return {"exit_code": 0, "sampling_verified": True, "session_coverage_verified": True,
                        "log_integrity_verified": True, "observation_verified": True}
            def save(self, name, report):
                self_test.assertTrue(report["unchanged_android"])
                self_test.assertTrue(report["monitor_verified"])
                self_test.assertEqual(len(report["samples"]), 12)
        self_test = self
        legacy = types.SimpleNamespace(LiveIO=FakeIO, usb_snapshot=lambda: {"serial": observation.SERIAL},
                                       validate_android=lambda _: None)
        with tempfile.TemporaryDirectory(prefix="test-thermal-observe-", dir=Path(__file__).parent) as tmp, \
             patch.object(observation, "ROOT", Path(tmp)), \
             patch.object(observation, "pinned_legacy", return_value=legacy), \
             patch.object(observation.time, "sleep"), \
             patch.object(sys, "argv", ["observe", "--execute-read-only"]), \
             contextlib.redirect_stdout(io.StringIO()):
            observation.main()

    def test_failed_sample_retains_postflight_and_cannot_pass(self):
        saved = []
        class FakeIO:
            def __init__(self, serial, output):
                (output / "tmp").mkdir()
                self.monitor = types.SimpleNamespace(healthy=lambda: True)
                self.base = types.SimpleNamespace(
                    command=lambda *a, **kw: {"exit_code": 1, "timed_out": False},
                    require_adb=lambda _: None, android=lambda _: ["same"])
            def start_monitor(self): pass
            def preflight(self): return ["same"]
            def stop_monitor(self, start, end):
                return {"exit_code": 0, "sampling_verified": True, "session_coverage_verified": True,
                        "log_integrity_verified": True, "observation_verified": True}
            def save(self, name, report): saved.append(report.copy())
        legacy = types.SimpleNamespace(LiveIO=FakeIO, usb_snapshot=lambda: {"serial": observation.SERIAL},
                                       validate_android=lambda _: None)
        with tempfile.TemporaryDirectory(prefix="test-thermal-fail-", dir=Path(__file__).parent) as tmp, \
             patch.object(observation, "ROOT", Path(tmp)), \
             patch.object(observation, "pinned_legacy", return_value=legacy), \
             patch.object(sys, "argv", ["observe", "--execute-read-only"]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                observation.main()
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(len(saved[0]["samples"]), 1)
        self.assertTrue(saved[0]["unchanged_android"])
        self.assertIn("temperature observation failed", saved[0]["error"])


if __name__ == "__main__":
    unittest.main()
