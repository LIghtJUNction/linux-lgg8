#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Diagnostic init validation, newc compatibility and atomic publication tests."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / "tools/mkinitramfs.py"
SPEC = importlib.util.spec_from_file_location("mkinitramfs_under_test", TOOL)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def elf(kind=2, segment=1, flags=5):
    data = bytearray(124)
    data[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into("<HHIQQQIHHHHHH", data, 16, kind, 183, 1, 0x400000, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into("<IIQQQQQQ", data, 64, segment, flags, 120, 0x400000, 0x400000, 4, 4, 4)
    data[120:] = bytes.fromhex("000080d2")
    return bytes(data)


class InitramfsTests(unittest.TestCase):
    def test_valid_static_archive_inventory_and_determinism(self):
        init = elf()
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
            first = m.build(init)
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "123456"}):
            second = m.build(init)
        self.assertEqual(first, second)
        self.assertEqual(len(first) % 512, 0)
        entries = m._bootimg.cpio(first)
        self.assertEqual(set(entries), {".", "dev", "proc", "sys", "dev/console", "dev/kmsg", "init"})
        self.assertEqual(entries["init"], (stat.S_IFREG | 0o755, init))
        self.assertTrue(stat.S_ISCHR(entries["dev/console"][0]))
        self.assertEqual(m._bootimg.check_init(entries, "")["resolved_elf"], "/init")

    def test_core_null_nonexecutable_and_dynamic_rejected(self):
        for label, init in (("ET_CORE", elf(kind=4)), ("PT_NULL", elf(segment=0)),
                            ("no execute permission", elf(flags=4)), ("ET_DYN", elf(kind=3)),
                            ("PT_INTERP", elf(segment=3)), ("PT_DYNAMIC", elf(segment=2))):
            with self.subTest(label=label), self.assertRaises(ValueError):
                m.build(init)

    def test_bad_elf_bounds_and_entry_rejected(self):
        corruptions = ((24, "<Q", 0x400004), (32, "<Q", 0xffff), (54, "<H", 55),
                       (64 + 8, "<Q", 0xffff), (64 + 40, "<Q", 3))
        for offset, fmt, value in corruptions:
            init = bytearray(elf())
            struct.pack_into(fmt, init, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                m.build(init)
        for init in (elf()[:20], elf()[:-1]):
            with self.assertRaises(ValueError):
                m.build(init)

    def test_wrong_format_architecture_and_unavailable_interpreter_rejected(self):
        for offset, value in ((4, 1), (5, 2), (18, 62)):
            init = bytearray(elf())
            init[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                m.build(init)
        for init in (b"not ELF", b"#!/bin/sh\necho hello\n"):
            with self.assertRaises(ValueError):
                m.build(init)

    def cli(self, directory, init, output):
        return subprocess.run([sys.executable, "-I", "-B", str(TOOL), "--init", str(init), "--output", str(output)],
                              cwd=directory, capture_output=True, text=True)

    def test_isolated_cli_import_and_replace_existing_archive(self):
        with tempfile.TemporaryDirectory(prefix="lgg8-initramfs-cli-") as folder:
            directory = Path(folder)
            init, output = directory / "init", directory / "initramfs.cpio"
            init.write_bytes(elf())
            output.write_bytes(b"old archive")
            result = self.cli(directory, init, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), m.build(elf()))
            self.assertEqual(set(p.name for p in directory.iterdir()), {"init", "initramfs.cpio"})

    def test_spec_import_without_tools_on_sys_path(self):
        with tempfile.TemporaryDirectory(prefix="lgg8-initramfs-import-") as folder:
            directory = Path(folder)
            init = directory / "init"
            init.write_bytes(elf())
            code = (
                "import importlib.util, sys; from pathlib import Path; "
                "s=importlib.util.spec_from_file_location('independent_loader', sys.argv[1]); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "sys.stdout.buffer.write(m.build(Path(sys.argv[2]).read_bytes()))"
            )
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(TOOL), str(init)], cwd=directory, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, m.build(elf()))

    def test_invalid_cli_input_preserves_old_output_and_creates_no_new_directory(self):
        with tempfile.TemporaryDirectory(prefix="lgg8-initramfs-reject-") as folder:
            directory = Path(folder)
            init, old, new = directory / "init", directory / "existing.cpio", directory / "new/initramfs.cpio"
            init.write_bytes(elf(kind=4))
            old.write_bytes(b"original archive")
            for output in (old, new):
                with self.subTest(output=output.name):
                    result = self.cli(directory, init, output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("invalid static init ELF", result.stderr)
            self.assertEqual(old.read_bytes(), b"original archive")
            self.assertFalse(new.parent.exists())
            self.assertEqual(set(p.name for p in directory.iterdir()), {"init", "existing.cpio"})

    def test_atomic_replace_failure_preserves_old_output_and_removes_temporary(self):
        with tempfile.TemporaryDirectory(prefix="lgg8-initramfs-atomic-") as folder:
            directory = Path(folder)
            init, output = directory / "init", directory / "initramfs.cpio"
            init.write_bytes(elf())
            output.write_bytes(b"original archive")
            argv = [str(TOOL), "--init", str(init), "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(m.os, "replace", side_effect=OSError("simulated replacement failure")):
                with self.assertRaisesRegex(OSError, "replacement failure"), contextlib.redirect_stdout(io.StringIO()):
                    m.main()
            self.assertEqual(output.read_bytes(), b"original archive")
            self.assertEqual(set(p.name for p in directory.iterdir()), {"init", "initramfs.cpio"})

    @unittest.skipUnless(shutil.which("cpio"), "GNU cpio is optional")
    def test_gnu_cpio_lists_archive_and_reads_exact_init(self):
        version = subprocess.run(["cpio", "--version"], capture_output=True, text=True)
        if version.returncode or "GNU cpio" not in version.stdout:
            self.skipTest("GNU cpio is not installed")
        archive = m.build(elf())
        listed = subprocess.run(["cpio", "--list", "--quiet"], input=archive, capture_output=True)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(set(listed.stdout.decode().splitlines()), {".", "dev", "proc", "sys", "dev/console", "dev/kmsg", "init"})
        extracted = subprocess.run(["cpio", "--extract", "--to-stdout", "--quiet", "init"], input=archive, capture_output=True)
        self.assertEqual(extracted.returncode, 0, extracted.stderr)
        self.assertEqual(extracted.stdout, elf())

    @unittest.skipUnless(shutil.which("aarch64-linux-gnu-gcc"), "AArch64 cross compiler is optional")
    def test_real_static_aarch64_elf(self):
        with tempfile.TemporaryDirectory(prefix="lgg8-initramfs-static-") as folder:
            path = Path(folder) / "init"
            result = subprocess.run(["aarch64-linux-gnu-gcc", "-static", "-Os", "-Wl,--build-id=none", "-x", "c", "-", "-o", str(path)],
                                    input="int main(void) { return 0; }\n", capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            init = path.read_bytes()
            archive = m.build(init)
            self.assertEqual(m._bootimg.cpio(archive)["init"][1], init)


if __name__ == "__main__":
    unittest.main()
