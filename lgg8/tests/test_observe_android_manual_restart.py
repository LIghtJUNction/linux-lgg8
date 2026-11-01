"""Offline tests for the passive manual-restart observer."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import observe_android_manual_restart as observer


class ObserverTest(unittest.TestCase):
    def test_default_never_touches_device(self):
        with patch.object(observer, "pinned_legacy") as legacy, \
             patch.object(sys, "argv", ["observe"]), contextlib.redirect_stdout(io.StringIO()):
            observer.main()
            legacy.assert_not_called()

    def test_monitor_and_new_boot_required(self):
        saved = []
        class FakeIO:
            def __init__(self, serial, output):
                (output / "tmp").mkdir()
                self.monitor = types.SimpleNamespace(healthy=lambda: True)
                self.base = types.SimpleNamespace(command=lambda *a, **kw: {"exit_code": 0, "stdout": b"1"},
                    require_adb=lambda _: None, android=lambda _: ["new"])
            def start_monitor(self): pass
            def preflight(self): return ["old"]
            def stop_monitor(self, start, end):
                return {"exit_code": 0, "sampling_verified": True, "session_coverage_verified": True,
                        "log_integrity_verified": True, "observation_verified": True}
            def save(self, name, data): saved.append(data.copy())
        snapshots = iter([{"status": "absent"}, {"status": "present", "serial": observer.SERIAL,
                                                  "vid": "1004", "pid": "631f"}])
        legacy = types.SimpleNamespace(LiveIO=FakeIO, usb_snapshot=lambda: next(snapshots),
                                       validate_return=lambda before, after: self.assertNotEqual(before, after))
        with tempfile.TemporaryDirectory(prefix="test-manual-restart-", dir=Path(__file__).parent) as tmp, \
             patch.object(observer, "ROOT", Path(tmp)), \
             patch.object(observer, "pinned_legacy", return_value=legacy), \
             patch.object(observer, "notify_user", return_value=True), \
             patch.object(observer.time, "sleep"), \
             patch.object(sys, "argv", ["observe", "--observe-manual-restart"]), \
             contextlib.redirect_stdout(io.StringIO()):
            observer.main()
        self.assertTrue(saved[0]["disconnect_observed"])
        self.assertTrue(saved[0]["android_return_verified"])
        self.assertTrue(saved[0]["monitor_verified"])
        self.assertIn("not unresponsive Linux recovery", saved[0]["scope"])


if __name__ == "__main__":
    unittest.main()
