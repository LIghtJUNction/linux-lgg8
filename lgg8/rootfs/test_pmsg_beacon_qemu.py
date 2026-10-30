#!/usr/bin/env python3
"""Run supervisor.c as QEMU PID 1 against dummy_hcd and verify iSerial receipt."""
from __future__ import annotations

import argparse
import gzip
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parent / "supervisor.c"
MODULES = {
    "udc-core": "kernel/drivers/usb/gadget/udc/udc-core.ko.zst",
    "libcomposite": "kernel/drivers/usb/gadget/libcomposite.ko.zst",
    "u_serial": "kernel/drivers/usb/gadget/function/u_serial.ko.zst",
    "usb_f_acm": "kernel/drivers/usb/gadget/function/usb_f_acm.ko.zst",
    "dummy_hcd": "kernel/drivers/usb/gadget/udc/dummy_hcd.ko.zst",
}


def command(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, **kwargs)


def make_case(root: Path, module_root: Path, cc: str, mode: str) -> Path:
    for directory in ("bin", "sbin", "modules", "usr/local/bin"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy2("/usr/bin/busybox", root / "bin/busybox")
    for applet in ("sh", "mount", "mkdir", "cat", "sleep", "insmod"):
        (root / "bin" / applet).symlink_to("busybox")
    for name, relative in MODULES.items():
        compressed = module_root / relative
        if not compressed.is_file():
            raise RuntimeError(f"Missing module: {compressed}")
        data = subprocess.run(["zstd", "-dc", str(compressed)], check=True,
                              stdout=subprocess.PIPE).stdout
        (root / "modules" / f"{name}.ko").write_bytes(data)

    extra = {
        "disabled": [],
        "open-error": [],
        "hang-open": ["-DLGG8_PMSG_TEST_HANG_OPEN"],
        "hang-write": ["-DLGG8_PMSG_PATH=\"/dev/full\"", "-DLGG8_PMSG_TEST_HANG_WRITE"],
        "write-ok": ["-DLGG8_PMSG_PATH=\"/dev/null\""],
        "write-error": ["-DLGG8_PMSG_PATH=\"/dev/full\""],
        "short-write": ["-DLGG8_PMSG_PATH=\"/dev/null\"", "-DLGG8_PMSG_TEST_SHORT_WRITE"],
    }[mode]
    command([cc, "-static", "-O2", "-Wall", "-Wextra", "-Werror", *extra,
             str(SOURCE), "-o", str(root / "sbin/supervisor")],
            capture_output=True, text=True)
    desktop = root / "usr/local/bin/desktop-start"
    desktop.write_text("#!/bin/sh\nexit 0\n")
    desktop.chmod(0o755)

    init = """#!/bin/sh
mkdir -p /proc /sys /dev /run
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
insmod /modules/udc-core.ko
insmod /modules/libcomposite.ko
insmod /modules/u_serial.ko
insmod /modules/usb_f_acm.ko
insmod /modules/dummy_hcd.ko
(
  i=0
  while [ "$i" -lt 18 ]; do
    for d in /sys/bus/usb/devices/*; do
      [ -r "$d/product" ] || continue
      p=$(cat "$d/product" 2>/dev/null)
      case "$p" in LGG8-RAM*) echo "HOST_ENUM product=$p serial=$(cat "$d/serial" 2>/dev/null)";; esac
    done
    sleep 1
    i=$((i+1))
  done
) &
exec /sbin/supervisor
"""
    (root / "init").write_text(init)
    (root / "init").chmod(0o755)
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("disabled", "open-error", "hang-open", "hang-write",
                                            "write-ok", "write-error", "short-write"),
                        default="open-error")
    parser.add_argument("--timeout", type=int, default=24,
                        help="host-side QEMU run time in seconds")
    parser.add_argument("--memory-mib", type=int, default=512)
    args = parser.parse_args()
    if args.timeout < 12:
        parser.error("timeout must be at least 12 seconds for module startup and USB enumeration")
    available_kib = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                             if line.startswith("MemAvailable:")))
    required_kib = max(1024 * 1024, args.memory_mib * 1024 + 384 * 1024)
    if available_kib < required_kib:
        raise SystemExit(f"Need {required_kib // 1024} MiB MemAvailable for this QEMU run")
    for tool in ("cc", "qemu-system-x86_64", "zstd", "cpio", "gzip", "timeout"):
        if not shutil.which(tool):
            raise SystemExit(f"Missing required tool: {tool}")
    kernel_release = subprocess.check_output(["uname", "-r"], text=True).strip()
    module_root = Path("/usr/lib/modules") / kernel_release
    kernel = module_root / "vmlinuz"
    if not kernel.is_file():
        raise SystemExit(f"Missing host kernel image: {kernel}")
    serial_original = "LGG8" + "-RAM"
    serial_base = serial_original + ";T=C196;"
    expected = {
        "disabled": serial_original,
        "open-error": serial_base + "O=ERR-2;W=NA",
        "hang-open": serial_base + "O=PEND;W=NA",
        "hang-write": serial_base + "O=OK;W=PEND",
        "write-ok": serial_base + "O=OK;W=OK",
        "write-error": serial_base + "O=OK;W=ERR-28",
        "short-write": serial_base + "O=OK;W=SHORT-",
    }[args.mode]
    with tempfile.TemporaryDirectory(prefix="lgg8-pmsg-qemu-") as temporary:
        base = Path(temporary)
        root = make_case(base / "root", module_root, shutil.which("cc"), args.mode)
        cpio_path = base / "initrd.cpio"
        with cpio_path.open("wb") as output:
            command(["bash", "-lc", 'cd "$1" && find . -print0 | cpio --null -o -H newc 2>/dev/null',
                     "_", str(root)], stdout=output)
        initrd = base / "initrd.gz"
        with cpio_path.open("rb") as source, initrd.open("wb") as output:
            with gzip.GzipFile(filename="", mode="wb", compresslevel=1, fileobj=output) as zipped:
                shutil.copyfileobj(source, zipped)
        print(f"mode={args.mode} initrd_bytes={initrd.stat().st_size}", flush=True)
        cmdline = "console=ttyS0,115200 rdinit=/init loglevel=7 panic=0 " \
                  "lgg8.desktop_backend=headless lgg8.usb_beacon=1"
        if args.mode != "disabled":
            cmdline += " lgg8.pmsg_probe=1 lgg8.pmsg_tag=C196"
        qemu = ["timeout", f"{args.timeout}s", "qemu-system-x86_64", "-accel", "tcg",
                "-cpu", "max", "-smp", "1", "-m", f"{args.memory_mib}M", "-kernel", str(kernel),
                "-initrd", str(initrd), "-append", cmdline,
                "-nographic", "-monitor", "none", "-nic", "none", "-no-reboot"]
        result = subprocess.run(qemu, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=args.timeout + 10)
        output = result.stdout.decode(errors="replace")
        for line in output.splitlines():
            if any(marker in line for marker in
                   ("LGG8_USER_PMSG_PROBE", "LGG8_SUPERVISOR", "LGG8_BEACON", "HOST_ENUM")):
                print(line)
        found = (re.search(re.escape(expected) + r"\d+/\d+", output) is not None
                 if args.mode == "short-write" else expected in output)
        if result.returncode != 124:
            raise SystemExit(f"QEMU exited unexpectedly: status={result.returncode}")
        if not found:
            print("\n".join(output.splitlines()[-80:]))
            raise SystemExit(f"Expected frozen USB serial not observed: {expected}")
        if "LGG8_BEACON bound" not in output or "HOST_ENUM" not in output:
            print("\n".join(output.splitlines()[-80:]))
            raise SystemExit("Gadget did not bind and enumerate on the guest USB host")
        print(f"PASS: PID1 survived; dummy_hcd host read frozen serial {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
