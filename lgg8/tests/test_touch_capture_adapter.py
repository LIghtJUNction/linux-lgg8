"""Synthetic checks of collector identity/health gates; no real USB or shell."""
import base64
import re
import unittest
from unittest.mock import patch
import touch_capture_adapter as adapter

INPUT = b'N: Name="LG SW42000 Touchscreen"\nH: Handlers=event3\n\n'


class Channel:
    def __init__(self, tmpfs=True):
        self.buffer = bytearray()
        self.tmpfs = tmpfs
    def send(self, command, deadline):
        self.command = command
    def until(self, predicate, deadline):
        match = re.search(rb"C234_[A-F0-9]{24}_READY", self.command)
        if match:
            self.buffer.extend(b"\n" + match[0] + (b"_0\n" if self.tmpfs else b"_1\n"))
        result = predicate(bytes(self.buffer))
        if not result:
            raise TimeoutError("no synthetic response")
        return result


class Legacy:
    def __init__(self, bad=None): self.bad = bad
    def synchronize_shell(self, channel, deadline): pass
    def capture_script(self, prefix, argv): return prefix.encode()
    def parse_frame(self, buffer, prefix): return {"prefix": prefix}
    def receipt_result(self, frame, kind, expected):
        return {"status": "INVALID_OUTPUT" if self.bad == kind else "OK",
                "stdout_b64": base64.b64encode(INPUT if kind == "touch_inputs" else b"cmdline").decode()}


class CollectorTest(unittest.TestCase):
    def test_gates_then_capture(self):
        seen = []
        def fake_capture(channel, node, deadline, healthy, notify):
            seen.append(node)
            return {"status": "PASS"}
        with patch.object(adapter, "capture", fake_capture):
            result = adapter.collect(Channel(), Legacy(), {"bootargs": "x"}, lambda: True, lambda: None, 10**20)
        self.assertEqual(result["event_node"], "/dev/input/event3")
        self.assertEqual(seen, ["/dev/input/event3"])

    def test_failed_gates_cannot_capture(self):
        for channel, legacy, healthy in ((Channel(False), Legacy(), lambda: True),
                                         (Channel(), Legacy("cmdline"), lambda: True),
                                         (Channel(), Legacy("touch_inputs"), lambda: True),
                                         (Channel(), Legacy(), lambda: False)):
            with self.subTest(channel=channel, legacy=legacy), patch.object(adapter, "capture") as mock:
                with self.assertRaises(RuntimeError):
                    adapter.collect(channel, legacy, {"bootargs": "x"}, healthy, lambda: None, 10**20)
                mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
