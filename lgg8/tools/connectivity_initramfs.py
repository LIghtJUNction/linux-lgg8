#!/usr/bin/env python3
"""Append verified stock WLAN/configuration inputs to a pinned private XZ archive."""
import argparse
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import stat

import bootimg
import modem_initramfs


def build(base, base_sha256, extra, board, host=None):
    blob = base.read_bytes()
    if bootimg.sha(blob) != base_sha256 or not blob.startswith(b'\xfd7zXZ\0'):
        raise ValueError('private XZ base identity mismatch')
    decoder = lzma.LZMADecompressor(memlimit=128 * 1024**2)
    raw = decoder.decompress(blob, max_length=bootimg.MAX_RAW + 1)
    if (not decoder.eof or decoder.unused_data or decoder.check != lzma.CHECK_CRC32 or
            len(raw) > bootimg.MAX_RAW):
        raise ValueError('unsupported or oversized private archive')
    receipt = json.loads((extra / 'verified.json').read_text())
    bdf_receipt = json.loads((board / 'verified.json').read_text())
    if receipt.get('copy_verified') is not True or bdf_receipt.get('copy_verified') is not True:
        raise ValueError('stock copies are not verified')
    files, inputs, total_bytes = {}, {}, 0

    def add(source, target, expected):
        nonlocal total_bytes
        if source.is_symlink() or not source.is_file():
            raise ValueError('invalid stock firmware file')
        total_bytes += source.stat().st_size
        if total_bytes > 32 * 1024**2:
            raise ValueError('stock additions exceed budget')
        data = source.read_bytes()
        if bootimg.describe(data) != expected:
            raise ValueError('stock copy changed: ' + target)
        files[target] = (stat.S_IFREG | 0o644, data)
        inputs[target] = expected

    for name, expected in receipt['files'].items():
        path = PurePosixPath(name)
        if (str(path) != name or path.is_absolute() or '..' in path.parts or
                not (name.startswith('modem_pr/') or name == 'wlanmdsp.mbn')):
            raise ValueError('unexpected stock firmware path')
        add(extra / name, 'lib/firmware/qcom/lg/alphalm/' + name, expected)
    if 'wlanmdsp.mbn' not in receipt['files']:
        raise ValueError('missing WLAN DSP firmware')
    add(board / 'bdwlan.bin', 'lib/firmware/ath10k/WCN3990/hw1.0/board.bin', bdf_receipt['file'])
    if host is not None:
        host_receipt = json.loads((host / 'verified.json').read_text())
        if host_receipt.get('copy_verified') is not True:
            raise ValueError('host firmware copy is not verified')
        allowed = {'ath10k/WCN3990/hw1.0/firmware-5.bin', 'regulatory.db', 'regulatory.db.p7s'}
        for name, expected in host_receipt['files'].items():
            if name not in allowed:
                raise ValueError('unexpected host firmware path')
            add(host / name, 'lib/firmware/' + name, expected)
    raw = modem_initramfs.extend(raw, files)
    if len(raw) > bootimg.MAX_RAW:
        raise ValueError('extended archive exceeds budget')
    archive = lzma.compress(raw, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, preset=9)
    if bootimg.initramfs_cpio(archive) != bootimg.cpio(raw):
        raise ValueError('archive roundtrip mismatch')
    return archive, {'base': bootimg.describe(blob), 'archive': bootimg.describe(archive),
                     'raw': bootimg.describe(raw), 'inputs': inputs, 'xz_preset': 9,
                     'may_contain_private_efs': True, 'device_execution_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'extra', 'board', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--base-sha256', required=True)
    parser.add_argument('--host', type=Path, help='verified ath10k metadata and signed regulatory database')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.output.parent.stat().st_mode & 0o077:
        raise ValueError('output requires a private directory (0700)')
    record = args.output.with_name(args.output.name + '.json')
    if args.output.exists() or record.exists():
        raise ValueError('output already exists')
    archive, receipt = build(args.base, args.base_sha256, args.extra, args.board, args.host)
    for path, data in ((args.output, archive), (record, (json.dumps(receipt, indent=2) + '\n').encode())):
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(data)
    print(json.dumps({'archive': receipt['archive'], 'inputs': len(receipt['inputs'])}))
