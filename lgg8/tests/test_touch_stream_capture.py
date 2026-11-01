"""Exercise transport-neutral capture with synthetic serial and health changes."""
import re
import unittest
from touch_stream_capture import capture


class FakeChannel:
    def __init__(self, rc=0):
        self.buffer = bytearray(b"old data\n")
        self.rc, self.sent = rc, False

    def send(self, data, deadline):
        self.sent = True
        nonce = re.search(rb"TOUCH_([A-F0-9]{24})_BEGIN", data)[1]
        self.output = (b"\nTOUCH_" + nonce + b"_BEGIN\r\n"
                       b"DEVICE LG SW42000 Touchscreen X=0..1439 Y=0..3119\r\n"
                       b"READY: tap and release within 20 seconds\r\n"
                       b"EVENTS contact release x=40 y=100\r\nTOUCH_" + nonce +
                       b"_END_" + str(self.rc).encode() + b"\r\n")

    def until(self, predicate, deadline):
        for i in range(0, len(self.output), 7):
            self.buffer.extend(self.output[i:i + 7])
            result = predicate(bytes(self.buffer))
            if result:
                return result
        raise TimeoutError("synthetic deadline")


class StreamTest(unittest.TestCase):
    def test_synthetic_capture_and_failure(self):
        for rc in (0, 1):
            messages = []
            result = capture(FakeChannel(rc), "/dev/input/event0", 1, lambda: True,
                             lambda: messages.append("ready"))
            self.assertEqual(result["status"], "PASS" if rc == 0 else "FAILED")
            self.assertEqual(messages, ["ready"])
            self.assertFalse(result["physical_origin_verified"])
            self.assertFalse(result["suspend_verified"])

    def test_health_loss_prevents_or_aborts(self):
        io = FakeChannel()
        with self.assertRaises(RuntimeError):
            capture(io, "/dev/input/event0", 1, lambda: False, lambda: None)
        self.assertFalse(io.sent)
        calls = iter((True, False))
        with self.assertRaises(RuntimeError):
            capture(FakeChannel(), "/dev/input/event0", 1, lambda: next(calls), lambda: None)


if __name__ == "__main__":
    unittest.main()
