import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import pty
import select
import signal
import time

from watchdog_transfer import send_batches, upload


class TransferTest(unittest.TestCase):
    def execute(self, data, corrupt=False):
        plan = upload(data, "A" * 24)
        with tempfile.TemporaryDirectory(prefix="watchdog-upload-", dir=Path(__file__).parent) as tmp:
            destination = str(Path(tmp) / "probe")
            output = []
            for index, batch in enumerate(plan["batches"]):
                command = batch["command"].decode().replace(plan["path"], destination)
                if corrupt and index == 1:
                    command = command.replace("printf %s '", "printf %s 'A", 1)
                self.assertLess(len(command.encode()), 4096)
                run = subprocess.run(["/bin/busybox", "sh", "-c", command],
                                     capture_output=True, check=True)
                output.append(run.stdout.decode())
            if corrupt:
                self.assertIn(plan["batches"][-1]["fail"], output[-1])
            else:
                for batch, stdout in zip(plan["batches"], output):
                    self.assertIn(batch["ok"], stdout.splitlines())
                self.assertEqual(Path(destination).read_bytes(), data)
                self.assertFalse(Path(destination + ".b64").exists())
                self.assertEqual(Path(destination).stat().st_mode & 0o777, 0o700)

    def test_multibatch_roundtrip(self):
        self.execute(os.urandom(32768))

    def test_corruption_cannot_pass_final_hash(self):
        self.execute(b"example" * 3000, corrupt=True)

    def test_acknowledgement_gating_and_failure(self):
        class Channel:
            def __init__(self, fail=False):
                self.buffer = bytearray()
                self.sent = 0
                self.fail = fail
            def send(self, data, deadline):
                self.sent += 1
                batch = plan["batches"][self.sent - 1]
                self.buffer.extend(data)  # echoed input alone is not a receipt
                marker = batch["fail"] if self.fail and self.sent == 2 else batch["ok"]
                self.buffer.extend(("\n" + marker + "\n").encode())
            def until(self, predicate, deadline):
                if not predicate(bytes(self.buffer)):
                    raise TimeoutError("missing acknowledgement")
        plan = upload(b"example" * 3000, "B" * 24)
        good = Channel()
        result = send_batches(good, plan, lambda: True, 9999999999)
        self.assertEqual(result["acknowledged_batches"], len(plan["batches"]))
        self.assertFalse(result["capture_authenticated"])
        bad = Channel(fail=True)
        with self.assertRaisesRegex(RuntimeError, "batch failed"):
            send_batches(bad, plan, lambda: True, 9999999999)
        self.assertEqual(bad.sent, 2)
        with self.assertRaisesRegex(RuntimeError, "identity"):
            send_batches(Channel(), plan, lambda: False, 9999999999)

    def test_interactive_busybox_pty_roundtrip(self):
        # Unlike sh -c, an interactive line editor can impose a shorter limit
        # and issue cursor-position queries. Exercise the actual input path.
        # Match the real transfer's encoded volume and enforce the production
        # reader's 1 MiB ceiling, not just the shell's line-length limit.
        data = os.urandom(370000)
        plan = upload(data, "C" * 24)
        with tempfile.TemporaryDirectory(prefix="wdt-pty-", dir=Path(__file__).parent) as tmp:
            destination = str(Path(tmp) / "probe")
            for batch in plan["batches"]:
                batch["command"] = batch["command"].replace(plan["path"].encode(), destination.encode())
            pid, master = pty.fork()
            if pid == 0:
                env = {**os.environ, "TERM": "linux", "PS1": "lgg8# ", "PS2": "> "}
                os.execve("/bin/busybox", ["/bin/busybox", "sh", "-i"], env)
            class Channel:
                def __init__(self):
                    self.buffer = bytearray()
                    self.replies = 0
                def send(self, data, deadline):
                    while data:
                        if time.monotonic() >= deadline or not select.select([], [master], [], 0.1)[1]:
                            raise TimeoutError("pty write")
                        data = data[os.write(master, data):]
                def until(self, predicate, deadline):
                    while time.monotonic() < deadline:
                        value = predicate(bytes(self.buffer))
                        if value:
                            return value
                        if not select.select([master], [], [], 0.05)[0]:
                            continue
                        self.buffer.extend(os.read(master, 8192))
                        if len(self.buffer) > 1024 * 1024:
                            raise ValueError("ACM capture exceeds 1 MiB")
                        pending = self.buffer.count(b"\x1b[6n") - self.replies
                        if pending:
                            self.send(b"\x1b[1;7R" * pending, deadline)
                            self.replies += pending
                    raise TimeoutError("pty receipt")
            try:
                channel = Channel()
                channel.until(lambda buf: b"lgg8# " in buf, time.monotonic() + 3)
                offset = len(channel.buffer)
                channel.send(b"printf 'unterminated\n", time.monotonic() + 2)
                channel.until(lambda buf: b"> " in buf[offset:], time.monotonic() + 3)
                offset = len(channel.buffer)
                channel.send(b"\x03\n", time.monotonic() + 2)
                channel.until(lambda buf: b"lgg8# " in buf[offset:], time.monotonic() + 3)
                send_batches(channel, plan, lambda: True, time.monotonic() + 15)
                self.assertEqual(Path(destination).read_bytes(), data)
            finally:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                os.close(master)

    def test_bounds_and_nonce(self):
        for payload, nonce in ((b"", "A" * 24), (b"x", "../bad"), (b"x" * (1024 * 1024 + 1), "A" * 24)):
            with self.assertRaises(ValueError):
                upload(payload, nonce)
        with self.assertRaises(ValueError):
            upload(os.urandom(500000), "A" * 24)


if __name__ == "__main__":
    unittest.main()
