"""Touch collector built around injected C234 framing helpers, no device opening.

The caller must bind the channel to the monitored physical port, enforce an
absolute recovery deadline and verify Android before and after the session.
"""
import base64
import secrets
import time

from touch_event_node import event_node
from touch_stream_capture import capture


def collect(channel, legacy, manifest, healthy, notify_ready, deadline):
    if not healthy():
        raise RuntimeError("USB binding or monitor invalid before collection")
    legacy.synchronize_shell(channel, min(deadline, time.monotonic() + 4))
    nonce = secrets.token_hex(12).upper()
    ready = "C234_" + nonce + "_READY"
    check = ("/bin/busybox awk '$5 == \"/run\" { n++; for(i=7;i<=NF;i++) "
             "if($i==\"-\" && $(i+1)==\"tmpfs\") ok++ } "
             "END { exit !(n==1 && ok==1) }' /proc/self/mountinfo")
    channel.send((f"if {check}; then printf '\\n{ready}_0\\n'; "
                  f"else printf '\\n{ready}_1\\n'; fi\n").encode(), deadline)

    def tmpfs_result(buffer):
        if not healthy():
            raise RuntimeError("USB binding or monitor lost while checking tmpfs")
        return next((line for line in buffer.replace(b"\r", b"").splitlines()
                     if line in ((ready + "_0").encode(), (ready + "_1").encode())), None)

    if channel.until(tmpfs_result, min(deadline, time.monotonic() + 3)) != (ready + "_0").encode():
        raise RuntimeError("/run is not a unique tmpfs mount")
    results = {}
    for index, (key, path, kind) in enumerate((("cmdline", "/proc/cmdline", "cmdline"),
                                               ("inputs", "/proc/bus/input/devices", "touch_inputs"))):
        if not healthy():
            raise RuntimeError("USB binding or monitor lost before identity read")
        prefix = f"C234_{nonce}_{index:02d}"
        channel.send(legacy.capture_script(prefix, ["/bin/busybox", "cat", path]), deadline)

        def frame(buffer):
            if not healthy():
                raise RuntimeError("USB binding or monitor lost during identity read")
            return legacy.parse_frame(buffer, prefix)

        receipt = channel.until(frame, min(deadline, time.monotonic() + 4))
        checked = legacy.receipt_result(receipt, kind, manifest["bootargs"] if kind == "cmdline" else None)
        if checked["status"] != "OK":
            raise RuntimeError("Linux identity failed: " + key)
        results[key] = checked
    node = event_node(base64.b64decode(results["inputs"]["stdout_b64"], validate=True))
    result = capture(channel, node, deadline, healthy, notify_ready)
    result.update(event_node=node, identity_receipts=results)
    return result
