#!/usr/bin/env python3
"""Insert a single observer into a verified newc archive; never overwrite inputs."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import stat

ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(source, executable):
    bootimg = load(ROOT / "lgg8/tools/bootimg.py", "probe_bootimg")
    mkinitramfs = load(ROOT / "lgg8/tools/mkinitramfs.py", "probe_mkinitramfs")
    before = bootimg.cpio(source)
    name = "usr/bin/sw42000-event-probe"
    if (name in before or len(executable) < 20 or executable[:6] != b"\x7fELF\x02\x01"
            or executable[18:20] != b"\xb7\x00"):
        raise ValueError("observer path exists or input is not AArch64 ELF64 little-endian")
    cursor = 0
    while True:
        fields = [int(source[cursor + 6 + i:cursor + 14 + i], 16) for i in range(0, 104, 8)]
        name_start = cursor + 110
        name_end = name_start + fields[11]
        entry_name = source[name_start:name_end - 1]
        if entry_name == b"TRAILER!!!":
            break
        cursor = bootimg.align(bootimg.align(name_end, 4) + fields[6], 4)
    result = (source[:cursor] + mkinitramfs.entry(name, stat.S_IFREG | 0o755, executable, ino=0x7ffffffe)
              + mkinitramfs.entry("TRAILER!!!", 0, b"", ino=0x7fffffff))
    after = bootimg.cpio(result)
    if after.pop(name) != (stat.S_IFREG | 0o755, executable) or after != before:
        raise ValueError("newc contents changed outside observer")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--observer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.input.read_bytes()
    if hashlib.sha256(source).hexdigest() != args.expected_sha256:
        raise ValueError("input initramfs SHA-256 mismatch")
    result = build(source, args.observer.read_bytes())
    with args.output.open("xb") as output:
        output.write(result)
    print("initramfs sha256:", hashlib.sha256(result).hexdigest())
    print("Verified: every pre-existing newc entry has unchanged mode and bytes")


if __name__ == "__main__":
    main()
