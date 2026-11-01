"""Build acknowledged /run-only upload batches; never open or run a watchdog.

Caller must validate /run as tmpfs, guard serial identity, send batches in order
and stop unless each unique OK marker is received. Partial files require cleanup
or a reboot. Echoed shell input is not an acknowledgement.
"""
import base64
import gzip
import hashlib
import re
import time

MAX_BINARY = 1024 * 1024
MAX_ENCODED = 600 * 1024


def upload(binary, nonce):
    if not 0 < len(binary) <= MAX_BINARY:
        raise ValueError("binary size outside bounds")
    if re.fullmatch(r"[A-F0-9]{24}", nonce) is None:
        raise ValueError("invalid nonce")
    encoded = base64.b64encode(gzip.compress(binary, mtime=0)).decode("ascii")
    if len(encoded) > MAX_ENCODED:
        raise ValueError("encoded payload exceeds transfer bound")
    path = "/run/wdt-" + nonce
    chunks = [encoded[i:i + 512] for i in range(0, len(encoded), 512)]
    digest = hashlib.sha256(binary).hexdigest()
    segments = [["umask 077", f"test ! -e {path}.b64", f"test ! -e {path}",
                 f": > {path}.b64"]]
    # Each batch is one interactive shell line. Joining four chunks with &&
    # exceeds BusyBox's line editor buffer even if the tty canonical limit is
    # larger; truncation leaves an unterminated quote and prevents recovery.
    for part in chunks:
        segments.append([f"printf %s '{part}' >> {path}.b64"])
    segments.append([
        f"/bin/busybox base64 -d {path}.b64 | /bin/busybox gzip -d > {path}",
        f"printf '%s  %s\\n' '{digest}' '{path}' | /bin/busybox sha256sum -c -",
        f"/bin/busybox chmod 700 {path}",
        f"/bin/busybox rm -f {path}.b64",
    ])
    batches = []
    for index, commands in enumerate(segments):
        marker = f"WDT_UPLOAD_{nonce}_{index:04d}"
        # Keep marker out of an echoed command line as a complete line; caller
        # must match an entire output line, not substring search.
        command = " && ".join(commands) + f" && printf '\\n{marker}_OK\\n' || printf '\\n{marker}_FAIL\\n'\n"
        batches.append({"command": command.encode("ascii"), "ok": marker + "_OK", "fail": marker + "_FAIL"})
    return {"batches": batches, "path": path, "staging": path + ".b64", "sha256": digest}


def send_batches(channel, plan, healthy, deadline):
    """Send only after the previous whole-line receipt; caller owns cleanup."""
    received = 0
    for batch in plan["batches"]:
        if not healthy():
            raise RuntimeError("USB monitor or identity invalid before upload")
        offset = len(channel.buffer)
        channel.send(batch["command"], deadline)
        expected, failed = batch["ok"].encode(), batch["fail"].encode()

        def receipt(buffer):
            if not healthy():
                raise RuntimeError("USB monitor or identity lost during upload")
            lines = buffer[offset:].replace(b"\r", b"").split(b"\n")[:-1]
            if failed in lines:
                raise RuntimeError("upload batch failed")
            if expected in lines:
                return True
            return None

        channel.until(receipt, min(deadline, time.monotonic() + 5))
        received += 1
    return {"acknowledged_batches": received, "sha256": plan["sha256"],
            "path": plan["path"], "capture_authenticated": False}
