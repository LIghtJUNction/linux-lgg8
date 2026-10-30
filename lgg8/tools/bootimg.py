#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""LG G8 Android-v0 packer. Offline format checks do not establish device support.

Only the three LLVM programs are needed for build; prepare/verify use stdlib.
The manifest is a trust input: keep its component hashes with your reviewed build.
Verification trusts its pinned shim bytes; it does not recompile the shim or
prove its instruction semantics. source_dtb/shim_source hashes record provenance.
Never commit extracted template binaries. No device commands are implemented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zlib

PAGE = 4096
ALIGN = 0x200000
LOAD = 0xaa000000
CMDLINE_LIMIT = 2047  # arch/arm64/include/uapi/asm/setup.h includes the NUL.
MAX_RAW = 256 * 1024 * 1024  # Decompression/allocation guard, not a partition size.
SHIM_SOURCE = Path(__file__).resolve().parents[1] / "boot/shim-mmu-off.S"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def align(n, boundary):
    return (n + boundary - 1) // boundary * boundary


def sha(data):
    return hashlib.sha256(data).hexdigest()


def describe(data):
    return {"size": len(data), "sha256": sha(data)}


def boot_id(kernel, ramdisk):
    digest = hashlib.sha1()
    for part in (kernel, ramdisk, b""):
        digest.update(part)
        digest.update(struct.pack("<I", len(part)))
    return digest.digest() + bytes(12)


def unpack_boot(blob):
    require(len(blob) >= PAGE and blob[:8] == b"ANDROID!", "Android boot magic/header")
    kernel_size, _, ramdisk_size, _, second_size, _, _, page, version = struct.unpack_from("<9I", blob, 8)
    require(page == PAGE and version == 0 and second_size == 0, "requires v0, page=4096, no second stage")
    require(kernel_size and ramdisk_size, "empty boot component")
    require(not any(blob[1632:PAGE]), "nonzero v0 header padding/unsupported extension")
    ramdisk_offset = PAGE + align(kernel_size, PAGE)
    end = ramdisk_offset + align(ramdisk_size, PAGE)
    require(len(blob) == end, "boot bounds/trailing data (partition dumps must first be trimmed)")
    kernel = blob[PAGE:PAGE + kernel_size]
    ramdisk = blob[ramdisk_offset:ramdisk_offset + ramdisk_size]
    require(not any(blob[PAGE + kernel_size:ramdisk_offset]) and
            not any(blob[ramdisk_offset + ramdisk_size:end]), "nonzero boot page padding")
    require(blob[576:608] == boot_id(kernel, ramdisk), "mkbootimg SHA-1 ID mismatch")
    return blob[:PAGE], kernel, ramdisk


def pack_boot(header, kernel, ramdisk):
    result = bytearray(header)
    struct.pack_into("<I", result, 8, len(kernel))
    result[576:608] = boot_id(kernel, ramdisk)
    require(struct.unpack_from("<I", header, 16)[0] == len(ramdisk), "template ramdisk size")
    return bytes(result) + kernel + bytes(align(len(kernel), PAGE) - len(kernel)) + ramdisk + bytes(align(len(ramdisk), PAGE) - len(ramdisk))


def gunzip_member(data):
    require(data[:3] == b"\x1f\x8b\x08", "gzip magic")
    decoder = zlib.decompressobj(31)
    try:
        raw = decoder.decompress(data, MAX_RAW + 1)
    except zlib.error as error:
        raise ValueError(f"invalid gzip: {error}") from error
    require(len(raw) <= MAX_RAW and not decoder.unconsumed_tail, "gzip expansion exceeds safety limit")
    require(decoder.eof, "truncated gzip member")
    return raw, decoder.unused_data


def gzip_member(raw, epoch):
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return (b"\x1f\x8b\x08\x00" + struct.pack("<I", epoch) + b"\x02\xff" +
            compressor.compress(raw) + compressor.flush() + struct.pack("<II", zlib.crc32(raw), len(raw)))


class Fdt:
    """Bounds-checked v17 flattened tree with lossless properties/reserve entries."""

    def __init__(self, blob):
        require(len(blob) >= 40, "short FDT header")
        magic, total, off_tree, off_strings, off_reserve, version, compatible, self.boot_cpu, strings_size, tree_size = struct.unpack_from(">10I", blob)
        require(magic == 0xd00dfeed and total == len(blob), "FDT magic/total size/trailing data")
        require(version == 17 and compatible <= 17, "requires FDT v17")
        require(off_tree % 4 == 0 and off_reserve % 8 == 0 and tree_size % 4 == 0, "FDT block alignment")
        for offset, size in ((off_tree, tree_size), (off_strings, strings_size)):
            require(40 <= offset <= total and 0 < size <= total - offset, "FDT block bounds")
        self.reserves = []
        cursor = off_reserve
        while True:
            require(40 <= cursor and cursor + 16 <= total, "FDT reserve table bounds/terminator")
            address, size = struct.unpack_from(">QQ", blob, cursor)
            cursor += 16
            if address == size == 0:
                break
            require(size > 0 and address + size <= 1 << 64, "invalid FDT memreserve")
            self.reserves.append((address, size))
        blocks = sorted(((0, 40), (off_reserve, cursor), (off_tree, off_tree + tree_size), (off_strings, off_strings + strings_size)))
        require(all(a[1] <= b[0] for a, b in zip(blocks, blocks[1:])), "overlapping FDT blocks")
        strings = blob[off_strings:off_strings + strings_size]
        cursor, limit, stack = off_tree, off_tree + tree_size, []
        self.nodes = {}
        closed = False
        while cursor + 4 <= limit:
            token = struct.unpack_from(">I", blob, cursor)[0]
            cursor += 4
            if token == 1:
                end = blob.find(b"\0", cursor, limit)
                require(end >= cursor and not closed, "FDT node name/root")
                name = blob[cursor:end].decode("ascii")
                require((not stack and name == "" and not self.nodes) or
                        (bool(stack) and name and "/" not in name and name not in (".", "..")), "invalid FDT node name")
                require(align(end + 1, 4) <= limit, "FDT node alignment bounds")
                cursor = align(end + 1, 4)
                stack.append(name)
                path = "/" + "/".join(stack[1:])
                require(path not in self.nodes, "duplicate FDT node")
                self.nodes[path] = {}
            elif token == 2:
                require(stack, "unbalanced FDT_END_NODE")
                stack.pop()
                closed = not stack
            elif token == 3:
                require(stack and cursor + 8 <= limit, "FDT property header")
                size, offset = struct.unpack_from(">II", blob, cursor)
                cursor += 8
                require(offset < len(strings) and size <= limit - cursor, "FDT property bounds")
                end = strings.find(b"\0", offset)
                require(end > offset, "FDT property name")
                name = strings[offset:end].decode("ascii")
                props = self.nodes["/" + "/".join(stack[1:])]
                require(name not in props, "duplicate FDT property")
                props[name] = blob[cursor:cursor + size]
                # libfdt edits can leave arbitrary alignment bytes; encode() clears them.
                require(align(cursor + size, 4) <= limit, "FDT property alignment bounds")
                cursor = align(cursor + size, 4)
            elif token == 4:
                pass
            elif token == 9:
                require(closed and not stack and cursor == limit, "FDT_END position")
                return
            else:
                raise ValueError(f"invalid FDT token {token}")
        raise ValueError("missing FDT_END")

    def encode(self):
        strings, offsets, tree = bytearray(), {}, bytearray()

        def word(value):
            tree.extend(struct.pack(">I", value))

        def node(path):
            word(1)
            tree.extend((path.rsplit("/", 1)[-1] if path != "/" else "").encode() + b"\0")
            tree.extend(bytes(align(len(tree), 4) - len(tree)))
            for name, value in self.nodes[path].items():
                if name not in offsets:
                    offsets[name] = len(strings)
                    strings.extend(name.encode() + b"\0")
                word(3)
                tree.extend(struct.pack(">II", len(value), offsets[name]))
                tree.extend(value)
                tree.extend(bytes(align(len(tree), 4) - len(tree)))
            for child in self.nodes:
                if child != "/" and (child.rsplit("/", 1)[0] or "/") == path:
                    node(child)
            word(2)

        node("/")
        word(9)
        reserve = b"".join(struct.pack(">QQ", a, n) for a, n in self.reserves) + bytes(16)
        off_tree = 40 + len(reserve)
        off_strings = off_tree + len(tree)
        header = struct.pack(">10I", 0xd00dfeed, off_strings + len(strings), off_tree, off_strings, 40, 17, 16, self.boot_cpu, len(strings), len(tree))
        return header + reserve + tree + strings

    def memory_contract(self, start, end):
        def cells(props, name, default):
            value = props.get(name, struct.pack(">I", default))
            require(len(value) == 4, "invalid FDT cell count")
            count = struct.unpack(">I", value)[0]
            require(count in (1, 2), "unsupported FDT address/size cells")
            return count

        def ranges(value, parent):
            ac, sc = cells(parent, "#address-cells", 2), cells(parent, "#size-cells", 1)
            stride = 4 * (ac + sc)
            require(value and len(value) % stride == 0, "invalid FDT reg tuples")
            result = []
            for offset in range(0, len(value), stride):
                a = int.from_bytes(value[offset:offset + 4 * ac], "big")
                n = int.from_bytes(value[offset + 4 * ac:offset + stride], "big")
                require(n and a + n <= 1 << 64, "invalid FDT RAM interval")
                result.append((a, a + n))
            return result

        banks, reservations = [], [("memreserve", a, a + n) for a, n in self.reserves]
        for path, props in self.nodes.items():
            if props.get("status", b"okay\0") not in (b"ok\0", b"okay\0"):
                continue
            if path.count("/") == 1 and props.get("device_type") == b"memory\0":
                banks.extend(ranges(props.get("reg", b""), self.nodes["/"]))
            if path.startswith("/reserved-memory/") and path.count("/") == 2:
                parent = self.nodes["/reserved-memory"]
                require(parent.get("ranges") == b"", "reserved-memory must use identity ranges")
                if "reg" in props:
                    reservations.extend((path, a, b) for a, b in ranges(props["reg"], parent))
                else:
                    require("size" not in props, "dynamic reserved RAM cannot be proven disjoint offline")
        banks.sort()
        require(banks and all(a[1] <= b[0] for a, b in zip(banks, banks[1:])), "missing/overlapping RAM banks")
        require(any(a <= start < end <= b for a, b in banks), "payload outside a real FDT RAM bank")
        for name, low, high in reservations:
            require(end <= low or high <= start, f"payload overlaps reserved RAM {name}: {low:#x}..{high:#x}")
        return {"banks": banks, "reserved": reservations}


def stock_dtbs(blob):
    cursor, hashes = 0, []
    while cursor < len(blob):
        require(cursor + 8 <= len(blob), "stock DTB trailer bounds")
        size = struct.unpack_from(">I", blob, cursor + 4)[0]
        require(40 <= size <= len(blob) - cursor, "stock DTB trailer size")
        part = blob[cursor:cursor + size]
        Fdt(part)
        hashes.append(sha(part))
        cursor += size
    require(hashes, "missing stock acceptance DTB trailer")
    return hashes


def cpio(blob):
    cursor, entries = 0, {}
    while True:
        require(cursor + 110 <= len(blob) and blob[cursor:cursor + 6] == b"070701", "newc header/bounds")
        header = blob[cursor + 6:cursor + 110]
        require(re.fullmatch(b"[0-9a-fA-F]{104}", header), "newc hex header")
        fields = [int(header[i:i + 8], 16) for i in range(0, 104, 8)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        name_start = cursor + 110
        name_end = name_start + namesize
        require(namesize > 1 and name_end <= len(blob) and blob[name_end - 1] == 0 and
                b"\0" not in blob[name_start:name_end - 1] and fields[12] == 0, "newc name/checksum")
        name = blob[name_start:name_end - 1].decode("utf-8")
        data_start, data_end = align(name_end, 4), align(name_end, 4) + size
        require(align(data_end, 4) <= len(blob), "newc data bounds")
        require(not any(blob[name_end:data_start]) and not any(blob[data_end:align(data_end, 4)]), "newc nonzero padding")
        if name == "TRAILER!!!":
            require(size == 0 and not any(blob[data_end:]), "newc trailer/trailing data")
            for path, (entry_mode, data) in entries.items():
                if stat.S_ISLNK(entry_mode):
                    target = data.decode("utf-8")
                    require(target and "\0" not in target and ".." not in target.split("/"), "unsafe newc symlink")
                for parent in PurePosixPath(path).parents:
                    if str(parent) in entries:
                        require(stat.S_ISDIR(entries[str(parent)][0]), "newc path crosses non-directory/symlink")
            return entries
        require(not name.startswith("/") and ".." not in name.split("/"), "unsafe newc path traversal")
        name = str(PurePosixPath(name))
        require(name not in entries and name, "duplicate/empty newc path")
        require(stat.S_IFMT(mode) in (stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK), "newc file type")
        require(name != "." or stat.S_ISDIR(mode), "newc root must be a directory")
        require(not stat.S_ISREG(mode) or fields[4] == 1, "newc hardlinked regular files are unsupported; store independent file data")
        require(stat.S_IFMT(mode) not in (stat.S_IFDIR, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK) or size == 0, "newc special file data")
        entries[name] = (mode, blob[data_start:data_end])
        cursor = align(data_end, 4)


def check_init(entries, bootargs):
    def resolve(path):
        require(path.startswith("/") and ".." not in path.split("/"), "unsafe init/interpreter path")
        path = str(PurePosixPath(path.lstrip("/")))
        seen = set()
        while True:
            require(path not in seen, "init symlink loop")
            seen.add(path)
            parts = path.split("/")
            for i in range(1, len(parts) + 1):
                prefix = "/".join(parts[:i])
                if prefix not in entries:
                    require(i < len(parts), "missing init/interpreter: /" + path)
                    continue
                mode, data = entries[prefix]
                if stat.S_ISLNK(mode):
                    target = data.decode("utf-8")
                    require(target and "\0" not in target and ".." not in target.split("/"), "unsafe newc symlink")
                    base = "" if target.startswith("/") else "/".join(parts[:i - 1])
                    path = str(PurePosixPath(base, target.lstrip("/"), *parts[i:]))
                    break
                require(i == len(parts) or stat.S_ISDIR(mode), "init path crosses non-directory")
            else:
                require(stat.S_ISREG(mode) and mode & 0o111 and data, "init/interpreter must be executable regular file")
                return path, data

    args = shlex.split(bootargs)
    selected = [arg.split("=", 1)[1] for arg in args if arg.startswith("rdinit=")]
    require(len(selected) <= 1, "duplicate rdinit")
    initial = selected[0] if selected else "/init"
    path, data = resolve(initial)
    chain = []
    while data.startswith(b"#!"):
        require(path not in chain and len(chain) < 4, "init script interpreter recursion")
        chain.append(path)
        line = data.split(b"\n", 1)[0]
        require(len(line) <= 255, "init shebang too long")
        # Linux passes the optional tail as one argument; it does not unquote it.
        interpreter = re.split(r"[ \t]+", line[2:].decode("ascii").strip(" \t"), maxsplit=1)
        require(interpreter[0], "unsupported init shebang")
        path, data = resolve(interpreter[0])
    require(len(data) >= 64 and data[:7] == b"\x7fELF\x02\x01\x01", "init requires static little-endian AArch64 ELF (or script with static interpreter)")
    kind, machine, version, entry, phoff = struct.unpack_from("<HHIQQ", data, 16)
    ehsize, phsize, phnum = struct.unpack_from("<HHH", data, 52)
    require((kind, machine, version, ehsize, phsize) == (2, 183, 1, 64, 56) and
            phnum and 64 <= phoff <= len(data) and phnum * phsize <= len(data) - phoff, "invalid static init ELF header/program bounds")
    executable = False
    for index in range(phnum):
        ptype, flags, offset, virtual, _, filesz, memsz, _ = struct.unpack_from("<IIQQQQQQ", data, phoff + index * phsize)
        require(ptype not in (2, 3), "dynamic init/interpreter is unsupported")
        require(offset <= len(data) and filesz <= len(data) - offset, "init ELF segment bounds")
        if ptype == 1:
            require(filesz <= memsz and virtual + memsz <= 1 << 64, "init ELF load segment size")
            executable |= bool(flags & 1 and virtual <= entry < virtual + filesz)
    require(executable, "init ELF entry outside executable segment")
    return {"entry": initial, "resolved_elf": "/" + path, "elf_sha256": sha(data)}


def kernel_header(kernel):
    require(len(kernel) >= 64 and kernel[56:60] == b"ARM\x64", "ARM64 Image magic/header")
    offset, size, flags = struct.unpack_from("<QQQ", kernel, 8)
    require(offset == 0 and len(kernel) <= size <= MAX_RAW - 2 * ALIGN and flags & 1 == 0 and flags & 8,
            "Image must be little endian, freely placeable, text_offset=0, with valid declared image_size")
    return size


def cmdline(data):
    value = data.decode("ascii")
    if value.endswith("\n"):
        value = value[:-1]
    require(value and len(value) <= CMDLINE_LIMIT and all(32 <= ord(c) < 127 for c in value), "cmdline must be one nonempty ASCII line, at most 2047 bytes")
    shlex.split(value)
    return value


def load_template(directory):
    info = json.loads((directory / "template.json").read_text())
    require(info["schema"] == "lgg8-boot-template-v1" and re.fullmatch(r"[0-9a-f]{64}", info["source_boot_sha256"]), "template schema/source SHA-256")
    parts = {}
    for key, filename in (("header", "header.bin"), ("external_ramdisk", "dummy-ramdisk"), ("stock_dtbs", "stock-dtbs.bin")):
        parts[key] = (directory / filename).read_bytes()
        require(describe(parts[key]) == info["components"][key], "template component hash: " + key)
    require(len(parts["header"]) == PAGE and parts["external_ramdisk"] == b"dummy\n", "template header/dummy ramdisk")
    require(stock_dtbs(parts["stock_dtbs"]) == info["stock_dtb_sha256"], "template stock DTB hashes")
    header = parts["header"]
    require(header[:8] == b"ANDROID!" and struct.unpack_from("<I", header, 36)[0] == PAGE and
            struct.unpack_from("<I", header, 40)[0] == 0 and struct.unpack_from("<I", header, 24)[0] == 0 and
            struct.unpack_from("<I", header, 16)[0] == 6 and not any(header[1632:]), "unsupported template header")
    require(info["kernel_size"] == struct.unpack_from("<I", header, 8)[0] and info["boot_id"] == header[576:608].hex(), "template original header fields")
    return info, parts


def publish(directory, files):
    # Exclusive mkdir also rejects dangling symlinks and empty existing directories.
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        for name, data in files.items():
            (directory / name).write_bytes(data)
    except BaseException:
        for name in files:
            (directory / name).unlink(missing_ok=True)
        directory.rmdir()
        raise


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def prepare_template(args):
    require(not args.output.exists() and not args.output.is_symlink(), "output already exists")
    blob = args.from_boot.read_bytes()
    require(re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256) and sha(blob) == args.sha256.lower(), "trusted full source boot SHA-256 mismatch")
    header, kernel, ramdisk = unpack_boot(blob)
    require(ramdisk == b"dummy\n", "template must be a verified RAM boot with external dummy ramdisk")
    raw, stock = gunzip_member(kernel)
    require(len(raw) >= PAGE + 64 and raw[56:60] == b"ARM\x64" and struct.unpack_from("<Q", raw, 16)[0] == len(raw), "template must contain ARM64 shim + payload")
    info = {"schema": "lgg8-boot-template-v1", "source_boot_sha256": sha(blob), "source_boot_size": len(blob),
            "kernel_size": len(kernel), "boot_id": header[576:608].hex(), "stock_dtb_sha256": stock_dtbs(stock),
            "components": {"header": describe(header), "external_ramdisk": describe(ramdisk), "stock_dtbs": describe(stock)},
            "acceptance": "Caller-pinned RAM-boot envelope only; no partition-size or device-acceptance inference."}
    publish(args.output, {"header.bin": header, "dummy-ramdisk": ramdisk, "stock-dtbs.bin": stock, "template.json": json_bytes(info)})
    return info


def compile_shim(source, payload, dtb_address):
    with tempfile.TemporaryDirectory(prefix="lgg8-bootimg-") as temporary:
        directory = Path(temporary)
        (directory / "shim.S").write_bytes(source)
        (directory / "payload.bin").write_bytes(payload)
        commands = [
            ["clang", "--target=aarch64-none-elf", "-c", "shim.S", "-DDIAGNOSTIC_PSCI_RESET", f"-DLOAD_ADDRESS={LOAD:#x}", f"-DDTB_ADDRESS={dtb_address:#x}", f"-DPAYLOAD_SIZE={len(payload)}", '-DPAYLOAD_PATH="payload.bin"', "-o", "shim.o"],
            ["ld.lld", "--image-base=0", "-Ttext=0", "--entry=_start", "shim.o", "-o", "shim.elf"],
            ["llvm-objcopy", "-O", "binary", "--only-section=.text", "shim.elf", "shim.Image"],
        ]
        for command in commands:
            result = subprocess.run(command, cwd=directory, capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
            require(result.returncode == 0, f"{command[0]} failed: {result.stderr.strip()}")
        raw = (directory / "shim.Image").read_bytes()
    require(len(raw) == PAGE + len(payload) and raw[PAGE:] == payload and raw[56:60] == b"ARM\x64" and
            struct.unpack_from("<Q", raw, 16)[0] == len(raw), "linked shim header/payload mismatch")
    return raw


def build_provenance(repo_root, config_path=None):
    """Record source/config/tool identity without making Git availability a build dependency."""
    repo_root = Path(repo_root).resolve()

    def git_output(*args):
        try:
            result = subprocess.run(["git", "-C", str(repo_root), *args], check=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            output = result.stdout
            return output.encode() if isinstance(output, str) else output
        except (OSError, subprocess.CalledProcessError):
            return None

    status = git_output("status", "--porcelain=v1", "--untracked-files=all")
    commit = git_output("rev-parse", "--verify", "HEAD")
    diff = git_output("diff", "--binary", "HEAD")
    untracked = git_output("ls-files", "--others", "--exclude-standard", "-z")

    untracked_hash = hashlib.sha256()
    untracked_count = 0
    if untracked is not None:
        for name in untracked.split(b"\0"):
            if not name:
                continue
            path = repo_root / os.fsdecode(name)
            untracked_hash.update(name + b"\0")
            try:
                if path.is_symlink():
                    untracked_hash.update(b"L" + os.fsencode(os.readlink(path)))
                elif path.is_file():
                    with path.open("rb") as stream:
                        while block := stream.read(1024 * 1024):
                            untracked_hash.update(block)
                else:
                    untracked_hash.update(b"MISSING")
            except OSError:
                untracked_hash.update(b"UNREADABLE")
            untracked_hash.update(b"\0")
            untracked_count += 1

    def version(command, *args):
        executable = shutil.which(command)
        if not executable:
            return None
        try:
            result = subprocess.run([executable, *args], check=True, capture_output=True,
                                    text=True, timeout=5, env={**os.environ, "LC_ALL": "C"})
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        output = result.stdout or result.stderr
        return output.splitlines()[0][:160] if output else None

    config = None
    symbols = {}
    if config_path is not None:
        config_bytes = Path(config_path).read_bytes()
        config_lines = config_bytes.decode("ascii", errors="replace").splitlines()
        wanted = ("CONFIG_DRM_MSM", "CONFIG_DRM_MSM_DPU_PSTORE_DIAG",
                  "CONFIG_PSTORE_CONSOLE", "CONFIG_PSTORE_RAM", "CONFIG_PSTORE_FTRACE")
        for symbol in wanted:
            value = next((line.split("=", 1)[1] for line in config_lines
                          if line.startswith(symbol + "=")), None)
            if value is None and f"# {symbol} is not set" in config_lines:
                value = "n"
            symbols[symbol] = value
        config = describe(config_bytes)

    seed_path = repo_root / "lgg8/configs/lgg8.config"
    seed_config = describe(seed_path.read_bytes()) if seed_path.is_file() else None
    return {
        "schema": "lgg8-build-provenance-v1",
        "source_commit": commit.decode().strip() if commit else None,
        "source_dirty": bool(status) if status is not None else None,
        "tracked_diff_sha256": sha(diff) if diff is not None else None,
        "untracked_file_count": untracked_count if untracked is not None else None,
        "untracked_tree_sha256": untracked_hash.hexdigest() if untracked is not None else None,
        "effective_config": config,
        "config_symbols": symbols,
        "seed_config": seed_config,
        "toolchain": {
            "clang": version("clang", "--version"),
            "ld_lld": version("ld.lld", "--version"),
            "dtc": version("dtc", "--version"),
            "make": version("make", "--version"),
            "aarch64_gcc": version("aarch64-linux-gnu-gcc", "--version"),
            "python": sys.version.split()[0],
        },
    }


def record_kernel_build(args):
    kernel, dtb = args.kernel.read_bytes(), args.dtb.read_bytes()
    config = args.config.read_bytes()
    receipt = {
        "schema": "lgg8-kernel-build-v1",
        "profile": args.profile,
        "components": {"kernel": describe(kernel), "dtb": describe(dtb), "effective_config": describe(config)},
        "provenance": build_provenance(Path(__file__).resolve().parents[2], args.config),
    }
    destination = args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + destination.name + ".", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json_bytes(receipt))
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return receipt


def load_kernel_build_provenance(path, kernel, dtb, config):
    receipt = json.loads(Path(path).read_text())
    require(receipt.get("schema") == "lgg8-kernel-build-v1", "kernel build provenance schema")
    for name, data in (("kernel", kernel), ("dtb", dtb), ("effective_config", config)):
        require(receipt.get("components", {}).get(name) == describe(data),
                "kernel build provenance input mismatch: " + name)
    require(receipt.get("provenance", {}).get("schema") == "lgg8-build-provenance-v1",
            "kernel build provenance source record")
    return {**receipt["provenance"], "capture_stage": "kernel-build", "profile": receipt.get("profile")}


def build(args):
    require(not args.output.exists() and not args.output.is_symlink(), "output already exists")
    require(args.partition_size > 0, "--partition-size must be confirmed positive bytes")
    info, template = load_template(args.template)
    minimum_size = PAGE + align(18 + len(template["stock_dtbs"]), PAGE) + align(len(template["external_ramdisk"]), PAGE)
    require(args.partition_size >= minimum_size, "boot image exceeds explicitly supplied partition size (envelope alone cannot fit)")
    kernel, initrd = args.kernel.read_bytes(), args.initramfs.read_bytes()
    source_dtb = args.dtb.read_bytes()
    config_path = getattr(args, "config", None)
    build_provenance_path = getattr(args, "build_provenance", None)
    config_bytes = Path(config_path).read_bytes() if config_path is not None else None
    if build_provenance_path is not None:
        require(config_bytes is not None, "--config is required with --build-provenance")
        provenance = load_kernel_build_provenance(build_provenance_path, kernel, source_dtb, config_bytes)
    else:
        provenance = build_provenance(Path(__file__).resolve().parents[2], config_path)
        provenance["capture_stage"] = "package"
    image_size = kernel_header(kernel)
    cmdline_file = args.cmdline_file.read_bytes()
    bootargs = cmdline(cmdline_file)
    init = check_init(cpio(initrd), bootargs)
    tree = Fdt(source_dtb)
    initrd_offset = align(image_size, ALIGN)
    dtb_offset = align(initrd_offset + len(initrd), ALIGN)
    require(dtb_offset + len(source_dtb) + 8192 <= MAX_RAW, "payload allocation limit")
    chosen = tree.nodes.setdefault("/chosen", {})
    chosen.update({"bootargs": bootargs.encode() + b"\0", "linux,initrd-start": struct.pack(">Q", LOAD + initrd_offset),
                   "linux,initrd-end": struct.pack(">Q", LOAD + initrd_offset + len(initrd))})
    dtb = tree.encode()
    require(len(dtb) <= ALIGN, "ARM64 boot DTB must not exceed 2 MiB")
    payload_size = align(dtb_offset + len(dtb), 16)
    memory = Fdt(dtb).memory_contract(LOAD, LOAD + payload_size)
    payload = bytearray(payload_size)
    payload[:len(kernel)] = kernel
    payload[initrd_offset:initrd_offset + len(initrd)] = initrd
    payload[dtb_offset:dtb_offset + len(dtb)] = dtb
    source = SHIM_SOURCE.read_bytes()
    raw = compile_shim(source, payload, LOAD + dtb_offset)
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    require(0 <= epoch <= 0xffffffff, "SOURCE_DATE_EPOCH must fit gzip uint32")
    compressed = gzip_member(raw, epoch)
    blob = pack_boot(template["header"], compressed + template["stock_dtbs"], template["external_ramdisk"])
    require(len(blob) <= args.partition_size, "boot image exceeds explicitly supplied partition size")
    components = {key: describe(value) for key, value in {
        "image": blob, "kernel": kernel, "initramfs": initrd, "dtb": dtb, "payload": payload,
        "shim": raw[:PAGE], "raw": raw, "gzip": compressed, "stock_dtbs": template["stock_dtbs"],
        "external_ramdisk": template["external_ramdisk"], "source_dtb": source_dtb, "shim_source": source,
        "cmdline_file": cmdline_file}.items()}
    manifest = {"schema": "lgg8-boot-image-v1", "source_date_epoch": epoch, "partition_size": args.partition_size,
                "template": info, "components": components, "load_address": LOAD, "kernel_image_size": image_size,
                "initrd_address": LOAD + initrd_offset, "initrd_end": LOAD + initrd_offset + len(initrd),
                "dtb_address": LOAD + dtb_offset, "payload_end": LOAD + payload_size, "memory": memory,
                "bootargs": bootargs, "init": init, "shim_defines": ["DIAGNOSTIC_PSCI_RESET"],
                "device_acceptance": "NOT_TESTED", "partition_size_source": "explicit caller argument; not probed",
                "provenance": provenance}
    verify_bytes(blob, manifest)
    publish(args.output, {"boot.img": blob, "manifest.json": json_bytes(manifest), "linux.dtb": dtb})
    return manifest


def verify_bytes(blob, manifest):
    require(manifest["schema"] == "lgg8-boot-image-v1", "manifest schema")
    parts = manifest["components"]

    def check(name, data):
        require(describe(data) == parts[name], "trusted manifest component hash/size: " + name)

    check("image", blob)
    require(type(manifest["partition_size"]) is int and 0 < len(blob) <= manifest["partition_size"], "partition size limit")
    header, packed, ramdisk = unpack_boot(blob)
    check("external_ramdisk", ramdisk)
    require(ramdisk == b"dummy\n", "external dummy ramdisk changed")
    info = manifest["template"]
    require(info["schema"] == "lgg8-boot-template-v1" and re.fullmatch("[0-9a-f]{64}", info["source_boot_sha256"]), "manifest template provenance")
    original = bytearray(header)
    struct.pack_into("<I", original, 8, info["kernel_size"])
    original[576:608] = bytes.fromhex(info["boot_id"])
    require(len(original) == PAGE and describe(original) == info["components"]["header"] and
            describe(ramdisk) == info["components"]["external_ramdisk"], "preserved exact template envelope")
    raw, stock = gunzip_member(packed)
    compressed = packed[:len(packed) - len(stock)]
    check("gzip", compressed)
    require(compressed[:10] == b"\x1f\x8b\x08\x00" + struct.pack("<I", manifest["source_date_epoch"]) + b"\x02\xff", "deterministic gzip header/epoch")
    check("stock_dtbs", stock)
    require(describe(stock) == info["components"]["stock_dtbs"] and stock_dtbs(stock) == info["stock_dtb_sha256"], "exact stock DTB acceptance trailer")
    check("raw", raw)
    require(len(raw) >= PAGE + 64 and raw[56:60] == b"ARM\x64" and
            struct.unpack_from("<QQQ", raw, 8) == (0, len(raw), 0xa), "shim Image header")
    check("shim", raw[:PAGE])
    payload = raw[PAGE:]
    check("payload", payload)
    require(manifest["load_address"] == LOAD and manifest["payload_end"] == LOAD + len(payload), "load/payload extent")
    kernel_size = parts["kernel"]["size"]
    require(type(kernel_size) is int and 64 <= kernel_size <= len(payload), "kernel embedded bounds")
    kernel = payload[:kernel_size]
    check("kernel", kernel)
    image_size = kernel_header(kernel)
    require(image_size == manifest["kernel_image_size"], "declared kernel Image size")
    initrd_offset = align(image_size, ALIGN)
    initrd_size = parts["initramfs"]["size"]
    require(type(initrd_size) is int and initrd_size > 0 and initrd_offset + initrd_size <= len(payload), "initramfs embedded bounds")
    dtb_offset = align(initrd_offset + initrd_size, ALIGN)
    dtb_size = parts["dtb"]["size"]
    require(type(dtb_size) is int and 40 <= dtb_size <= ALIGN and dtb_offset + dtb_size <= len(payload) and
            len(payload) == align(dtb_offset + dtb_size, 16), "DTB embedded bounds")
    require(manifest["initrd_address"] == LOAD + initrd_offset and manifest["initrd_end"] == LOAD + initrd_offset + initrd_size and
            manifest["dtb_address"] == LOAD + dtb_offset, "initramfs/DTB placement")
    require(not any(payload[kernel_size:initrd_offset]) and not any(payload[initrd_offset + initrd_size:dtb_offset]) and
            not any(payload[dtb_offset + dtb_size:]), "nonzero payload padding/kernel BSS")
    initrd, dtb = payload[initrd_offset:initrd_offset + initrd_size], payload[dtb_offset:dtb_offset + dtb_size]
    check("initramfs", initrd)
    check("dtb", dtb)
    tree = Fdt(dtb)
    chosen = tree.nodes.get("/chosen", {})
    bootargs = manifest["bootargs"]
    require(cmdline(bootargs.encode()) == bootargs, "invalid manifest bootargs")
    require(parts["cmdline_file"] in (describe(bootargs.encode()), describe(bootargs.encode() + b"\n")), "cmdline file hash")
    require(chosen.get("bootargs") == bootargs.encode() + b"\0" and
            chosen.get("linux,initrd-start") == struct.pack(">Q", LOAD + initrd_offset) and
            chosen.get("linux,initrd-end") == struct.pack(">Q", LOAD + initrd_offset + initrd_size), "chosen bootargs/initrd addresses")
    memory = tree.memory_contract(LOAD, LOAD + len(payload))
    require(json_bytes(memory) == json_bytes(manifest["memory"]), "manifest RAM contract")
    require(check_init(cpio(initrd), bootargs) == manifest["init"], "manifest init execution chain")
    return {"status": "PASSED", "image_sha256": sha(blob), "image_size": len(blob), "partition_size": manifest["partition_size"],
            "stock_dtb_count": len(info["stock_dtb_sha256"]), "device_acceptance": "NOT_TESTED"}


def number(value):
    return int(value, 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-template", help="extract private, caller-SHA-pinned verified v0 RAM-boot envelope")
    prepare.add_argument("--from-boot", required=True, type=Path)
    prepare.add_argument("--sha256", required=True, help="trusted full SHA-256, obtained independently")
    prepare.add_argument("--output", required=True, type=Path, help="new directory; never overwritten")
    pack = sub.add_parser("build", help="build boot.img, manifest.json and patched linux.dtb")
    for name in ("kernel", "dtb", "initramfs", "template", "cmdline-file", "output"):
        pack.add_argument("--" + name, required=True, type=Path)
    pack.add_argument("--config", type=Path, help="effective kernel .config used to build the Image")
    pack.add_argument("--build-provenance", type=Path, help="kernel-build receipt; rejects inputs that differ from the recorded build")
    pack.add_argument("--partition-size", required=True, type=number, help="confirmed partition capacity in bytes; decimal or 0x hex, no default")
    record = sub.add_parser("record-kernel-build", help="record source/config and exact kernel/DTB hashes after a build")
    for name in ("kernel", "dtb", "config", "output"):
        record.add_argument("--" + name, required=True, type=Path)
    record.add_argument("--profile", required=True, help="build.sh action that produced these outputs")
    verify = sub.add_parser("verify", help="independently inspect embedded components against a trusted manifest",
                            description="The trusted manifest pins the compiled shim bytes. Verification does not recompile the shim or prove its instruction semantics/device acceptance.")
    verify.add_argument("--image", required=True, type=Path)
    verify.add_argument("--manifest", required=True, type=Path, help="trusted, reviewed manifest; an image and untrusted manifest can be changed together")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-template":
            result = prepare_template(args)
        elif args.command == "build":
            result = build(args)
        elif args.command == "record-kernel-build":
            result = record_kernel_build(args)
        else:
            result = verify_bytes(args.image.read_bytes(), json.loads(args.manifest.read_text()))
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, struct.error, RecursionError) as error:
        print(f"bootimg: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
