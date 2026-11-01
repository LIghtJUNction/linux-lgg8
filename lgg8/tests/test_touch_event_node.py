"""Reject ambiguous procfs input identities, without accessing real devices."""
import unittest
from touch_event_node import event_node

TOUCH = b'I: Bus=0018\nN: Name="LG SW42000 Touchscreen"\nH: Handlers=event5\n\n'
OTHER = b'N: Name="other"\nH: Handlers=event0\n\n'


class EventNodeTest(unittest.TestCase):
    def test_one_exact_device(self):
        self.assertEqual(event_node(OTHER + TOUCH), "/dev/input/event5")

    def test_reject_ambiguous_or_invalid(self):
        for data in (OTHER, TOUCH + TOUCH,
                     TOUCH.replace(b"event5", b"event5 event6"),
                     TOUCH.replace(b"event5", b"event5;reboot"),
                     TOUCH.replace(b"H: Handlers=event5", b""),
                     TOUCH.replace(b"H: Handlers=event5", b"H: Handlers=event5\nH: Handlers=event6"),
                     TOUCH + b"\0", b"x" * 16385):
            with self.subTest(data=data[:100]), self.assertRaises(ValueError):
                event_node(data)


if __name__ == "__main__":
    unittest.main()
