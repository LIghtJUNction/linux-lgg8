#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Test five real SPMI irqchip definitions, using anonymous memfd build outputs.

Only transport/MMIO and kernel types are substituted. No device access, /tmp,
kernel build, source edits or disk compiler outputs. This is not hardware ACK,
interrupt timing, arbitration, teardown, or IRQ-storm validation.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "drivers/spmi/spmi-pmic-arb.c"
TEST = Path(__file__).with_suffix(".c")


def production_definitions(source):
    patterns = [(r"^#define SPMI_PIC_ACC_ENABLE_BIT[^\n]+$", 1),
                (r"^#define HWIRQ_(?:SID|PID|IRQID|APID)_MASK[^\n]+$", 4),
                (r"^#define hwirq_to_(?:sid|per|irq|apid)\(hwirq\)[^\n]+$", 4),
                (r"^enum qpnpint_regs \{.*?^\};", 1)]
    for name in ("qpnpint_spmi_write", "qpnpint_spmi_read", "qpnpint_irq_unmask",
                 "qpnpint_get_irqchip_state", "qpnpint_irq_domain_activate"):
        patterns.append((rf"^static (?:int|void) {name}\(.*?^\}}", 1))
    blocks = []
    for pattern, count in patterns:
        matches = list(re.finditer(pattern, source, re.MULTILINE | re.DOTALL))
        if len(matches) != count:
            raise RuntimeError(f"Expected {count} production definitions: {pattern}")
        for match in matches:
            line = source.count("\n", 0, match.start()) + 1
            blocks.append(f"#line {line} {json.dumps(str(SOURCE))}\n{match.group()}\n")
    return "\n".join(blocks)


def run(compiler, sanitized, expected_sha):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    source_bytes = SOURCE.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    if digest != expected_sha:
        raise RuntimeError("Production source changed; rerun against a stable snapshot")
    test_bytes = TEST.read_bytes()
    template = test_bytes.decode()
    marker = "/* ACTUAL_IRQCHIP_DEFINITIONS */"
    assert template.count(marker) == 1
    unit = template.replace(marker, production_definitions(source_bytes.decode()))
    flags = ["-pipe", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-Wno-unused-parameter", "-fPIC"]
    if sanitized:
        runtime = subprocess.check_output(
            [compiler, "-print-file-name=libubsan.so"], text=True).strip()
        ctypes.CDLL(runtime, mode=ctypes.RTLD_GLOBAL)
        flags += ["-fsanitize=undefined", "-fno-sanitize-recover=undefined"]
    obj = os.memfd_create("spmi-irq-object")
    library = os.memfd_create("spmi-irq-tests")
    try:
        subprocess.run([compiler, *flags, "-x", "c", "-c", "-", "-o",
                        f"/proc/self/fd/{obj}"], input=unit, text=True,
                       pass_fds=(obj,), check=True, timeout=30)
        output = f"/proc/self/fd/{library}"
        subprocess.run(["/usr/bin/ld", "-shared", "-o", output,
                        f"/proc/self/fd/{obj}"], pass_fds=(obj, library), check=True, timeout=30)
        suite = ctypes.CDLL(output)
        suite.spmi_irq_errors_tests.restype = ctypes.c_uint
        count = suite.spmi_irq_errors_tests()
        assert count > 0
        assert SOURCE.read_bytes() == source_bytes and TEST.read_bytes() == test_bytes
        print(f"{'UBSan' if sanitized else 'Strict'}: {count} actual irqchip cases passed; "
              f"source SHA256 {digest}", flush=True)
    finally:
        os.close(library)
        os.close(obj)


class SpmiIrqErrorsTest(unittest.TestCase):
    def test_actual_irqchip(self):
        subprocess.run([sys.executable, "-B", str(Path(__file__).resolve())],
                       check=True, timeout=90)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--worker", choices=("strict", "ubsan"), help=argparse.SUPPRESS)
    parser.add_argument("--expected-sha", help=argparse.SUPPRESS)
    args = parser.parse_args()
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit(f"Compiler not found: {args.cc}")
    digest = args.expected_sha or hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if args.worker:
        run(compiler, args.worker == "ubsan", digest)
    else:
        for mode in ("strict", "ubsan"):
            subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                            "--cc", compiler, "--worker", mode, "--expected-sha", digest],
                           check=True, timeout=40)
