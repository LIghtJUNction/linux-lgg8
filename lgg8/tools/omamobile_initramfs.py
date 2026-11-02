#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Adapt a reviewed OmaMobile RAM-probe newc archive to the LG envelope."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess

import bootimg


def canonical_links(raw):
    """Preserve newc headers and data; root only leading-parent symlinks."""
    result, changes = bytearray(), []
    cursor = 0
    while True:
        if cursor + 110 > len(raw) or raw[cursor:cursor + 6] != b'070701':
            raise ValueError('invalid source newc header')
        header = bytearray(raw[cursor:cursor + 110])
        mode = int(header[14:22], 16)
        size, namesize = int(header[54:62], 16), int(header[94:102], 16)
        name_end = cursor + 110 + namesize
        start = bootimg.align(name_end, 4)
        end = bootimg.align(start + size, 4)
        if namesize < 1 or end > len(raw) or raw[name_end - 1:name_end] != b'\0':
            raise ValueError('invalid source newc bounds')
        name_data = raw[cursor + 110:name_end]
        if b'\0' in name_data[:-1] or any(raw[name_end:start]) or any(raw[start + size:end]):
            raise ValueError('invalid source newc name or padding')
        name = name_data[:-1].decode('utf-8')
        while name.startswith('./'):
            name = name[2:]
        if name.startswith('/') or '..' in name.split('/'):
            raise ValueError('unsafe source newc name')
        data = raw[start:start + size]
        if stat.S_ISLNK(mode) and '..' in data.decode('utf-8').split('/'):
            target = data.decode('utf-8')
            if target.startswith('/') or '\0' in target:
                raise ValueError('unsafe parent symlink')
            rest = list(PurePosixPath(target).parts)
            parent = list(PurePosixPath(name).parent.parts)
            while rest and rest[0] == '..':
                if not parent:
                    raise ValueError('symlink escapes the archive root')
                parent.pop()
                rest.pop(0)
            if '..' in rest:
                raise ValueError('only leading parent components can be normalized')
            data = ('/' + '/'.join(parent + rest)).encode('utf-8')
            header[54:62] = f'{len(data):08x}'.encode('ascii')
            changes.append({'name': name, 'from': target, 'to': data.decode()})
        result.extend(header)
        result.extend(name_data)
        result.extend(bytes(bootimg.align(len(result), 4) - len(result)))
        result.extend(data)
        result.extend(bytes(bootimg.align(len(result), 4) - len(result)))
        cursor = end
        if name == 'TRAILER!!!':
            if size or any(raw[cursor:]):
                raise ValueError('source newc has trailing data')
            break
    result.extend(bytes(bootimg.align(len(result), 512) - len(result)))
    entries = bootimg.cpio(bytes(result))
    for change in changes:
        for parent in PurePosixPath(change['name']).parents:
            if str(parent) != '.' and not stat.S_ISDIR(entries.get(str(parent), (0, b''))[0]):
                raise ValueError('normalized symlink has a non-directory ancestor')
    return bytes(result), changes


def build(raw, shared_init, public_key, compatible):
    normalized, changes = canonical_links(raw)
    entries = bootimg.cpio(normalized)
    expected = {'init': shared_init, 'root/.ssh/authorized_keys': public_key,
                'etc/omamobile-compatible': compatible, 'etc/omamobile-ram-probe': b''}
    for name, data in expected.items():
        if name not in entries or not stat.S_ISREG(entries[name][0]) or entries[name][1] != data:
            raise ValueError('probe input mismatch: ' + name)
    storage_mode, storage = entries.get('etc/omamobile-ufs-rw', (0, b'not empty'))
    if not stat.S_ISREG(storage_mode) or storage.strip():
        raise ValueError('RAM probe has a writable storage allowlist')
    if (len(public_key.splitlines()) != 1 or len(public_key.split()) < 2 or
            public_key.split()[0] not in (b'ssh-ed25519', b'ssh-rsa', b'ecdsa-sha2-nistp256')):
        raise ValueError('not an explicit SSH public key')
    if any(name.startswith('root/.ssh/') and name != 'root/.ssh/authorized_keys' for name in entries):
        raise ValueError('unexpected SSH material in the probe')
    init = bootimg.check_init(entries, 'rdinit=/init')
    archive = lzma.compress(normalized, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, preset=6)
    if bootimg.initramfs_cpio(archive) != entries:
        raise ValueError('archive roundtrip mismatch')
    return archive, {'source_raw': bootimg.describe(raw), 'normalized_raw': bootimg.describe(normalized),
                     'archive': bootimg.describe(archive), 'init': init,
                     'shared_init_sha256': bootimg.sha(shared_init), 'symlinks_normalized': changes,
                     'ram_probe': True, 'storage_allowlist_empty': True, 'device_execution_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'shared-init', 'public-key', 'dtb', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--base-sha256', required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix('.json').exists() or args.output.parent.stat().st_mode & 0o077:
        raise ValueError('use new outputs in an existing private directory (0700)')
    if args.base.stat().st_size > 64 * 1024**2:
        raise ValueError('compressed probe exceeds budget')
    with args.base.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != args.base_sha256:
            raise ValueError('source archive identity mismatch')
        stream.seek(0)
        with subprocess.Popen(['lz4', '-dc'], stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            raw = process.stdout.read(bootimg.MAX_RAW + 1)
            if len(raw) > bootimg.MAX_RAW:
                process.kill()
                raise ValueError('expanded probe exceeds budget')
            if process.wait() != 0:
                raise ValueError('source LZ4 decode failed')
        stream.seek(0)
        if hashlib.file_digest(stream, 'sha256').hexdigest() != args.base_sha256:
            raise ValueError('source archive changed during decode')
    dtb = args.dtb.read_bytes()
    compatible = bootimg.Fdt(dtb).nodes['/']['compatible'].split(b'\0')[0] + b'\n'
    archive, receipt = build(raw, args.shared_init.read_bytes(), args.public_key.read_bytes(), compatible)
    receipt.update(source_dtb=bootimg.describe(dtb), compatible=compatible.decode('ascii').strip())
    receipt['source_lz4_sha256'] = args.base_sha256
    os.umask(0o077)
    with args.output.open('xb') as stream:
        stream.write(archive)
    with args.output.with_suffix('.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
