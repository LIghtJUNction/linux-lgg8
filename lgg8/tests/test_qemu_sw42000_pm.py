#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Diskless QEMU virt test: real SW42000 + device PM core, simulated hardware.

Default/--check is READ-ONLY: validate source generation, pairing and critical
exports; no compiler, QEMU, recursive scan or build-directory creation.
--run explicitly enables a small external-module build and three QEMU boots.
It first refuses high I/O pressure, then performs the space-first df/dust/
prefixlens checks before copying anything. There is NO full kernel build.
Build intermediates live in a unique directory beneath this draft directory
and are removed on exit. A separate unique run directory retains complete
command/guest stdout, result or failure JSON. /tmp is never used.

The kernel Image and generated headers must match a fresh private-build receipt.
This is a dedicated QEMU configuration, NOT a phone configuration. The kernel's
built-in SW42000 is NOT the test driver: the complete current driver is copied
into an isolated module, removing only module_i2c_driver() registration.
Only its registration name/ID/OF match are isolated; skip_pm is a deliberate
negative control. No production PM function body is translated or replaced.

Coverage: device prepare/suspend/resume/complete, failure recovery, threaded
software IRQ overlap/suppression/delivery, input state, and module teardown.
NOT covered: exact IRQ nesting depth, late/noirq, freezer/platform/s2idle entry,
electrical safety, retained phone rails/clocks, physical IRQ or real touch IC.
"""

import argparse
import ast
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

sys.dont_write_bytecode = True
DRAFT = Path(__file__).resolve().parent
ROOT = next(p for p in DRAFT.parents if (p / "lgg8/tests/test_qemu_fg_irq.py").is_file())
BUILD = ROOT / "out/lgg8-qemu-pm-paired-20261101/kernel"
RECEIPT = BUILD.parent / "paired-provenance.json"
RESULTS = BUILD.parent / "runs"
SOURCE = ROOT / "drivers/input/touchscreen/lge_sw42000.c"
HEADER = SOURCE.with_name("lge_sw42000_protocol.h")
FIXTURE = DRAFT / "qemu_sw42000_pm_fixture.c"
GUEST = DRAFT / "qemu_sw42000_pm_init.c"
MARKER = "/* LGG8_SW42000_COMPLETE_DRIVER */"
REGISTRATION = "module_i2c_driver(sw42000_driver);"
COPY_INPUTS = ("include", "arch/arm64/include", "scripts")
RUN_RECORD = None
COMMAND_NUMBER = 0
CRITICAL_EXPORTS = """
irq_get_irq_data handle_simple_irq irq_set_chip_and_handler_name irq_modify_status
__irq_alloc_descs irq_free_descs generic_handle_irq_safe synchronize_irq
lock_system_sleep unlock_system_sleep dpm_suspend_start dpm_resume_end
gpiochip_add_data_with_key gpiochip_remove gpiod_add_lookup_table gpiod_remove_lookup_table
i2c_add_adapter i2c_del_adapter i2c_register_driver i2c_del_driver
i2c_new_client_device i2c_unregister_device __root_device_register root_device_unregister
kthread_create_on_node kthread_should_stop kthread_stop complete complete_all
wait_for_completion_timeout sysfs_create_group sysfs_remove_group kobject_create_and_add
kobject_put kernel_kobj
""".split()


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_helper(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exports():
    return {fields[1]: fields for line in (BUILD / "Module.symvers").read_text().splitlines()
            if len(fields := line.split()) >= 4}


def definitions():
    source = SOURCE.read_text()
    template = FIXTURE.read_text()
    if source.count(REGISTRATION) != 1 or template.count(MARKER) != 1:
        raise RuntimeError("Source insertion/registration marker is not unique")
    if "DEFINE_SIMPLE_DEV_PM_OPS(sw42000_pm_ops, sw42000_suspend, sw42000_resume)" not in source:
        raise RuntimeError("Current driver no longer has the expected production PM table")
    # Verbatim whole driver, NOT function extraction or a reconstructed callback.
    copied = source.replace(REGISTRATION, "/* Registration owned by QEMU fixture. */")
    inserted = f'#line 1 {json.dumps(str(SOURCE))}\n{copied}\n#line 1 "qemu-fixture"\n'
    return template.replace(MARKER, inserted)


def check_static():
    watched = [SOURCE, HEADER, FIXTURE, GUEST, Path(__file__).resolve()]
    before = {path: digest(path) for path in watched}
    ast.parse(Path(__file__).read_text())
    fixture = FIXTURE.read_text()
    # These are source-shape tripwires, not proof that the runtime path works.
    cycle = re.search(r"^static int pm_cycle\(.*?^\}", fixture, re.M | re.S)
    if not cycle:
        raise RuntimeError("Cannot identify pm_cycle")
    body = cycle.group()
    if body.count("dpm_suspend_start(PMSG_SUSPEND)") != 1 or body.count("dpm_resume_end(PMSG_RESUME)") != 1:
        raise RuntimeError("PM cycle must contain exactly one start and end")
    between = body.split("ret = dpm_suspend_start(PMSG_SUSPEND);", 1)[1].split(
        "dpm_resume_end(PMSG_RESUME);", 1)[0]
    between = re.sub(r"/\*.*?\*/", "", between, flags=re.S)
    if re.search(r"\b(return|goto|break|continue)\b", between):
        raise RuntimeError("A PM unwind may be bypassed")
    if re.search(r"\birq_to_desc\s*\(", fixture):
        raise RuntimeError("Unexported IRQ descriptor access")
    if re.search(r"\bsw42000_(suspend|resume)\s*\(", fixture):
        raise RuntimeError("Fixture must not directly call production PM callbacks")
    table = exports()
    missing = [name for name in CRITICAL_EXPORTS
               if name not in table or table[name][2] != "vmlinux"]
    if missing:
        raise RuntimeError(f"Critical exports absent from built-in kernel: {missing}")
    config = (BUILD / ".config").read_text()
    for option in ("CONFIG_MODULES", "CONFIG_MODULE_UNLOAD", "CONFIG_SUSPEND",
                   "CONFIG_PM_SLEEP", "CONFIG_I2C", "CONFIG_GPIOLIB", "CONFIG_INPUT"):
        if f"{option}=y\n" not in config:
            raise RuntimeError(f"Missing built-in prerequisite: {option}")
    generated = definitions()
    if before != {path: digest(path) for path in watched}:
        raise RuntimeError("Driver/header/draft changed during static inspection; retry later")
    return {"status": "STATIC_CHECKS_ONLY", "runtime_validated": False,
            "driver_sha256": before[SOURCE], "protocol_sha256": before[HEADER],
            "fixture_sha256": before[FIXTURE], "guest_sha256": before[GUEST],
            "runner_sha256": before[Path(__file__).resolve()],
            "generated_translation_unit_sha256": hashlib.sha256(generated.encode()).hexdigest(),
            "critical_vmlinux_exports_checked": len(CRITICAL_EXPORTS),
            "full_undefined_symbol_audit": "PENDING_MODULE_BUILD",
            "exact_irq_depth_proven": False}, generated


def io_pressure():
    lines = Path("/proc/pressure/io").read_text().splitlines()
    return {line.split()[0]: {k: float(v) for item in line.split()[1:]
                             for k, v in [item.split("=")] if k.startswith("avg")}
            for line in lines}


def pressure_gate():
    pressure = io_pressure()
    if any(pressure[kind][period] >= 10 for kind in ("some", "full")
           for period in ("avg10", "avg60")):
        raise RuntimeError(f"DEFERRED_HIGH_IO (no build/QEMU started): {pressure}")
    return pressure


def run(argv, env=None, timeout=60, cwd=ROOT):
    global COMMAND_NUMBER
    number = COMMAND_NUMBER
    COMMAND_NUMBER += 1
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        if RUN_RECORD:
            (RUN_RECORD / f"command-{number:02d}.stdout").write_bytes(error.stdout or b"")
            (RUN_RECORD / f"command-{number:02d}.json").write_text(json.dumps(
                {"argv": argv, "cwd": str(cwd), "timeout": timeout}, indent=2) + "\n")
        raise
    if RUN_RECORD:
        (RUN_RECORD / f"command-{number:02d}.stdout").write_bytes(p.stdout)
        (RUN_RECORD / f"command-{number:02d}.json").write_text(json.dumps(
            {"argv": argv, "cwd": str(cwd), "returncode": p.returncode}, indent=2) + "\n")
    if p.returncode:
        sys.stderr.buffer.write(p.stdout)
        raise RuntimeError(f"Command failed ({p.returncode}): {argv}")
    return p.stdout


def space_first():
    # Run only AFTER the pressure gate. Narrow targets, no whole-out/repo scan.
    for tool in ("df", "dust", "prefixlens", "ionice"):
        if not shutil.which(tool):
            raise RuntimeError(f"Space-first tool missing: {tool}; no build started")
    readouts = []
    commands = [["df", "-h", str(DRAFT)],
                ["ionice", "-c", "3", "dust", "-d", "0",
                 *[str(BUILD / n) for n in COPY_INPUTS]],
                ["prefixlens", str(BUILD.parent), "--summary"]]
    for cmd in commands:
        readouts.append(run(cmd, timeout=15).decode(errors="replace"))
    if shutil.disk_usage(DRAFT).free < 1024 ** 3:
        raise RuntimeError("Need 1 GiB free for the bounded private module workspace")
    return readouts


def verify_undefined(module, env):
    # Complete symbol audit after modpost, including compiler-generated imports.
    table = exports()
    raw = run(["llvm-nm", "--undefined-only", "--format=posix", str(module)], env).decode()
    names = [line.split()[0] for line in raw.splitlines() if line.split()]
    missing = [name for name in names if name not in table or table[name][2] != "vmlinux"]
    if missing:
        raise RuntimeError(f"Module imports non-built-in/unexported symbols: {missing}")
    return sorted(names)


def execute(report, generated):
    global RUN_RECORD
    pressure = pressure_gate()  # Before any recursive walk, mkdir or compiler.
    for p, key in ((SOURCE, "driver_sha256"), (HEADER, "protocol_sha256"),
                   (FIXTURE, "fixture_sha256"), (GUEST, "guest_sha256"),
                   (Path(__file__).resolve(), "runner_sha256")):
        if digest(p) != report[key]:
            raise RuntimeError(f"Input changed since source generation: {p}")
    if generated != definitions():
        raise RuntimeError("Generated driver identity changed before execution")
    available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    if available < 1024 * 1024:
        raise RuntimeError("DEFERRED_LOW_MEMORY: need 1 GiB MemAvailable")
    for tool in ("make", "clang", "llvm-nm", "aarch64-linux-gnu-gcc", "qemu-system-aarch64"):
        if not shutil.which(tool):
            raise RuntimeError(f"Missing local tool: {tool}")
    space = space_first()
    pressure_gate()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    RUN_RECORD = RESULTS / f"run-{stamp}-{secrets.token_hex(4)}"
    RUN_RECORD.mkdir(mode=0o700, parents=True)
    report["record_directory"] = str(RUN_RECORD)
    (RUN_RECORD / "preflight.json").write_text(json.dumps(
        {**report, "space_first_readouts": space}, indent=2) + "\n")
    print("Run records:", RUN_RECORD, flush=True)
    fg = load_helper(ROOT / "lgg8/tests/test_qemu_fg_irq.py", "sw42000_fg_helpers")
    archive = load_helper(ROOT / "lgg8/tools/mkinitramfs.py", "sw42000_archive")
    receipt = json.loads(RECEIPT.read_text())
    if receipt.get("schema") != "lgg8-qemu-paired-v1":
        raise RuntimeError("A fresh paired-build receipt is required; old C232 is not accepted")
    if any(fg.tree_digest(BUILD / n) != receipt["generated_tree_sha256"][n]
           for n in COPY_INPUTS):
        raise RuntimeError("Generated inputs differ from the paired-build receipt")
    if digest(BUILD / "Module.symvers") != receipt["symvers_sha256"]:
        raise RuntimeError("Export manifest differs from the paired-build receipt")
    image = BUILD / "arch/arm64/boot/Image"
    config, symvers = (BUILD / ".config").read_bytes(), (BUILD / "Module.symvers").read_bytes()
    if digest(image) != receipt["components"]["kernel"]["sha256"] or hashlib.sha256(
            config).hexdigest() != receipt["components"]["effective_config"]["sha256"]:
        raise RuntimeError("Private Image/config no longer matches paired-build receipt")
    if receipt["provenance"]["tracked_diff_sha256"] != hashlib.sha256(b"").hexdigest():
        raise RuntimeError("Paired receipt does not identify an unmodified tracked baseline")
    # The current driver is intentionally newer; core/API headers must not drift.
    incompatible = run(["git", "diff", "--name-only", receipt["provenance"]["source_commit"],
                        "--", "Makefile", "include", "arch/arm64/include", "scripts",
                        "drivers/base/power", "kernel/power", "drivers/i2c/i2c-core-base.c"])
    if incompatible.strip():
        raise RuntimeError(f"Paired kernel core/build interface drift: {incompatible.decode()}")
    watched = [SOURCE, HEADER, FIXTURE, GUEST, Path(__file__).resolve(), RECEIPT,
               image, BUILD / ".config", BUILD / "Module.symvers"]
    identities = {p: digest(p) for p in watched}
    before = {name: fg.tree_digest(BUILD / name) for name in COPY_INPUTS}
    with tempfile.TemporaryDirectory(prefix=".sw42000-qemu-work-", dir=RUN_RECORD) as tmp:
        work = Path(tmp)
        env = {**os.environ, "TMPDIR": tmp, "TMP": tmp, "TEMP": tmp,
               "PYTHONDONTWRITEBYTECODE": "1", "SOURCE_DATE_EPOCH": "1792365298",
               "KBUILD_BUILD_USER": "lgg8", "KBUILD_BUILD_HOST": "builder",
               "KBUILD_BUILD_VERSION": "1", "LOCALVERSION": ""}
        private, mod = work / "kernel-build", work / "module"
        private.mkdir()
        mod.mkdir()
        try:
            for name in COPY_INPUTS:
                shutil.copytree(BUILD / name, private / name, symlinks=True)
            # Refuse symlinks that could make Kbuild write into an existing tree.
            for directory, dirs, files in os.walk(private, followlinks=False):
                for name in dirs + files:
                    p = Path(directory) / name
                    if p.is_symlink() and not p.resolve().is_relative_to(private):
                        raise RuntimeError(f"Private build contains an external symlink: {p}")
            if any(fg.tree_digest(private / n) != before[n] for n in COPY_INPUTS):
                raise RuntimeError("Generated-header snapshot is inconsistent")
            (private / ".config").write_bytes(config)
            (private / "Module.symvers").write_bytes(symvers)
            (private / "source").symlink_to(ROOT, target_is_directory=True)
            (private / "Makefile").write_text(f"export KBUILD_OUTPUT = {private}\ninclude {ROOT / 'Makefile'}\n")
            (mod / "sw42000_pm_fixture.c").write_text(generated)
            (mod / HEADER.name).write_bytes(HEADER.read_bytes())
            (mod / "Makefile").write_text("obj-m := sw42000_pm_fixture.o\n")
            shutil.copyfile(image, work / "Image")
            pressure_gate()
            run(["ionice", "-c", "3", "make", f"O={private}", "ARCH=arm64", "LLVM=1",
                 "WERROR=1", "-j1", f"M={mod}", "modules"], env, timeout=60)
            module = mod / "sw42000_pm_fixture.ko"
            imports = verify_undefined(module, env)
            if (private / ".config").read_bytes() != config or (
                    private / "Module.symvers").read_bytes() != symvers:
                raise RuntimeError("Private build identity changed")
            run(["ionice", "-c", "3", "aarch64-linux-gnu-gcc", "-static", "-Os", "-Wall",
                 "-Wextra", "-Werror", "-Wl,--build-id=none", "-o", str(work / "init"), str(GUEST)], env)
            records = [(".", stat.S_IFDIR | 0o755, b"", (0, 0)),
                       *[(n, stat.S_IFDIR | 0o755, b"", (0, 0)) for n in ("dev", "sys", "proc")],
                       ("dev/console", stat.S_IFCHR | 0o600, b"", (5, 1)),
                       ("init", stat.S_IFREG | 0o755, (work / "init").read_bytes(), (0, 0)),
                       ("sw42000_pm_fixture.ko", stat.S_IFREG | 0o644, module.read_bytes(), (0, 0)),
                       ("TRAILER!!!", 0, b"", (0, 0))]
            initramfs = work / "initramfs.cpio"
            initramfs.write_bytes(b"".join(archive.entry(n, m, b, ino=i, rdev=r)
                                         for i, (n, m, b, r) in enumerate(records, 1)))
            base = ["qemu-system-aarch64", "-M", "virt,gic-version=3", "-cpu", "cortex-a76",
                    "-accel", "tcg,thread=single", "-smp", "1", "-m", "512M", "-nodefaults",
                    "-display", "none", "-serial", "stdio", "-monitor", "none", "-nic", "none",
                    "-no-reboot", "-kernel", str(work / "Image"), "-initrd", str(initramfs)]
            bootargs = "console=ttyAMA0 rdinit=/init panic=5 panic_on_warn=1 loglevel=7"
            logs = {}

            def boot(name, extra, marker, dtb=None):
                pressure_gate()
                args = base + (["-dtb", str(dtb)] if dtb else []) + ["-append", bootargs + extra]
                try:
                    log = run(args, env, timeout=55)
                except subprocess.TimeoutExpired as error:
                    sys.stderr.buffer.write(error.stdout or b"")
                    raise RuntimeError("QEMU timeout; no PASS") from error
                logs[name] = hashlib.sha256(log).hexdigest()
                (RUN_RECORD / f"{name}.stdout").write_bytes(log)
                if marker.encode() not in log or b"SW42000_QEMU_GUEST: FAIL" in log or fg.has_kernel_error(log):
                    sys.stderr.buffer.write(log)
                    raise RuntimeError(f"{name} guest assertions/kernel diagnostics failed")
                if name != "guard" and b"SW42000_QEMU_PM: cleanup passed" not in log:
                    raise RuntimeError(f"{name} did not complete module teardown")
                if name == "normal":
                    for i in range(7):
                        if f"SW42000_QEMU_PM: scenario {i} passed".encode() not in log:
                            raise RuntimeError(f"Missing scenario {i}")

            boot("normal", "", "device PM integration passed")
            boot("negative", " sw42000.negative=1", "missing-PM negative control passed")
            dtb = work / "virt.dtb"
            run(["qemu-system-aarch64", "-machine", f"virt,gic-version=3,dumpdtb={dtb}",
                 "-cpu", "cortex-a76", "-smp", "1", "-m", "512M", "-nodefaults",
                 "-display", "none", "-monitor", "none", "-nic", "none"], env, timeout=20)
            tree = archive._bootimg.Fdt(dtb.read_bytes())
            if tree.nodes["/"].get("compatible") != b"linux,dummy-virt\0":
                raise RuntimeError("Unexpected virt root identity")
            tree.nodes["/"]["compatible"] = b"sw42000-test,not-virt\0"
            dtb.write_bytes(tree.encode())
            boot("guard", " sw42000.expect_reject=1", "non-virt rejection passed", dtb)
            report.update(status="PASS_QEMU_SIMULATED_HARDWARE", runtime_validated=True,
                          kernel_sha256=digest(work / "Image"), module_sha256=digest(module),
                          paired_source_commit=receipt["provenance"]["source_commit"],
                          initramfs_sha256=digest(initramfs), boot_log_sha256=logs,
                          full_undefined_symbol_audit=imports, physical_phone_tested=False,
                          exact_irq_depth_proven=False, system_sleep_entry_tested=False,
                          io_pressure_before_run=pressure, space_first_readouts=space)
        finally:
            # On failures too: never silently claim the existing build stayed intact.
            if any(digest(p) != value for p, value in identities.items()) or any(
                    fg.tree_digest(BUILD / name) != value for name, value in before.items()):
                raise RuntimeError("Inputs/paired build changed during the test; invalidate result")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="read-only checks (default)")
    mode.add_argument("--run", action="store_true", help="private module build and QEMU; pressure gated")
    args = p.parse_args()
    report, generated = check_static()
    report["io_pressure"] = io_pressure()
    if args.run:
        report = execute(report, generated)
        (RUN_RECORD / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        if RUN_RECORD:
            (RUN_RECORD / "failure.json").write_text(json.dumps(
                {"status": "NOT_VALIDATED", "error": str(error)}, indent=2) + "\n")
        print(f"NOT_VALIDATED: {error}", file=sys.stderr)
        raise SystemExit(1)
