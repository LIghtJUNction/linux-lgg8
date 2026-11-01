"""Host-only framing checks; successful parsing is not physical touch proof."""
import unittest
from touch_capture_protocol import TouchCapture

NONCE = "0123456789ABCDEF01234567"
BEGIN = f"TOUCH_{NONCE}_BEGIN"
END = f"TOUCH_{NONCE}_END_"
DEVICE = "DEVICE LG SW42000 Touchscreen X=0..1439 Y=0..3119"
READY = "READY: tap and release within 20 seconds"
EVENT = "EVENTS contact release x=40 y=100"


class ProtocolTest(unittest.TestCase):
    def test_complete(self):
        p = TouchCapture(NONCE)
        for line in ("echo " + BEGIN, READY, BEGIN, DEVICE, READY, EVENT, END + "0"):
            p.line(line)
        self.assertEqual((p.state, p.event, p.returncode), ("DONE", (40, 100), 0))
        with self.assertRaises(ValueError):
            p.line(EVENT)

    def test_incomplete_or_failed_are_not_success(self):
        for lines in ((BEGIN, DEVICE, READY, END + "0"),
                      (BEGIN, DEVICE, EVENT, END + "0"),
                      (BEGIN, DEVICE, READY, EVENT, END + "1"),
                      (BEGIN, READY, EVENT, END + "0")):
            p = TouchCapture(NONCE)
            for line in lines:
                p.line(line)
            self.assertEqual(p.state, "FAILED")

    def test_reject_bad_bounds_and_out_of_range(self):
        p = TouchCapture(NONCE)
        p.line(BEGIN)
        with self.assertRaisesRegex(ValueError, "invalid device bounds"):
            p.line("DEVICE LG SW42000 Touchscreen X=2..1 Y=0..4")
        p = TouchCapture(NONCE)
        for line in (BEGIN, DEVICE, READY):
            p.line(line)
        with self.assertRaisesRegex(ValueError, "outside device bounds"):
            p.line("EVENTS contact release x=1440 y=100")

    def test_bad_frame_and_nonce(self):
        with self.assertRaises(ValueError):
            TouchCapture("bad")
        for suffix in ("-1", "256", "0 extra", ""):
            p = TouchCapture(NONCE)
            p.line(BEGIN)
            with self.assertRaises(ValueError):
                p.line(END + suffix)


if __name__ == "__main__":
    unittest.main()
