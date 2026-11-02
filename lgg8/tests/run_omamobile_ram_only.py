#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Review or explicitly RAM-boot the shared OmaMobile init; never install."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import subprocess
import sys
import time

import run_touch_ram_only as touch
from touch_session import run_session

ROOT = Path(__file__).resolve().parents[2]
OMA = ROOT.parent / 'omarchy-mobile'
PRIVATE = OMA / 'out/alphalm/m1/private'
CANDIDATE = OMA / 'out/alphalm/m1-compatible/private/boot'
IMAGE_SHA = '3e6544cfe2bac4bb6b8d7135ee06005335c9fa73df2fcbe4d7c10118577d7937'
MANIFEST_SHA = 'd84b9c105172e512378000a19e6008e059463f1dde2fc8cff94920a9fdaf2f1c'
INIT_SHA = '52957d7fc9902178b515bf65665062d0a7111d548bbc5298407277dd5e28d79c'
BUSYBOX_SHA = '999cb969d09093a71716cfc747bb53cdada3f332c05eb5046c56e0f66a4d6d22'
PORT = '1-2'
USB_ID = ('1d6b', '0104', 'omamobile')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check():
    image, manifest = CANDIDATE / 'boot.img', CANDIDATE / 'manifest.json'
    if digest(image) != IMAGE_SHA or digest(manifest) != MANIFEST_SHA:
        raise ValueError('OmaMobile candidate identity mismatch')
    data = json.loads(manifest.read_bytes())
    if (data.get('schema') != 'lgg8-boot-image-v1' or
            data['components']['image'] != {'sha256': IMAGE_SHA, 'size': image.stat().st_size} or
            image.stat().st_size > data['partition_size'] or
            [arg for arg in data['bootargs'].split() if arg.startswith('maxcpus=')] != ['maxcpus=8'] or
            [arg for arg in data['bootargs'].split() if arg.startswith('watchdog.open_timeout=')] != ['watchdog.open_timeout=120'] or
            digest(OMA / 'initramfs/init') != INIT_SHA):
        raise ValueError('OmaMobile candidate contract mismatch')
    public = (PRIVATE / 'ssh_ed25519.pub').read_bytes().split()[:2]
    actual = subprocess.run(['ssh-keygen', '-y', '-P', '', '-f', str(PRIVATE / 'ssh_ed25519')],
                            capture_output=True, timeout=3, check=True).stdout.split()[:2]
    if len(public) != 2 or public != actual:
        raise ValueError('probe client key does not match the packed public key')
    return {'status': 'IDENTITY_MATCH', 'image_sha256': IMAGE_SHA,
            'shared_init_sha256': INIT_SHA, 'device_execution': False}


def usb_parent(path):
    try:
        resolved = path.resolve(strict=True)
        for parent in (resolved, *resolved.parents):
            if (parent / 'idVendor').is_file() and (parent / 'idProduct').is_file():
                identity = tuple((parent / name).read_text().strip().lower()
                                 for name in ('idVendor', 'idProduct', 'serial'))
                return parent if parent.name == PORT and identity == USB_ID else None
    except OSError:
        pass
    return None


def acm_for_port(dev=Path('/dev'), tty=Path('/sys/class/tty')):
    found = []
    for node in sorted(dev.glob('ttyACM*')):
        parent = usb_parent(tty / node.name / 'device')
        if parent is not None:
            found.append((node, parent, USB_ID[2]))
    if len(found) > 1:
        raise RuntimeError('ambiguous ACM interfaces on the pinned USB port')
    return found[0] if found else None


def net_for_port(parent, net=Path('/sys/class/net')):
    found = [node.name for node in net.iterdir() if usb_parent(node / 'device') == parent]
    if len(found) > 1:
        raise RuntimeError('ambiguous network interfaces on the pinned USB port')
    if found and re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', found[0]) is None:
        raise RuntimeError('invalid interface name')
    return found[0] if found else None


class Network:
    """Own a fresh namespace containing only the pinned phone's USB interface."""
    def __init__(self, interface, output, healthy, command=subprocess.run):
        self.interface, self.output, self.healthy = interface, output, healthy
        self.command, self.name = command, 'lgg8-oma-' + secrets.token_hex(5)
        self.created = False

    def root(self, argv, *, check=True):
        return self.command(['sudo', '-n', *argv], capture_output=True, timeout=8, check=check)

    def ip(self, *argv, check=True):
        return self.root(['ip', '-n', self.name, *argv], check=check)

    def __enter__(self):
        try:
            if not self.healthy():
                raise RuntimeError('USB binding lost before network setup')
            self.root(['ip', 'netns', 'add', self.name])
            self.created = True
            if not self.healthy():
                raise RuntimeError('USB binding lost before moving its interface')
            self.root(['ip', 'link', 'set', 'dev', self.interface, 'down'])
            self.root(['ip', 'link', 'set', 'dev', self.interface, 'netns', self.name])
            self.ip('link', 'set', 'lo', 'up')
            self.ip('addr', 'add', '172.16.42.2/24', 'dev', self.interface)
            self.ip('link', 'set', self.interface, 'up')
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, *unused):
        if self.created:
            try:
                self.ip('addr', 'del', '172.16.42.2/24', 'dev', self.interface, check=False)
                self.ip('link', 'set', self.interface, 'down', check=False)
            finally:
                self.root(['ip', 'netns', 'delete', self.name])
                self.created = False

    def ssh(self, argv, *, strict):
        if not self.healthy():
            raise RuntimeError('USB binding lost before SSH')
        options = ['-F', '/dev/null', '-n', '-T', '-i', str(PRIVATE / 'ssh_ed25519'),
                   '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                   '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                   '-o', 'ConnectTimeout=3', '-o', 'ConnectionAttempts=1',
                   '-o', 'ServerAliveInterval=2', '-o', 'ServerAliveCountMax=1',
                   '-o', 'StrictHostKeyChecking=' + ('yes' if strict else 'accept-new'),
                   '-o', 'UserKnownHostsFile=' + str(self.output / 'known_hosts'),
                   '-o', 'GlobalKnownHostsFile=/dev/null']
        result = self.root(['ip', 'netns', 'exec', self.name, 'setpriv', '--reuid', str(os.getuid()),
                            '--regid', str(os.getgid()), '--init-groups', '/usr/bin/ssh', *options,
                            'root@172.16.42.1', shlex.join(argv)], check=False)
        if not self.healthy():
            raise RuntimeError('USB binding lost during SSH')
        return result


HEALTH = """set -eu
test -f /etc/omamobile-ram-probe
test -z "$(cat /etc/omamobile-ufs-rw)"
test "$(tr '\\000' '\\n' </proc/device-tree/compatible | head -n 1)" = lge,alphalm
read p </run/omamobile-ram-guardian.pid
kill -0 "$p"
awk '$5=="/run" {n++; for(i=7;i<=NF;i++) if($i=="-" && $(i+1)=="tmpfs") ok++} END {exit !(n==1 && ok==1)}' /proc/self/mountinfo
for s in /sys/block/sd* /sys/block/sd*/sd*; do
 [ -r "$s/ro" ] || continue
 test "$(cat "$s/ro")" = 1
done
printf 'OMA_RAM_HEALTH_OK\\n'
sha256sum /init /bin/busybox /root/.ssh/authorized_keys
"""
HEALTH_ARGV = ['/bin/busybox', 'sh', '-c', HEALTH]


def health_identity(stdout):
    expected = (f'OMA_RAM_HEALTH_OK\n{INIT_SHA}  /init\n{BUSYBOX_SHA}  /bin/busybox\n'
                f'{digest(PRIVATE / "ssh_ed25519.pub")}  /root/.ssh/authorized_keys\n').encode()
    if stdout.replace(b'\r\n', b'\n') != expected:
        raise ValueError('shared init, BusyBox or packed SSH identity mismatch')


def synchronize(channel, deadline):
    marker = ('OMA_SYNC_' + secrets.token_hex(12).upper()).encode()
    channel.send(b'\x15\n', deadline)
    channel.send(b"printf '\\n" + marker + b"\\n'\n", deadline)
    channel.until(lambda data: marker in data.replace(b'\r', b'').splitlines(), deadline)


def tasks():
    return [('health', HEALTH_ARGV),
            ('pid1', ['/bin/busybox', 'cat', '/proc/1/cmdline']),
            ('uptime', ['/bin/busybox', 'cat', '/proc/uptime']),
            ('guardian', ['/bin/busybox', 'cat', '/run/omamobile-ram-guardian.pid']),
            ('inputs', ['/bin/busybox', 'cat', '/proc/bus/input/devices']),
            ('display', ['/bin/busybox', 'sh', '-c', 'for p in /sys/class/drm/card*-DSI-*/modes; do [ ! -f "$p" ] || cat "$p"; done'])]


def capture_script(legacy, prefix, argv):
    if argv not in [command for _, command in tasks()]:
        raise ValueError('command is outside the OmaMobile probe whitelist')
    original = ['/bin/busybox', 'cat', '/proc/cmdline']
    envelope = legacy.capture_script(prefix, original)
    needle = shlex.join(original).encode()
    if envelope.count(needle) != 1:
        raise ValueError('pinned capture envelope changed')
    result = envelope.replace(needle, shlex.join(argv).encode())
    if len(result) >= 4000:
        raise ValueError('command exceeds the serial canonical line budget')
    return result


class DeviceIO(touch.DeviceIO):
    def __init__(self, serial, output):
        touch.CANDIDATE, touch.check = CANDIDATE, check
        super().__init__(serial, output)
        self.inner.base.acm_parent_for_port = acm_for_port
        self.legacy.synchronize_shell = synchronize

    def capture_touch(self):
        inner, legacy = self.inner, self.legacy
        end = min(inner.deadline - 15, inner.boot_time + 110)
        while time.monotonic() < end:
            if not inner.monitor.healthy():
                raise RuntimeError('USB monitor stopped before OmaMobile collection')
            located = acm_for_port()
            if located:
                node, parent, _ = located
                fingerprint = legacy.usb_snapshot()
                def healthy():
                    return inner.monitor.healthy() and fingerprint == legacy.usb_snapshot() and acm_for_port() == located
                channel = legacy.SerialChannel(node, self.output)
                try:
                    guarded = touch.GuardedChannel(channel, healthy)
                    synchronize(guarded, min(end, time.monotonic() + 4))
                    receipts = {}
                    for index, (key, argv) in enumerate(tasks()):
                        prefix = f'C234_{secrets.token_hex(12).upper()}_{index:02d}'
                        guarded.send(capture_script(legacy, prefix, argv), end)
                        frame = guarded.until(lambda data: legacy.parse_frame(data, prefix), min(end, time.monotonic() + 4))
                        if frame['exit_code'] or frame['stderr_length']:
                            raise RuntimeError('OmaMobile ACM command failed: ' + key)
                        receipts[key] = {k: v for k, v in frame.items() if k not in ('stdout', 'stderr')}
                        receipts[key].update(stdout_b64=base64.b64encode(frame['stdout']).decode(),
                                             stderr_b64=base64.b64encode(frame['stderr']).decode())
                        inner.save('omamobile-acm-capture', receipts)
                    health_identity(base64.b64decode(receipts['health']['stdout_b64'], validate=True))
                    if b'/init\0' not in base64.b64decode(receipts['pid1']['stdout_b64'], validate=True):
                        raise RuntimeError('shared init is not PID 1')
                    interface = net_for_port(parent)
                    if interface is None:
                        raise RuntimeError('no network interface on the pinned USB device')
                    with Network(interface, self.output, healthy) as network:
                        for strict in (False, True):
                            result = network.ssh(HEALTH_ARGV, strict=strict)
                            inner.save('omamobile-ssh-' + ('strict' if strict else 'first'),
                                       {'exit_code': result.returncode,
                                        'stdout_b64': base64.b64encode(result.stdout).decode(),
                                        'stderr_b64': base64.b64encode(result.stderr).decode()})
                            if result.returncode:
                                raise RuntimeError('OmaMobile SSH health failed')
                            health_identity(result.stdout)
                    inner.save('omamobile-capture', {'status': 'PASS', 'shared_init_verified': True,
                               'fresh_ssh_connections': 2, 'client_multiplexing': False,
                               'guardian_alive': True, 'manual_reboot_requested': False,
                               'visual_display_verified': False, 'physical_touch_verified': False,
                               'arch_rootfs_verified': False})
                    return 'PASS'
                finally:
                    channel.close()
            snap = legacy.usb_snapshot()
            if snap.get('vid') == '1004' and snap.get('serial') == inner.serial:
                raise RuntimeError('Android returned before OmaMobile capture')
            if snap.get('vid') == '18d1' and snap.get('pid') == '4ee0' and time.monotonic() - inner.boot_time >= 30:
                raise RuntimeError('fastboot still present after 30 seconds')
            time.sleep(0.2)
        raise TimeoutError('OmaMobile collection deadline')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-ram-only', action='store_true')
    parser.add_argument('--serial')
    args = parser.parse_args()
    if not args.execute_ram_only:
        if args.serial:
            parser.error('serial requires --execute-ram-only')
        print(json.dumps(check(), indent=2))
        return
    if not args.serial or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', args.serial) is None:
        parser.error('execution requires one explicit device serial')
    check()
    legacy = touch.pinned_legacy()
    for _, argv in tasks():
        capture_script(legacy, 'C234_' + 'A' * 24 + '_00', argv)
    os.umask(0o077)
    output = PRIVATE / (time.strftime('run-%Y%m%d-%H%M%S', time.gmtime()) + '-' + secrets.token_hex(4))
    output.mkdir(mode=0o700)
    io = DeviceIO(args.serial, output)
    def interrupt(signum, unused):
        if not io.inner.recovering:
            raise InterruptedError('signal ' + str(signum))
    handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        result = run_session(io)
        result.update(image_sha256=IMAGE_SHA, arch_rootfs_verified=False,
                      visual_display_verified=False, physical_touch_verified=False,
                      charging_safety_verified=False)
        io.inner.save('omamobile-result', result)
        print(json.dumps({'directory': str(output), **result}, indent=2))
        if not result['success']:
            sys.exit(1)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
