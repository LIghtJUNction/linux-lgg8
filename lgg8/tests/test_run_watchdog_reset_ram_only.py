import hashlib
import types
import unittest
from unittest.mock import patch

import run_watchdog_reset_ram_only as runner


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.binary = b"fake binary"
        self.digest = hashlib.sha256(self.binary).hexdigest()
        self.channel = types.SimpleNamespace(send=lambda data, deadline: None)
        self.legacy = types.SimpleNamespace(
            usb_snapshot=lambda: {"status": "present"},
            request_ram_reboot=lambda channel, deadline: {"sent": True})
        self.io = types.SimpleNamespace(legacy=self.legacy,
            inner=types.SimpleNamespace(monitor=types.SimpleNamespace(healthy=lambda: True)))
        self.receipts = {"misc": {"exit_code": 0, "stdout": "watchdog"},
                         "device": {"exit_code": 0, "stdout": runner.DEVICE},
                         "driver": {"exit_code": 0, "stdout": runner.DRIVER}}

    def test_binding_failure_reboots_without_upload(self):
        self.receipts["driver"]["stdout"] = "wrong\n"
        with patch.object(runner, "BINARY_SHA", self.digest), \
             patch.object(runner.registration, "inventory", return_value=self.receipts), \
             patch.object(runner.watchdog_transfer, "upload") as upload:
            result = runner.perform(self.channel, self.io, lambda: True, 9999999999, self.binary)
        upload.assert_not_called()
        self.assertEqual(result["status"], "FAILED")
        self.assertTrue(result["fallback_reboot"]["sent"])

    def test_timed_disconnect_is_not_cause_proof(self):
        with patch.object(runner, "BINARY_SHA", self.digest), \
             patch.object(runner.registration, "inventory", return_value=self.receipts), \
             patch.object(runner.watchdog_transfer, "upload", return_value={"path": "/run/wdt-" + "A" * 24}), \
             patch.object(runner.watchdog_transfer, "send_batches", return_value={"acknowledged_batches": 1}), \
             patch.object(runner.watchdog_reset_capture, "capture", return_value={"outcome": "TIMED_DISCONNECT_ONLY"}):
            # fake probe marks the binding gone before the final recovery check
            result = runner.perform(self.channel, self.io, lambda: False, 9999999999, self.binary)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["watchdog_reset_verified"])
        self.assertFalse(result["suspend_verified"])
        self.assertNotIn("fallback_reboot", result)

    def test_transfer_failure_reboots_without_arming(self):
        with patch.object(runner, "BINARY_SHA", self.digest), \
             patch.object(runner.registration, "inventory", return_value=self.receipts), \
             patch.object(runner.watchdog_transfer, "upload", return_value={"path": "/run/wdt-" + "A" * 24}), \
             patch.object(runner.watchdog_transfer, "send_batches", side_effect=TimeoutError("upload")), \
             patch.object(runner.watchdog_reset_capture, "capture") as probe:
            result = runner.perform(self.channel, self.io, lambda: True, 9999999999, self.binary)
        probe.assert_not_called()
        self.assertEqual(result["status"], "FAILED")
        self.assertTrue(result["fallback_reboot"]["sent"])

    def test_no_reset_requests_fallback_reboot(self):
        with patch.object(runner, "BINARY_SHA", self.digest), \
             patch.object(runner.registration, "inventory", return_value=self.receipts), \
             patch.object(runner.watchdog_transfer, "upload", return_value={"path": "/run/wdt-" + "A" * 24}), \
             patch.object(runner.watchdog_transfer, "send_batches", return_value={}), \
             patch.object(runner.watchdog_reset_capture, "capture", return_value={"outcome": "NO_RESET_OBSERVED"}):
            result = runner.perform(self.channel, self.io, lambda: True, 9999999999, self.binary)
        self.assertEqual(result["status"], "FAILED")
        self.assertTrue(result["fallback_reboot"]["sent"])

    def test_bad_local_hash_stops_before_any_send(self):
        result = runner.perform(self.channel, self.io, lambda: True, 9999999999, self.binary)
        self.assertIn("binary changed", result["error"])
        self.assertTrue(result["fallback_reboot"]["sent"])


if __name__ == "__main__":
    unittest.main()
