#!/usr/bin/env python3
"""Build a pinned upstream RMTFS with its sysfs backend and static ARM64 libc."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PINS = {'rmtfs': 'b30a3eb38f9af283f18dbd3c7755653efc52c094',
        'qrtr': '29e36ae164389580a0f8ea7a7fdb728140ae978d'}


def build(vendor, output):
    for name, pin in PINS.items():
        repo = vendor / name
        if subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() != pin:
            raise ValueError('unreviewed source revision: ' + name)
        if subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True):
            raise ValueError('modified upstream source: ' + name)
    if output.exists():
        raise ValueError('output exists')
    compat = output.parent / 'compat/sys'
    compat.mkdir(parents=True, exist_ok=True)
    # Upstream's ANDROID switch chooses direct Linux /sys/class/rmtfs access.
    # It otherwise only requires this endian-header spelling compatibility.
    (compat / 'endian.h').write_text('#include <endian.h>\n')
    r, q = vendor / 'rmtfs', vendor / 'qrtr'
    sources = [r / name for name in ('qmi_rmtfs.c', 'rmtfs.c', 'rproc.c',
                                     'sharedmem.c', 'storage.c', 'util.c')]
    sources += [q / 'lib' / name for name in ('qrtr.c', 'qmi.c', 'logging.c')]
    command = ['aarch64-linux-gnu-gcc', '-D_GNU_SOURCE', '-DANDROID', '-static', '-Os',
               '-Wall', '-Wextra', '-Wl,--build-id=none', '-s',
               '-I' + str(compat.parent), '-I' + str(q / 'include'), '-I' + str(r),
               *map(str, sources), '-pthread', '-o', str(output)]
    result = subprocess.run(command, capture_output=True)
    output.with_suffix('.build.log').write_bytes(result.stdout + result.stderr)
    result.check_returncode()
    data = output.read_bytes()
    # In this backend ENOENT leads to unsupported UIO and aborts. Optimized
    # output must not contain the otherwise-available raw /dev/mem fallback.
    if b'/dev/mem\0' in data:
        raise ValueError('unexpected raw physical-memory backend in binary')
    receipt = {'sources': PINS, 'command': command,
               'binary': {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()},
               'backend': 'upstream direct Linux rmtfs sysfs (ANDROID switch)',
               'raw_devmem_fallback': False,
               'device_execution_verified': False}
    output.with_suffix('.build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.vendor, args.output), indent=2))
