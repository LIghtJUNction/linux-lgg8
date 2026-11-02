"""Archive extension preserves device nodes and rejects path replacement."""
from pathlib import Path
import stat
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import bootimg
import modem_initramfs
from mkinitramfs import entry


class ArchiveTest(unittest.TestCase):
    def test_preserves_original_device_metadata_and_adds_parents(self):
        original = entry('dev', stat.S_IFDIR | 0o755, ino=1)
        original += entry('dev/console', stat.S_IFCHR | 0o600, ino=2, rdev=(5, 1))
        base = original + entry('TRAILER!!!', 0, ino=3)
        result = modem_initramfs.extend(base, {'lib/firmware/test': (stat.S_IFREG | 0o644, b'abc')})
        self.assertTrue(result.startswith(original))
        self.assertEqual(bootimg.cpio(result)['lib/firmware/test'][1], b'abc')

    def test_rejects_replacement_and_unsafe_paths(self):
        base = entry('init', stat.S_IFREG | 0o755, b'original') + entry('TRAILER!!!', 0)
        for name in ('init', '/escape', '../escape', 'a/../escape'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                modem_initramfs.extend(base, {name: (stat.S_IFREG | 0o644, b'bad')})


if __name__ == '__main__':
    unittest.main()
