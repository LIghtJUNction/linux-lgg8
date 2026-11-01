"""Construct one bounded touch-observer command; no shell execution here."""
import re


def command(nonce, event):
    if re.fullmatch(r"[A-F0-9]{24}", nonce) is None:
        raise ValueError("invalid nonce")
    if re.fullmatch(r"/dev/input/event[0-9]{1,5}", event) is None:
        raise ValueError("invalid event node")
    # Both interpolated values are strict ASCII whitelists, not shell fragments.
    # timeout is independent of the observer's own CLOCK_MONOTONIC deadline.
    return (f"printf '\\nTOUCH_{nonce}_BEGIN\\n'; "
            f"/bin/busybox timeout -s KILL 23 /usr/bin/sw42000-event-probe {event} 2>&1; "
            f"touch_rc=$?; printf '\\nTOUCH_{nonce}_END_%s\\n' \"$touch_rc\"\n").encode("ascii")
