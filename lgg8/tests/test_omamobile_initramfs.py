# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the standard OmaMobile archive at the LG envelope boundary."""
import lzma
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import bootimg as b
import omamobile_initramfs as oma
from test_bootimg import archive, static_pie, tree

INIT = b'#!/bin/sh\necho shared-init\n'
KEY = b'ssh-ed25519 AAAATEST probe\n'
REG = stat.S_IFREG | 0o644
DIR = stat.S_IFDIR | 0o755
LINK = stat.S_IFLNK | 0o777


def records():
    return [('init', REG | 0o111, INIT), ('bin', DIR, b''),
            ('bin/busybox', REG | 0o111, static_pie()), ('bin/sh', LINK, b'/bin/busybox'),
            ('root', DIR, b''), ('root/.ssh', stat.S_IFDIR | 0o700, b''),
            ('root/.ssh/authorized_keys', stat.S_IFREG | 0o600, KEY),
            ('etc', DIR, b''), ('etc/omamobile-compatible', REG, b'lge,alphalm\n'),
            ('etc/omamobile-ram-probe', REG, b''), ('etc/omamobile-ufs-rw', REG, b'\n')]


class ArchiveTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('lz4'), 'LZ4 unavailable')
    def test_cli_checks_the_compiled_dtb_before_publishing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dtb = tree()
            dtb.nodes['/']['compatible'] = b'lge,alphalm\0qcom,sm8150\0'
            (root/'board.dtb').write_bytes(dtb.encode())
            (root/'init').write_bytes(INIT)
            (root/'key.pub').write_bytes(KEY)
            def call(items, output):
                packed = subprocess.run(['lz4', '-zc'], input=archive(items),
                                        capture_output=True, check=True).stdout
                (root/'input.lz4').write_bytes(packed)
                return subprocess.run([sys.executable, '-B', str(Path(oma.__file__)),
                    '--base', str(root/'input.lz4'), '--base-sha256', b.sha(packed),
                    '--dtb', str(root/'board.dtb'), '--shared-init', str(root/'init'),
                    '--public-key', str(root/'key.pub'), '--output', str(root/output)],
                    capture_output=True)
            wrong = [(n, m, b'lg,alphalm\n' if n == 'etc/omamobile-compatible' else data)
                     for n, m, data in records()]
            result = call(wrong, 'wrong.xz')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root/'wrong.xz').exists())
            self.assertEqual(call(records(), 'ready.xz').returncode, 0)
            receipt = json.loads((root/'ready.json').read_text())
            self.assertEqual(receipt['compatible'], 'lge,alphalm')
            self.assertEqual(receipt['source_dtb'], b.describe(dtb.encode()))
            self.assertEqual(b.initramfs_cpio((root/'ready.xz').read_bytes())['init'][1], INIT)

    def test_static_pie_probe_retains_shared_init_and_empty_storage_policy(self):
        raw = archive(records())
        packed, receipt = oma.build(raw, INIT, KEY, b'lge,alphalm\n')
        self.assertEqual(b.cpio(lzma.decompress(packed)), b.cpio(raw))
        self.assertEqual(b.initramfs_cpio(packed), b.cpio(raw))
        self.assertEqual(receipt['init']['elf_type'], 'static-pie')
        self.assertFalse(receipt['device_execution_verified'])

    def test_internal_parent_links_preserve_metadata_and_resolution(self):
        raw = bytearray(archive([('etc', DIR, b''), ('etc/test', DIR, b''),
                                 ('etc/value', REG, b'value'),
                                 ('etc/test/link', LINK, b'../value')]))
        # Exercise metadata absent from the strict parser's returned mapping.
        raw[22:30], raw[30:38], raw[46:54] = b'000003e8', b'000003e9', b'76543210'
        output, changes = oma.canonical_links(bytes(raw))
        self.assertEqual(output[:110], raw[:110])
        self.assertEqual(b.cpio(output)['etc/test/link'], (LINK, b'/etc/value'))
        self.assertEqual(changes, [{'name': 'etc/test/link', 'from': '../value', 'to': '/etc/value'}])
        # Safe top-level landing is allowed, with no escape above root.
        rooted, _ = oma.canonical_links(archive([('etc', DIR, b''), ('etc/link', LINK, b'../bin')]))
        self.assertEqual(b.cpio(rooted)['etc/link'][1], b'/bin')

    def test_reject_escaping_and_nonleading_parent_links(self):
        for target in (b'../../outside', b'/../outside', b'child/../value', b'../child/../value'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                oma.canonical_links(archive([('etc', DIR, b''), ('etc/link', LINK, target)]))

    def test_reject_missing_or_symlink_parent_directory(self):
        for dirs in ([], [('etc', LINK, b'/tmp')]):
            with self.subTest(dirs=dirs), self.assertRaises(ValueError):
                oma.canonical_links(archive(dirs + [('etc/link', LINK, b'../bin')]))

    def test_existing_archive_checks_remain_active(self):
        invalids = [archive([('../outside', REG, b'x')]),
                    archive([('etc', DIR, b''), ('etc', DIR, b'')]),
                    archive([('root', LINK, b'/etc'), ('root/file', REG, b'x')]),
                    archive([('init', REG, b'x')]) + b'nonzero']
        hardlink = bytearray(archive([('file', REG, b'x')]))
        hardlink[38:46] = b'00000002'
        invalids.append(bytes(hardlink))
        padding = bytearray(archive([('xy', REG, b'x')]))
        padding[113] = 1
        invalids.append(bytes(padding))
        for raw in invalids:
            with self.subTest(raw=raw[:35]), self.assertRaises(ValueError):
                oma.canonical_links(raw)

    def test_probe_identity_and_ssh_material_are_checked(self):
        for name, value in [('init', b'wrong'), ('etc/omamobile-compatible', b'another,board\n'),
                            ('etc/omamobile-ram-probe', b'wrong'),
                            ('etc/omamobile-ufs-rw', b'userdata\n'),
                            ('root/.ssh/authorized_keys', b'other key\n')]:
            changed = [(n, m, value if n == name else data) for n, m, data in records()]
            with self.subTest(name=name), self.assertRaises(ValueError):
                oma.build(archive(changed), INIT, KEY, b'lge,alphalm\n')
        with self.assertRaises(ValueError):
            oma.build(archive(records() + [('root/.ssh/id_ed25519', REG, b'private')]), INIT, KEY, b'lge,alphalm\n')
        with self.assertRaises(ValueError):
            oma.build(archive([r for r in records() if r[0] != 'etc/omamobile-ram-probe']), INIT, KEY, b'lge,alphalm\n')
        # The original descriptor typo must fail against the compiled DTB.
        changed = [(n, m, b'lg,alphalm\n' if n == 'etc/omamobile-compatible' else data)
                   for n, m, data in records()]
        with self.assertRaises(ValueError):
            oma.build(archive(changed), INIT, KEY, b'lge,alphalm\n')


if __name__ == '__main__':
    unittest.main()
