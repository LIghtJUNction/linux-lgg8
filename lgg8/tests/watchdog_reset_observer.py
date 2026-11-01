"""Parse untrusted watchdog probe serial output; never claim reset causality."""
import re


class Observation:
    def __init__(self):
        self.pending = b""
        self.armed_at = None
        self.timeout = None
        self.no_reset = False
        self.fault = None

    def feed(self, data, timestamp):
        self.pending += data.replace(b"\r", b"")
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            match = re.fullmatch(rb"ARMED timeout_seconds=([0-9]+)", line)
            if match:
                value = int(match.group(1))
                if self.armed_at is not None or not 5 <= value <= 20:
                    self.fault = "invalid or duplicate armed marker"
                else:
                    self.armed_at, self.timeout = timestamp, value
            elif line == b"NO_RESET_OBSERVED":
                self.no_reset = True
            elif line in (b"OPEN_FAILED", b"IDENTITY_OR_CAPABILITY_MISMATCH",
                          b"TIMEOUT_UNSUPPORTED", b"WAIT_FAILED",
                          b"MAGIC_CLOSE_WRITE_FAILED_WATCHDOG_MAY_STILL_RUN",
                          b"CLOSE_FAILED_WATCHDOG_MAY_STILL_RUN"):
                self.fault = line.decode("ascii")
        if len(self.pending) > 4096:
            raise ValueError("unbounded serial line")

    def disconnect(self, timestamp, monitor_alive):
        if not monitor_alive:
            return "MONITOR_FAILED"
        if self.fault:
            return "PROBE_FAILED"
        if self.no_reset:
            return "NO_RESET_OBSERVED"
        if self.armed_at is None:
            return "UNEXPECTED_DISCONNECT_BEFORE_ARMED"
        elapsed = timestamp - self.armed_at
        if elapsed < self.timeout - 2:
            return "DISCONNECT_TOO_EARLY"
        if elapsed > self.timeout + 10:
            return "DISCONNECT_TOO_LATE"
        # Other reset sources (including the host guardian) remain possible.
        return "TIMED_DISCONNECT_ONLY"
