import unittest
from unittest.mock import patch

import run_watchdog_registration_ram_only as runner


class Legacy:
    def __init__(self):
        self.METADATA = []
        self.NODE_LINKS = []
        self.commands = []

    def capture_script(self, prefix, argv):
        self.commands.append(argv)
        return prefix.encode()

    def parse_frame(self, data, prefix):
        if prefix.encode() not in data:
            return None
        return {"exit_code": 0, "stdout": b"observed\n", "stderr": b"",
                "payload_integrity_verified": True}


class Channel:
    def send(self, data, deadline):
        self.data = data

    def until(self, predicate, deadline):
        return predicate(self.data)


class WatchdogInventoryTest(unittest.TestCase):
    def test_fixed_commands_and_no_watchdog_device_open(self):
        legacy = Legacy()
        result = runner.inventory(Channel(), legacy, lambda: True, 9999999999)
        self.assertEqual(set(result), {"misc", "device", "driver"})
        self.assertEqual(legacy.commands[0], ["/bin/busybox", "cat", "/proc/misc"])
        self.assertEqual(len(legacy.NODE_LINKS), 2)
        self.assertTrue(all("/dev/watchdog" not in " ".join(cmd) for cmd in legacy.commands))
        self.assertTrue(all(r["payload_integrity_verified"] for r in result.values()))

    def test_monitor_failure_rejects_capture(self):
        with self.assertRaisesRegex(RuntimeError, "binding"):
            runner.inventory(Channel(), Legacy(), lambda: False, 9999999999)

    def test_invalid_frame_is_rejected(self):
        legacy = Legacy()
        with patch.object(legacy, "parse_frame", return_value={"payload_integrity_verified": False}):
            with self.assertRaisesRegex(RuntimeError, "unverified"):
                runner.inventory(Channel(), legacy, lambda: True, 9999999999)


if __name__ == "__main__":
    unittest.main()
