# SPDX-License-Identifier: GPL-2.0-only
"""Binding, cleanup and framing tests; no ADB, fastboot or host mutation."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import run_omamobile_ram_only as oma


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dev, self.tty, self.net = (self.root/n for n in ('dev', 'tty', 'net'))
        for path in (self.dev, self.tty, self.net):
            path.mkdir()
        self.usb = self.root/'usb'/'1-2'
        self.usb.mkdir(parents=True)
        for name, value in zip(('idVendor', 'idProduct', 'serial'), oma.USB_ID):
            (self.usb/name).write_text(value)

    def link(self, kind, name):
        interface = self.usb/'1-2:1.0'
        interface.mkdir(exist_ok=True)
        (kind/name).mkdir()
        (kind/name/'device').symlink_to(interface, target_is_directory=True)
        if kind == self.tty:
            (self.dev/name).touch()

    def test_requires_exact_port_vid_pid_serial(self):
        self.link(self.tty, 'ttyACM0')
        self.assertEqual(oma.acm_for_port(self.dev, self.tty), (self.dev/'ttyACM0', self.usb, 'omamobile'))
        for name in ('idVendor', 'idProduct', 'serial'):
            before = (self.usb/name).read_text()
            (self.usb/name).write_text('wrong')
            self.assertIsNone(oma.acm_for_port(self.dev, self.tty))
            (self.usb/name).write_text(before)
        wrong = self.usb.with_name('1-3')
        self.usb.rename(wrong)
        self.assertIsNone(oma.acm_for_port(self.dev, self.tty))

    def test_refuses_ambiguous_acm_and_net(self):
        for name in ('ttyACM0', 'ttyACM1'):
            self.link(self.tty, name)
        with self.assertRaises(RuntimeError):
            oma.acm_for_port(self.dev, self.tty)
        self.link(self.net, 'usbTest0')
        self.assertEqual(oma.net_for_port(self.usb, self.net), 'usbTest0')
        (self.net/'lo').mkdir()
        self.assertEqual(oma.net_for_port(self.usb, self.net), 'usbTest0')
        self.link(self.net, 'usbTest1')
        with self.assertRaises(RuntimeError):
            oma.net_for_port(self.usb, self.net)


class NetworkTests(unittest.TestCase):
    def command(self, argv, **kwargs):
        self.calls.append(argv)
        if self.fail and self.fail(argv):
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b'', stderr=b'')

    def setUp(self):
        self.calls, self.fail = [], None
        self.network = oma.Network('usbTest0', Path('/test/output'), lambda: True, self.command)

    def test_cleanup_on_success_and_failed_move(self):
        with self.network:
            result = self.network.ssh(['/bin/busybox', 'true'], strict=True)
            self.assertEqual(result.returncode, 0)
        ssh = next(call for call in self.calls if '/usr/bin/ssh' in call)
        self.assertIn('ControlPath=none', ssh)
        self.assertIn('StrictHostKeyChecking=yes', ssh)
        self.assertIn('UserKnownHostsFile=/test/output/known_hosts', ssh)
        self.assertEqual(self.calls[-1], ['sudo', '-n', 'ip', 'netns', 'delete', self.network.name])
        self.assertFalse(self.network.created)
        self.calls.clear()
        self.fail = lambda argv: 'netns' in argv and argv[-1] == self.network.name and 'set' in argv
        with self.assertRaises(subprocess.CalledProcessError):
            with self.network:
                self.fail('must never enter')
        self.assertIn('delete', self.calls[-1])
        self.assertFalse(self.network.created)

    def test_failed_creation_cannot_delete_an_unowned_namespace(self):
        self.fail = lambda argv: 'add' in argv
        with self.assertRaises(subprocess.CalledProcessError):
            with self.network:
                self.fail('must never enter')
        self.assertFalse(any('delete' in call for call in self.calls))

    def test_binding_loss_prevents_setup_or_ssh(self):
        self.network.healthy = lambda: False
        with self.assertRaises(RuntimeError):
            with self.network:
                self.fail('must never enter')
        self.assertEqual(self.calls, [])
        with self.assertRaises(RuntimeError):
            self.network.ssh(['/bin/busybox', 'true'], strict=False)
        self.assertEqual(self.calls, [])


class FramingTests(unittest.TestCase):
    def test_shared_shell_uses_nonce_lines_not_the_old_prompt(self):
        class Channel:
            def __init__(self):
                self.sent = []
            def send(self, data, deadline):
                self.sent.append(data)
            def until(self, predicate, deadline):
                marker = self.sent[-1].split(b"\\n")[1]
                self.assert_false = not predicate(b'/ # ' + self.sent[-1])
                assert self.assert_false
                assert predicate(b'/ # \r\n' + marker + b'\r\n')
        oma.synchronize(Channel(), 0)

    def test_command_whitelist_and_actual_pinned_envelope_syntax(self):
        legacy = oma.touch.pinned_legacy()
        for _, argv in oma.tasks():
            script = oma.capture_script(legacy, 'C234_'+'A'*24+'_00', argv)
            subprocess.run(['/bin/sh', '-n'], input=script, check=True, capture_output=True)
            self.assertLess(len(script), 4000)
        with self.assertRaises(ValueError):
            oma.capture_script(legacy, 'C234_'+'A'*24+'_00', ['/bin/busybox', 'reboot'])

    @unittest.skipUnless(shutil.which('busybox'), 'host BusyBox unavailable')
    def test_receipt_integrity_with_real_busybox_and_tmpfiles(self):
        legacy = oma.touch.pinned_legacy()
        prefix = 'C234_'+'B'*24+'_00'
        script = oma.capture_script(legacy, prefix, ['/bin/busybox', 'cat', '/proc/uptime'])
        with tempfile.TemporaryDirectory() as temp:
            script = script.replace(b'/bin/busybox', shutil.which('busybox').encode())
            script = script.replace(b'/run/'+prefix.encode(), str(Path(temp)/prefix).encode())
            result = subprocess.run(['/bin/sh'], input=script, capture_output=True, check=True)
            frame = legacy.parse_frame(result.stdout, prefix)
            self.assertEqual(frame['exit_code'], 0)
            self.assertEqual(frame['stderr'], b'')
            self.assertTrue(frame['payload_integrity_verified'])


if __name__ == '__main__':
    unittest.main()
