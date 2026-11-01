#!/usr/bin/env python3
import stat
import unittest

from make_sw42000_probe_initramfs import ROOT, load
from replace_supervisor_initramfs import replace

mk = load(ROOT / 'lgg8/tools/mkinitramfs.py', 'test_replace_mk')
boot = load(ROOT / 'lgg8/tools/bootimg.py', 'test_replace_boot')


def elf(payload=b''):
    return b'\x7fELF\x02\x01' + b'\0' * 12 + b'\xb7\x00' + payload


def archive(init=True, mode=stat.S_IFREG | 0o755):
    entries = mk.entry('x', stat.S_IFREG | 0o644, b'keep', ino=1)
    if init:
        entries += mk.entry('init', mode, elf(b'old'), ino=2)
    entries += mk.entry('other', stat.S_IFREG | 0o600, b'unchanged', ino=3)
    return entries + mk.entry('TRAILER!!!', 0, b'', ino=4)


class ReplaceSupervisorTest(unittest.TestCase):
    def test_only_init_changes_for_all_alignments(self):
        source = archive()
        for size in range(8):
            with self.subTest(size=size):
                new = elf(b'x' * size)
                before = boot.cpio(source)
                after = boot.cpio(replace(source, new))
                self.assertEqual(after.pop('init'), (stat.S_IFREG | 0o755, new))
                before.pop('init')
                self.assertEqual(after, before)

    def test_reject_missing_wrong_mode_and_wrong_arch(self):
        for source, binary in ((archive(False), elf()),
                               (archive(mode=stat.S_IFREG | 0o644), elf()),
                               (archive(), b'bad'),
                               (archive(), elf()[:18] + b'\x3e\x00')):
            with self.subTest(source=len(source), binary=binary):
                with self.assertRaises(ValueError):
                    replace(source, binary)


if __name__ == '__main__':
    unittest.main()
