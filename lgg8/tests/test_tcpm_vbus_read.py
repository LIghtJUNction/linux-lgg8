#!/usr/bin/env python3
"""Run the actual TCPM VBUS event handler against offline API boundaries.

The whole event handler is copied verbatim, not reimplemented. Mutexes,
CC/PD handlers and TCPC callbacks are fixtures, not the kernel or PMIC.
Builds use anonymous memfds, never /tmp. No device commands are implemented.
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
SOURCE = ROOT / "drivers/usb/typec/tcpm/tcpm.c"
FIXTURE = Path(__file__).with_suffix(".c")


def definitions(source):
    def function(name):
        match = re.search(r"^static (?:int|void|bool) " + re.escape(name)
                          + r"\([^;{}]*\)\n\{", source, re.MULTILINE)
        if not match:
            raise RuntimeError(f"Missing production function {name}")
        end = source.index("\n}\n", match.start()) + 3
        line = source.count("\n", 0, match.start()) + 1
        return f"#line {line} {json.dumps(str(SOURCE))}\n" + source[match.start():end]

    states = source[source.index("#define FOREACH_STATE(S)"):
                    source.index("#define GENERATE_ENUM")]
    states += "\n#define GENERATE_ENUM(e) e\n"
    states += "enum tcpm_state { FOREACH_STATE(GENERATE_ENUM) };\n"
    constants = "\n".join(re.findall(
        r"^#define TCPM_(?:\w+_EVENT|"
        r"SOURCING_VBUS|PORT_CLEAN|PORT_ERROR)\s+[^\n]+", source, re.MULTILINE))
    return states, constants, function("tcpm_pd_event_handler")


def run(compiler, sanitize):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (SOURCE, FIXTURE)}
    states, constants, functions = definitions(SOURCE.read_text())
    fixture = FIXTURE.read_text()
    unit = fixture.replace("/* STATES */", states + constants).replace(
        "/* PRODUCTION */", functions)
    flags = ["-pipe", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-Wno-unused-function", "-fPIC"]
    if sanitize:
        runtime = subprocess.check_output([compiler, "-print-file-name=libubsan.so"],
                                          text=True).strip()
        ctypes.CDLL(runtime, mode=ctypes.RTLD_GLOBAL)
        flags += ["-fsanitize=undefined", "-fno-sanitize-recover=undefined"]
    obj = os.memfd_create("tcpm-vbus-object")
    lib = os.memfd_create("tcpm-vbus-tests")
    try:
        subprocess.run([compiler, *flags, "-x", "c", "-c", "-", "-o",
                        f"/proc/self/fd/{obj}"], input=unit, text=True,
                       pass_fds=(obj,), check=True, timeout=40)
        subprocess.run(["/usr/bin/ld", "-shared", "-o", f"/proc/self/fd/{lib}",
                        f"/proc/self/fd/{obj}"], pass_fds=(obj, lib),
                       check=True, timeout=20)
        suite = ctypes.CDLL(f"/proc/self/fd/{lib}")
        suite.tcpm_vbus_read_tests.restype = ctypes.c_uint
        count = suite.tcpm_vbus_read_tests()
        assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
        print(f"{'UBSan' if sanitize else 'Strict'}: {count} cases; "
              f"tcpm SHA256 {before[SOURCE]}", flush=True)
    finally:
        os.close(obj)
        os.close(lib)


class VbusReadTest(unittest.TestCase):
    def test_actual_functions(self):
        subprocess.run([sys.executable, "-B", str(Path(__file__).resolve())],
                       check=True, timeout=150)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--worker", choices=("strict", "ubsan"))
    args = parser.parse_args()
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit(f"Compiler not found: {args.cc}")
    if args.worker:
        run(compiler, args.worker == "ubsan")
    else:
        for worker in ("strict", "ubsan"):
            subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                            "--cc", compiler, "--worker", worker],
                           check=True, timeout=65)
