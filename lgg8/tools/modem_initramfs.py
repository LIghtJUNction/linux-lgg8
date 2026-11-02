#!/usr/bin/env python3
"""Append verified private modem inputs while preserving the base newc headers."""
import argparse
import json
from pathlib import Path, PurePosixPath
import stat

import bootimg
from mkinitramfs import entry
from modem_firmware import audit


def extend(base, files):
    old = bootimg.cpio(base)
    offset = 0
    while True:
        size = int(base[offset + 54:offset + 62], 16)
        namesize = int(base[offset + 94:offset + 102], 16)
        name = base[offset + 110:offset + 110 + namesize - 1]
        if name == b'TRAILER!!!':
            break
        offset = bootimg.align(bootimg.align(offset + 110 + namesize, 4) + size, 4)
    added = dict(files)
    for name in files:
        path = PurePosixPath(name)
        if str(path) != name or path.is_absolute() or '..' in path.parts or name in old:
            raise ValueError('invalid or colliding added path: ' + name)
        for parent in path.parents:
            if str(parent) != '.' and str(parent) not in old:
                added.setdefault(str(parent), (stat.S_IFDIR | 0o755, b''))
    # Keep ownership, rdev, inode and link metadata of every original entry.
    result = bytearray(base[:offset])
    ordered = sorted(added, key=lambda name: (len(PurePosixPath(name).parts), name))
    for index, name in enumerate(ordered, 100000):
        mode, data = added[name]
        result.extend(entry(name, mode, data, ino=index))
    result.extend(entry('TRAILER!!!', 0, ino=100000 + len(ordered)))
    result.extend(bytes(-len(result) % 512))
    result = bytes(result)
    parsed = bootimg.cpio(result)
    if any(parsed[name] != record for name, record in old.items()):
        raise ValueError('base archive entry changed')
    if any(parsed[name] != record for name, record in added.items()):
        raise ValueError('added archive entry mismatch')
    return result


def build(base, additions, firmware):
    files = {}
    for path in additions.rglob('*'):
        if path.is_symlink():
            raise ValueError('symlink in additions')
        if path.is_file():
            files[path.relative_to(additions).as_posix()] = (path.stat().st_mode, path.read_bytes())
    receipt = json.loads((firmware / 'verified.json').read_text())
    if receipt.get('copy_verified') is not True or audit(firmware)['status'] != 'PASS':
        raise ValueError('firmware copy is not verified')
    for name, expected in receipt['files'].items():
        if PurePosixPath(name).name != name:
            raise ValueError('invalid firmware receipt filename')
        path = firmware / name
        if path.is_symlink():
            raise ValueError('firmware symlink')
        data = path.read_bytes()
        if bootimg.describe(data) != expected:
            raise ValueError('firmware receipt mismatch: ' + name)
        target = 'lib/firmware/qcom/lg/alphalm/' + name
        if target in files:
            raise ValueError('duplicate firmware input')
        files[target] = (stat.S_IFREG | 0o644, data)
    return bootimg.gzip_member(extend(base.read_bytes(), files), 0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--additions', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument('--output', type=Path)
    output.add_argument('--verify-existing', type=Path)
    args = parser.parse_args()
    data = build(args.base, args.additions, args.firmware)
    if args.verify_existing:
        if args.verify_existing.read_bytes() != data:
            raise ValueError('rebuilt initramfs differs from existing artifact')
    else:
        with args.output.open('xb') as stream:
            stream.write(data)
    print(json.dumps(bootimg.describe(data), indent=2))
