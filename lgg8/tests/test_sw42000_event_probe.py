"""Host-only checks for the bounded evdev observer; no device access."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "lgg8/tests/sw42000_event_probe.c"


class ProbeTest(unittest.TestCase):
    def test_model_and_rejections(self):
        with tempfile.TemporaryDirectory(prefix="event-probe-", dir=ROOT / "lgg8/tests") as temp:
            binary = Path(temp) / "probe"
            subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-D_POSIX_C_SOURCE=200809L",
                            "-O2", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
                            str(SOURCE), "-o", str(binary)], check=True)
            subprocess.run([str(binary), "--self-test"], check=True, timeout=3)
            for args in ([], ["/dev/null"], ["/dev/input/event-does-not-exist"]):
                result = subprocess.run([str(binary), *args], capture_output=True, timeout=3)
                self.assertNotEqual(result.returncode, 0, args)


if __name__ == "__main__":
    unittest.main()
