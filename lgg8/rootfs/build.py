#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build a selective signed-APK RAM desktop; never install packages on the host."""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parent
REPO = SOURCE.parents[1]
OUT = Path(os.environ.get("LGG8_DESKTOP_OUT", REPO / "out/lgg8/desktop")).resolve()
LOCK = SOURCE / "package-lock.json"
EPOCH = 1792365298

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1048576), b""): h.update(b)
    return h.hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], capture_output=True,
                            timeout=kwargs.pop("timeout", 60), **kwargs)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}\n{result.stderr.decode(errors='replace')}")
    return result

def fetch(rec, cache, record=False):
    path = cache / rec["url"].rsplit("/", 1)[1]
    expected = rec.get("apk_sha256", rec.get("sha256"))
    if not expected and not record:
        raise ValueError("Unpinned archive: use --record-lock for the first trusted verification")
    if not path.exists():
        partial = path.with_suffix(path.suffix + ".partial")
        maximum = rec.get("apk_bytes", rec.get("bytes", 0))
        try:
            with urllib.request.urlopen(rec["url"], timeout=40) as response, partial.open("wb") as f:
                total = 0
                while b := response.read(262144):
                    total += len(b)
                    if total > maximum: raise ValueError("Download exceeds pinned size")
                    f.write(b)
            if total != maximum: raise ValueError("Archive size mismatch")
            if expected and sha(partial) != expected: raise ValueError("Archive SHA-256 mismatch")
            partial.replace(path)
        finally: partial.unlink(missing_ok=True)
    if path.stat().st_size != rec.get("apk_bytes", rec.get("bytes")):
        raise ValueError(f"Wrong archive size: {path}")
    if expected and sha(path) != expected: raise ValueError(f"Wrong archive SHA-256: {path}")
    return path

def clean_owned(path):
    if path.parent != OUT or path.name not in {"root", "scratch", "boot", "bootstrap"}:
        raise ValueError("Refusing cleanup outside owned working paths")
    if path.is_symlink(): raise ValueError("Owned directory must not be a symlink")
    if path.exists(): shutil.rmtree(path)

def guest_normal(path):
    return posixpath.normpath("/" + str(path).lstrip("/"))

def guest_file(root, name, follow_last=True):
    """Resolve absolute guest symlinks inside root, never against host /."""
    name = guest_normal(name)
    for _ in range(40):
        parts = PurePosixPath(name).parts[1:]
        for i in range(1, len(parts) + (1 if follow_last else 0)):
            p = root.joinpath(*parts[:i])
            if p.is_symlink():
                target = os.readlink(p)
                base = "/" if target.startswith("/") else "/" + "/".join(parts[:i-1])
                name = guest_normal(posixpath.join(base, target, *parts[i:]))
                break
        else: return root.joinpath(*parts)
    raise ValueError("Guest symlink loop")

def copy_member(root, name, mode, data=None, link=None, absolute=True):
    if ".." in PurePosixPath(name).parts or str(name).startswith("/"):
        raise ValueError("Archive path traversal")
    dest = guest_file(root, name, follow_last=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if stat.S_ISDIR(mode):
        if dest.is_symlink(): raise ValueError("Directory crossing symlink")
        dest.mkdir(exist_ok=True); dest.chmod(stat.S_IMODE(mode)); return dest
    if dest.is_symlink() or dest.is_file(): dest.unlink()
    if link is not None:
        target = guest_normal(posixpath.join("/" + str(PurePosixPath(name).parent), link))
        if not absolute: target = posixpath.relpath(target, "/" + str(PurePosixPath(name).parent))
        dest.symlink_to(target)
    elif data is not None:
        dest.write_bytes(data); dest.chmod(stat.S_IMODE(mode) & 0o777)
    else: raise ValueError("Unexpected archive file type")
    return dest

def untar_base(archive, root, origins=None, absolute=True):
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        for m in tf:
            name = m.name.removeprefix("./")
            if not name: continue
            if m.isdir(): mode, data, link = stat.S_IFDIR | m.mode, None, None
            elif m.issym(): mode, data, link = stat.S_IFLNK | 0o777, None, m.linkname
            elif m.isfile() or m.islnk(): mode, data, link = stat.S_IFREG | m.mode, tf.extractfile(m).read(), None
            else: raise ValueError(f"Unexpected base member {m.name}")
            dest = copy_member(root, name, mode, data, link, absolute)
            if origins is not None:
                origins[dest.relative_to(root).as_posix()] = {"origin": "alpine-minirootfs", "archive_member": m.name}

def apk_command(bootstrap, root):
    return [bootstrap / "lib/ld-musl-x86_64.so.1", "--library-path",
            str(bootstrap / "lib") + ":" + str(bootstrap / "usr/lib"), bootstrap / "sbin/apk",
            "--root", root, "--keys-dir", "etc/apk/keys"]

def install_files(rec, archive, root, bootstrap, origins, evidence):
    command = apk_command(bootstrap, root)
    verified = run(command + ["verify", archive])
    # APK v2 consists of concatenated gzip/tar streams. tarfile is used only
    # to inspect package identity; extraction itself is done by trusted apk.
    if archive.read_bytes()[:2] != b"\x1f\x8b":
        raise ValueError("Package identity inspection currently requires APK v2")
    with tarfile.open(archive, "r:gz", ignore_zeros=True) as tf:
        info = tf.extractfile(".PKGINFO").read().decode()
    fields = dict(line.split(" = ", 1) for line in info.splitlines() if " = " in line)
    for key, value in [("pkgname", rec["name"]), ("pkgver", rec["version"])]:
        if fields.get(key) != value: raise ValueError("Signed package identity mismatch")
    if fields.get("arch") not in {"aarch64", "noarch"}: raise ValueError("Wrong signed package architecture")
    rec["apk_architecture"] = fields["arch"]
    scratch = OUT / "scratch"; clean_owned(scratch); scratch.mkdir()
    try:
        extracted = run(command + ["extract", "--no-chown", "--destination", scratch, archive])
        for directory, dirs, files in os.walk(scratch, followlinks=False):
            for filename in dirs + files:
                src = Path(directory) / filename; name = src.relative_to(scratch).as_posix()
                st = src.lstat()
                if stat.S_ISDIR(st.st_mode): data, link = None, None
                elif stat.S_ISLNK(st.st_mode): data, link = None, os.readlink(src)
                elif stat.S_ISREG(st.st_mode): data, link = src.read_bytes(), None
                else: raise ValueError(f"Unsupported package special file: {name}")
                dest = copy_member(root, name, st.st_mode, data, link)
                origins[dest.relative_to(root).as_posix()] = {"origin": rec["name"], "version": rec["version"], "archive_member": name}
        evidence.append({"name": rec["name"], "version": rec["version"], "url": rec["url"],
            "sha256": sha(archive), "signature_verified": True,
            "upstream_url": fields.get("url"), "license": fields.get("license"),
            "aports_origin": fields.get("origin"), "pkginfo_sha256": hashlib.sha256(info.encode()).hexdigest(),
            "apkbuild_url": f"https://gitlab.alpinelinux.org/alpine/aports/-/blob/{rec.get('aports_commit')}/{rec['repository']}/{fields.get('origin')}/APKBUILD",
            "verification_stdout": verified.stdout.decode(), "verification_stderr": verified.stderr.decode(),
            "extract_stderr": extracted.stderr.decode(), "scripts_executed": False})
    finally: clean_owned(scratch)

def elf(path):
    data = path.read_bytes()
    if data[:4] != b"\x7fELF": return None
    if data[:7] != b"\x7fELF\x02\x01\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError(f"Not a little-endian AArch64 ELF: {path}")
    kind = struct.unpack_from("<H", data, 16)[0]
    off = struct.unpack_from("<Q", data, 32)[0]
    size, count = struct.unpack_from("<HH", data, 54)
    segments = [struct.unpack_from("<IIQQQQQQ", data, off+i*size) for i in range(count)]
    interpreter, dynamic = None, []
    for ptype, flags, offset, address, _, filesz, memsz, alignment in segments:
        if ptype == 3: interpreter = data[offset:offset+filesz].rstrip(b"\0").decode()
        if ptype == 2:
            dynamic = [struct.unpack_from("<QQ", data, x) for x in range(offset, offset+filesz, 16)]
    strings = next((v for t,v in dynamic if t == 5), None)
    table = None
    if strings is not None:
        table = next(o + strings-a for t,fl,o,a,_,s,ms,al in segments if t == 1 and a <= strings < a+s)
    def string(index): return data[table+index:data.index(b"\0", table+index)].decode()
    return {"kind": kind, "interpreter": interpreter,
            "needed": [string(v) for t,v in dynamic if t == 1],
            "runpaths": [string(v) for t,v in dynamic if t in (15,29)],
            "has_dynamic_segment": any(p[0] == 2 for p in segments)}

def curate(root):
    keep_modules = {"drm-backend.so", "headless-backend.so"}
    for p in (root / "usr/lib/libweston-14").glob("*"):
        if p.name not in keep_modules:
            if p.is_dir(): shutil.rmtree(p)
            else: p.unlink()
    for p in (root / "usr/lib/weston").glob("*"):
        if not (p.name == "desktop-shell.so" or p.name.startswith("libexec_weston.so")): p.unlink()
    tools = {"weston", "weston-terminal", "weston-capture", "weston-debug"}
    for p in (root / "usr/bin").glob("weston*"):
        if p.name not in tools: p.unlink()
    for p in (root / "usr/libexec").glob("weston-*"):
        if p.name not in {"weston-desktop-shell", "weston-keyboard", "weston-simple-im"}: p.unlink()
    # No storage/network/module-loader rule processing in the diagnostic RAM root.
    for directory in [root/"usr/lib/udev/rules.d", root/"lib/udev/rules.d"]:
        if not directory.is_dir(): continue
        for p in directory.glob("*.rules"):
            if not any(word in p.name for word in ["input", "evdev", "touchpad", "seat", "uaccess"]): p.unlink()
    # This is a file-curated image, not a package-managed installed system.
    for p in [root / "lib/apk/db", root / "etc/init.d", root / "etc/runlevels"]:
        if p.is_dir(): shutil.rmtree(p)

def audit(root):
    reports, missing = [], []
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file(): continue
        with p.open("rb") as f: magic = f.read(4)
        if magic != b"\x7fELF": continue
        result = elf(p); result["path"] = "/" + p.relative_to(root).as_posix()
        result["resolved"] = {}
        if result["interpreter"]:
            target = guest_file(root, result["interpreter"])
            if not target.is_file(): missing.append([result["path"], result["interpreter"]])
        search = ["/lib", "/usr/lib"]
        for entries in result["runpaths"]:
            for entry in entries.split(":"):
                search.insert(0, entry.replace("${ORIGIN}", posixpath.dirname(result["path"])).replace("$ORIGIN", posixpath.dirname(result["path"])))
        for dependency in result["needed"]:
            found = next((guest_file(root, x + "/" + dependency) for x in search
                          if guest_file(root, x + "/" + dependency).is_file()), None)
            if found is None: missing.append([result["path"], dependency])
            else: result["resolved"][dependency] = "/" + found.relative_to(root).as_posix()
        reports.append(result)
    actual_elf_paths = {r["path"] for r in reports}
    for item in reports:
        for target in item["resolved"].values():
            if target not in actual_elf_paths: missing.append([item["path"], "dependency is not an audited AArch64 ELF: " + target])
        if item["interpreter"]:
            target = "/" + guest_file(root,item["interpreter"]).relative_to(root).as_posix()
            if target not in actual_elf_paths: missing.append([item["path"], "interpreter is not an audited AArch64 ELF: " + target])
    required = ["sbin/udevd", "sbin/udevadm", "usr/bin/seatd", "usr/bin/weston", "usr/bin/weston-terminal",
        "usr/lib/libweston-14/drm-backend.so", "usr/lib/libweston-14/headless-backend.so",
        "usr/lib/weston/desktop-shell.so", "usr/libexec/weston-desktop-shell", "etc/fonts/fonts.conf",
        "usr/share/fonts/liberation/LiberationMono-Regular.ttf", "usr/share/X11/xkb/rules/evdev",
        "usr/share/weston/icon_terminal.png", "usr/lib/udev/rules.d/60-input-id.rules",
        "usr/lib/udev/rules.d/80-libinput-device-groups.rules"]
    data_audit = {}
    for name in required:
        path = guest_file(root,name)
        ok = path.is_file()
        if name in {"sbin/udevd","sbin/udevadm","usr/bin/seatd"}: ok = ok and os.access(path,os.X_OK)
        data_audit["/"+name] = {"present":ok,"sha256":sha(path) if ok else None}
        if not ok: missing.append(["runtime data or daemon",name])
    forbidden = ["usr/lib/libweston-14/gl-renderer.so", "usr/lib/dri", "usr/lib/libLLVM.so"]
    for name in forbidden:
        if (root/name).exists(): missing.append(["unexpected excluded component",name])
    result = {"status": "PASSED" if not missing else "FAILED", "elf_count": len(reports), "missing": missing, "elf": reports,
              "runtime_files": data_audit,
              "dynamic_modules": {"retained": ["drm-backend.so", "headless-backend.so", "desktop-shell.so", "libexec_weston.so"],
              "renderer": "pixman built into libweston; GL renderer removed; no software fallback to GL",
              "remaining_device_gate": "Actual DRM dumb-buffer/libseat/libinput paths must be tested on phone; QEMU proves only explicit headless path"}}
    save(OUT / "elf-audit.json", result)
    if missing: raise ValueError(f"Missing retained ELF dependencies: {missing}")
    return result

def pack_cpio(root, origins, bootimg):
    manifest = []
    output = OUT / "initramfs.cpio"
    inode = 0
    def entry(name, mode, data=b"", rdev=(0,0)):
        nonlocal inode
        inode += 1
        encoded = name.encode() + b"\0"
        fields = (inode, mode, 0, 0, 2 if stat.S_ISDIR(mode) else 1,
                  EPOCH, len(data), 0, 0, rdev[0], rdev[1], len(encoded), 0)
        blob = b"070701" + b"".join(f"{v:08x}".encode() for v in fields) + encoded
        blob += bytes(-len(blob) % 4); blob += data; blob += bytes(-len(blob) % 4)
        f.write(blob)
    with output.open("wb") as f:
        entry(".", stat.S_IFDIR | 0o755)
        for p in sorted(root.rglob("*")):
            name = p.relative_to(root).as_posix(); st = p.lstat()
            if p.is_symlink(): data = os.readlink(p).encode(); mode = stat.S_IFLNK | 0o777
            elif p.is_dir(): data = b""; mode = stat.S_IFDIR | stat.S_IMODE(st.st_mode)
            elif p.is_file(): data = p.read_bytes(); mode = stat.S_IFREG | stat.S_IMODE(st.st_mode)
            else: raise ValueError("Unexpected host node in working root")
            entry(name, mode, data)
            manifest.append({"path": "/"+name, "mode": oct(mode), "uid": 0, "gid": 0,
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "symlink_target": data.decode() if stat.S_ISLNK(mode) else None,
                "provenance": origins.get(name, {"origin": "generated directory"})})
        for name, major, minor in [("dev/console",5,1), ("dev/kmsg",1,11), ("dev/null",1,3)]:
            if (root/name).exists(): raise ValueError("Unexpected pre-existing device node")
            entry(name, stat.S_IFCHR | 0o600, rdev=(major,minor))
            manifest.append({"path": "/"+name, "mode": oct(stat.S_IFCHR | 0o600), "rdev": [major,minor], "provenance": {"origin": "generated CPIO-only device metadata"}})
        entry("TRAILER!!!", 0); f.write(bytes(-f.tell() % 512))
    if output.stat().st_size > 64*2**20: raise ValueError("CPIO exceeds 64 MiB: material budget failure")
    archive = output.read_bytes(); entries = bootimg.cpio(archive)
    checked_init = bootimg.check_init(entries, "rdinit=/init")
    save(OUT / "file-origins.json", {"schema": "lgg8-desktop-files-v1", "files": manifest,
         "cpio_sha256": sha(output), "cpio_bytes": len(archive), "entry_validation": checked_init})
    return checked_init

def build(args, lock, bootimg):
    cache = OUT / "cache"; cache.mkdir(exist_ok=True)
    bootstrap_archive = fetch(lock["bootstrap"], cache)
    bootstrap = OUT / "bootstrap"
    clean_owned(bootstrap)
    untar_base(bootstrap_archive, bootstrap, absolute=False)
    # Local reuse is explicit; public locks never contain private workspace paths.
    base = Path(args.base).expanduser().resolve() if args.base else fetch(lock["base"], cache)
    if not base.is_file(): raise ValueError("Explicit --base archive does not exist")
    if sha(base) != lock["base"]["sha256"]: raise ValueError("ARM base archive hash mismatch")
    root = OUT / "root"; clean_owned(root); origins = {}
    untar_base(base, root, origins)
    packages = lock["packages"]
    budget = bootstrap_archive.stat().st_size + sum(r["apk_bytes"] for r in packages)
    if budget > lock["limits"]["download_bytes"]: raise ValueError("Archive download budget exceeds 60 MiB")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        archives = list(pool.map(lambda rec: fetch(rec, cache, args.record_lock), packages))
    evidence = []
    for i,(rec, archive) in enumerate(zip(packages, archives), 1):
        install_files(rec, archive, root, bootstrap, origins, evidence)
        rec["apk_sha256"] = sha(archive)
        rec["signature_verified"] = True
        print(f"verified/extracted {i}/{len(packages)} {rec['name']}", flush=True)
    save(OUT / "archive-verification.json", {"archives": evidence, "bootstrap": lock["bootstrap"],
         "base_sha256": sha(base), "verifier_version": run(apk_command(bootstrap, root) + ["--version"]).stdout.decode()})
    if args.record_lock:
        lock["source_status"] = "ARCHIVE_SHA256_LOCKED_AFTER_TRUSTED_APK_SIGNATURE_VERIFICATION"
        save(LOCK, lock)
    curate(root)
    for dirname in ["dev", "proc", "sys", "run", "tmp", "root", "usr/local/bin"]: (root/dirname).mkdir(parents=True,exist_ok=True)
    run(["aarch64-linux-gnu-gcc", "-static", "-fno-pie", "-no-pie", "-Os", "-Wall", "-Wextra", "-Werror",
         "-ffile-prefix-map="+str(REPO)+"=.", "-Wl,--build-id=none", "-s", SOURCE/"supervisor.c", "-o", root/"init"])
    origins["init"] = {"origin": "lgg8/rootfs/supervisor.c", "source_sha256": sha(SOURCE/"supervisor.c")}
    for source, destination in [("desktop-start.sh","usr/local/bin/desktop-start"), ("terminal.sh","usr/local/bin/lgg8-terminal")]:
        dest=root/destination; shutil.copyfile(SOURCE/source,dest);dest.chmod(0o755)
        origins[destination]={"origin":"lgg8/rootfs/"+source,"source_sha256":sha(SOURCE/source)}
    (root/"tmp").chmod(0o1777)
    # No mutable APK database remains; record every actually retained file.
    audit(root); checked=pack_cpio(root,origins,bootimg)
    save(OUT/"build-report.json",{"status":"PASSED_STATIC_CHECKS", "kernel_sha256":lock["kernel_sha256"],
         "cpio_sha256":sha(OUT/"initramfs.cpio"),"cpio_bytes":(OUT/"initramfs.cpio").stat().st_size,
         "package_archive_bytes":sum(r["apk_bytes"] for r in packages),"bootstrap_archive_bytes":bootstrap_archive.stat().st_size,
         "init":checked,"device_acceptance":"NOT_TESTED","source_lock_sha256":sha(LOCK)})

def frame_proof(text):
    """Require attach(non-null)->damage->commit->done for the SAME surface.

    frame() requests belong to a surface and are associated with its next
    commit. Object IDs are scoped to this single terminal WAYLAND_DEBUG trace.
    Both modern '#' and older '@' debug ID formatting are accepted.
    """
    surfaces, callbacks, completed = {}, {}, []
    for line_number, line in enumerate(text.splitlines(), 1):
        # The console also contains printk copies of forwarded client logs.
        # Parse the original one-client WAYLAND_DEBUG stream exactly once.
        if not re.match(r"^\[\s*\d+\.\d+\]\s+\{[^}]+\}", line): continue
        match = re.search(r"wl_surface[#@](\d+)\.(frame|attach|damage|damage_buffer|commit)\((.*)\)", line)
        if match and " -> " in line:
            surface, operation, args = match.groups()
            state = surfaces.setdefault(surface, {"requested_callbacks": []})
            if operation == "frame":
                callback = re.search(r"new id wl_callback[#@](\d+)", args)
                if callback:
                    state["requested_callbacks"].append((callback[1], line_number))
            elif operation == "attach":
                buffer = re.match(r"wl_buffer[#@](\d+),", args)
                state.update(buffer_id=buffer[1] if buffer else None,
                             attach_line=line_number, damage_line=None)
            elif operation in {"damage", "damage_buffer"}:
                if state.get("buffer_id") is not None:
                    state["damage_line"] = line_number
            elif operation == "commit":
                if state.get("buffer_id") and state.get("damage_line"):
                    for callback, request_line in state["requested_callbacks"]:
                        callbacks[callback] = {"surface_id": surface,
                            "buffer_id": state["buffer_id"], "callback_id": callback,
                            "frame_request_line": request_line,
                            "attach_line": state["attach_line"],
                            "damage_line": state["damage_line"], "commit_line": line_number}
                state["requested_callbacks"] = []
                state["buffer_id"] = None
                state["damage_line"] = None
        done = re.search(r"wl_callback[#@](\d+)\.done\(", line)
        if done and " -> " not in line and done[1] in callbacks:
            event = callbacks.pop(done[1]); event["done_line"] = line_number
            if event["attach_line"] < event["damage_line"] < event["commit_line"] < line_number:
                completed.append(event)
    return completed

def evaluate_qemu(lock, report):
    kernel = REPO/"out/lgg8/kernel/arch/arm64/boot/Image"
    if report.get("cpio_sha256") != sha(OUT/"initramfs.cpio"):
        raise ValueError("QEMU report belongs to a different CPIO")
    if report.get("kernel_sha256") != lock["kernel_sha256"]:
        raise ValueError("QEMU report belongs to a different kernel")
    text = (OUT/"qemu.log").read_text(errors="replace")
    frames = frame_proof(text)
    proof = {"pid1": "LGG8_SUPERVISOR pid=1 backend=headless" in text,
        "socket": "LGG8_WAYLAND_SOCKET_READY backend=headless" in text,
        "desktop_shell": "Loading module '/usr/lib/weston/desktop-shell.so'" in text
                         and "launching '/usr/libexec/weston-desktop-shell'" in text,
        "terminal_shell_executed": "LGG8_TERMINAL_SHELL_EXECUTED" in text,
        "same_surface_buffer_damage_commit_frame_done": bool(frames),
        "guest_state_mirrored_to_kmsg": bool(re.search(r"^\[\s*\d+\.\d+\] lgg8 /run/desktop-events\.log:", text, re.M)),
        "weston_log_mirrored_to_kmsg": bool(re.search(r"^\[\s*\d+\.\d+\] lgg8 /run/weston\.log:", text, re.M)),
        "guest_20_second_limit": "LGG8_QEMU_TIMEOUT seconds=20" in text,
        "immutable_kernel": sha(kernel) == lock["kernel_sha256"],
        "no_crash": not any(x in text for x in ["Kernel panic", "Segmentation fault", "Error loading shared library", "Error relocating"])}
    report.update(status="PASSED" if all(proof.values()) and not report["wall_timeout"]
                  and report["exit_code"] == 0 else "FAILED", proof=proof,
                  completed_frames=frames, log_sha256=sha(OUT/"qemu.log"),
                  verifier_source_sha256=sha(Path(__file__)),
                  phone_drm_acceptance="NOT_TESTED")
    save(OUT/"qemu-report.json", report)
    print(json.dumps(report, indent=2))
    if report["status"] != "PASSED": raise ValueError("QEMU desktop proof failed; inspect qemu.log")

def qemu(lock):
    available = next(int(l.split()[1])*1024 for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemAvailable:"))
    if available < 2*2**30:
        pending={"status":"PENDING_MEMORY", "available_bytes":available,"required_bytes":2*2**30}
        save(OUT/"qemu-report.json",pending);print(json.dumps(pending,indent=2));raise SystemExit(3)
    kernel=REPO/"out/lgg8/kernel/arch/arm64/boot/Image"
    if sha(kernel)!=lock["kernel_sha256"]:raise ValueError("Immutable kernel SHA mismatch")
    cmd=["qemu-system-aarch64","-machine","virt,gic-version=3","-cpu","cortex-a76","-smp","1","-m","768M",
         "-nographic","-monitor","none","-nic","none","-no-reboot","-kernel",str(kernel),"-initrd",str(OUT/"initramfs.cpio"),
         "-append","console=ttyAMA0 rdinit=/init loglevel=7 panic=1 lgg8.desktop_backend=headless lgg8.desktop_timeout=20"]
    start=time.monotonic(); wall_timeout=False
    with (OUT/"qemu.log").open("wb") as log:
        proc=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        try:code=proc.wait(timeout=45)
        except subprocess.TimeoutExpired:
            wall_timeout=True;proc.terminate()
            try:code=proc.wait(timeout=2)
            except subprocess.TimeoutExpired:proc.kill();code=proc.wait(timeout=2)
    report={
        "command":cmd,"wall_seconds":time.monotonic()-start,"wall_timeout":wall_timeout,"exit_code":code,
        "available_bytes_before_start":available,"kernel_sha256":lock["kernel_sha256"],
        "cpio_sha256":sha(OUT/"initramfs.cpio"),"phone_drm_acceptance":"NOT_TESTED"}
    evaluate_qemu(lock, report)

def pack(lock, args):
    kernel=REPO/"out/lgg8/kernel/arch/arm64/boot/Image"
    if sha(kernel)!=lock["kernel_sha256"]:raise ValueError("Immutable kernel SHA mismatch")
    if not args.template: raise ValueError("Set TEMPLATE_DIR or --template to the verified private template")
    if args.partition_size is None or args.partition_size <= 0:
        raise ValueError("Set PARTITION_SIZE or --partition-size to explicitly confirmed positive bytes")
    template=Path(args.template).expanduser().resolve()
    capacity=args.partition_size
    cmdline=(REPO/"lgg8/boot/cmdline.txt").read_text().replace("lgg8_build=source-v1","lgg8_build=desktop-v1")
    if "desktop_backend=headless" in cmdline:raise ValueError("Headless profile forbidden in phone image")
    (OUT/"cmdline.txt").write_text(cmdline)
    clean_owned(OUT/"boot")
    program=REPO/"lgg8/tools/bootimg.py"
    command=[sys.executable,program,"build","--kernel",kernel,"--dtb",REPO/"out/lgg8/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb",
        "--initramfs",OUT/"initramfs.cpio","--template",template,"--cmdline-file",OUT/"cmdline.txt",
        "--partition-size",str(capacity),"--output",OUT/"boot"]
    run(command,timeout=120)
    result=run([sys.executable,program,"verify","--image",OUT/"boot/boot.img","--manifest",OUT/"boot/manifest.json"],timeout=60)
    (OUT/"boot-verification.json").write_bytes(result.stdout)

def receipt(lock):
    """Bind final source, signed inputs, actual QEMU evidence and packed bytes."""
    build=json.loads((OUT/"build-report.json").read_text())
    audit_report=json.loads((OUT/"elf-audit.json").read_text())
    simulation=json.loads((OUT/"qemu-report.json").read_text())
    verification=json.loads((OUT/"boot-verification.json").read_text())
    manifest=json.loads((OUT/"boot/manifest.json").read_text())
    origins=json.loads((OUT/"file-origins.json").read_text())
    files={f["path"]:f for f in origins["files"]}
    if not all(x["status"]=="PASSED" for x in [audit_report,simulation,verification]):
        raise ValueError("Receipt requires ELF, QEMU and boot verification PASSED")
    cpio_sha=sha(OUT/"initramfs.cpio")
    if not all(h==cpio_sha for h in [build["cpio_sha256"],simulation["cpio_sha256"],manifest["components"]["initramfs"]["sha256"],origins["cpio_sha256"]]):
        raise ValueError("Evidence is not bound to the same CPIO")
    for source,dest in [("desktop-start.sh","/usr/local/bin/desktop-start"),("terminal.sh","/usr/local/bin/lgg8-terminal")]:
        if sha(SOURCE/source)!=files[dest]["sha256"]:raise ValueError("Guest source changed since CPIO build")
    if sha(SOURCE/"supervisor.c")!=files["/init"]["provenance"]["source_sha256"]:
        raise ValueError("Supervisor source changed since CPIO build")
    if sha(OUT/"boot/boot.img")!=verification["image_sha256"]:raise ValueError("Boot bytes changed")
    if sha(REPO/"out/lgg8/kernel/arch/arm64/boot/Image")!=lock["kernel_sha256"]:raise ValueError("Kernel changed")
    if sha(OUT/"qemu.log")!=simulation["log_sha256"]:raise ValueError("QEMU log changed")
    for rec in lock["packages"]:
        if sha(OUT/"cache"/rec["url"].rsplit("/",1)[1])!=rec["apk_sha256"]:raise ValueError("APK cache changed")
    artifact_names=["initramfs.cpio","boot/boot.img","boot/manifest.json","boot/linux.dtb",
        "archive-verification.json","file-origins.json","elf-audit.json","build-report.json",
        "qemu.log","qemu-report.json","boot-verification.json","cmdline.txt"]
    report={"schema":"lgg8-desktop-receipt-v1","status":"READY_OFFLINE_AND_QEMU_PASSED",
        "device_acceptance":"NOT_TESTED","kernel_sha256":lock["kernel_sha256"],
        "sources":{str(p.relative_to(REPO)):sha(p) for p in sorted(SOURCE.iterdir()) if p.is_file()},
        "artifacts":{n:{"sha256":sha(OUT/n),"bytes":(OUT/n).stat().st_size} for n in artifact_names},
        "compiler":run(["aarch64-linux-gnu-gcc","--version"]).stdout.decode(),
        "qemu":run(["qemu-system-aarch64","--version"]).stdout.decode(),
        "public_keys":{p.name:sha(p) for p in (OUT/"root/etc/apk/keys").iterdir()},
        "archive_download_bytes":lock["bootstrap"]["bytes"]+sum(p["apk_bytes"] for p in lock["packages"]),
        "package_count":len(lock["packages"]),"elf_count":audit_report["elf_count"],
        "file_count":len(origins["files"]),"cpio_cap_bytes":64*2**20,
        "payload_end":hex(manifest["payload_end"]),"qemu_wall_seconds":simulation["wall_seconds"],
        "limits":"QEMU headless and offline format only; no phone DRM/input/retention proof"}
    save(OUT/"provenance.json",report)
    print(json.dumps({"status":report["status"],"cpio":report["artifacts"]["initramfs.cpio"],"boot":report["artifacts"]["boot/boot.img"]},indent=2))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["build","qemu","qemu-check","pack","receipt"])
    parser.add_argument("--record-lock",action="store_true",help="pin SHA-256 only after trusted signature verification")
    parser.add_argument("--base",help="existing verified ARM mini archive; no duplicate copy")
    parser.add_argument("--template",default=os.environ.get("TEMPLATE_DIR"),help="verified template; or TEMPLATE_DIR")
    parser.add_argument("--partition-size",type=lambda s:int(s,0),default=os.environ.get("PARTITION_SIZE"),
                        help="confirmed positive partition capacity in bytes; or PARTITION_SIZE; never inferred")
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);(OUT/"tmp").mkdir(exist_ok=True)
    os.environ.update(TMPDIR=str(OUT/"tmp"),SOURCE_DATE_EPOCH=str(EPOCH),PYTHONDONTWRITEBYTECODE="1")
    lock=json.loads(LOCK.read_text())
    spec=importlib.util.spec_from_file_location("bootimg",REPO/"lgg8/tools/bootimg.py")
    bootimg=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootimg)
    if args.action=="build":build(args,lock,bootimg)
    elif args.action=="qemu":qemu(lock)
    elif args.action=="qemu-check":evaluate_qemu(lock,json.loads((OUT/"qemu-report.json").read_text()))
    elif args.action=="receipt":receipt(lock)
    else:pack(lock,args)

if __name__=="__main__": main()
