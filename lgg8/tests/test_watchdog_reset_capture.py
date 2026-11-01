import unittest
from unittest.mock import patch

from watchdog_reset_capture import capture


class FakeChannel:
    def __init__(self, chunks):
        self.buffer = bytearray()
        self.chunks = chunks
        self.sent = []
    def send(self, data, deadline):
        self.sent.append(data)
    def until(self, predicate, deadline):
        for data in self.chunks:
            self.buffer.extend(data)
            value = predicate(bytes(self.buffer))
            if value:
                return value
        raise TimeoutError()


class CaptureTest(unittest.TestCase):
    def test_timed_detach_does_not_claim_cause(self):
        channel = FakeChannel([b"ARMED timeout_seconds=10\n", b""])
        states = iter(["same", "same", "absent"])
        # start, deadline, first receipt, second receipt, detach classification
        with patch("watchdog_reset_capture.time.monotonic", side_effect=[100, 100, 100, 110, 110]):
            result = capture(channel, "/run/wdt-" + "A" * 24, lambda: True,
                             lambda: True, lambda: next(states), 200)
        self.assertEqual(result["outcome"], "TIMED_DISCONNECT_ONLY")
        self.assertFalse(result["watchdog_reset_verified"])
        self.assertFalse(result["capture_authenticated"])
        self.assertEqual(channel.sent, [("/run/wdt-" + "A" * 24 + " --arm-and-expect-reset\n").encode()])

    def test_surviving_probe_and_monitor_failure(self):
        channel = FakeChannel([b"ARMED timeout_seconds=10\nNO_RESET_OBSERVED\n"])
        result = capture(channel, "/run/wdt-" + "A" * 24, lambda: True,
                         lambda: True, lambda: "same", 9999999999)
        self.assertEqual(result["outcome"], "NO_RESET_OBSERVED")
        channel = FakeChannel([b"ARMED timeout_seconds=10\n"])
        alive = iter([True, False])
        result = capture(channel, "/run/wdt-" + "A" * 24, lambda: True,
                         lambda: next(alive), lambda: "same", 9999999999)
        self.assertEqual(result["outcome"], "MONITOR_FAILED")

    def test_never_sends_on_invalid_identity_or_path(self):
        channel = FakeChannel([])
        with self.assertRaises(ValueError):
            capture(channel, "/run/wdt-../../bad", lambda: True, lambda: True, lambda: "same", 1)
        with self.assertRaises(RuntimeError):
            capture(channel, "/run/wdt-" + "A" * 24, lambda: False, lambda: True, lambda: "same", 1)
        self.assertEqual(channel.sent, [])


if __name__ == "__main__":
    unittest.main()
