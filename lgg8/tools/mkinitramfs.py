#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Create a deterministic newc archive containing only the diagnostic init."""
import argparse
import importlib.util
import os
from pathlib import Path
import stat
import tempfile


# Load the sibling by exact path: also works for isolated CLI/spec-based imports.
_spec = importlib.util.spec_from_file_location("_lgg8_bootimg", Path(__file__).resolve().with_name("bootimg.py"))
_bootimg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bootimg)


def entry(name, mode, data=b"", ino=1, rdev=(0, 0)):
    encoded = name.encode() + b"\0"
    fields = (ino, mode, 0, 0, 2 if stat.S_ISDIR(mode) else 1, 0,
              len(data), 0, 0, rdev[0], rdev[1], len(encoded), 0)
    header = b"070701" + b"".join(f"{value:08x}".encode() for value in fields)
    record = header + encoded
    record += b"\0" * (-len(record) % 4) + data
    return record + b"\0" * (-len(record) % 4)


def build(init):
    _bootimg.check_init({"init": (stat.S_IFREG | 0o755, init)}, "rdinit=/init")
    data = entry(".", stat.S_IFDIR | 0o755)
    for index, name in enumerate(("dev", "proc", "sys"), 2):
        data += entry(name, stat.S_IFDIR | 0o755, ino=index)
    data += entry("dev/console", stat.S_IFCHR | 0o600, ino=5, rdev=(5, 1))
    data += entry("dev/kmsg", stat.S_IFCHR | 0o600, ino=6, rdev=(1, 11))
    data += entry("init", stat.S_IFREG | 0o755, init, ino=7)
    data += entry("TRAILER!!!", 0, ino=8)
    return data + b"\0" * (-len(data) % 512)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    archive = build(args.init.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=args.output.parent, delete=False) as f:
        temporary = Path(f.name)
        try:
            f.write(archive)
            f.flush()
            os.fsync(f.fileno())
            os.replace(temporary, args.output)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"{args.output}: {len(archive)} bytes")


if __name__ == "__main__":
    main()
