import unittest
from watchdog_reset_observer import Observation


class WatchdogObservationTest(unittest.TestCase):
    def test_fragmented_armed_line_and_only_timed_disconnect(self):
        obs = Observation()
        obs.feed(b"shell noise\r\nARMED timeout_", 99)
        obs.feed(b"seconds=10\r\n", 100)
        self.assertEqual(obs.disconnect(110, True), "TIMED_DISCONNECT_ONLY")
        self.assertEqual(obs.disconnect(107.9, True), "DISCONNECT_TOO_EARLY")
        self.assertEqual(obs.disconnect(120.1, True), "DISCONNECT_TOO_LATE")
        self.assertEqual(obs.disconnect(110, False), "MONITOR_FAILED")

    def test_duplicate_marker_and_probe_failure_cannot_pass(self):
        obs = Observation()
        self.assertEqual(obs.disconnect(1, True), "UNEXPECTED_DISCONNECT_BEFORE_ARMED")
        obs.feed(b"ARMED timeout_seconds=10\nARMED timeout_seconds=10\n", 2)
        self.assertEqual(obs.disconnect(12, True), "PROBE_FAILED")
        obs = Observation()
        obs.feed(b"ARMED timeout_seconds=21\n", 2)
        self.assertEqual(obs.disconnect(12, True), "PROBE_FAILED")

    def test_survival_and_close_failure(self):
        obs = Observation()
        obs.feed(b"ARMED timeout_seconds=10\n", 10)
        obs.feed(b"NO_RESET_OBSERVED\n", 30)
        self.assertEqual(obs.disconnect(31, True), "NO_RESET_OBSERVED")
        obs.feed(b"MAGIC_CLOSE_WRITE_FAILED_WATCHDOG_MAY_STILL_RUN\n", 31)
        self.assertEqual(obs.disconnect(32, True), "PROBE_FAILED")

    def test_partial_line_bounded_and_not_a_marker(self):
        obs = Observation()
        obs.feed(b"ARMED timeout_seconds=10", 1)
        self.assertEqual(obs.disconnect(11, True), "UNEXPECTED_DISCONNECT_BEFORE_ARMED")
        with self.assertRaises(ValueError):
            obs.feed(b"x" * 4097, 2)


if __name__ == "__main__":
    unittest.main()
