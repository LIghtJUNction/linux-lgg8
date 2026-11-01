#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the real FG IRQ callback and power-supply uevent in QEMU only.

The IRQ source and battery are fixtures. This does not test the phone, PMIC,
physical IRQ delivery, calibration, or charging safety. The fixture module
also refuses to load unless the machine identifies as QEMU's dummy virt.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
SOURCE = ROOT / "drivers/power/supply/qcom_fg_observer.c"
BUILD = ROOT / "out/lgg8/kernel"
DEFAULT_OUT = ROOT / "out/lgg8/qemu-fg-irq-test"
MARKER = "/* LGG8_FG_PRODUCTION_DEFINITIONS */"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(path):
    checksum = hashlib.sha256()
    for base, dirs, files in os.walk(path, followlinks=False):
        dirs.sort()
        for name in sorted(dirs + files):
            entry = Path(base) / name
            info = entry.lstat()
            checksum.update(str(entry.relative_to(path)).encode() + b"\0")
            checksum.update(str(info.st_mode).encode() + b"\0")
            if stat.S_ISLNK(info.st_mode):
                checksum.update(os.readlink(entry).encode() + b"\0")
            elif stat.S_ISREG(info.st_mode):
                checksum.update(hashlib.sha256(entry.read_bytes()).digest())
    return checksum.hexdigest()


def has_kernel_error(log):
    return re.search(rb"(?im)(?:^|\]\s+)(?:WARNING:|BUG:|Oops:|Kernel panic|"
                     rb"Unable to handle kernel|Internal error:|KASAN:|UBSAN:|"
                     rb"general protection fault|Call trace:|------------\[ cut here \])", log) is not None


def source_definitions(source):
    patterns = (r"^struct qcom_fg_observer \{.*?^\};",
                r"^static irqreturn_t fg_observer_irq\(.*?^\}")
    result = []
    for pattern in patterns:
        matches = list(re.finditer(pattern, source, re.MULTILINE | re.DOTALL))
        if len(matches) != 1:
            raise RuntimeError("Cannot uniquely identify FG callback definition")
        match = matches[0]
        line = source.count("\n", 0, match.start()) + 1
        result.append(f"#line {line} {json.dumps(str(SOURCE))}\n{match.group()}\n")
    return "\n".join(result)


def run(argv, env, timeout=60):
    try:
        return subprocess.run(argv, cwd=ROOT, env=env, check=True, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        sys.stderr.buffer.write(error.stdout or b"")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT,
                        help="parent directory for unique test records")
    output = parser.parse_args().output.resolve()
    for tool in ("make", "clang", "aarch64-linux-gnu-gcc", "qemu-system-aarch64", "git"):
        if not shutil.which(tool):
            raise RuntimeError(f"Missing required local tool: {tool}")
    kernel = BUILD / "arch/arm64/boot/Image"
    receipt = json.loads((BUILD / "build-provenance.json").read_text())
    kernel_bytes = kernel.read_bytes()
    config_bytes = (BUILD / ".config").read_bytes()
    kernel_sha = hashlib.sha256(kernel_bytes).hexdigest()
    config_sha = hashlib.sha256(config_bytes).hexdigest()
    if kernel_sha != receipt["components"]["kernel"]["sha256"]:
        raise RuntimeError("Kernel image differs from build receipt")
    if config_sha != receipt["components"]["effective_config"]["sha256"]:
        raise RuntimeError("Kernel configuration differs from build receipt")
    if receipt["provenance"].get("tracked_diff_sha256") != hashlib.sha256(b"").hexdigest():
        raise RuntimeError("Kernel build used tracked source modifications")
    commit = receipt["provenance"]["source_commit"]
    source_bytes = SOURCE.read_bytes()
    committed_source = subprocess.run(["git", "show", f"{commit}:{SOURCE.relative_to(ROOT)}"],
                                      cwd=ROOT, check=True, stdout=subprocess.PIPE).stdout
    if source_bytes != committed_source:
        raise RuntimeError("FG source differs from kernel build commit")
    original_source = source_bytes.decode()
    original_sha = hashlib.sha256(source_bytes).hexdigest()
    template_bytes = (TESTS / "qemu_fg_irq_fixture.c").read_bytes()
    guest_bytes = (TESTS / "qemu_fg_irq_init.c").read_bytes()
    template = template_bytes.decode()
    if template.count(MARKER) != 1:
        raise RuntimeError("Fixture must contain exactly one source marker")
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    result_dir = output / f"run-{stamp}-{secrets.token_hex(4)}"
    result_dir.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix="qemu-fg-irq-", dir=result_dir) as temp:
        work = Path(temp)
        env = {**os.environ, "TMPDIR": str(work), "TMP": str(work), "TEMP": str(work),
               "SOURCE_DATE_EPOCH": "1792365298", "KBUILD_BUILD_USER": "lgg8",
               "KBUILD_BUILD_HOST": "builder", "KBUILD_BUILD_VERSION": "1"}
        module_dir = work / "module"
        module_dir.mkdir()
        private_build = work / "kernel-build"
        private_build.mkdir()
        inputs = ("include", "arch/arm64/include", "scripts")
        before = {name: tree_digest(BUILD / name) for name in inputs}
        for name in inputs:
            shutil.copytree(BUILD / name, private_build / name, symlinks=True)
        if any(tree_digest(private_build / name) != before[name] or
               tree_digest(BUILD / name) != before[name] for name in inputs):
            raise RuntimeError("Kernel build headers changed while being copied")
        if (BUILD / ".config").read_bytes() != config_bytes:
            raise RuntimeError("Kernel configuration changed while being copied")
        symvers = (BUILD / "Module.symvers").read_bytes()
        (private_build / "Module.symvers").write_bytes(symvers)
        (private_build / ".config").write_bytes(config_bytes)
        (private_build / "source").symlink_to(ROOT, target_is_directory=True)
        (private_build / "Makefile").write_text(f"export KBUILD_OUTPUT = {private_build}\ninclude {ROOT / 'Makefile'}\n")
        private_kernel = work / "Image"
        private_kernel.write_bytes(kernel_bytes)
        (module_dir / "lgg8_fg_irq_fixture.c").write_text(
            template.replace(MARKER, source_definitions(original_source)))
        (module_dir / "Makefile").write_text("obj-m := lgg8_fg_irq_fixture.o\n")
        run(["make", f"O={private_build}", "ARCH=arm64", "LLVM=1", "WERROR=1",
             f"M={module_dir}", "modules"], env, timeout=60)
        if ((private_build / ".config").read_bytes() != config_bytes or
                (private_build / "Module.symvers").read_bytes() != symvers):
            raise RuntimeError("Private kernel build identity changed during module build")
        if any(tree_digest(private_build / name) != before[name]
               for name in ("include", "arch/arm64/include")):
            raise RuntimeError("Private generated headers changed during module build")
        module = module_dir / "lgg8_fg_irq_fixture.ko"
        init = work / "init"
        guest_source = work / "init.c"
        guest_source.write_bytes(guest_bytes)
        run(["aarch64-linux-gnu-gcc", "-static", "-Os", "-Wall", "-Wextra", "-Werror",
             "-Wl,--build-id=none", "-o", str(init), str(guest_source)], env)
        spec = importlib.util.spec_from_file_location("mkinitramfs", ROOT / "lgg8/tools/mkinitramfs.py")
        archive = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(archive)
        records = [(".", stat.S_IFDIR | 0o755, b"", (0, 0)),
                   ("dev", stat.S_IFDIR | 0o755, b"", (0, 0)),
                   ("proc", stat.S_IFDIR | 0o755, b"", (0, 0)),
                   ("sys", stat.S_IFDIR | 0o755, b"", (0, 0)),
                   ("dev/console", stat.S_IFCHR | 0o600, b"", (5, 1)),
                   ("init", stat.S_IFREG | 0o755, init.read_bytes(), (0, 0)),
                   ("fg_irq_fixture.ko", stat.S_IFREG | 0o644, module.read_bytes(), (0, 0)),
                   ("TRAILER!!!", 0, b"", (0, 0))]
        initramfs = work / "initramfs.cpio"
        initramfs.write_bytes(b"".join(archive.entry(name, mode, data, ino=i, rdev=rdev)
                                     for i, (name, mode, data, rdev) in enumerate(records, 1)))
        command = ["qemu-system-aarch64", "-M", "virt,gic-version=3", "-cpu", "cortex-a76",
                   "-smp", "1", "-m", "512M", "-nodefaults", "-display", "none", "-serial", "stdio",
                   "-monitor", "none", "-nic", "none", "-no-reboot", "-kernel", str(private_kernel),
                   "-initrd", str(initramfs), "-append", "console=ttyAMA0 rdinit=/init panic=5 panic_on_warn=1 loglevel=6"]
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=55)
        except subprocess.TimeoutExpired as error:
            (result_dir / "qemu.log").write_bytes(error.stdout or b"")
            raise RuntimeError("QEMU test timed out") from error
        (result_dir / "qemu.log").write_bytes(result.stdout)
        required = (b"LGG8_QEMU_IRQ: negative control passed",
                    b"LGG8_QEMU_IRQ: IRQ -> FG callback -> power_supply uevent passed",
                    b"LGG8_QEMU_IRQ: cleanup passed")
        if (result.returncode or any(marker not in result.stdout for marker in required)
                or b"LGG8_QEMU_IRQ: FAIL" in result.stdout or has_kernel_error(result.stdout)):
            raise RuntimeError(f"QEMU integration failed; see {result_dir / 'qemu.log'}")
        virt_dtb = work / "virt.dtb"
        run(["qemu-system-aarch64", "-machine", f"virt,gic-version=3,dumpdtb={virt_dtb}",
             "-cpu", "cortex-a76", "-smp", "1", "-m", "512M", "-nodefaults",
             "-display", "none", "-monitor", "none", "-nic", "none"], env, timeout=20)
        test_fdt = archive._bootimg.Fdt(virt_dtb.read_bytes())
        if test_fdt.nodes["/"].get("compatible") != b"linux,dummy-virt\0":
            raise RuntimeError("Unexpected QEMU virt root compatible")
        test_fdt.nodes["/"]["compatible"] = b"lgg8-test,not-dummy-virt\0"
        other_dtb = work / "non-virt.dtb"
        other_dtb.write_bytes(test_fdt.encode())
        reject_command = list(command) + ["-dtb", str(other_dtb)]
        reject_command[reject_command.index("-append") + 1] += " lgg8.expect_reject=1"
        try:
            reject = subprocess.run(reject_command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=55)
        except subprocess.TimeoutExpired as error:
            (result_dir / "qemu-reject.log").write_bytes(error.stdout or b"")
            raise RuntimeError("QEMU non-virt rejection test timed out") from error
        (result_dir / "qemu-reject.log").write_bytes(reject.stdout)
        if (reject.returncode or b"LGG8_QEMU_IRQ: non-virt module rejection passed" not in reject.stdout
                or b"LGG8_QEMU_IRQ: FAIL" in reject.stdout or has_kernel_error(reject.stdout)):
            raise RuntimeError(f"QEMU machine guard failed; see {result_dir / 'qemu-reject.log'}")
        report = {"result": "PASS", "source_commit": commit, "source_sha256": original_sha,
                  "kernel_sha256": kernel_sha, "config_sha256": config_sha,
                  "fixture_source_sha256": hashlib.sha256(template_bytes).hexdigest(),
                  "guest_source_sha256": hashlib.sha256(guest_bytes).hexdigest(),
                  "test_module_sha256": digest(module), "initramfs_sha256": digest(initramfs),
                  "physical_phone_tested": False, "physical_irq_delivery_proven": False,
                  "non_virt_module_rejection": "PASS",
                  "record_dir": str(result_dir)}
        (result_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
