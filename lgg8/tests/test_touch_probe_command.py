"""Host-only fake shell exercise; no evdev or phone is opened."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from touch_capture_protocol import TouchCapture
from touch_probe_command import command

NONCE = "0123456789ABCDEF01234567"
HERE = Path(__file__).resolve().parent


class CommandTest(unittest.TestCase):
    def test_invalid_values_rejected(self):
        for nonce, event in (("bad", "/dev/input/event0"),
                             (NONCE, "/dev/input/event0;reboot"),
                             (NONCE, "/dev/input/event"),
                             (NONCE, "/dev/input/event123456")):
            with self.subTest(event=event), self.assertRaises(ValueError):
                command(nonce, event)

    def test_fake_shell_stream_success_and_failure(self):
        with tempfile.TemporaryDirectory(prefix="touch-cmd-", dir=HERE) as tmp:
            probe = Path(tmp) / "probe"
            for rc in (0, 1):
                probe.write_text("#!/bin/sh\nprintf '%s\\n' 'DEVICE LG SW42000 Touchscreen X=0..1439 Y=0..3119' "
                                 "'READY: tap and release within 20 seconds' 'EVENTS contact release x=40 y=100'\n"
                                 f"exit {rc}\n")
                probe.chmod(0o700)
                cmd = command(NONCE, "/dev/input/event0").decode()
                cmd = cmd.replace("/bin/busybox timeout", "/usr/bin/timeout")
                cmd = cmd.replace("/usr/bin/sw42000-event-probe", str(probe))
                result = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, check=True, timeout=3)
                capture = TouchCapture(NONCE)
                capture.feed_bytes(result.stdout)
                self.assertEqual(capture.state, "DONE" if rc == 0 else "FAILED")
                self.assertEqual(capture.returncode, rc)


if __name__ == "__main__":
    unittest.main()
