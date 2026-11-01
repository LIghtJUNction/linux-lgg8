#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the real SMB5 getter/descriptor with a small offline regmap boundary.

Production definitions are extracted verbatim, not reimplemented. This does not
test Linux regmap/power_supply internals or hardware. All build outputs use memfd;
no device, kernel build, disk temporary directory, or /tmp is used.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "drivers/power/supply/qcom_smb5.c"
TEST = Path(__file__).with_suffix(".c")


def production_definitions(source):
    patterns = [r"^#define SMB5_\w+\s+[^\n]+$",
                r"^struct qcom_smb5 \{.*?^\};",
                r"^static enum power_supply_property qcom_smb5_properties\[\] = \{.*?^\};",
                r"^static int qcom_smb5_get_property\(.*?^\}",
                r"^static const struct power_supply_desc qcom_smb5_desc = \{.*?^\};"]
    blocks = []
    for i, pattern in enumerate(patterns):
        matches = list(re.finditer(pattern, source, re.MULTILINE | re.DOTALL))
        if not matches or (i and len(matches) != 1):
            raise RuntimeError(f"Cannot identify production definition: {pattern}")
        for match in matches:
            line = source.count("\n", 0, match.start()) + 1
            blocks.append(f"#line {line} {json.dumps(str(SOURCE))}\n{match.group()}\n")
    return "\n".join(blocks)


def run(compiler, sanitized):
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (SOURCE, TEST)}
    template = TEST.read_text()
    marker = "/* ACTUAL_DRIVER_DEFINITIONS */"
    assert template.count(marker) == 1
    unit = template.replace(marker, production_definitions(SOURCE.read_text()))
    flags = ["-pipe", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-Wconversion", "-Wsign-conversion", "-fPIC"]
    if sanitized:
        runtime = subprocess.check_output(
            [compiler, "-print-file-name=libubsan.so"], text=True).strip()
        ctypes.CDLL(runtime, mode=ctypes.RTLD_GLOBAL)
        flags += ["-fsanitize=undefined", "-fno-sanitize-recover=undefined"]
    obj = os.memfd_create("smb5-config-object")
    library = os.memfd_create("smb5-config-tests")
    try:
        subprocess.run([compiler, *flags, "-x", "c", "-c", "-", "-o",
                        f"/proc/self/fd/{obj}"], input=unit, text=True,
                       pass_fds=(obj,), check=True, timeout=30)
        output = f"/proc/self/fd/{library}"
        subprocess.run(["/usr/bin/ld", "-shared", "-o", output,
                        f"/proc/self/fd/{obj}"], pass_fds=(obj, library),
                       check=True, timeout=30)
        suite = ctypes.CDLL(output)
        suite.smb5_config_properties_tests.restype = ctypes.c_uint
        count = suite.smb5_config_properties_tests()
        assert count > 0
        assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
        print(f"{'UBSan' if sanitized else 'Strict'}: {count} actual-getter cases passed; "
              f"driver SHA256 {before[SOURCE]}", flush=True)
    finally:
        os.close(library)
        os.close(obj)


class Smb5ConfigPropertiesTest(unittest.TestCase):
    def test_production_getter(self):
        subprocess.run([sys.executable, "-B", str(Path(__file__).resolve())],
                       check=True, timeout=90)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--worker", choices=("strict", "ubsan"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit(f"Compiler not found: {args.cc}")
    if args.worker:
        run(compiler, args.worker == "ubsan")
    else:
        for mode in ("strict", "ubsan"):
            subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                            "--cc", compiler, "--worker", mode], check=True, timeout=40)
