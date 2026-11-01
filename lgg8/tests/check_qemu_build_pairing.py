#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only pairing tripwire; PASS does not prove a kernel/module ABI.

Checks Image/config receipt hashes, embedded IKCONFIG, generated autoconf,
and the ELF export tables against Image bytes and Module.symvers. No builds,
filesystem writes, temporary files, module loads or phone operations.
Run with python3 -B; a failed check exits 1. --self-test needs no build.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import unittest


def config_defines(config):
    result = {}
    for line in config.splitlines():
        if not line.startswith("CONFIG_"):
            continue
        key, value = line.split("=", 1)
        if value == "m":
            key, value = key + "_MODULE", "1"
        elif value == "y":
            value = "1"
        result[key] = value
    return result


def embedded_config(image):
    start = image.index(b"IKCFG_ST") + 8
    end = image.index(b"IKCFG_ED", start)
    return gzip.decompress(image[start:end])


def elf_export_sections(elf, image):
    """Bind ELF export metadata to the raw Image before using nm names."""
    if elf[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Expected ELF64 little-endian vmlinux")
    phoff, = struct.unpack_from("<Q", elf, 32)
    shoff, = struct.unpack_from("<Q", elf, 40)
    phsize, phnum, shsize, shnum, names_index = struct.unpack_from("<HHHHH", elf, 54)
    if phsize != 56 or shsize != 64 or not shnum or names_index >= shnum:
        raise ValueError("Unsupported ELF table layout")
    loads = [struct.unpack_from("<IIQQQQQQ", elf, phoff + i * phsize)
             for i in range(phnum)]
    base = min(p[4] for p in loads if p[0] == 1 and p[5])
    sections = [struct.unpack_from("<IIQQQQIIQQ", elf, shoff + i * shsize)
                for i in range(shnum)]
    names = sections[names_index]
    strings = elf[names[4]:names[4] + names[5]]
    checked = []
    for s in sections:
        name = strings[s[0]:strings.index(b"\0", s[0])].decode()
        if name not in ("__ksymtab", "__ksymtab_strings", "__kflagstab"):
            continue
        offset, size = s[3] - base, s[5]
        if (s[1] != 1 or not s[2] & 2 or not size or offset < 0
                or offset + size > len(image) or s[4] + size > len(elf)
                or elf[s[4]:s[4] + size] != image[offset:offset + size]):
            raise ValueError(f"ELF export section does not match Image: {name}")
        checked.append(name)
    if set(checked) != {"__ksymtab", "__ksymtab_strings", "__kflagstab"}:
        raise ValueError("Missing ELF export sections")
    return checked


def audit(build, receipt_path):
    receipt = json.loads(receipt_path.read_text())
    image = (build / "arch/arm64/boot/Image").read_bytes()
    config = (build / ".config").read_bytes()
    elf = (build / "vmlinux").read_bytes()
    sha = lambda data: hashlib.sha256(data).hexdigest()
    sections = elf_export_sections(elf, image)
    nm = subprocess.run(["llvm-nm", "--defined-only", "--format=posix",
                         str(build / "vmlinux")], check=True, capture_output=True,
                        text=True).stdout
    binary_exports = {line.split()[0][len("__ksymtab_"):]
                      for line in nm.splitlines() if line.startswith("__ksymtab_")}
    symvers = (build / "Module.symvers").read_bytes()
    claimed_exports = {fields[1] for line in symvers.decode().splitlines()
                       if len(fields := line.split()) >= 4 and fields[2] == "vmlinux"}
    generated = dict(re.findall(r"^#define (CONFIG_\w+) (.+)$",
                               (build / "include/generated/autoconf.h").read_text(), re.M))
    checks = {
        "image_matches_receipt": sha(image) == receipt["components"]["kernel"]["sha256"],
        "config_matches_receipt": sha(config) == receipt["components"]["effective_config"]["sha256"],
        "image_embedded_config_matches": embedded_config(image) == config,
        "autoconf_matches_config": config_defines(config.decode()) == generated,
        "symvers_export_names_match_image": binary_exports == claimed_exports,
    }
    return {
        "status": "PAIRING_TRIPWIRES_PASS" if all(checks.values()) else "PAIRING_REJECTED",
        "abi_proven": False,
        "checks": checks,
        "elf_export_sections_bound_to_image": sections,
        "image_sha256": sha(image), "vmlinux_sha256": sha(elf),
        "symvers_sha256": sha(symvers), "config_sha256": sha(config),
        "image_export_count": len(binary_exports),
        "symvers_vmlinux_export_count": len(claimed_exports),
        "only_in_symvers": sorted(claimed_exports - binary_exports),
        "only_in_image": sorted(binary_exports - claimed_exports),
        "generated_utsrelease": (build / "include/generated/utsrelease.h").read_text().strip(),
        "limits": "Checks names, not type/layout compatibility, namespace or license flags; "
                  "does not prove all generated headers or source provenance. No runtime test.",
    }


class Tests(unittest.TestCase):
    def test_config(self):
        self.assertEqual(config_defines('CONFIG_A=y\nCONFIG_B=m\n# CONFIG_C is not set\n'
                                        'CONFIG_D="-test"\nCONFIG_E=0x12\n'),
                         {"CONFIG_A": "1", "CONFIG_B_MODULE": "1",
                          "CONFIG_D": '"-test"', "CONFIG_E": "0x12"})

    def test_ikconfig(self):
        self.assertEqual(embedded_config(b"prefixIKCFG_ST" + gzip.compress(b"CONFIG_A=y\n")
                                         + b"IKCFG_EDsuffix"), b"CONFIG_A=y\n")
        with self.assertRaises(ValueError):
            embedded_config(b"no embedded config")
        with self.assertRaises((OSError, EOFError)):
            embedded_config(b"IKCFG_STbadIKCFG_ED")

    def test_export_section_binding_and_negative_controls(self):
        elf = bytearray(640)
        elf[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<Q", elf, 32, 64)
        struct.pack_into("<Q", elf, 40, 120)
        struct.pack_into("<HHHHH", elf, 54, 56, 1, 64, 5, 1)
        struct.pack_into("<IIQQQQQQ", elf, 64, 1, 4, 600, 0x1000, 0x1000, 9, 9, 1)
        names = b"\0.shstrtab\0__ksymtab\0__ksymtab_strings\0__kflagstab\0"
        elf[450:450 + len(names)] = names
        struct.pack_into("<IIQQQQIIQQ", elf, 184, 1, 3, 0, 0, 450, len(names), 0, 0, 1, 0)
        for index, name in enumerate((b"__ksymtab", b"__ksymtab_strings", b"__kflagstab")):
            struct.pack_into("<IIQQQQIIQQ", elf, 120 + (index + 2) * 64,
                             names.index(name + b"\0"), 1, 2, 0x1000 + index * 3,
                             600 + index * 3, 3, 0, 0, 1, 0)
        elf[600:609] = b"abcdefghi"
        self.assertEqual(len(elf_export_sections(elf, b"abcdefghi")), 3)
        for image in (b"xbcdefghi", b"abc", b""):
            with self.subTest(image=image), self.assertRaises(ValueError):
                elf_export_sections(elf, image)
        # Removing the final section must not turn a partial match into PASS.
        struct.pack_into("<H", elf, 60, 4)
        with self.assertRaises(ValueError):
            elf_export_sections(elf, b"abcdefghi")

    def test_reject_non_elf(self):
        with self.assertRaises(ValueError):
            elf_export_sections(b"not an ELF", b"")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--build", type=Path, default=root / "out/lgg8/kernel")
    parser.add_argument("--receipt", type=Path,
                        default=root / "out/lgg8-c232-fg-irq-20261101/build-provenance.json")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        unittest.main(argv=[__file__])
    else:
        report = audit(args.build, args.receipt)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if all(report["checks"].values()) else 1)
