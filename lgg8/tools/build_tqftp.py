#!/usr/bin/env python3
"""Build pinned upstream QRTR TFTP; runtime writes must be placed in RAM."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PINS = {'tqftpserv': 'eb4b9a04ff92d2753ededf32cc3b6ed287f6e29b',
        'qrtr': '29e36ae164389580a0f8ea7a7fdb728140ae978d'}


def build(tqftpserv, qrtr, output):
    for name, repo in [('tqftpserv', tqftpserv), ('qrtr', qrtr)]:
        if subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() != PINS[name]:
            raise ValueError('unreviewed source revision: ' + name)
        if subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain']):
            raise ValueError('modified upstream source: ' + name)
    if output.exists():
        raise ValueError('output exists')
    command = ['aarch64-linux-gnu-gcc', '-static', '-Os', '-Wall', '-Wextra',
               '-Wl,--build-id=none', '-s', '-I' + str(qrtr / 'include'),
               str(tqftpserv / 'tqftpserv.c'), str(tqftpserv / 'translate.c'),
               str(qrtr / 'lib/qrtr.c'), str(qrtr / 'lib/logging.c'), '-o', str(output)]
    result = subprocess.run(command, capture_output=True)
    output.with_suffix('.build.log').write_bytes(result.stdout + result.stderr)
    result.check_returncode()
    data = output.read_bytes()
    receipt = {'sources': PINS, 'command': command,
               'binary': {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()},
               'compressed_file_support': False,
               'runtime_write_directory': '/var/lib/tqftpserv',
               'requires_bounded_ram_mount': True, 'device_execution_verified': False}
    output.with_suffix('.build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tqftpserv', type=Path, required=True)
    parser.add_argument('--qrtr', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.tqftpserv, args.qrtr, args.output), indent=2))
