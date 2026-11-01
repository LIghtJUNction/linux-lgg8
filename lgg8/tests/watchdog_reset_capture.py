"""Bounded serial observation of a watchdog probe, not reset-cause proof.

The caller must already have authenticated the *local* binary hash, validated
/run as tmpfs and the watchdog binding, and set up an independent recovery
plan. USB serial itself is unauthenticated. No phone may be booted by this file.
"""
import re
import time

from watchdog_reset_observer import Observation


def capture(channel, path, healthy, monitor_alive, usb_state, deadline):
    if re.fullmatch(r"/run/wdt-[A-F0-9]{24}", path) is None:
        raise ValueError("invalid probe path")
    if not healthy() or not monitor_alive() or usb_state() != "same":
        raise RuntimeError("device identity or monitor not valid before arming")
    # The executable tries magic close on ordinary exit, but killing it or
    # close failures can leave a timer active. The caller must recover Android.
    offset = len(channel.buffer)
    channel.send((path + " --arm-and-expect-reset\n").encode(), deadline)
    obs = Observation()
    cursor = offset
    start = time.monotonic()

    def consume(buffer):
        nonlocal cursor
        if len(buffer) < cursor:
            raise RuntimeError("serial buffer reset")
        obs.feed(buffer[cursor:], time.monotonic())
        cursor = len(buffer)
        if not monitor_alive():
            return "MONITOR_FAILED"
        state = usb_state()
        if state == "absent":
            return obs.disconnect(time.monotonic(), True)
        if state != "same":
            return "USB_IDENTITY_CHANGED_OR_UNREADABLE"
        if obs.fault:
            return "PROBE_FAILED"
        if obs.no_reset:
            return "NO_RESET_OBSERVED"
        return None

    try:
        # A normal GuardedChannel rejects USB removal before its predicate;
        # use its underlying reader here and explicitly check monitor + port.
        reader = getattr(channel, "channel", channel)
        outcome = reader.until(consume, min(deadline, start + 35))
    except EOFError:
        # EOF alone is not a USB detach or watchdog reset. Recheck the
        # independent monitor and port instead of treating EOF as success.
        state = usb_state()
        if state == "absent":
            outcome = obs.disconnect(time.monotonic(), monitor_alive())
        else:
            outcome = "SERIAL_EOF_WITHOUT_VERIFIED_ABSENCE"
    except TimeoutError:
        outcome = "OBSERVATION_TIMEOUT"
    return {"outcome": outcome, "watchdog_reset_verified": False,
            "sleep_verified": False, "fault": obs.fault,
            "armed_timeout_seconds": obs.timeout, "armed_received_monotonic": obs.armed_at,
            "capture_authenticated": False}
