"""Failure-injection tests of orchestration only, no device operations."""
import unittest
from touch_session import run_session


class Fake:
    def __init__(self, fail=None):
        self.fail, self.calls = fail, []
        self.gates = 0

    def step(self, name, value=None):
        self.calls.append(name)
        if self.fail == name:
            raise RuntimeError(name)
        if self.fail == name + "-interrupt":
            raise KeyboardInterrupt(name)
        return value

    def candidate_gate(self):
        self.gates += 1
        return self.step("gate" + str(self.gates))
    def start_monitor(self): return self.step("monitor")
    def preflight(self): return self.step("preflight", "before")
    def validate_android(self, before): return self.step("validate-before")
    def arm_recovery_deadline(self): return self.step("arm")
    def enter_fastboot(self): return self.step("transition")
    def check_fastboot(self): return self.step("fastboot-check")
    def boot_ram_only(self): return self.step("boot", self.fail != "boot-rejected")
    def capture_touch(self): return self.step("capture", "PASS")
    def recover_android(self): return self.step("recover", "after")
    def validate_return(self, before, after): return self.step("validate-return")
    def stop_and_verify_monitor(self): return self.step("monitor-stop", self.fail != "monitor-unverified")


class SessionTest(unittest.TestCase):
    def test_success_order(self):
        io = Fake()
        self.assertTrue(run_session(io)["success"])
        self.assertEqual(io.calls, ["gate1", "monitor", "preflight", "validate-before", "arm",
                                    "transition", "fastboot-check", "gate2", "boot", "capture",
                                    "recover", "validate-return", "monitor-stop"])

    def test_early_failure_never_transitions(self):
        for failure in ("gate1", "monitor", "preflight", "validate-before", "arm"):
            with self.subTest(failure=failure):
                io = Fake(failure)
                self.assertFalse(run_session(io)["success"])
                self.assertNotIn("transition", io.calls)
                self.assertNotIn("recover", io.calls)
                if failure != "gate1":
                    self.assertIn("monitor-stop", io.calls)

    def test_uncertain_transition_always_recovers(self):
        for failure in ("transition", "transition-interrupt", "fastboot-check", "gate2", "boot",
                        "boot-rejected", "capture"):
            with self.subTest(failure=failure):
                io = Fake(failure)
                result = run_session(io)
                self.assertFalse(result["success"])
                self.assertTrue(result["android_return_verified"])
                self.assertIn("monitor-stop", io.calls)
                if failure != "capture":
                    self.assertNotIn("capture", io.calls)

    def test_unverified_recovery_or_monitor_cannot_pass(self):
        for failure in ("recover", "validate-return", "monitor-stop", "monitor-unverified"):
            with self.subTest(failure=failure):
                io = Fake(failure)
                result = run_session(io)
                self.assertFalse(result["success"])
                if failure in ("recover", "validate-return"):
                    self.assertTrue(result["manual_recovery_required"])
                self.assertIn("monitor-stop", io.calls)


if __name__ == "__main__":
    unittest.main()
