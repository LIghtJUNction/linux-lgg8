"""Exercise actual C234 SerialChannel against a local pseudo-terminal, not a phone."""
import hashlib
import os
from pathlib import Path
import pty
import re
import select
import tempfile
import threading
import time
import unittest

from run_touch_ram_only import pinned_legacy
from touch_stream_capture import capture
from touch_capture_adapter import collect

HERE = Path(__file__).resolve().parent


class PtyIntegrationTest(unittest.TestCase):
    def test_complete_collector_using_real_legacy_framing(self):
        legacy = pinned_legacy()
        master, slave = pty.openpty()
        node = os.ttyname(slave)
        errors = []
        with tempfile.TemporaryDirectory(prefix="touch-pty-", dir=HERE) as temp:
            channel = legacy.SerialChannel(node, Path(temp))
            os.close(slave)

            def emit_receipt(prefix, payload):
                h = hashlib.sha256(payload).hexdigest().encode()
                empty = hashlib.sha256(b"").hexdigest().encode()
                return (b"\n" + prefix + b"_BEGIN\n" + prefix + b"_OUT_META_" +
                        str(len(payload)).encode() + b"_" + h + b"\n" + prefix + b"_OUT\n" +
                        payload.hex(" ").encode() + b"\n" + prefix + b"_ERR_META_0_" + empty +
                        b"\n" + prefix + b"_ERR\n" + prefix + b"_APPLET_RC_0_0_0_0_0_0_0\n" +
                        prefix + b"_RC_0\n" + prefix + b"_END\n")

            def peer():
                try:
                    os.write(master, b"lgg8# ")
                    pending = bytearray()
                    end = time.monotonic() + 4
                    while time.monotonic() < end:
                        if not select.select([master], [], [], 0.1)[0]:
                            continue
                        pending.extend(os.read(master, 8192))
                        while b"\n" in pending:
                            line, _, tail = pending.partition(b"\n")
                            pending = bytearray(tail)
                            ready = re.search(rb"C234_[A-F0-9]{24}_READY", line)
                            prefix = re.search(rb"C234_[A-F0-9]{24}_[0-9]{2}", line)
                            touch = re.search(rb"TOUCH_([A-F0-9]{24})_BEGIN", line)
                            if ready:
                                os.write(master, b"\n" + ready[0] + b"_0\n")
                            elif prefix:
                                payload = (b"example command line\n" if b"/proc/cmdline" in line else
                                           b'N: Name="LG SW42000 Touchscreen"\nH: Handlers=event3\n\n')
                                os.write(master, emit_receipt(prefix[0], payload))
                            elif touch:
                                n = touch[1]
                                os.write(master, b"\nTOUCH_" + n + b"_BEGIN\n"
                                         b"DEVICE LG SW42000 Touchscreen X=0..1439 Y=0..3119\n"
                                         b"READY: tap and release within 20 seconds\n"
                                         b"EVENTS contact release x=40 y=100\nTOUCH_" + n + b"_END_0\n")
                                return
                            else:
                                os.write(master, b"\nlgg8# ")
                    raise TimeoutError("synthetic collector peer timed out")
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=peer)
            worker.start()
            ready = []
            try:
                result = collect(channel, legacy, {"bootargs": "example command line"},
                                 lambda: True, lambda: ready.append(True), time.monotonic() + 4)
            finally:
                worker.join(timeout=5)
                channel.close()
                os.close(master)
            self.assertFalse(errors)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result["event_node"], "/dev/input/event3")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(ready, [True])
            self.assertFalse(result["physical_origin_verified"])

    def test_real_serial_channel_with_fragmented_synthetic_frames(self):
        legacy = pinned_legacy()
        master, slave = pty.openpty()
        node = os.ttyname(slave)
        errors = []
        with tempfile.TemporaryDirectory(prefix="touch-pty-", dir=HERE) as temp:
            channel = legacy.SerialChannel(node, Path(temp))
            os.close(slave)

            def peer():
                try:
                    received = bytearray()
                    end = time.monotonic() + 2
                    while b"\n" not in received and time.monotonic() < end:
                        if select.select([master], [], [], 0.1)[0]:
                            received.extend(os.read(master, 4096))
                    match = re.search(rb"TOUCH_([A-F0-9]{24})_BEGIN", received)
                    if not match:
                        raise RuntimeError("missing command frame")
                    nonce = match[1]
                    output = (b"\r\nTOUCH_" + nonce + b"_BEGIN\r\n"
                              b"DEVICE LG SW42000 Touchscreen X=0..1439 Y=0..3119\r\n"
                              b"READY: tap and release within 20 seconds\r\n"
                              b"EVENTS contact release x=40 y=100\r\nTOUCH_" + nonce + b"_END_0\r\n")
                    for offset in range(0, len(output), 11):
                        os.write(master, output[offset:offset + 11])
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=peer)
            worker.start()
            ready = []
            try:
                result = capture(channel, "/dev/input/event0", time.monotonic() + 3,
                                 lambda: True, lambda: ready.append(True))
            finally:
                worker.join(timeout=3)
                channel.close()
                os.close(master)
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["event"], (40, 100))
            self.assertEqual(ready, [True])
            self.assertFalse(result["physical_origin_verified"])
            self.assertGreater((Path(temp) / "acm-raw.bin").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
