"""Exercise archive preservation and rejection without phone or build artifacts."""
import importlib.util
from pathlib import Path
import stat
import unittest

HERE = Path(__file__).resolve().parent


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


maker = load(HERE / "make_sw42000_probe_initramfs.py")
newc = load(HERE.parent / "tools/mkinitramfs.py")
boot = newc._bootimg


class ArchiveTest(unittest.TestCase):
    def test_preserves_and_rejects(self):
        old = (newc.entry(".", stat.S_IFDIR | 0o755) +
               newc.entry("init", stat.S_IFREG | 0o755, b"old-init") +
               newc.entry("TRAILER!!!", 0))
        executable = bytearray(32)
        executable[:6] = b"\x7fELF\x02\x01"
        executable[18:20] = b"\xb7\x00"
        result = maker.build(old, bytes(executable))
        entries = boot.cpio(result)
        self.assertEqual(entries.pop("usr/bin/sw42000-event-probe"),
                         (stat.S_IFREG | 0o755, bytes(executable)))
        self.assertEqual(entries, boot.cpio(old))
        with self.assertRaises(ValueError):
            maker.build(result, bytes(executable))
        with self.assertRaises(ValueError):
            maker.build(old, b"not ELF")
        with self.assertRaises(ValueError):
            maker.build(old[:-10], bytes(executable))
        executable[18] = 0x3e  # x86-64
        with self.assertRaises(ValueError):
            maker.build(old, bytes(executable))


if __name__ == "__main__":
    unittest.main()
