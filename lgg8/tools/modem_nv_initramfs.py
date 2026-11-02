#!/usr/bin/env python3
"""Add verified private EFS copies to a RAM initramfs; output stays private."""
import argparse
import json
import lzma
from pathlib import Path
import stat

import bootimg
from modem_initramfs import extend

MAPPING = {'modemst1': 'modem_fs1', 'modemst2': 'modem_fs2',
           'fsg': 'modem_fsg', 'fsc': 'modem_fsc'}


def build(base, snapshot, encoding):
    receipt = json.loads((snapshot / 'verified.json').read_text())
    if (receipt.get('copy_verified') is not True or
            receipt.get('before_local_after_sha256_match') is not True or
            set(receipt['files']) != set(MAPPING)):
        raise ValueError('unverified or incomplete private EFS snapshot')
    files = {}
    for name, target in MAPPING.items():
        path = snapshot / name
        if path.is_symlink():
            raise ValueError('EFS symlink')
        data = path.read_bytes()
        if bootimg.describe(data) != receipt['files'][name]:
            raise ValueError('private EFS file changed: ' + name)
        files['opt/lgg8-rmtfs-input/' + target] = (stat.S_IFREG | 0o600, data)
    raw, tail = bootimg.gunzip_member(base.read_bytes())
    if tail:
        raise ValueError('base initramfs has trailing data')
    raw = extend(raw, files)
    if encoding == 'xz':
        return lzma.compress(raw, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, preset=6)
    if encoding == 'gzip':
        return bootimg.gzip_member(raw, 0)
    raise ValueError('unsupported encoding')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--encoding', choices=('xz', 'gzip'), default='xz')
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument('--output', type=Path)
    output.add_argument('--verify-existing', type=Path)
    args = parser.parse_args()
    data = build(args.base, args.snapshot, args.encoding)
    if args.verify_existing:
        if args.verify_existing.read_bytes() != data:
            raise ValueError('private initramfs rebuild differs')
    else:
        if stat.S_IMODE(args.output.parent.stat().st_mode) & 0o077:
            raise ValueError('private output directory must deny group/other access')
        with args.output.open('xb') as stream:
            stream.write(data)
        args.output.chmod(0o600)
    print(json.dumps({'encoding': args.encoding, 'size': len(data), 'private_efs_verified': True}))
