"""Transport-neutral touch capture; requires externally verified live channel.

The runner owns USB identity checks, deadline selection and recovery. A PASS
here means a parsed stream, never proof of a physical tap or device suspend.
"""
import secrets

from touch_capture_protocol import TouchCapture
from touch_probe_command import command


def capture(channel, event, deadline, healthy, notify_ready):
    nonce = secrets.token_hex(12).upper()
    parser = TouchCapture(nonce)
    if not healthy():
        raise RuntimeError("monitor or USB identity invalid before capture")
    # Ignore bytes already received during shell synchronization or identity checks.
    offset = len(channel.buffer)
    channel.send(command(nonce, event), deadline)
    ready_notified = False

    def consume(buffer):
        nonlocal offset, ready_notified
        if not healthy():
            raise RuntimeError("monitor or USB identity lost during capture")
        if len(buffer) < offset:
            raise RuntimeError("serial buffer unexpectedly reset")
        chunk = buffer[offset:]
        offset = len(buffer)
        # Deliver readiness as soon as its complete line is parsed, before
        # consuming later lines that might already be in the same read.
        for part in chunk.splitlines(keepends=True):
            parser.feed_bytes(part)
            if parser.state == "READY" and not ready_notified:
                notify_ready()
                ready_notified = True
        if parser.state in ("DONE", "FAILED"):
            return parser.state
        return None

    outcome = channel.until(consume, deadline)
    if not healthy():
        raise RuntimeError("monitor or USB identity lost after capture")
    return {"status": "PASS" if outcome == "DONE" and ready_notified else "FAILED",
            "device_bounds": parser.bounds, "event": parser.event,
            "exit_code": parser.returncode, "ready_notified": ready_notified,
            "physical_origin_verified": False, "suspend_verified": False}
