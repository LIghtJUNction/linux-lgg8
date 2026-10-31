#!/usr/bin/env python3
"""C224 review by default. Device execution requires --execute-ram-only --serial.

The observation commands only read the whitelist. USB bus power can continue
inherited charging. Neither this runner nor successful recovery proves stop,
fresh temperature, functioning protection, or charging safety.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import re
import secrets
import select
import shlex
import signal
import struct
import subprocess
import sys
import termios
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "out/lgg8-c224-fg-presence-observe-20261031"
IMAGE = HERE / "boot/boot.img"
IMAGE_SHA = "c535c66a42eaf836c0267b4c29913962b23824e8a8df3b788c14aadee3b7f4cf"
REFERENCE = ROOT / "out/lgg8-c210-sw42000-touch-20261031/run-c210-ram-only.py"
REFERENCE_SHA = "2a9ab6fbb93c863287c69b97604597aa53f10220e0fc049b4c82b48ebf68288a"
C223 = ROOT / "out/lgg8-c223-smb5-icl-observe-20261031"
C223_SHA = "5ba74b93049fcdf6b95bf7a2c14977f4dba765ea8641fb8d98ed4f68fdddc203"
PORT = "1-2"
USB_ROOT = Path("/sys/bus/usb/devices")
PARTITION_SIZE = 100663296
BOOT_HASHES = {
    "boot_a": "a826651669b4e9c8e2835e315082cedb821585a683fea9afede3f23517cfe4e6",
    "boot_b": "fec418e5227a31927af27daf71d2225246f5adcf8dda38b5856200760b5205cd",
}
RISK = {
    "external_usb_power_possible": True,
    "inherited_charging_possible": True,
    "charging_control_writes_requested": False,
    "charging_stopped_verified": False,
    "charging_safety_validated": False,
    "temperature_freshness_verified": False,
    "whole_kernel_zero_pmic_writes_proven": False,
    "transport_authentication_provided": False,
}
MAX_SAMPLE_GAP_NS = 1_000_000_000
MONITOR_STOP_SECONDS = 2.0
HEARTBEAT = struct.Struct("!QQQ32s")
FG = "/sys/class/power_supply/pm8150b-fg-observer"
SMB = "/sys/class/power_supply/pm8150b-smb5-status"
FIELDS = (
    [("fg_" + k, FG + "/" + k, "bool" if k == "present" else "int")
     for k in ("present", "voltage_now", "current_now")]
    + [("fg_" + k, FG + "/device/" + k, "raw") for k in (
        "battery_temp_status", "rradc_realtime_status", "battery_temp_rr_raw",
        "rradc_therm_config", "rradc_therm_period")]
    + [("smb_" + k, SMB + "/" + k, "bool") for k in ("present", "online")]
    + [("smb_" + k, SMB + "/device/" + k, "raw") for k in (
        "charger_status", "battery_status", "temperature_status",
        "charge_enable_command", "charge_pause_command", "usb_suspend_command",
        "jeita_config", "jeita_soft_hot_msb", "jeita_soft_hot_lsb",
        "jeita_soft_cold_msb", "jeita_soft_cold_lsb", "thermal_source_config",
        "usb_icl_config", "icl_max_status", "aicl_icl_status")]
)
METADATA = [
    ("linux_boot_id", "/proc/sys/kernel/random/boot_id", "uuid"),
    ("linux_cmdline", "/proc/cmdline", "cmdline"),
    ("linux_uptime", "/proc/uptime", "uptime"),
]
NODE_LINKS = [
    ("fg_driver", FG + "/device/driver", "/sys/bus/platform/drivers/qcom-pm8150b-fg-observer"),
    ("smb_driver", SMB + "/device/driver", "/sys/bus/platform/drivers/qcom-pm8150b-smb5-status"),
    ("fg_of_node", FG + "/device/of_node", "/sys/firmware/devicetree/base/soc@0/spmi@c440000/pmic@2/battery-info@4100"),
    ("smb_of_node", SMB + "/device/of_node", "/sys/firmware/devicetree/base/soc@0/spmi@c440000/pmic@2/charger@1000"),
]


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_manifest(m, baseline, provenance):
    if m.get("schema") != "lgg8-boot-image-v1" or m.get("device_acceptance") != "NOT_TESTED":
        raise RuntimeError("candidate schema/acceptance mismatch")
    if m.get("partition_size") != PARTITION_SIZE:
        raise RuntimeError("partition ceiling mismatch")
    if m["components"]["image"]["sha256"] != IMAGE_SHA:
        raise RuntimeError("manifest image hash mismatch")
    if baseline["components"]["image"]["sha256"] != C223_SHA:
        raise RuntimeError("C223 reference identity mismatch")
    for name in ("dtb", "source_dtb", "initramfs", "stock_dtbs", "external_ramdisk", "cmdline_file"):
        if m["components"][name] != baseline["components"][name]:
            raise RuntimeError("changed C223 input: " + name)
    if m["bootargs"] != baseline["bootargs"] or m.get("source_date_epoch") != baseline.get("source_date_epoch"):
        raise RuntimeError("bootargs/timestamp differs from C223")
    if not all(x in m["bootargs"].split() for x in (
            "rdinit=/init", "watchdog.open_timeout=60", "lgg8.usb_shell=1", "lgg8.pmsg_tag=C198")):
        raise RuntimeError("missing existing recovery/USB settings")
    if provenance.get("schema") != "lgg8-kernel-build-v1" or provenance.get("profile") != "kernel":
        raise RuntimeError("invalid build provenance")
    for name, key in (("kernel", "kernel"), ("dtb", "source_dtb")):
        if provenance["components"][name] != m["components"][key]:
            raise RuntimeError("build provenance component mismatch: " + name)
    p = dict(m["provenance"])
    if p.pop("capture_stage", None) != "kernel-build" or p.pop("profile", None) != "kernel":
        raise RuntimeError("incorrect provenance capture stage/profile")
    if p != provenance["provenance"]:
        raise RuntimeError("build provenance receipt mismatch")


def review():
    # No subprocess, legacy-module import, USB enumeration, or /dev access.
    if file_sha(IMAGE) != IMAGE_SHA:
        raise RuntimeError("C224 full image hash mismatch")
    if file_sha(REFERENCE) != REFERENCE_SHA:
        raise RuntimeError("legacy helper hash mismatch; review before importing")
    m = json.loads((HERE / "boot/manifest.json").read_text())
    baseline = json.loads((C223 / "boot/manifest.json").read_text())
    provenance = json.loads((HERE / "build-provenance.json").read_text())
    check_manifest(m, baseline, provenance)
    if IMAGE.stat().st_size != m["components"]["image"]["size"] or IMAGE.stat().st_size > PARTITION_SIZE:
        raise RuntimeError("image size mismatch")
    return {"candidate": "C224", "mode": "OFFLINE_REVIEW_ONLY", "image_sha256": IMAGE_SHA,
            "reference_sha256": REFERENCE_SHA, "sysfs_fields": FIELDS,
            "metadata": METADATA, "node_identity_links": NODE_LINKS,
            "risk": dict(RISK), "device_acceptance": "NOT_TESTED",
            "kernel_comparison": "not a single-variable comparison with C223"}


def usb_snapshot(root=USB_ROOT):
    p = root / PORT
    try:
        return {"status": "present", "port": PORT,
                **{k: (p / f).read_text().strip() for k, f in (
                    ("vid", "idVendor"), ("pid", "idProduct"),
                    ("serial", "serial"), ("devnum", "devnum"))}}
    except FileNotFoundError as e:
        return {"status": "unreadable" if p.exists() else "absent", "port": PORT, "error": repr(e)}
    except OSError as e:
        return {"status": "unreadable", "port": PORT, "error": repr(e)}


def monitor_loop(path, root, stop_read, stop_write, heartbeat_read, heartbeat_write, interval=0.2):
    # A terminal interrupt must not also kill the recovery observer.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.close(stop_write)
    os.close(heartbeat_read)
    try:
        with Path(path).open("xb") as out:
            seq = 0
            while not select.select([stop_read], [], [], 0)[0]:
                started = time.monotonic_ns()
                snapshot = usb_snapshot(root)
                finished = time.monotonic_ns()
                row = {"seq": seq, "sample_started_ns": started,
                       "monotonic_ns": finished, "snapshot": snapshot}
                line = (json.dumps(row) + "\n").encode()
                out.write(line)
                out.flush()
                # Never block the sampler if the parent is busy. Missing
                # heartbeat sequence/coverage is a failure, not invented data.
                try:
                    os.write(heartbeat_write, HEARTBEAT.pack(seq, started, finished, hashlib.sha256(line).digest()))
                except BlockingIOError:
                    pass
                seq += 1
                if select.select([stop_read], [], [], interval)[0]:
                    break
    finally:
        os.close(stop_read)
        os.close(heartbeat_write)


def sample_coverage(rows, start_ns, done_ns, required_start_ns, required_end_ns):
    result = {"sampling_verified": False, "session_coverage_verified": False,
              "samples": len(rows), "coverage_start_ns": start_ns, "coverage_end_ns": done_ns,
              "required_start_ns": required_start_ns, "required_end_ns": required_end_ns}
    if not rows or not start_ns <= required_start_ns <= required_end_ns <= done_ns:
        return result
    # Snapshot reads are intervals, not instantaneous observations. Bound the
    # uncertainty from one read's start through the next read's completion.
    gaps = [b["sample_started_ns"] - a["sample_started_ns"] for a, b in zip(rows, rows[1:])]
    spans = [b["monotonic_ns"] - a["sample_started_ns"] for a, b in zip(rows, rows[1:])]
    durations = [x["monotonic_ns"] - x["sample_started_ns"] for x in rows]
    head = rows[0]["monotonic_ns"] - start_ns
    tail = done_ns - rows[-1]["sample_started_ns"]
    valid = (len(rows) >= 2 and [x["seq"] for x in rows] == list(range(len(rows))) and
             all(start_ns <= x["sample_started_ns"] <= x["monotonic_ns"] <= done_ns for x in rows) and
             all(a["monotonic_ns"] <= b["sample_started_ns"] for a, b in zip(rows, rows[1:])) and
             all(0 <= x <= MAX_SAMPLE_GAP_NS for x in durations) and
             all(0 < x <= MAX_SAMPLE_GAP_NS for x in gaps) and
             all(0 < x <= MAX_SAMPLE_GAP_NS for x in spans) and
             0 <= head <= MAX_SAMPLE_GAP_NS and 0 <= tail <= MAX_SAMPLE_GAP_NS)
    result.update(max_gap_seconds=max(gaps, default=0) / 1e9,
                  max_read_seconds=max(durations, default=0) / 1e9,
                  max_observation_span_seconds=max(spans, default=0) / 1e9,
                  head_gap_seconds=head / 1e9, tail_gap_seconds=tail / 1e9,
                  sampling_verified=valid, session_coverage_verified=valid)
    return result


def verify_usb_log(path, samples):
    """Local host log, independently compared with digests from the sampler pipe."""
    result = {"log_integrity_verified": False, "observation_verified": False}
    with Path(path).open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024 or not raw.endswith(b"\n"):
        return result | {"log_error": "oversized/truncated log"}
    lines = raw.splitlines(keepends=True)
    if len(lines) != len(samples):
        return result | {"log_error": "log/heartbeat sample count mismatch"}
    unreadable = present = absent = 0
    modes = set()
    for line, expected in zip(lines, samples):
        if hashlib.sha256(line).hexdigest() != expected["line_sha256"]:
            return result | {"log_error": "log/heartbeat SHA256 mismatch"}
        row = json.loads(line)
        if any(row[k] != expected[k] for k in ("seq", "sample_started_ns", "monotonic_ns")):
            return result | {"log_error": "log/heartbeat fields mismatch"}
        snap = row["snapshot"]
        if snap.get("port") != PORT:
            return result | {"log_error": "snapshot port mismatch"}
        status = snap.get("status")
        if status == "unreadable":
            unreadable += 1
        elif status == "absent":
            absent += 1
        elif status == "present":
            if (not all(isinstance(snap.get(k), str) for k in ("vid", "pid", "serial", "devnum")) or
                    re.fullmatch(r"[0-9a-fA-F]{4}", snap["vid"]) is None or
                    re.fullmatch(r"[0-9a-fA-F]{4}", snap["pid"]) is None or
                    not snap["serial"] or re.fullmatch(r"[1-9][0-9]*", snap["devnum"]) is None):
                return result | {"log_error": "malformed present snapshot"}
            present += 1
            modes.add(snap["vid"].lower() + ":" + snap["pid"].lower())
        else:
            return result | {"log_error": "unknown snapshot status"}
    return result | {"log_integrity_verified": True, "observation_verified": bool(present and not unreadable),
                     "unreadable_samples": unreadable, "present_samples": present, "absent_samples": absent,
                     "observed_vid_pids": sorted(modes),
                     "port_observation_scope": "readable samples; not proof of every transition or electrical VBUS"}


def _log_verifier(path, samples, read_fd, write_fd):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    os.close(read_fd)
    try:
        try:
            result = verify_usb_log(path, samples)
        except Exception as e:
            result = {"log_integrity_verified": False, "observation_verified": False, "log_error": repr(e)}
        os.write(write_fd, json.dumps(result).encode())
    finally:
        os.close(write_fd)


def bounded_log_verification(path, samples, deadline):
    # Isolate even filesystem blocking from the parent's single stop deadline.
    failed = {"log_integrity_verified": False, "observation_verified": False}
    if time.monotonic() >= deadline:
        return failed | {"log_error": "no stop budget left for log verification"}
    read_fd, write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    worker = multiprocessing.get_context("fork").Process(target=_log_verifier,
                                                         args=(path, samples, read_fd, write_fd))
    data = bytearray()
    try:
        worker.start()
        os.close(write_fd)
        write_fd = -1
        while time.monotonic() < deadline:
            if not select.select([read_fd], [], [], min(0.01, max(0, deadline - time.monotonic())))[0]:
                continue
            chunk = os.read(read_fd, 8192)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > 8192:
                return failed | {"log_error": "oversized verifier response"}
        worker.join(max(0, deadline - time.monotonic()))
        if worker.is_alive() or worker.exitcode != 0:
            return failed | {"log_error": "log verification exceeded stop budget or failed"}
        return json.loads(data)
    except (OSError, ValueError) as e:
        return failed | {"log_error": repr(e)}
    finally:
        if worker.pid is not None and worker.is_alive():
            worker.kill()
            worker.join(max(0, deadline - time.monotonic()))
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


class USBMonitor:
    """Separate process, including heartbeat samples while ACM/ADB calls block."""
    def __init__(self, output, root=USB_ROOT, interval=0.2):
        self.path = Path(output) / "usb-samples.jsonl"
        ctx = multiprocessing.get_context("fork")
        self.stop_read, self.stop_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.heartbeat_read, self.heartbeat_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.samples, self.pending = [], bytearray()
        self.coverage_start_ns = None
        self.stop_requested_ns = None
        self.heartbeat_overflow = False
        self.process = ctx.Process(target=monitor_loop, args=(
            self.path, root, self.stop_read, self.stop_write,
            self.heartbeat_read, self.heartbeat_write, interval))

    def drain(self):
        # All descriptors are nonblocking, all iterations and allocations bounded.
        if self.heartbeat_read < 0:
            return
        for _ in range(128):
            try:
                chunk = os.read(self.heartbeat_read, 8192)
            except BlockingIOError:
                break
            if not chunk:
                break
            self.pending.extend(chunk)
            while len(self.pending) >= HEARTBEAT.size:
                seq, started, finished, digest = HEARTBEAT.unpack(self.pending[:HEARTBEAT.size])
                del self.pending[:HEARTBEAT.size]
                if len(self.samples) >= 20000:
                    self.heartbeat_overflow = True
                    return
                self.samples.append({"seq": seq, "sample_started_ns": started, "monotonic_ns": finished,
                                     "line_sha256": digest.hex()})
        else:
            self.heartbeat_overflow = True

    def start(self):
        self.coverage_start_ns = time.monotonic_ns()
        self.process.start()
        for name in ("stop_read", "heartbeat_write"):
            os.close(getattr(self, name))
            setattr(self, name, -1)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.healthy():
                return
            if not self.process.is_alive():
                break
            time.sleep(0.01)
        raise RuntimeError("independent USB monitor did not produce a fresh completed sample")

    def healthy(self):
        self.drain()
        if not self.process.is_alive() or not self.samples or self.heartbeat_overflow:
            return False
        now, last = time.monotonic_ns(), self.samples[-1]
        return (0 <= now - last["monotonic_ns"] <= MAX_SAMPLE_GAP_NS and
                0 <= last["monotonic_ns"] - last["sample_started_ns"] <= MAX_SAMPLE_GAP_NS and
                0 <= now - last["sample_started_ns"] <= MAX_SAMPLE_GAP_NS)

    def stop(self, required_start_ns=None, required_end_ns=None):
        self.stop_requested_ns = time.monotonic_ns()
        deadline = time.monotonic() + MONITOR_STOP_SECONDS
        if self.process.pid is None:
            for name in ("stop_read", "stop_write", "heartbeat_read", "heartbeat_write"):
                if getattr(self, name) >= 0:
                    os.close(getattr(self, name))
                    setattr(self, name, -1)
            return {"exit_code": None, "not_started": True}
        premature = not self.process.is_alive()
        notify_error = None
        try:
            if self.stop_write >= 0:
                os.write(self.stop_write, b"S")
        except OSError as e:
            notify_error = repr(e)
        self.drain()
        self.process.join(max(0, deadline - time.monotonic() - 0.25))
        forced = self.process.is_alive()
        if forced:
            self.process.kill()
            self.process.join(max(0, deadline - time.monotonic()))
        self.drain()
        log_result = bounded_log_verification(self.path, self.samples, deadline)
        done_ns = time.monotonic_ns()
        result = {"exit_code": self.process.exitcode, "forced": forced, "premature": premature,
                  "sampling_verified": False, "session_coverage_verified": False,
                  "stop_requested_ns": self.stop_requested_ns, "monitor_done_ns": done_ns,
                  "stop_budget_seconds": MONITOR_STOP_SECONDS}
        start = min(self.coverage_start_ns, required_start_ns or self.coverage_start_ns)
        result.update(sample_coverage(self.samples, start, done_ns,
                                      required_start_ns if required_start_ns is not None else start,
                                      required_end_ns if required_end_ns is not None else self.stop_requested_ns))
        result["timing_coverage_verified"] = result["sampling_verified"]
        result.update(log_result)
        for name in ("stop_write", "heartbeat_read"):
            if getattr(self, name) >= 0:
                os.close(getattr(self, name))
                setattr(self, name, -1)
        result["stop_elapsed_seconds"] = (time.monotonic_ns() - self.stop_requested_ns) / 1e9
        result["stop_budget_exceeded"] = result["stop_elapsed_seconds"] > MONITOR_STOP_SECONDS
        if (self.pending or self.heartbeat_overflow or notify_error or forced or premature or
                result["exit_code"] != 0 or result["stop_budget_exceeded"] or
                not result.get("log_integrity_verified") or not result.get("observation_verified")):
            result.update(sampling_verified=False, session_coverage_verified=False)
        if notify_error:
            result["notify_error"] = notify_error
        return result


def capture_script(prefix, argv):
    if re.fullmatch(r"C224_[A-F0-9]{24}_[a-z0-9_]+", prefix) is None:
        raise ValueError("invalid frame prefix")
    allowed = [["/bin/busybox", "cat", p] for _, p, _ in METADATA + FIELDS]
    allowed += [["/bin/busybox", "readlink", "-f", p] for _, p, _ in NODE_LINKS]
    if argv not in allowed:
        raise ValueError("command is outside the read-only whitelist")
    # Only tmpfs files; the caller verifies /run is a unique tmpfs mount first.
    tmp = "/run/" + prefix
    cmd = shlex.join(argv)
    return (f"LC_ALL=C; export LC_ALL; printf '\\n{prefix}_BEGIN\\n'; "
            f"/bin/busybox timeout -s KILL 1 {cmd} >{tmp}.out 2>{tmp}.err; rc=$?; "
            f"out_n=$(/bin/busybox wc -c <{tmp}.out); out_n_rc=$?; "
            f"out_h=$(/bin/busybox sha256sum {tmp}.out); out_h_rc=$?; "
            f"err_n=$(/bin/busybox wc -c <{tmp}.err); err_n_rc=$?; "
            f"err_h=$(/bin/busybox sha256sum {tmp}.err); err_h_rc=$?; "
            f"printf '\\n{prefix}_OUT_META_%s_%s\\n' \"$out_n\" \"${{out_h%% *}}\"; "
            f"printf '\\n{prefix}_OUT\\n'; /bin/busybox od -An -v -tx1 {tmp}.out; "
            "out_hex_rc=$?; "
            f"printf '\\n{prefix}_ERR_META_%s_%s\\n' \"$err_n\" \"${{err_h%% *}}\"; "
            f"printf '\\n{prefix}_ERR\\n'; /bin/busybox od -An -v -tx1 {tmp}.err; "
            "err_hex_rc=$?; "
            f"/bin/busybox rm -f {tmp}.out {tmp}.err; cleanup_rc=$?; "
            f"printf '\\n{prefix}_APPLET_RC_%s_%s_%s_%s_%s_%s_%s\\n' "
            '"$out_n_rc" "$out_h_rc" "$out_hex_rc" "$err_n_rc" "$err_h_rc" "$err_hex_rc" "$cleanup_rc"; '
            f"printf '\\n{prefix}_RC_%s\\n' \"$rc\"; "
            f"printf '\\n{prefix}_END\\n'\n").encode()


def parse_frame(raw, prefix):
    lines = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").splitlines()
    p = prefix.encode()
    names = [p + s for s in (b"_BEGIN", b"_OUT", b"_ERR", b"_END")]
    counts = [lines.count(name) for name in names]
    if any(n > 1 for n in counts):
        raise ValueError("duplicate frame marker")
    if not all(counts):
        if counts[-1]:
            raise ValueError("completed frame lacks required markers")
        return None
    indices = [lines.index(name) for name in names]
    b, o, e, end = indices
    rcs = [(i, x) for i, x in enumerate(lines) if x.startswith(p + b"_RC_")]
    if len(rcs) != 1 or not b < o < e < rcs[0][0] < end:
        raise ValueError("missing/duplicate/out-of-order receipt")
    match = re.fullmatch(re.escape(p) + rb"_RC_([0-9]{1,3})", rcs[0][1])
    if match is None or int(match[1]) > 255:
        raise ValueError("invalid command status")
    def control(suffix, pattern):
        found = [(i, x) for i, x in enumerate(lines) if x.startswith(p + suffix)]
        if len(found) != 1:
            raise ValueError("missing or duplicate payload metadata")
        m = re.fullmatch(re.escape(p + suffix) + pattern, found[0][1])
        if m is None:
            raise ValueError("malformed payload metadata")
        return found[0][0], m
    om, out_meta = control(b"_OUT_META_", rb"[ \t]*([0-9]{1,8})[ \t]*_([0-9a-f]{64})")
    em, err_meta = control(b"_ERR_META_", rb"[ \t]*([0-9]{1,8})[ \t]*_([0-9a-f]{64})")
    ai, applets = control(b"_APPLET_RC_", rb"([0-9]{1,3})_([0-9]{1,3})_([0-9]{1,3})_([0-9]{1,3})_([0-9]{1,3})_([0-9]{1,3})_([0-9]{1,3})")
    if not b < om < o < em < e < ai < rcs[0][0] < end:
        raise ValueError("out-of-order payload metadata")
    applet_codes = dict(zip(("stdout_wc", "stdout_sha256sum", "stdout_od", "stderr_wc",
                            "stderr_sha256sum", "stderr_od", "cleanup_rm"), map(int, applets.groups())))
    if any(applet_codes.values()):
        raise ValueError("capture BusyBox applet failed: " + repr(applet_codes))
    def unhex(part):
        data = b"".join(part)
        if len(data) > 32768 or re.fullmatch(rb"[0-9a-fA-F \t]*", data) is None:
            raise ValueError("invalid or oversized hex payload")
        return bytes.fromhex(data.decode("ascii"))
    out, err = unhex(lines[o + 1:em]), unhex(lines[e + 1:ai])
    for name, payload, meta in (("stdout", out, out_meta), ("stderr", err, err_meta)):
        if len(payload) != int(meta[1]) or hashlib.sha256(payload).hexdigest().encode() != meta[2]:
            raise ValueError(name + " length/SHA256 mismatch")
    return {"exit_code": int(match[1]), "stdout": out, "stderr": err,
            "stdout_length": int(out_meta[1]), "stdout_sha256": out_meta[2].decode(),
            "stderr_length": int(err_meta[1]), "stderr_sha256": err_meta[2].decode(),
            "applet_exit_codes": applet_codes, "payload_integrity_verified": True,
            "authentication_provided": False}


def receipt_result(frame, kind, expected=None):
    rc, out, err = frame["exit_code"], frame["stdout"], frame["stderr"]
    result = {"exit_code": rc, "stdout_b64": base64.b64encode(out).decode(),
              "stderr_b64": base64.b64encode(err).decode(), "errno": None,
              "errno_note": "cat exit status is not kernel errno; original stderr retained",
              "command_timeout_or_signal": rc in (124, 137), "status": "READ_ERROR"}
    for key in ("stdout_length", "stdout_sha256", "stderr_length", "stderr_sha256",
                "applet_exit_codes", "payload_integrity_verified", "authentication_provided"):
        if key in frame:
            result[key] = frame[key]
    if rc:
        return result
    valid = frame.get("payload_integrity_verified") is True and not err
    if kind == "raw":
        valid &= re.fullmatch(rb"0x[0-9a-fA-F]{2}\n", out) is not None
    elif kind == "bool":
        valid &= out in (b"0\n", b"1\n")
    elif kind == "int":
        valid &= re.fullmatch(rb"-?[0-9]+\n", out) is not None
        if valid:
            valid &= -(2**31) <= int(out) < 2**31
    elif kind == "uuid":
        try:
            valid &= str(uuid.UUID(out.decode().strip())) == out.decode().strip()
        except (ValueError, UnicodeError):
            valid = False
    elif kind == "cmdline":
        valid &= out == (expected + "\n").encode()
    elif kind == "uptime":
        valid &= re.fullmatch(rb"[0-9]+\.[0-9]+ [0-9]+\.[0-9]+\n", out) is not None
    elif kind == "link":
        valid &= out == (expected + "\n").encode()
    else:
        raise ValueError("unsupported receipt kind")
    result["status"] = "OK" if valid else "INVALID_OUTPUT"
    return result


class SerialChannel:
    def __init__(self, node, output):
        self.fd = os.open(node, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.raw = None
        try:
            self.raw = (Path(output) / "acm-raw.bin").open("xb")
            self.configure()
        except BaseException:
            if self.raw is not None:
                self.raw.close()
            os.close(self.fd)
            raise

    def configure(self):
        self.buffer = bytearray()
        settings = termios.tcgetattr(self.fd)
        settings[0] &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP |
                         termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
        settings[1] &= ~termios.OPOST
        settings[2] &= ~(termios.CSIZE | termios.PARENB)
        settings[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
        settings[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
        settings[4] = settings[5] = termios.B115200
        settings[6][termios.VMIN] = 0
        settings[6][termios.VTIME] = 1
        termios.tcsetattr(self.fd, termios.TCSANOW, settings)

    def close(self):
        self.raw.close()
        os.close(self.fd)

    def send(self, data, deadline):
        sent = 0
        while sent < len(data) and time.monotonic() < deadline:
            if select.select([], [self.fd], [], 0.05)[1]:
                try:
                    sent += os.write(self.fd, data[sent:])
                except BlockingIOError:
                    pass
        if sent != len(data):
            raise TimeoutError("serial command send incomplete")

    def until(self, predicate, deadline):
        while time.monotonic() < deadline:
            value = predicate(bytes(self.buffer))
            if value:
                return value
            if not select.select([self.fd], [], [], 0.05)[0]:
                continue
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                continue
            if not chunk:
                raise EOFError("ACM disconnected")
            self.raw.write(chunk)
            self.raw.flush()
            self.buffer.extend(chunk)
            if len(self.buffer) > 1024 * 1024:
                raise ValueError("ACM capture exceeds 1 MiB")
        raise TimeoutError("serial receipt timeout")


def collect(channel, manifest, monitor, save):
    report = {"status": "INCOMPLETE", "receipts": [], "risk": dict(RISK)}
    nonce = secrets.token_hex(12).upper()
    deadline = time.monotonic() + 15
    try:
        channel.until(lambda b: b"lgg8# " in b, min(deadline, time.monotonic() + 4))
        ready = "C224_" + nonce + "_READY"
        # No scratch file or register read before this check. Only /run is used.
        check = ("/bin/busybox awk '$5 == \"/run\" { n++; for(i=7;i<=NF;i++) "
                 "if($i==\"-\" && $(i+1)==\"tmpfs\") ok++ } "
                 "END { exit !(n==1 && ok==1) }' /proc/self/mountinfo")
        channel.send((f"if {check}; then printf '\\n{ready}_0\\n'; "
                      f"else printf '\\n{ready}_1\\n'; fi\n").encode(), deadline)
        token = channel.until(lambda b: next((x for x in b.replace(b"\r", b"").splitlines()
                                             if x in ((ready + "_0").encode(), (ready + "_1").encode())), None),
                              min(deadline, time.monotonic() + 2))
        if token != (ready + "_0").encode():
            raise RuntimeError("/run is not a unique verified tmpfs mount")
        tasks = [(k, p, "link", expected) for k, p, expected in NODE_LINKS]
        tasks += [(k, p, kind, manifest["bootargs"] if kind == "cmdline" else None)
                  for k, p, kind in METADATA + FIELDS]
        for index, (key, path, kind, expected) in enumerate(tasks):
            receipt = {"key": key, "path": path, "started_monotonic_ns": time.monotonic_ns()}
            report["receipts"].append(receipt)
            if not monitor.healthy():
                raise RuntimeError("USB monitor stopped during capture")
            if time.monotonic() >= deadline:
                receipt["status"] = "NOT_ATTEMPTED_BUDGET"
                raise TimeoutError("15-second total capture budget exhausted")
            prefix = f"C224_{nonce}_{index:02d}"
            argv = ["/bin/busybox", "readlink", "-f", path] if kind == "link" else ["/bin/busybox", "cat", path]
            channel.send(capture_script(prefix, argv), min(deadline, time.monotonic() + 1))
            frame = channel.until(lambda b: parse_frame(b, prefix), min(deadline, time.monotonic() + 2.5))
            receipt.update(receipt_result(frame, kind, expected))
            receipt["finished_monotonic_ns"] = time.monotonic_ns()
            save(report)
            if kind in ("link", "uuid", "cmdline") and receipt["status"] != "OK":
                raise RuntimeError("Linux node/boot identity failed: " + key)
        report["status"] = "PASS" if all(r["status"] == "OK" for r in report["receipts"]) else "COMPLETE_WITH_ERRORS"
    except (Exception, KeyboardInterrupt) as e:
        report["error"] = repr(e)
        for receipt in report["receipts"]:
            if "status" not in receipt:
                receipt.update(status="TRANSPORT_ERROR", host_error=repr(e),
                               finished_monotonic_ns=time.monotonic_ns())
        # Explicit rows for every sysfs field, even after identity/transport failure.
        existing = {r["key"] for r in report["receipts"]}
        report["receipts"] += [{"key": k, "path": p, "status": "NOT_ATTEMPTED"}
                               for k, p, _ in FIELDS if k not in existing]
    finally:
        save(report)
    return report


def validate_android(fields):
    if len(fields) != 7 or fields[:4] != ["LM-G820", "alphalm_lao_com", "_b", "1"]:
        raise RuntimeError("Android identity/slot/boot_completed mismatch")
    if str(uuid.UUID(fields[4])) != fields[4]:
        raise RuntimeError("invalid Android boot ID")
    for index, name in ((5, "boot_b"), (6, "boot_a")):
        if re.fullmatch(re.escape(BOOT_HASHES[name]) + r"\s+\*?/dev/block/by-name/" + name, fields[index]) is None:
            raise RuntimeError("Android " + name + " differs from pinned baseline")


def validate_return(before, after):
    validate_android(before)
    validate_android(after)
    if before[4] == after[4]:
        raise RuntimeError("Android boot ID did not rotate")


def run_session(io):
    """Same state machine for real I/O and offline fakes; no auto retries/boots."""
    report = {"candidate": "C224", "image_sha256": IMAGE_SHA, "risk": dict(RISK),
              "android_return_verified": False, "capture": {"status": "NOT_ATTEMPTED"}}
    left_android_possible = False
    session_start_ns = None
    try:
        report["offline_gate"] = io.gate()
        session_start_ns = time.monotonic_ns()
        io.start_monitor()
        before = io.preflight()
        validate_android(before)
        report["before"] = before
        # Set before sending: lost ACK or an interrupt is an uncertain transition.
        io.arm_recovery()
        left_android_possible = True
        io.enter_fastboot()
        io.check_fastboot()
        io.gate()
        report["ram_boot_command_accepted"] = io.boot()
        report["capture"] = io.observe()
    except BaseException as e:
        report["error"] = repr(e)
    finally:
        if left_android_possible:
            io.recovering = True
            try:
                after = io.recover()
                report["after"] = after
                validate_return(report["before"], after)
                report["android_return_verified"] = True
            except BaseException as e:
                report["recovery_error"] = repr(e)
                report["manual_recovery_required"] = True
        try:
            session_end_ns = time.monotonic_ns()
            report["session_range"] = {"start_ns": session_start_ns, "end_ns": session_end_ns}
            report["usb_monitor"] = io.stop_monitor(session_start_ns, session_end_ns)
        except Exception as e:
            report["usb_monitor"] = {"error": repr(e)}
        report["success"] = bool(report["android_return_verified"] and
                                 report.get("ram_boot_command_accepted") and
                                 report["capture"]["status"] == "PASS" and
                                 report["usb_monitor"].get("exit_code") == 0 and
                                 report["usb_monitor"].get("sampling_verified") and
                                 report["usb_monitor"].get("session_coverage_verified") and
                                 report["usb_monitor"].get("log_integrity_verified") and
                                 report["usb_monitor"].get("observation_verified") and
                                 not report["usb_monitor"].get("forced") and
                                 not report["usb_monitor"].get("premature") and not report.get("error"))
        io.save("result", report)
    return report


class LiveIO:
    """Only constructed after the explicit CLI execution option and local gate."""
    def __init__(self, serial, out):
        if file_sha(REFERENCE) != REFERENCE_SHA:
            raise RuntimeError("legacy helper changed")
        spec = importlib.util.spec_from_file_location("c224_pinned_legacy", REFERENCE)
        self.base = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.base)  # C210 defines helpers; does not enumerate devices at import.
        b = self.base
        b.SERIAL, b.HERE, b.OUT, b.LOCAL_TMP = serial, HERE, out, out / "tmp"
        b.LOCAL_TMP.mkdir(mode=0o700)
        os.environ.update({"TMPDIR": str(b.LOCAL_TMP), "TMP": str(b.LOCAL_TMP), "TEMP": str(b.LOCAL_TMP)})
        self.serial, self.out = serial, out
        self.monitor = None
        self.deadline = None
        self.boot_time = None
        self.recovering = False
        self.recovery_notes = []
        self.locks = []
        self.manifest = json.loads((HERE / "boot/manifest.json").read_text())
        original_command = b.command
        def bounded_command(name, args, timeout=20, check=True):
            if not self.recovering and self.monitor is not None and not self.monitor.healthy():
                raise RuntimeError("USB monitor heartbeat stale before device command")
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("fixed recovery deadline reached")
                timeout = min(timeout, remaining)
            return original_command(name, args, timeout=timeout, check=check)
        b.command = bounded_command

    def save(self, name, data):
        self.base.save_json(name, data)

    def gate(self):
        return review()

    def start_monitor(self):
        b = self.base
        b.LOCK_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        for key in (hashlib.sha256(self.serial.encode()).hexdigest()[:16], "port_" + PORT):
            b.acquire_lock(str(b.LOCK_ROOT / ("lg_g8_" + key + ".lock")), self.locks)
        self.monitor = USBMonitor(self.out)
        self.monitor.start()

    def preflight(self):
        self.base.require_adb("preflight-adb")
        snap = usb_snapshot()
        if snap.get("serial") != self.serial or snap.get("vid") != "1004" or snap.get("pid") not in ("631f", "633e"):
            raise RuntimeError("Android physical USB identity mismatch")
        fields = self.base.android("preflight-android")
        validate_android(fields)
        if not self.base.capture_pstore("pre-pstore")["snapshot_verified"]:
            raise RuntimeError("pre-run pstore not verified")
        return fields

    def arm_recovery(self):
        self.deadline = time.monotonic() + 300

    def enter_fastboot(self):
        self.base.require_adb("before-reboot-adb")
        self.base.command("reboot-bootloader", ["adb", "-s", self.serial, "reboot", "bootloader"])

    def check_fastboot(self):
        b = self.base
        if b.find_fastboot() != self.serial:
            raise RuntimeError("fastboot serial differs from preflight")
        for key, value in (("product", "msmnile"), ("unlocked", "yes"), ("current-slot", "b"),
                           ("battery-soc-ok", "yes"), ("slot-successful:b", "yes"), ("slot-unbootable:b", "no")):
            b.getvar(self.serial, key, value)
        b.optional_capacity(self.serial)
        b.require_fastboot_physical(self.serial)

    def boot(self):
        self.base.require_fastboot_physical(self.serial)
        review()  # Rehash immediately before the sole RAM boot command.
        if not self.monitor.healthy():
            raise RuntimeError("monitor stopped before RAM boot")
        self.boot_time = time.monotonic()
        result = self.base.command("fastboot-boot", ["fastboot", "-s", self.serial, "boot", str(IMAGE)],
                                   timeout=60, check=False)
        return result["exit_code"] == 0 and not result["timed_out"]

    def observe(self):
        end = min(self.deadline, self.boot_time + 180)
        while time.monotonic() < end:
            if not self.monitor.healthy():
                raise RuntimeError("USB monitor stopped while waiting for ACM")
            located = self.base.acm_parent_for_port()
            if located:
                node, parent, serial = located
                fingerprint = usb_snapshot()
                channel = SerialChannel(node, self.out)
                try:
                    if fingerprint != usb_snapshot() or self.base.acm_parent_for_port() != located:
                        raise RuntimeError("ACM identity changed while opening")
                    result = collect(channel, self.manifest, self.monitor,
                                     lambda r: self.save("capture", r))
                    result["usb_binding"] = {"tty": str(node), "parent": str(parent),
                                             "gadget_serial": serial, "snapshot": fingerprint}
                    result["raw_capture"] = str(self.out / "acm-raw.bin")
                    self.save("capture", result)
                    return result
                finally:
                    channel.close()
            snap = usb_snapshot()
            if snap.get("vid") == "1004" and snap.get("serial") == self.serial:
                return {"status": "NO_ACM_BEFORE_ANDROID_RETURN"}
            if (snap.get("vid"), snap.get("pid"), snap.get("serial")) == ("18d1", "4ee0", self.serial) and time.monotonic() - self.boot_time >= 30:
                return {"status": "STILL_FASTBOOT_AFTER_30_SECONDS"}
            time.sleep(0.2)
        return {"status": "NO_ACM_WITHIN_DEADLINE"}

    def recover(self):
        # Fixed from before the transition; no timeout renewal on retries/signals.
        rebooted_fastboot = False
        early_pstore_done = False
        count = 0
        while time.monotonic() < self.deadline:
            count += 1
            snap = usb_snapshot()
            if (snap.get("vid"), snap.get("pid"), snap.get("serial")) == ("18d1", "4ee0", self.serial):
                if not rebooted_fastboot and (self.boot_time is None or time.monotonic() - self.boot_time >= 30):
                    # Only after exact physical + CLI identity checks, never flash/set_active.
                    try:
                        self.base.require_fastboot_physical(self.serial)
                        b = self.base.command("recovery-fastboot-devices", ["fastboot", "devices", "-l"], check=False)
                        rows = [x.split() for x in b["stdout"].decode(errors="replace").splitlines()
                                if x.split() and x.split()[0] == self.serial]
                        valid_row = len(rows) == 1 and rows[0][:2] == [self.serial, "fastboot"]
                        ports = [x for x in rows[0][2:] if x.startswith("usb:")] if valid_row else []
                        if b["exit_code"] == 0 and valid_row and ports in ([], ["usb:" + PORT]):
                            rebooted_fastboot = True
                            self.base.require_fastboot_physical(self.serial)
                            self.base.command("recovery-fastboot-reboot", ["fastboot", "-s", self.serial, "reboot"], check=False)
                    except (RuntimeError, OSError) as e:
                        self.recovery_notes.append({"fastboot_recovery_error": repr(e)})
            if snap.get("vid") == "1004" and snap.get("pid") in ("631f", "633e") and snap.get("serial") == self.serial:
                try:
                    self.base.require_adb(f"recovery-adb-{count:03d}")
                    if not early_pstore_done:
                        early_pstore_done = True
                        try:
                            self.save("early-pstore-receipt", self.base.capture_pstore("early-pstore"))
                        except Exception as e:
                            self.recovery_notes.append({"early_pstore_error": repr(e)})
                    r = self.base.command(f"boot-completed-{count:03d}",
                                          ["adb", "-s", self.serial, "shell", "getprop", "sys.boot_completed"],
                                          timeout=5, check=False)
                    if r["exit_code"] == 0 and r["stdout"].strip() == b"1":
                        self.base.require_adb("postflight-adb")
                        after = self.base.android("post-android")
                        try:
                            self.save("post-pstore-receipt", self.base.capture_pstore("post-pstore"))
                        except Exception as e:
                            self.recovery_notes.append({"post_pstore_error": repr(e)})
                        self.save("recovery-notes", self.recovery_notes)
                        return after
                except (RuntimeError, OSError) as e:
                    self.recovery_notes.append({"attempt": count, "error": repr(e)})
            time.sleep(min(0.5, max(0, self.deadline - time.monotonic())))
        self.save("recovery-notes", self.recovery_notes)
        raise TimeoutError("Android recovery unverified after fixed 300-second deadline; manual recovery required")

    def stop_monitor(self, session_start_ns=None, session_end_ns=None):
        try:
            return self.monitor.stop(session_start_ns, session_end_ns) if self.monitor else {"exit_code": None, "not_started": True}
        finally:
            for fd in reversed(self.locks):
                os.close(fd)


def entrypoint(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-ram-only", action="store_true",
                        help="explicit future device execution; never used by offline review/tests")
    parser.add_argument("--serial", help="explicit Android/fastboot serial; no environment autodetection")
    args = parser.parse_args(argv)
    if not args.execute_ram_only:
        if args.serial is not None:
            parser.error("--serial without explicit execution is rejected")
        print(json.dumps(review(), indent=2))
        return 0
    if not args.serial or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", args.serial) is None:
        parser.error("execution requires one explicit, well-formed --serial")
    review()  # Before output allocation, helper import, locks or device commands.
    os.umask(0o077)
    out = HERE / (time.strftime("run-%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(4))
    out.mkdir(mode=0o700)
    io = LiveIO(args.serial, out)
    signals = []
    def interrupted(signum, frame):
        signals.append(signum)
        if not io.recovering:
            raise InterruptedError("signal " + str(signum))
    previous = {s: signal.signal(s, interrupted) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        result = run_session(io)
        io.save("signals", signals)
        print(json.dumps(result, indent=2))
        return 0 if result["success"] else 1
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


if __name__ == "__main__":
    raise SystemExit(entrypoint())
