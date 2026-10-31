#!/usr/bin/env python3
"""Decode raw PM8150B C223-style ACM observations, without device I/O."""

import argparse
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="acm-shell-probe.json")
    args = parser.parse_args()
    capture = json.loads(args.capture.read_text())
    if capture.get("status") != "PASS" or capture.get("marker_verified") is not True:
        raise SystemExit("capture was not complete and marker-verified")
    readings = capture.get("readings")
    if not isinstance(readings, list):
        raise SystemExit("capture lacks readings")
    parsed = {}
    for line in readings:
        if not isinstance(line, str):
            raise SystemExit("invalid reading type")
        match = re.fullmatch(r"FG_([a-z0-9_]+)=(0x[0-9a-fA-F]{2})", line)
        if not match:
            continue
        name, value = match.groups()
        if name in parsed:
            raise SystemExit(f"duplicate raw reading: {name}")
        parsed[name] = int(value, 16)
    needed = (
        "usb_icl_config", "icl_max_status", "aicl_icl_status", "aicl_status",
        "usb_icl_options", "usb_load_config", "usb_icl_override_command",
        "charge_enable_command", "usb_suspend_command",
    )
    missing = [name for name in needed if name not in parsed]
    if missing:
        raise SystemExit("missing raw readings: " + ", ".join(missing))
    for name in ("usb_icl_config", "icl_max_status", "aicl_icl_status"):
        if parsed[name] > 100:
            raise SystemExit(f"{name} exceeds the vendor PM8150B encoding range")
    result = {
        "source": str(args.capture),
        "raw": {name: f"0x{parsed[name]:02x}" for name in needed},
        "icl_configuration_ua": parsed["usb_icl_config"] * 50000,
        "icl_max_status_ua": parsed["icl_max_status"] * 50000,
        "aicl_icl_status_ua": parsed["aicl_icl_status"] * 50000,
        "aicl_done_bit": bool(parsed["aicl_status"] & 1),
        "charge_enable_command_bit": bool(parsed["charge_enable_command"] & 1),
        "usb_suspend_command_bit": bool(parsed["usb_suspend_command"] & 1),
        "usb_mode_change_bit": bool(parsed["usb_icl_options"] & 1),
        "usb51_bit": bool(parsed["usb_icl_options"] & 2),
        "usb3_bit": bool(parsed["usb_icl_options"] & 4),
        "icl_override_bit": bool(parsed["usb_icl_override_command"] & 1),
        "override_after_apsd_bit": bool(parsed["usb_load_config"] & 0x10),
        "limitations": (
            "PM8150B vendor encoding only; sequential register values are not "
            "measured current, an atomic snapshot, device identity, or proof "
            "of the active mode."
        ),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
