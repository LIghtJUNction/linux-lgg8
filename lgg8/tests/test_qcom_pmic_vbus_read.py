#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the production PMIC VBUS getters without a device or disk output."""
import ctypes
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "drivers/usb/typec/tcpm/qcom/qcom_pmic_typec_port.c"
TEST = Path(__file__).with_suffix(".c")


def production(source):
    patterns = (r"^#define TYPEC_MISC_STATUS_REG\s+[^\n]+$",
                r"^#define TYPEC_VBUS_DETECT\s+[^\n]+$",
                r"^#define PMIC_TYPEC_VBUS_IRQ\s+[^\n]+$",
                r"^#define PMIC_TYPEC_CC_STATE_IRQ\s+[^\n]+$",
                r"^#define PMIC_TYPEC_ATTACH_DETACH_IRQ\s+[^\n]+$",
                r"^static irqreturn_t pmic_typec_port_isr\(.*?^\}",
                r"^static int qcom_pmic_typec_port_vbus_detect\(.*?^\}",
                r"^static int qcom_pmic_typec_port_get_vbus\(.*?^\}")
    blocks = []
    for pattern in patterns:
        matches = list(re.finditer(pattern, source, re.MULTILINE | re.DOTALL))
        if len(matches) != 1:
            raise RuntimeError(f"Cannot uniquely extract {pattern}")
        match = matches[0]
        line = source.count("\n", 0, match.start()) + 1
        blocks.append(f'#line {line} "{SOURCE}"\n{match.group()}\n')
    return "\n".join(blocks)


def run(sanitized):
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (SOURCE, TEST)}
    marker = "/* ACTUAL_DRIVER_DEFINITIONS */"
    template = TEST.read_text()
    if template.count(marker) != 1:
        raise RuntimeError("Invalid test fixture marker")
    unit = template.replace(marker, production(SOURCE.read_text()))
    compiler = shutil.which("cc")
    if not compiler:
        raise RuntimeError("C compiler not found")
    flags = ["-pipe", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-Wconversion", "-Wsign-conversion", "-Wno-unused-parameter", "-fPIC"]
    if sanitized:
        runtime = subprocess.check_output([compiler, "-print-file-name=libubsan.so"],
                                          text=True).strip()
        ctypes.CDLL(runtime, mode=ctypes.RTLD_GLOBAL)
        flags += ["-fsanitize=undefined", "-fno-sanitize-recover=undefined"]
    obj = os.memfd_create("qcom-vbus-read-object")
    library = os.memfd_create("qcom-vbus-read-test")
    try:
        subprocess.run([compiler, *flags, "-x", "c", "-c", "-", "-o",
                        f"/proc/self/fd/{obj}"], input=unit, text=True,
                       pass_fds=(obj,), check=True, timeout=30)
        subprocess.run(["/usr/bin/ld", "-shared", "-o", f"/proc/self/fd/{library}",
                        f"/proc/self/fd/{obj}"], pass_fds=(obj, library),
                       check=True, timeout=30)
        suite = ctypes.CDLL(f"/proc/self/fd/{library}")
        suite.qcom_pmic_vbus_read_tests.restype = ctypes.c_uint
        count = suite.qcom_pmic_vbus_read_tests()
        if count != 278:
            raise RuntimeError(f"Unexpected case count: {count}")
        if before != {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}:
            raise RuntimeError("Source changed during test")
        print(f"{'UBSan' if sanitized else 'Strict'}: {count} cases passed; "
              f"driver SHA256 {before[SOURCE]}", flush=True)
    finally:
        os.close(library)
        os.close(obj)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in ("strict", "ubsan"):
        run(sys.argv[1] == "ubsan")
    elif len(sys.argv) == 1:
        for mode in ("strict", "ubsan"):
            subprocess.run([sys.executable, "-B", __file__, mode], check=True, timeout=40)
    else:
        raise SystemExit("Usage: test_qcom_pmic_vbus_read.py [strict|ubsan]")
