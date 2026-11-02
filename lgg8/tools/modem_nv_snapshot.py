#!/usr/bin/env python3
"""Read a stable private EFS snapshot; never write a phone partition."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from modem_firmware import decode_transport

NAMES = ('modemst1', 'modemst2', 'fsg', 'fsc')
MAX_EACH = 16 * 1024 * 1024


def snapshot(serial, destination):
    if re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', serial) is None:
        raise ValueError('invalid explicit serial')

    def command(text):
        result = subprocess.run(['adb', '-s', serial, 'exec-out', 'su', '-c', text],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if result.returncode or result.stderr:
            raise ValueError('private snapshot read command failed')
        return result.stdout

    paths = ['/dev/block/by-name/' + name for name in NAMES]
    sizes = {}
    for name, path in zip(NAMES, paths):
        value = command('blockdev --getsize64 ' + path).decode('ascii').strip()
        if not value.isdigit() or not 0 < int(value) <= MAX_EACH:
            raise ValueError('unexpected EFS partition size')
        sizes[name] = int(value)

    def hashes():
        result = {}
        for line in command('sha256sum ' + ' '.join(paths)).decode('ascii').splitlines():
            value, path = line.split(None, 1)
            if path not in paths or path in result or not re.fullmatch(r'[0-9a-f]{64}', value):
                raise ValueError('invalid EFS hash receipt')
            result[path] = value
        if set(result) != set(paths):
            raise ValueError('incomplete EFS hash receipt')
        return result

    before = hashes()
    os.umask(0o077)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    local = {}
    for name, path in zip(NAMES, paths):
        data = decode_transport(command('base64 ' + path))
        if len(data) != sizes[name] or hashlib.sha256(data).hexdigest() != before[path]:
            raise ValueError('unstable EFS transfer; partial snapshot is not verified')
        with (destination / name).open('xb') as stream:
            stream.write(data)
        if hashlib.sha256((destination / name).read_bytes()).hexdigest() != before[path]:
            raise ValueError('local EFS copy mismatch')
        local[name] = {'size': sizes[name], 'sha256': before[path]}
    if hashes() != before:
        raise ValueError('EFS changed during snapshot; partial snapshot is not verified')
    receipt = {'schema': 'lgg8-private-efs-snapshot-v1', 'files': local,
               'copy_verified': True, 'before_local_after_sha256_match': True,
               'device_writes': False, 'contains_private_device_configuration': True}
    (destination / 'verified.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return {'copy_verified': True, 'files': len(local), 'bytes': sum(sizes.values()),
            'private_directory': str(destination), 'device_writes': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(snapshot(args.serial, args.output), indent=2))
