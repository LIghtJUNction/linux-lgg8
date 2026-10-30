#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline packer tests. All generated binaries live in auto-cleaned temp dirs."""
import argparse
import copy
import importlib.util
import json
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

SPEC = importlib.util.spec_from_file_location("bootimg", Path(__file__).resolve().parents[1] / "tools/bootimg.py")
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


def elf(dynamic=False):
    data = bytearray(124)
    data[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into("<HHIQQQIHHHHHH", data, 16, 2, 183, 1, 0x400000, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into("<IIQQQQQQ", data, 64, 3 if dynamic else 1, 5, 120, 0x400000, 0x400000, 4, 4, 4)
    data[120:] = bytes.fromhex("00000014")
    return bytes(data)


def archive(records=None):
    records = records if records is not None else [("init", stat.S_IFREG | 0o755, elf()), ("dev", stat.S_IFDIR | 0o755, b""), ("dev/console", stat.S_IFCHR | 0o600, b"")]
    result = bytearray()
    for inode, (name, mode, data) in enumerate([*records, ("TRAILER!!!", 0, b"")], 1):
        name = name.encode() + b"\0"
        values = [inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name), 0]
        result.extend(b"070701" + b"".join(f"{v:08x}".encode() for v in values) + name)
        result.extend(bytes(b.align(len(result), 4) - len(result)))
        result.extend(data)
        result.extend(bytes(b.align(len(result), 4) - len(result)))
    return bytes(result)


def tree():
    result = b.Fdt.__new__(b.Fdt)
    result.boot_cpu, result.reserves = 0, []
    result.nodes = {
        "/": {"#address-cells": struct.pack(">I", 2), "#size-cells": struct.pack(">I", 2), "compatible": b"lg,alphalm\0"},
        "/memory@80000000": {"device_type": b"memory\0", "reg": struct.pack(">QQ", 0x80000000, 0x80000000)},
        "/reserved-memory": {"#address-cells": struct.pack(">I", 2), "#size-cells": struct.pack(">I", 2), "ranges": b""},
        "/reserved-memory/ramoops@b0000000": {"reg": struct.pack(">QQ", 0xb0000000, 0x100000)},
    }
    return result


def image():
    kernel = bytearray(128)
    kernel[:4] = bytes.fromhex("10000014")
    struct.pack_into("<QQQ", kernel, 8, 0, 0x40000, 0xa)
    kernel[56:60] = b"ARM\x64"
    return bytes(kernel)


def template_image():
    raw = bytearray(b.PAGE + 128)
    struct.pack_into("<QQQ", raw, 8, 0, len(raw), 0xa)
    raw[56:60] = b"ARM\x64"
    raw[b.PAGE:] = image()
    header = bytearray(b.PAGE)
    header[:8] = b"ANDROID!"
    struct.pack_into("<10I", header, 8, 0, 0x8000, 6, 0x1000000, 0, 0, 0x100, b.PAGE, 0, 369099144)
    stock = tree().encode() * 2
    return b.pack_boot(header, b.gzip_member(raw, 0) + stock, b"dummy\n")


class StructureTests(unittest.TestCase):
    def test_newc_minimal_init_and_arbitrary_inventory(self):
        entries = b.cpio(archive())
        self.assertEqual(len(entries), 3)
        self.assertEqual(b.check_init(entries, "console=tty0")["entry"], "/init")
        records = [(f"file{i}", stat.S_IFREG | 0o644, b"hello") for i in range(40)]
        records.append(("init", stat.S_IFREG | 0o755, elf()))
        self.assertEqual(len(b.cpio(archive(records))), 41)

    def test_cpio_bounds_names_padding_and_trailer(self):
        good = archive()
        bad_size = bytearray(good)
        bad_size[54:62] = b"ffffffff"
        bad_name = bytearray(good)
        bad_name[94:102] = b"ffffffff"
        bad_pad = bytearray(good)
        bad_pad[115] = 1
        for broken in (good[:20], good[:-1], bytes(bad_size), bytes(bad_name), bytes(bad_pad), good + b"x", good + archive()):
            with self.subTest(size=len(broken)), self.assertRaises(ValueError):
                b.cpio(broken)

    def test_cpio_traversal_duplicate_and_symlink_ancestors(self):
        for records in (
            [("../init", stat.S_IFREG | 0o755, elf())],
            [("/init", stat.S_IFREG | 0o755, elf())],
            [("init", stat.S_IFREG | 0o755, elf()), ("./init", stat.S_IFREG | 0o755, elf())],
            [("link", stat.S_IFLNK | 0o777, b"../escape")],
            [("dir", stat.S_IFLNK | 0o777, b"/elsewhere"), ("dir/file", stat.S_IFREG | 0o644, b"x")],
        ):
            with self.subTest(records=records), self.assertRaises(ValueError):
                b.cpio(archive(records))

    def test_cpio_hardlink_aliases_cannot_replace_verified_init(self):
        bad = bytearray(archive())
        bad[38:46] = b"00000002"
        with self.assertRaisesRegex(ValueError, "hardlink"):
            b.cpio(bad)

    def test_dynamic_or_nonexecutable_or_missing_init_rejected(self):
        elf32 = bytearray(elf())
        elf32[4] = 1
        wrong_machine = bytearray(elf())
        struct.pack_into("<H", wrong_machine, 18, 62)
        for entries in (
            {"init": (stat.S_IFREG | 0o755, elf(True))},
            {"init": (stat.S_IFREG | 0o644, elf())},
            {"init": (stat.S_IFREG | 0o755, b"#!/bin/sh\necho hi\n")},
            {"init": (stat.S_IFREG | 0o755, elf()[:-1])},
            {"init": (stat.S_IFLNK | 0o777, b"init")},
            {"init": (stat.S_IFREG | 0o755, bytes(elf32))},
            {"init": (stat.S_IFREG | 0o755, bytes(wrong_machine))},
        ):
            with self.subTest(entries=list(entries)), self.assertRaises(ValueError):
                b.check_init(entries, "rdinit=/init")

    def test_script_static_interpreter_and_rdinit(self):
        entries = {"start": (stat.S_IFREG | 0o755, b"#!/bin/sh\nexec true\n"),
                   "bin/sh": (stat.S_IFLNK | 0o777, b"busybox"), "bin/busybox": (stat.S_IFREG | 0o755, elf())}
        self.assertEqual(b.check_init(entries, "rdinit=/start")["resolved_elf"], "/bin/busybox")
        entries["start"] = (stat.S_IFREG | 0o755, b'#!"/bin/sh"\ntrue\n')
        with self.assertRaises(ValueError):
            b.check_init(entries, "rdinit=/start")

    def test_fdt_roundtrip_and_stock_trailer(self):
        blob = tree().encode()
        self.assertEqual(b.Fdt(blob).encode(), blob)
        self.assertEqual(b.stock_dtbs(blob + blob), [b.sha(blob)] * 2)
        for broken in (blob + b"x", blob[:-1], b"", blob + bytes(4), b.gzip_member(b"bad", 0)):
            with self.subTest(size=len(broken)), self.assertRaises(ValueError):
                b.stock_dtbs(broken)

    def test_fdt_block_overlap_and_bad_structure(self):
        blob = bytearray(tree().encode())
        struct.pack_into(">I", blob, 12, 40)
        with self.assertRaises(ValueError):
            b.Fdt(blob)
        blob = bytearray(tree().encode())
        struct.pack_into(">I", blob, struct.unpack_from(">I", blob, 8)[0], 2)
        with self.assertRaises(ValueError):
            b.Fdt(blob)

    def test_actual_ram_bank_and_reserved_overlap_including_memreserve(self):
        good = tree()
        good.memory_contract(b.LOAD, b.LOAD + 0x500000)
        for kind in ("fixed", "reusable", "memreserve", "dynamic", "outside"):
            bad = tree()
            if kind == "memreserve":
                bad.reserves = [(b.LOAD + 0x300000, 0x1000)]
            elif kind == "outside":
                bad.nodes["/memory@80000000"]["reg"] = struct.pack(">QQ", 0x80000000, 0x100000)
            else:
                props = {"reg": struct.pack(">QQ", b.LOAD + 0x300000, 0x1000)}
                if kind == "reusable":
                    props["reusable"] = b""
                if kind == "dynamic":
                    props = {"size": struct.pack(">Q", 0x1000)}
                bad.nodes["/reserved-memory/collision"] = props
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                b.Fdt(bad.encode()).memory_contract(b.LOAD, b.LOAD + 0x500000)

    def test_invalid_kernel_contract(self):
        for offset, value in ((8, 0x80000), (16, 0), (16, 64), (16, b.MAX_RAW), (24, 0xb), (24, 2)):
            bad = bytearray(image())
            struct.pack_into("<Q", bad, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                b.kernel_header(bad)
        with self.assertRaises(ValueError):
            b.kernel_header(b"not Image")

    def test_boot_header_padding_hash_and_trailing_data(self):
        good = template_image()
        b.unpack_boot(good)
        for offset in (0, 40, 576, 2000, len(good) - 1):
            bad = bytearray(good)
            bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                b.unpack_boot(bad)
        for bad in (good[:-1], good + bytes(b.PAGE)):
            with self.assertRaises(ValueError):
                b.unpack_boot(bad)

    def test_gzip_corrupt_truncated_and_expansion_limit(self):
        packed = b.gzip_member(b"a" * 1024, 0)
        self.assertEqual(b.gunzip_member(packed + tree().encode())[0], b"a" * 1024)
        corrupted = bytearray(packed)
        corrupted[-8] ^= 1
        for bad in (bytes(corrupted), packed[:-1], b"bad gzip"):
            with self.assertRaises(ValueError):
                b.gunzip_member(bad)
        with patch.object(b, "MAX_RAW", 100), self.assertRaises(ValueError):
            b.gunzip_member(packed)

    def test_arm64_command_line_limit_and_single_line(self):
        self.assertEqual(b.cmdline(b"x" * 2047 + b"\n"), "x" * 2047)
        for invalid in (b"x" * 2048, b"", b"x\ny", b"x\0", b"x\r\n", b"bad\xff", b'rdinit="unterminated'):
            with self.subTest(data=invalid[:20]), self.assertRaises(ValueError):
                b.cmdline(invalid)

    def test_partial_publication_failure_removes_output_directory(self):
        with tempfile.TemporaryDirectory(prefix="lgg8-bootimg-publish-") as folder:
            output = Path(folder) / "new"
            original = Path.write_bytes

            def write(path, data):
                if path.name == "second":
                    raise OSError("simulated full disk")
                return original(path, data)

            with patch.object(Path, "write_bytes", write), self.assertRaisesRegex(OSError, "full disk"):
                b.publish(output, {"first": b"one", "second": b"two"})
            self.assertFalse(output.exists())


@unittest.skipUnless(all(shutil.which(name) for name in ("clang", "ld.lld", "llvm-objcopy")), "LLVM toolchain required for build integration")
class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="lgg8-bootimg-tests-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        stock = template_image()
        (cls.root / "source.img").write_bytes(stock)
        b.prepare_template(argparse.Namespace(from_boot=cls.root / "source.img", sha256=b.sha(stock), output=cls.root / "template"))
        (cls.root / "Image").write_bytes(image())
        (cls.root / "board.dtb").write_bytes(tree().encode())
        (cls.root / "initramfs.cpio").write_bytes(archive())
        (cls.root / "cmdline.txt").write_text("console=tty0 rdinit=/init\n")
        (cls.root / ".config").write_text("CONFIG_DRM_MSM=y\nCONFIG_PSTORE_CONSOLE=y\nCONFIG_PSTORE_RAM=y\n")
        cls.args = argparse.Namespace(kernel=cls.root / "Image", dtb=cls.root / "board.dtb", initramfs=cls.root / "initramfs.cpio",
                                      template=cls.root / "template", cmdline_file=cls.root / "cmdline.txt", output=cls.root / "build",
                                      partition_size=1024 * 1024, config=cls.root / ".config")
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
            cls.manifest = b.build(cls.args)
        cls.blob = (cls.root / "build/boot.img").read_bytes()

    def test_real_llvm_build_and_independent_cli_verification(self):
        result = subprocess.run([sys.executable, "-B", str(Path(b.__file__)), "verify", "--image", str(self.root / "build/boot.img"),
                                 "--manifest", str(self.root / "build/manifest.json")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["stock_dtb_count"], 2)
        self.assertEqual(report["device_acceptance"], "NOT_TESTED")
        self.assertEqual(sorted(p.name for p in (self.root / "build").iterdir()), ["boot.img", "linux.dtb", "manifest.json"])
        # The verifier has no dependency on the input paths or extracted template.
        b.verify_bytes(self.blob, json.loads(json.dumps(self.manifest)))
        provenance = self.manifest["provenance"]
        self.assertEqual(provenance["schema"], "lgg8-build-provenance-v1")
        self.assertEqual(provenance["effective_config"]["sha256"], b.sha((self.root / ".config").read_bytes()))
        self.assertEqual(provenance["config_symbols"]["CONFIG_DRM_MSM"], "y")

    def test_provenance_tracks_commit_dirty_diff_untracked_and_effective_config(self):
        with tempfile.TemporaryDirectory(prefix="lgg8-provenance-tests-") as folder:
            repo = Path(folder)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / ".gitignore").write_text("out/\n")
            seed = repo / "lgg8/configs/lgg8.config"
            seed.parent.mkdir(parents=True)
            seed.write_text("CONFIG_DRM_MSM=y\n")
            source = repo / "drivers/example.c"
            source.parent.mkdir()
            source.write_text("int original;\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=LG G8 Test", "-c",
                            "user.email=test@example.invalid", "commit", "-q", "-m", "base"], check=True)
            source.write_text("int modified;\n")
            new_input = repo / "lgg8/configs/diag.config"
            new_input.write_text("CONFIG_DRM_MSM_DPU_PSTORE_DIAG=y\n")
            effective = repo / "out/kernel/.config"
            effective.parent.mkdir(parents=True)
            effective.write_text("CONFIG_DRM_MSM=y\nCONFIG_DRM_MSM_DPU_PSTORE_DIAG=y\n# CONFIG_PSTORE_FTRACE is not set\n")

            first = b.build_provenance(repo, effective)
            self.assertRegex(first["source_commit"], r"^[0-9a-f]{40}$")
            self.assertTrue(first["source_dirty"])
            self.assertRegex(first["tracked_diff_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(first["untracked_file_count"], 1)
            self.assertEqual(first["effective_config"]["sha256"], b.sha(effective.read_bytes()))
            self.assertEqual(first["config_symbols"]["CONFIG_DRM_MSM_DPU_PSTORE_DIAG"], "y")
            self.assertEqual(first["config_symbols"]["CONFIG_PSTORE_FTRACE"], "n")

            new_input.write_text("CONFIG_DRM_MSM_DPU_PSTORE_DIAG=n\n")
            second = b.build_provenance(repo, effective)
            self.assertNotEqual(first["untracked_tree_sha256"], second["untracked_tree_sha256"])

    def test_kernel_build_receipt_binds_exact_kernel_dtb_and_config(self):
        receipt_path = self.root / "kernel-build-provenance.json"
        receipt = b.record_kernel_build(argparse.Namespace(kernel=self.root / "Image", dtb=self.root / "board.dtb",
                                                            config=self.root / ".config", profile="unit-test", output=receipt_path))
        args = copy.copy(self.args)
        args.output = self.root / "receipt-build"
        args.build_provenance = receipt_path
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
            manifest = b.build(args)
        self.assertEqual(manifest["provenance"]["capture_stage"], "kernel-build")
        self.assertEqual(manifest["provenance"]["profile"], "unit-test")
        self.assertEqual(receipt["components"]["kernel"], b.describe((self.root / "Image").read_bytes()))

        changed_dtb = self.root / "different.dtb"
        changed_tree = tree()
        changed_tree.nodes["/"]["model"] = b"changed\0"
        changed_dtb.write_bytes(changed_tree.encode())
        args.dtb = changed_dtb
        args.output = self.root / "receipt-mismatch"
        with self.assertRaisesRegex(ValueError, "provenance input mismatch: dtb"):
            b.build(args)
        self.assertFalse(args.output.exists())

    def test_determinism_and_source_date_epoch(self):
        args = copy.copy(self.args)
        args.output = self.root / "repeat"
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
            b.build(args)
        self.assertEqual((args.output / "boot.img").read_bytes(), self.blob)
        self.assertEqual((args.output / "manifest.json").read_bytes(), (self.root / "build/manifest.json").read_bytes())
        packed = b.gzip_member(b"payload", 123456)
        self.assertEqual(struct.unpack_from("<I", packed, 4)[0], 123456)

    def test_template_pin_tampering_and_overwrite(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            b.prepare_template(argparse.Namespace(from_boot=self.root / "source.img", sha256="0" * 64, output=self.root / "bad-template"))
        self.assertFalse((self.root / "bad-template").exists())
        with self.assertRaisesRegex(ValueError, "already exists"):
            stock = (self.root / "source.img").read_bytes()
            b.prepare_template(argparse.Namespace(from_boot=self.root / "source.img", sha256=b.sha(stock), output=self.root / "template"))
        with self.assertRaisesRegex(ValueError, "already exists"):
            b.build(self.args)
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            dest = Path(folder)
            for part in (self.root / "template").iterdir():
                shutil.copyfile(part, dest / part.name)
            (dest / "stock-dtbs.bin").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "component hash"):
                b.load_template(dest)

    def test_partition_limit_build_and_verify(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["partition_size"] = len(self.blob) - 1
        with self.assertRaisesRegex(ValueError, "partition"):
            b.verify_bytes(self.blob, manifest)
        args = copy.copy(self.args)
        args.output, args.partition_size = self.root / "too-small", 1
        with self.assertRaisesRegex(ValueError, "partition size"):
            b.build(args)
        self.assertFalse(args.output.exists())

    def test_invalid_inputs_and_compiler_failure_leave_no_output(self):
        fixed = tree()
        fixed.nodes["/reserved-memory/collision"] = {"reg": struct.pack(">QQ", b.LOAD + 0x1000, 0x1000)}
        reserved = tree()
        reserved.reserves = [(b.LOAD + 0x1000, 0x1000)]
        cases = (("kernel", b"bad kernel"), ("initramfs", archive([("init", stat.S_IFREG | 0o755, elf(True))])),
                 ("dtb", fixed.encode()), ("dtb", reserved.encode()))
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            directory = Path(folder)
            for index, (argument, data) in enumerate(cases):
                source = directory / f"input-{index}"
                source.write_bytes(data)
                args = copy.copy(self.args)
                setattr(args, argument, source)
                args.output = directory / f"output-{index}"
                with self.subTest(argument=argument, index=index), self.assertRaises(ValueError):
                    b.build(args)
                self.assertFalse(args.output.exists())
            args = copy.copy(self.args)
            args.output = directory / "compiler-failed"
            with patch.object(b.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "compiler rejected source")), self.assertRaisesRegex(ValueError, "clang failed"):
                b.build(args)
            self.assertFalse(args.output.exists())

    def test_modified_or_truncated_image_and_manifest_hash(self):
        for bad in (self.blob[:-1], self.blob + bytes(4096), self.blob[:5000] + b"bad" + self.blob[5003:]):
            with self.assertRaises(ValueError):
                b.verify_bytes(bad, self.manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest["components"]["kernel"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "kernel"):
            b.verify_bytes(self.blob, manifest)

    def test_bad_gzip_even_with_updated_outer_hash_and_id(self):
        header, packed, ramdisk = b.unpack_boot(self.blob)
        _, stock = b.gunzip_member(packed)
        compressed = bytearray(packed[:-len(stock)])
        compressed[-8] ^= 1
        blob = b.pack_boot(header, compressed + stock, ramdisk)
        manifest = copy.deepcopy(self.manifest)
        manifest["components"]["image"] = b.describe(blob)
        with self.assertRaisesRegex(ValueError, "gzip"):
            b.verify_bytes(blob, manifest)

    def repack_raw(self, raw):
        header, packed, ramdisk = b.unpack_boot(self.blob)
        _, stock = b.gunzip_member(packed)
        compressed = b.gzip_member(raw, 0)
        blob = b.pack_boot(header, compressed + stock, ramdisk)
        manifest = copy.deepcopy(self.manifest)
        for key, value in (("image", blob), ("gzip", compressed), ("raw", raw), ("payload", raw[b.PAGE:])):
            manifest["components"][key] = b.describe(value)
        return blob, manifest

    def test_independent_embedded_padding_and_address_validation(self):
        _, packed, _ = b.unpack_boot(self.blob)
        raw, _ = b.gunzip_member(packed)
        bad = bytearray(raw)
        bad[b.PAGE + len(image()) + 8] = 1
        blob, manifest = self.repack_raw(bad)
        with self.assertRaisesRegex(ValueError, "padding"):
            b.verify_bytes(blob, manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest["initrd_address"] += 16
        with self.assertRaisesRegex(ValueError, "placement"):
            b.verify_bytes(self.blob, manifest)

    def test_reserved_overlap_in_embedded_fdt_with_rehashed_components(self):
        _, packed, _ = b.unpack_boot(self.blob)
        raw, _ = b.gunzip_member(packed)
        raw = bytearray(raw)
        offset = b.PAGE + self.manifest["dtb_address"] - b.LOAD
        dtb_size = self.manifest["components"]["dtb"]["size"]
        dtb = bytearray(raw[offset:offset + dtb_size])
        needle = struct.pack(">QQ", 0xb0000000, 0x100000)
        where = dtb.index(needle)
        dtb[where:where + 16] = struct.pack(">QQ", b.LOAD + 0x1000, 0x1000)
        raw[offset:offset + dtb_size] = dtb
        blob, manifest = self.repack_raw(raw)
        manifest["components"]["dtb"] = b.describe(dtb)
        with self.assertRaisesRegex(ValueError, "overlaps reserved RAM"):
            b.verify_bytes(blob, manifest)

    def test_cpio_structure_checked_independently_of_component_hashes(self):
        _, packed, _ = b.unpack_boot(self.blob)
        raw, _ = b.gunzip_member(packed)
        raw = bytearray(raw)
        offset = b.PAGE + self.manifest["initrd_address"] - b.LOAD
        raw[offset:offset + 6] = b"070707"
        blob, manifest = self.repack_raw(raw)
        size = manifest["components"]["initramfs"]["size"]
        manifest["components"]["initramfs"] = b.describe(raw[offset:offset + size])
        with self.assertRaisesRegex(ValueError, "newc header"):
            b.verify_bytes(blob, manifest)

    def test_stock_acceptance_bytes_preserved_and_parsed(self):
        header, packed, ramdisk = b.unpack_boot(self.blob)
        _, stock = b.gunzip_member(packed)
        self.assertEqual(stock, (self.root / "template/stock-dtbs.bin").read_bytes())
        # A second gzip member or garbage is not an acceptance FDT trailer.
        for tail in (b.gzip_member(b"second", 0), stock + b"trailing"):
            broken = b.pack_boot(header, packed[:-len(stock)] + tail, ramdisk)
            manifest = copy.deepcopy(self.manifest)
            manifest["components"]["image"] = b.describe(broken)
            with self.assertRaises(ValueError):
                b.verify_bytes(broken, manifest)


if __name__ == "__main__":
    unittest.main()
