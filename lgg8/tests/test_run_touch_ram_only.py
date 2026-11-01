"""Offline adapter and execution-gate tests, no USB or device access."""
import contextlib
import io
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import run_touch_ram_only as runner

HERE = Path(__file__).resolve().parent


class FakeInner:
    def __init__(self, serial, output):
        self.serial = serial
        self.output = output
        self.deadline = 10**20
        self.boot_time = runner.time.monotonic()
        self.monitor = types.SimpleNamespace(healthy=lambda: True)
        self.base = types.SimpleNamespace(acm_parent_for_port=lambda: ("tty", "parent", "serial"))
        self.saved = []
    def save(self, name, value): self.saved.append((name, value))


class FakeChannel:
    def __init__(self, node, output): self.closed = False
    def close(self): self.closed = True


class RunnerTest(unittest.TestCase):
    def test_default_is_review_only_and_rejects_serial(self):
        with patch.object(runner, "review", return_value={"device_execution": False}), \
             patch.object(runner, "DeviceIO") as device, patch("sys.argv", ["runner"]), \
             contextlib.redirect_stdout(io.StringIO()):
            runner.main()
            device.assert_not_called()
        with patch("sys.argv", ["runner", "--serial", "A"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): runner.main()

    def test_candidate_adapter_capture_and_binding_failure(self):
        snap = {"vid": "18d1", "pid": "4ee7", "serial": "gadget"}
        legacy = types.SimpleNamespace(LiveIO=FakeInner, IMAGE=None, review=None,
                                       SerialChannel=FakeChannel, usb_snapshot=lambda: snap,
                                       request_ram_reboot=lambda channel, deadline: {"sent": True})
        with tempfile.TemporaryDirectory(prefix="touch-runner-test-", dir=HERE) as temp, \
             patch.object(runner, "pinned_legacy", return_value=legacy), \
             patch.object(runner, "collect", return_value={"status": "PASS"}):
            device = runner.DeviceIO("serial", Path(temp))
            self.assertEqual(device.capture_touch(), "PASS")
            saved = device.inner.saved[0][1]
            self.assertEqual(saved["usb_binding"]["parent"], "parent")
            self.assertTrue(saved["reboot_request"]["sent"])
            self.assertEqual(legacy.IMAGE, runner.CANDIDATE / "boot.img")
        values = iter((snap, {"vid": "changed"}))
        legacy.usb_snapshot = lambda: next(values)
        with tempfile.TemporaryDirectory(prefix="touch-runner-test-", dir=HERE) as temp, \
             patch.object(runner, "pinned_legacy", return_value=legacy), \
             patch.object(runner, "collect") as collector:
            device = runner.DeviceIO("serial", Path(temp))
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                device.capture_touch()
            collector.assert_not_called()

    def test_reference_hash_and_real_default_review(self):
        self.assertFalse(runner.review()["device_execution"])
        module = runner.pinned_legacy()
        self.assertTrue(callable(module.LiveIO))
        self.assertTrue(callable(module.validate_return))


if __name__ == "__main__":
    unittest.main()
