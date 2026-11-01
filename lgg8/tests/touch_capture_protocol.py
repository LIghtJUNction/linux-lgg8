"""Pure framed-serial parser for a future human-assisted touch capture.

No device access, subprocesses or recovery actions. The runner must still bind
USB identity, enforce deadlines, and request an intentional physical tap.
"""
import re


class TouchCapture:
    def __init__(self, nonce):
        if re.fullmatch(r"[A-F0-9]{24}", nonce) is None:
            raise ValueError("invalid nonce")
        self.begin = f"TOUCH_{nonce}_BEGIN"
        self.end = f"TOUCH_{nonce}_END_"
        self.state = "WAIT_BEGIN"
        self.event = None
        self.bounds = None
        self.returncode = None

    def line(self, line):
        # Inputs are complete decoded serial lines; shell echoes are not frames.
        if self.state == "WAIT_BEGIN":
            if line == self.begin:
                self.state = "WAIT_DEVICE"
            return
        if self.state in ("DONE", "FAILED"):
            raise ValueError("line after completion")
        if line.startswith(self.end):
            suffix = line[len(self.end):]
            if re.fullmatch(r"[0-9]{1,3}", suffix) is None or int(suffix) > 255:
                raise ValueError("invalid exit code")
            self.returncode = int(suffix)
            self.state = "DONE" if self.state == "HAVE_EVENT" and self.returncode == 0 else "FAILED"
            return
        if self.state == "WAIT_DEVICE":
            match = re.fullmatch(r"DEVICE LG SW42000 Touchscreen X=(-?\d+)\.\.(-?\d+) Y=(-?\d+)\.\.(-?\d+)", line)
            if match:
                xmin, xmax, ymin, ymax = map(int, match.groups())
                if xmin > xmax or ymin > ymax:
                    raise ValueError("invalid device bounds")
                self.bounds = (xmin, xmax, ymin, ymax)
                self.state = "WAIT_READY"
        elif self.state == "WAIT_READY":
            if line == "READY: tap and release within 20 seconds":
                self.state = "READY"
        elif self.state == "READY":
            match = re.fullmatch(r"EVENTS contact release x=(-?\d+) y=(-?\d+)", line)
            if match:
                x, y = map(int, match.groups())
                xmin, xmax, ymin, ymax = self.bounds
                if not (xmin <= x <= xmax and ymin <= y <= ymax):
                    raise ValueError("event outside device bounds")
                self.event = (x, y)
                self.state = "HAVE_EVENT"
