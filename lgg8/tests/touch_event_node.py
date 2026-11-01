"""Extract exactly one SW42000 event node from a procfs input snapshot."""
import re


def event_node(snapshot):
    if len(snapshot) > 16384 or b"\0" in snapshot:
        raise ValueError("oversized or invalid input snapshot")
    matches = []
    for block in snapshot.split(b"\n\n"):
        lines = block.splitlines()
        if b'N: Name="LG SW42000 Touchscreen"' not in lines:
            continue
        if lines.count(b'N: Name="LG SW42000 Touchscreen"') != 1:
            raise ValueError("duplicate name line")
        handlers = [line[len(b"H: Handlers="):].split() for line in lines
                    if line.startswith(b"H: Handlers=")]
        if len(handlers) != 1:
            raise ValueError("missing or duplicate handlers")
        events = [item for item in handlers[0] if re.fullmatch(rb"event[0-9]{1,5}", item)]
        if len(events) != 1:
            raise ValueError("expected exactly one event node")
        matches.append(events[0].decode("ascii"))
    if len(matches) != 1:
        raise ValueError("expected exactly one SW42000 input device")
    return "/dev/input/" + matches[0]
