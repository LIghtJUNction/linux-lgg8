#!/usr/bin/env python3
"""Compile unmodified kernel .c via offline API substitutes, run, then clean."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    tests = Path(__file__).resolve().parent
    root = tests.parents[1]
    sources = [root / "drivers/power/supply/qcom_fg_dma_experimental.c",
               root / "drivers/power/supply/qcom_fg_dma_experimental.h"]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    build = Path(tempfile.mkdtemp(prefix="test_fg_dma_kernel_build_", dir=tests))
    env = dict(os.environ, TMPDIR=str(build), TMP=str(build), TEMP=str(build),
               ASAN_OPTIONS="halt_on_error=1:detect_leaks=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    try:
        linux = build / "linux"
        linux.mkdir()
        for name in ("bitops", "delay", "err", "errno", "kernel", "regmap",
                     "string", "ktime", "mutex", "types"):
            (linux / (name + ".h")).write_text(
                '#include_next <linux/errno.h>\n' if name == "errno" else
                '#include "test_fg_dma_kernel_shim.h"\n')
        flags = ["cc", "-pipe", "-std=c11", "-pthread", "-Wall", "-Wextra",
                 "-Werror", "-Wno-unused-parameter", "-DTEST_FG_DMA_KERNEL_OFFLINE=1",
                 "-I" + str(build), "-I" + str(tests)]
        print(subprocess.check_output(["cc", "--version"], text=True).splitlines()[0], flush=True)
        for label, extra in (
            ("strict", ["-O2"]),
            ("asan-ubsan", ["-O1", "-g", "-fsanitize=address,undefined",
                            "-fno-omit-frame-pointer"]),
        ):
            binary = build / label
            print(label, flush=True)
            subprocess.run(flags + extra + [str(tests / "test_fg_dma_kernel_source.c"),
                                            "-o", str(binary)], env=env, check=True)
            subprocess.run([str(binary)], env=env, check=True, timeout=30)
    finally:
        shutil.rmtree(build)
        print("Task-created build directory removed.", flush=True)
        for p, digest in before.items():
            if hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"Source changed during test: {p}")
        print("Actual source/header SHA-256 unchanged:", flush=True)
        for p, digest in before.items():
            print(p.relative_to(root), digest, flush=True)


if __name__ == "__main__":
    main()
