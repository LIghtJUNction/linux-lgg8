#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the complete policy and C behavioral suite in anonymous memory."""

import argparse
import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "drivers/power/supply/qcom_smb5_thermal_policy.c"
HEADER = POLICY.with_suffix(".h")
TEST = Path(__file__).with_suffix(".c")


class ThermalPolicyTest(unittest.TestCase):
    def test_actual_policy(self):
        subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                        "--strict-only"], check=True, timeout=90)


def run(compiler, sanitized):
    descriptors = []
    try:
        flags = ["-pipe", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wconversion",
                 "-Wsign-conversion", "-pedantic", "-fPIC", "-O2",
                 "-I", str(HEADER.parent)]
        if sanitized:
            # Loading the runtime first resolves the shared object's UBSan hooks.
            runtime = subprocess.check_output(
                [compiler, "-print-file-name=libubsan.so"], text=True).strip()
            ctypes.CDLL(runtime, mode=ctypes.RTLD_GLOBAL)
            flags += ["-fsanitize=undefined", "-fno-sanitize-recover=undefined"]
        objects = []
        for source in (POLICY, TEST):
            fd = os.memfd_create("smb5-thermal-object")
            descriptors.append(fd)
            obj = f"/proc/self/fd/{fd}"
            # -c + -pipe avoids compiler temporary objects/assembly on disk.
            subprocess.run([compiler, *flags, "-c", str(source), "-o", obj],
                           pass_fds=(fd,), check=True, timeout=30)
            objects.append(obj)
        library = os.memfd_create("smb5-thermal-tests")
        descriptors.append(library)
        output = f"/proc/self/fd/{library}"
        subprocess.run(["/usr/bin/ld", "-shared", "-o", output, *objects],
                       pass_fds=tuple(descriptors), check=True, timeout=30)
        suite = ctypes.CDLL(output)
        suite.smb5_thermal_policy_tests.restype = ctypes.c_int
        assert suite.smb5_thermal_policy_tests() == 0
    finally:
        for fd in descriptors:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="cc", help="C compiler executable")
    parser.add_argument("--strict-only", action="store_true",
                        help="skip the second, undefined-behavior-sanitized run")
    parser.add_argument("--worker", choices=("strict", "ubsan"),
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit(f"Compiler not found: {args.cc}")
    if args.worker:
        run(compiler, args.worker == "ubsan")
        return
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (POLICY, HEADER, TEST)}
    for sanitized in (False, True) if not args.strict_only else (False,):
        print("UBSan" if sanitized else "Strict C11", flush=True)
        # Separate loaders prevent dlopen from caching a reused /proc/self/fd/N
        # pathname and accidentally executing the previous, uninstrumented suite.
        subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                        "--cc", compiler, "--worker", "ubsan" if sanitized else "strict"],
                       check=True, timeout=90)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    print("Source/header unchanged; all compiler outputs used anonymous memfd.")


if __name__ == "__main__":
    main()
