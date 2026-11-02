#!/usr/bin/env python3
"""Copy only stock modem firmware through encoded ADB and audit its load range."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess

REMOTE = '/vendor/firmware_mnt/image'
MAX_TOTAL = 96 * 1024 * 1024
MEM_BASE, MEM_SIZE = 0x8e000000, 0xa000000


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def decode_transport(data):
    # This phone's root shell translates LF to CRLF even with adb exec-out.
    # Encode on the phone before that terminal transformation occurs.
    return base64.b64decode(data.replace(b'\r', b'').replace(b'\n', b''), validate=True)


def audit(directory):
    data = (directory / 'modem.mdt').read_bytes()
    if len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('expected little-endian ELF32 MDT')
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
    if header[2] != 164 or header[8:10] != (52, 32):
        raise ValueError('unexpected Hexagon ELF header')
    offset, count = header[5], header[10]
    if not 1 <= count <= 100 or offset < 52 or offset + count * 32 > len(data):
        raise ValueError('program header table outside MDT')
    segments = []
    for index in range(count):
        kind, _, _, address, size, memory, flags, _ = struct.unpack_from('<8I', data, offset + index * 32)
        if kind != 1 or (flags & (7 << 24)) == 2 << 24 or not memory:
            continue
        if size > memory or address + memory > 2**32:
            raise ValueError('invalid load segment bounds')
        if size:
            path = directory / f'modem.b{index:02d}'
            if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
                raise ValueError(f'load segment {index} size mismatch or missing')
        segments.append({'index': index, 'address': address, 'file_size': size,
                         'memory_size': memory, 'relocatable': bool(flags & (1 << 27))})
    if not segments:
        raise ValueError('no loadable segments')
    low = min(s['address'] for s in segments)
    high = max((s['address'] + s['memory_size'] + 4095) & ~4095 for s in segments)
    relocatable = any(s['relocatable'] for s in segments)
    origin = low if relocatable else MEM_BASE
    for segment in segments:
        start = segment['address'] - origin
        if start < 0 or start + segment['memory_size'] > MEM_SIZE:
            raise ValueError('firmware exceeds the LG MPSS reserved region')
    if high - low > MEM_SIZE:
        raise ValueError('aligned firmware span exceeds MPSS region')
    return {'status': 'PASS', 'memory_base': MEM_BASE, 'memory_size': MEM_SIZE,
            'load_span': high - low, 'relocatable': relocatable, 'segments': segments,
            'signature_authenticated': False, 'phone_execution_verified': False}


def collect(serial, destination=None):
    if re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', serial) is None:
        raise ValueError('invalid explicit serial')

    def command(text, **kwargs):
        return subprocess.run(['adb', '-s', serial, 'exec-out', 'su', '-c', text],
                              stderr=subprocess.PIPE, timeout=60, check=True, **kwargs)

    paths = command(f'ls -1 {REMOTE}/modem.mdt {REMOTE}/modem.b[0-9][0-9]',
                    stdout=subprocess.PIPE).stdout.decode('ascii').splitlines()
    if not paths or len(set(paths)) != len(paths) or len(paths) > 101:
        raise ValueError('invalid firmware file list')
    if any(re.fullmatch(re.escape(REMOTE) + r'/modem\.(mdt|b[0-9]{2})', p) is None for p in paths):
        raise ValueError('unexpected firmware path')
    joined = shlex.join(paths)
    sizes = {}
    for line in command("stat -c '%s %n' " + joined, stdout=subprocess.PIPE).stdout.decode('ascii').splitlines():
        size, path = line.split(' ', 1)
        if path not in paths or path in sizes or not size.isdigit():
            raise ValueError('invalid stat receipt')
        sizes[path] = int(size)
    if set(sizes) != set(paths) or not 0 < sum(sizes.values()) <= MAX_TOTAL:
        raise ValueError('firmware size outside copy budget')

    def hashes():
        result = {}
        for line in command('sha256sum ' + joined, stdout=subprocess.PIPE).stdout.decode('ascii').splitlines():
            value, path = line.split(None, 1)
            if path not in paths or path in result or re.fullmatch(r'[0-9a-f]{64}', value) is None:
                raise ValueError('invalid hash receipt')
            result[path] = value
        if set(result) != set(paths):
            raise ValueError('incomplete firmware hashes')
        return result

    before = hashes()
    report = {'schema': 'lgg8-modem-firmware-v1', 'files': {
        Path(p).name: {'size': sizes[p], 'sha256': before[p]} for p in paths},
        'total_size': sum(sizes.values()), 'device_writes': False}
    if destination is None:
        return report
    probe = command("printf 'A\\nB\\r\\nC\\000D' | base64", stdout=subprocess.PIPE).stdout
    if decode_transport(probe) != b'A\nB\r\nC\0D':
        raise ValueError('ADB encoded channel changed bytes')
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for path in paths:
        target = destination / Path(path).name
        encoded = command('base64 ' + shlex.quote(path), stdout=subprocess.PIPE).stdout
        binary = decode_transport(encoded)
        if len(binary) != sizes[path] or hashlib.sha256(binary).hexdigest() != before[path]:
            raise ValueError('encoded firmware transfer mismatch')
        with target.open('xb') as stream:
            stream.write(binary)
        if target.stat().st_size != sizes[path] or digest(target) != before[path]:
            raise ValueError('local firmware copy mismatch')
    if hashes() != before:
        raise ValueError('phone firmware changed during copy')
    report['audit'] = audit(destination)
    report['transport'] = 'ADB root base64 with before/local/after SHA-256 verification'
    report['copy_verified'] = True
    (destination / 'verified.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, help='new directory for a verified local copy; omitted means inventory only')
    args = parser.parse_args()
    print(json.dumps(collect(args.serial, args.output), indent=2))
