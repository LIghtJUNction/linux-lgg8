#!/usr/bin/env python3
"""Replace only /init in a verified newc archive, never overwrite input."""
import argparse
import hashlib
from pathlib import Path
import stat

from make_sw42000_probe_initramfs import ROOT, load


def replace(source, executable):
    bootimg = load(ROOT / 'lgg8/tools/bootimg.py', 'replace_bootimg')
    before = bootimg.cpio(source)
    old = before.get('init')
    if (old is None or old[0] != stat.S_IFREG | 0o755 or len(executable) < 20
            or executable[:6] != b'\x7fELF\x02\x01' or executable[18:20] != b'\xb7\x00'):
        raise ValueError('Expected executable /init and AArch64 ELF64 little-endian replacement')
    cursor = 0
    found = None
    while True:
        if source[cursor:cursor + 6] != b'070701':
            raise ValueError('Expected uncompressed newc archive')
        fields = [int(source[cursor + 6 + i:cursor + 14 + i], 16) for i in range(0, 104, 8)]
        name_start = cursor + 110
        name_end = name_start + fields[11]
        name = source[name_start:name_end - 1]
        end = bootimg.align(bootimg.align(name_end, 4) + fields[6], 4)
        if name == b'init':
            if found is not None:
                raise ValueError('Duplicate /init')
            found = cursor, end, fields
        if name == b'TRAILER!!!':
            break
        cursor = end
    if found is None:
        raise ValueError('Missing /init')
    start, end, fields = found
    # Keep every original header field, including ownership and inode, except size.
    if len(executable) > 0xffffffff:
        raise ValueError('Executable exceeds newc size limit')
    header = bytearray(source[start:start + 110])
    header[54:62] = f'{len(executable):08x}'.encode('ascii')
    name = source[start + 110:start + 110 + fields[11]]
    entry = bytes(header) + name
    entry += b'\0' * ((-len(entry)) % 4)
    entry += executable
    entry += b'\0' * ((-len(entry)) % 4)
    result = source[:start] + entry + source[end:]
    after = bootimg.cpio(result)
    if after.pop('init') != (old[0], executable):
        raise ValueError('Replacement /init verification failed')
    del before['init']
    if after != before:
        raise ValueError('Other archive contents changed')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--supervisor', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.input.read_bytes()
    if hashlib.sha256(source).hexdigest() != args.expected_sha256:
        raise ValueError('Input initramfs SHA-256 mismatch')
    result = replace(source, args.supervisor.read_bytes())
    with args.output.open('xb') as output:
        output.write(result)
    print('initramfs sha256:', hashlib.sha256(result).hexdigest())
    print('Only /init bytes and newc filesize changed; every other entry verified')


if __name__ == '__main__':
    main()
