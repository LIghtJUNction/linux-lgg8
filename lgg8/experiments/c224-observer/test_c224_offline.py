"""Offline only: fake USB files, framed replies and fake lifecycle I/O.

Never import the legacy runner or call LiveIO's constructor. Temporary data
stays within the workspace and is automatically removed. No adb/fastboot/devices.
"""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

SOURCE_DIR = Path(__file__).resolve().parent
HERE = SOURCE_DIR.parents[2] / "out/lgg8-c224-fg-presence-observe-20261031"
TEMP_ROOT = HERE if HERE.is_dir() else SOURCE_DIR
spec = importlib.util.spec_from_file_location("c224_offline_target", SOURCE_DIR / "run-c224-observe.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
ARTIFACT_PATHS = (r.IMAGE, r.REFERENCE, HERE / "boot/manifest.json",
                  HERE / "build-provenance.json", r.C223 / "boot/manifest.json")
NO_ARTIFACTS = not any(path.exists() for path in ARTIFACT_PATHS)
PREFIX = "C224_" + "A" * 24 + "_00"
LINUX_ID = "00000000-0000-4000-8000-000000000003"


def android(boot_id="00000000-0000-4000-8000-000000000001"):
    return ["LM-G820", "alphalm_lao_com", "_b", "1", boot_id,
            r.BOOT_HASHES["boot_b"] + "  /dev/block/by-name/boot_b",
            r.BOOT_HASHES["boot_a"] + "  /dev/block/by-name/boot_a"]


def frame(prefix=PREFIX, out=b"0x00\n", err=b"", rc=0, applet_codes=(0,) * 7):
    return (f"\n{prefix}_BEGIN\n{prefix}_OUT_META_{len(out)}_{hashlib.sha256(out).hexdigest()}\n"
            f"{prefix}_OUT\n{out.hex(' ')}\n"
            f"{prefix}_ERR_META_{len(err)}_{hashlib.sha256(err).hexdigest()}\n"
            f"{prefix}_ERR\n{err.hex(' ')}\n"
            f"{prefix}_APPLET_RC_{'_'.join(map(str, applet_codes))}\n"
            f"{prefix}_RC_{rc}\n{prefix}_END\n").encode()


class HealthyMonitor:
    def healthy(self):
        return True


class FakeChannel:
    def __init__(self, fail_key=None, rc=1, err=b"cat: read error: Input/output error\n", disconnect=False):
        self.buffer = b"lgg8# "
        self.fail_key, self.rc, self.err = fail_key, rc, err
        self.disconnect = disconnect
        self.sent = []
        self.all_tasks = [(k, p, "link", expected) for k, p, expected in r.NODE_LINKS]
        self.all_tasks += [(k, p, kind, None) for k, p, kind in r.METADATA + r.FIELDS]

    def send(self, script, deadline):
        self.sent.append(script)
        if b"_READY" in script:
            token = re.search(rb"C224_[A-F0-9]{24}_READY", script)[0]
            self.buffer += b"\n" + token + b"_0\n"
            return
        prefix = re.search(rb"C224_[A-F0-9]{24}_[0-9]+_BEGIN", script)[0][:-6].decode()
        index = int(prefix.rsplit("_", 1)[1])
        key, path, kind, expected = self.all_tasks[index]
        argv = shlex.split(re.search(rb"timeout -s KILL 1 (.*?) >/run/", script)[1].decode())
        assert argv[-1] == path
        if key == self.fail_key:
            if self.disconnect:
                raise EOFError("offline unplug")
            self.buffer += frame(prefix, b"", self.err, self.rc)
            return
        values = {"raw": b"0x02\n", "bool": b"1\n", "int": b"1234\n",
                  "uuid": (LINUX_ID + "\n").encode(), "cmdline": b"offline-args\n",
                  "uptime": b"35.01 20.02\n", "link": ((expected or "") + "\n").encode()}
        self.buffer += frame(prefix, values[kind])

    def until(self, predicate, deadline):
        value = predicate(self.buffer)
        if not value:
            raise TimeoutError("offline missing receipt")
        return value


class FakeIO:
    recovering = False

    def __init__(self, failure=None, error=None):
        self.failure = failure
        self.error = error or RuntimeError("offline injected failure")
        self.calls, self.saved = [], {}
        self.gates = 0
        self.before = android()
        self.after = android("00000000-0000-4000-8000-000000000002")
        self.capture_status = "PASS"
        self.monitor_result = {"exit_code": 0, "forced": False, "premature": False,
                               "sampling_verified": True, "session_coverage_verified": True,
                               "log_integrity_verified": True, "observation_verified": True}
        self.boot_accepted = True

    def hit(self, name):
        self.calls.append(name)
        if self.failure == name:
            raise self.error

    def gate(self):
        self.gates += 1
        self.hit("gate" + str(self.gates))
        return {"mode": "OFFLINE_FAKE"}

    def start_monitor(self): self.hit("start_monitor")
    def preflight(self): self.hit("preflight"); return self.before
    def arm_recovery(self): self.hit("arm_recovery")
    def enter_fastboot(self): self.hit("enter_fastboot")
    def check_fastboot(self): self.hit("check_fastboot")
    def boot(self): self.hit("boot"); return self.boot_accepted
    def observe(self): self.hit("observe"); return {"status": self.capture_status}
    def recover(self): self.hit("recover"); return self.after
    def stop_monitor(self, start_ns=None, end_ns=None):
        self.session_window = (start_ns, end_ns)
        self.hit("stop_monitor")
        return self.monitor_result
    def save(self, name, data): self.saved[name] = copy.deepcopy(data)


class OfflineTests(unittest.TestCase):
    def test_import_and_default_review_never_launch_or_enumerate(self):
        with mock.patch.object(r, "LiveIO", side_effect=AssertionError("live forbidden")), \
             mock.patch.object(r, "usb_snapshot", side_effect=AssertionError("USB forbidden")), \
             mock.patch.object(r.subprocess, "run", side_effect=AssertionError("subprocess forbidden")), \
             mock.patch.object(r.subprocess, "Popen", side_effect=AssertionError("subprocess forbidden")), \
             mock.patch.object(r.importlib.util, "spec_from_file_location", side_effect=AssertionError("legacy import forbidden")), \
             mock.patch.object(r, "review", return_value={"device_acceptance": "NOT_TESTED"}), \
             mock.patch("builtins.print"):
            self.assertEqual(r.entrypoint([]), 0)

    @unittest.skipIf(NO_ARTIFACTS, "local C224/C223/C210 artifacts are absent")
    def test_local_artifacts_review(self):
        with mock.patch.object(r, "LiveIO", side_effect=AssertionError("live forbidden")), \
             mock.patch.object(r, "usb_snapshot", side_effect=AssertionError("USB forbidden")), \
             mock.patch.object(r.subprocess, "run", side_effect=AssertionError("subprocess forbidden")), \
             mock.patch.object(r.subprocess, "Popen", side_effect=AssertionError("subprocess forbidden")), \
             mock.patch.object(r.importlib.util, "spec_from_file_location", side_effect=AssertionError("legacy import forbidden")):
            self.assertEqual(r.review()["device_acceptance"], "NOT_TESTED")

    def test_cli_rejects_implicit_or_malformed_execution(self):
        with mock.patch.object(r, "LiveIO", side_effect=AssertionError("live forbidden")), \
             mock.patch.object(r, "review", side_effect=AssertionError("review not reached")), \
             mock.patch("sys.stderr"):
            for args in (["--serial", "offline"], ["--execute-ram-only"],
                         ["--execute-ram-only", "--serial", "bad serial"], ["--run"], ["boot"]):
                with self.subTest(args=args), self.assertRaises(SystemExit):
                    r.entrypoint(args)

    def test_full_image_and_helper_hash_fail_closed(self):
        with mock.patch.object(r, "file_sha", return_value="0" * 64), \
             self.assertRaisesRegex(RuntimeError, "full image hash"):
            r.review()
        with mock.patch.object(r, "file_sha", side_effect=[r.IMAGE_SHA, "0" * 64]), \
             self.assertRaisesRegex(RuntimeError, "helper hash"):
            r.review()

    @unittest.skipIf(NO_ARTIFACTS, "local C224/C223/C210 artifacts are absent")
    def test_manifest_negative_changes(self):
        m = json.loads((HERE / "boot/manifest.json").read_text())
        b = json.loads((r.C223 / "boot/manifest.json").read_text())
        p = json.loads((HERE / "build-provenance.json").read_text())
        r.check_manifest(m, b, p)
        mutations = [lambda x: x.update(device_acceptance="PASS"),
                     lambda x: x.update(partition_size=1),
                     lambda x: x["components"]["image"].update(sha256="0" * 64),
                     lambda x: x.update(bootargs=x["bootargs"] + " extra=1"),
                     lambda x: x["provenance"].update(source_commit="0" * 40),
                     lambda x: x["provenance"].update(profile="other"),
                     lambda x: x["provenance"].update(capture_stage="other")]
        for component in ("dtb", "source_dtb", "initramfs", "stock_dtbs", "external_ramdisk", "cmdline_file", "kernel"):
            mutations.append(lambda x, c=component: x["components"][c].update(sha256="0" * 64))
        for i, mutate in enumerate(mutations):
            changed = copy.deepcopy(m)
            mutate(changed)
            with self.subTest(index=i), self.assertRaises(RuntimeError):
                r.check_manifest(changed, b, p)

    def test_frames_preserve_error_bytes_and_do_not_invent_errno(self):
        err = b"cat: read error: Operation not supported\n\xff\x00"
        f = r.parse_frame(frame(out=b"", err=err, rc=1), PREFIX)
        result = r.receipt_result(f, "raw")
        self.assertEqual(result["status"], "READ_ERROR")
        self.assertEqual(base64.b64decode(result["stderr_b64"]), err)
        self.assertEqual(base64.b64decode(result["stdout_b64"]), b"")
        self.assertIsNone(result["errno"])
        for rc, out, stderr in ((0, b"", b""), (0, b"READ_ERROR\n", b""),
                                (0, b"0x00\n", b"unexpected warning"), (0, b"0x000\n", b"")):
            self.assertEqual(r.receipt_result({"exit_code": rc, "stdout": out, "stderr": stderr}, "raw")["status"], "INVALID_OUTPUT")

    def test_truncated_echo_duplicate_bad_hex_and_wrong_nonce_rejected(self):
        valid = frame()
        self.assertIsNone(r.parse_frame(valid[:valid.index((PREFIX + "_END").encode())], PREFIX))
        self.assertIsNone(r.parse_frame(r.capture_script(PREFIX, ["/bin/busybox", "cat", r.FIELDS[0][1]]), PREFIX))
        self.assertIsNone(r.parse_frame(valid, PREFIX.replace("A", "B")))
        for raw in (valid + valid, valid.replace(b"30 78", b"ZZ"),
                    valid.replace(b"_RC_0", b"_RC_999"),
                    valid.replace((PREFIX + "_OUT").encode(), (PREFIX + "_ERR").encode())):
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                r.parse_frame(raw, PREFIX)

    def test_only_whitelisted_read_commands_and_shell_syntax(self):
        self.assertEqual(len(r.FIELDS), 25)
        self.assertEqual(len({p for _, p, _ in r.FIELDS}), 25)
        for _, path, _ in r.METADATA + r.FIELDS:
            script = r.capture_script(PREFIX, ["/bin/busybox", "cat", path])
            self.assertEqual(script.count(path.encode()), 1)
            self.assertNotIn(b">/sys", script)
            self.assertNotIn(b"/dev/block", script)
            self.assertNotIn(b"/tmp", script)
            # Parse only, never execute the generated device script.
            subprocess.run(["/bin/sh", "-n"], input=script, check=True, capture_output=True)
        for argv in (["/bin/busybox", "cat", "/sys/class/power_supply/bms/temp"],
                     ["/bin/busybox", "cat", "/sys/bus/iio/devices/iio:device0/in_voltage2_input"],
                     ["sh", "-c", "echo 1 >/sys/anything"], ["reboot"]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                r.capture_script(PREFIX, argv)

    def test_complete_capture_and_each_sysfs_failure(self):
        saved = []
        result = r.collect(FakeChannel(), {"bootargs": "offline-args"}, HealthyMonitor(), lambda d: saved.append(copy.deepcopy(d)))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["receipts"]), 32)
        for key, _, _ in r.FIELDS:
            with self.subTest(key=key):
                result = r.collect(FakeChannel(fail_key=key), {"bootargs": "offline-args"}, HealthyMonitor(), lambda d: None)
                self.assertEqual(result["status"], "COMPLETE_WITH_ERRORS")
                failed = [x for x in result["receipts"] if x["status"] != "OK"]
                self.assertEqual([x["key"] for x in failed], [key])
                self.assertEqual(failed[0]["exit_code"], 1)

    def test_disconnect_and_identity_failure_leave_explicit_unread_rows(self):
        for key in ("fg_driver", "linux_cmdline", "fg_present", "smb_jeita_soft_hot_msb"):
            with self.subTest(key=key):
                result = r.collect(FakeChannel(fail_key=key, disconnect=True), {"bootargs": "offline-args"}, HealthyMonitor(), lambda d: None)
                self.assertEqual(result["status"], "INCOMPLETE")
                keys = [x["key"] for x in result["receipts"]]
                self.assertTrue(all(keys.count(k) == 1 for k, _, _ in r.FIELDS))
                self.assertTrue(any(x["status"] == "NOT_ATTEMPTED" for x in result["receipts"]))

    def test_capture_budget_and_dead_monitor_do_not_silently_drop_fields(self):
        class SlowChannel(FakeChannel):
            now = 0
            def send(self, script, deadline):
                super().send(script, deadline)
                self.now += 1
        channel = SlowChannel()
        with mock.patch.object(r.time, "monotonic", side_effect=lambda: channel.now):
            result = r.collect(channel, {"bootargs": "offline-args"}, HealthyMonitor(), lambda d: None)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(channel.now, 15)
        self.assertTrue(any(x["status"] == "NOT_ATTEMPTED_BUDGET" for x in result["receipts"]))
        dead = mock.Mock()
        dead.healthy.return_value = False
        result = r.collect(FakeChannel(), {"bootargs": "offline-args"}, dead, lambda d: None)
        self.assertEqual(result["status"], "INCOMPLETE")
        for key, _, _ in r.FIELDS:
            self.assertEqual(sum(x["key"] == key for x in result["receipts"]), 1)

    def test_session_success_keeps_safety_claims_false(self):
        result = r.run_session(FakeIO())
        self.assertTrue(result["success"])
        self.assertFalse(result["risk"]["charging_stopped_verified"])
        self.assertFalse(result["risk"]["charging_safety_validated"])
        self.assertTrue(result["risk"]["inherited_charging_possible"])

    def test_interrupt_and_error_after_transition_always_recover(self):
        for stage in ("enter_fastboot", "check_fastboot", "gate2", "boot", "observe"):
            for error in (RuntimeError("failure"), KeyboardInterrupt(), InterruptedError("SIGTERM")):
                with self.subTest(stage=stage, error=type(error).__name__):
                    io = FakeIO(stage, error)
                    result = r.run_session(io)
                    self.assertFalse(result["success"])
                    self.assertTrue(result["android_return_verified"])
                    self.assertIn("recover", io.calls)
                    self.assertTrue(io.recovering)
                    self.assertEqual(io.calls[-1], "stop_monitor")
                    self.assertEqual(io.calls.count("boot"), int(stage in ("boot", "observe")))

    def test_preflight_failures_never_transition_or_boot(self):
        for stage in ("gate1", "start_monitor", "preflight", "arm_recovery"):
            io = FakeIO(stage)
            result = r.run_session(io)
            self.assertFalse(result["success"])
            self.assertNotIn("enter_fastboot", io.calls)
            self.assertNotIn("recover", io.calls)
        for index in range(7):
            io = FakeIO()
            io.before[index] = "wrong"
            result = r.run_session(io)
            self.assertFalse(result["success"])
            self.assertNotIn("enter_fastboot", io.calls)

    def test_after_identity_hash_or_boot_id_failure_never_passes(self):
        for index in range(7):
            io = FakeIO()
            io.after[index] = "wrong"
            result = r.run_session(io)
            self.assertFalse(result["android_return_verified"])
            self.assertTrue(result["manual_recovery_required"])
        io = FakeIO()
        io.after[4] = io.before[4]
        self.assertFalse(r.run_session(io)["success"])
        io = FakeIO("recover", TimeoutError("offline deadline"))
        result = r.run_session(io)
        self.assertTrue(result["manual_recovery_required"])

    def test_unknown_boot_ack_partial_capture_or_dead_monitor_never_passes(self):
        for change in (lambda io: setattr(io, "boot_accepted", False),
                       lambda io: setattr(io, "capture_status", "INCOMPLETE"),
                       lambda io: io.monitor_result.update(exit_code=1),
                       lambda io: io.monitor_result.update(sampling_verified=False),
                       lambda io: io.monitor_result.update(premature=True),
                       lambda io: io.monitor_result.update(forced=True)):
            io = FakeIO()
            change(io)
            result = r.run_session(io)
            self.assertFalse(result["success"])
            self.assertTrue(result["android_return_verified"])

    def test_independent_monitor_samples_during_blocking_work_and_survives_sigint(self):
        with tempfile.TemporaryDirectory(prefix="offline-c224-", dir=TEMP_ROOT) as temp:
            root = Path(temp)
            port = root / r.PORT
            port.mkdir()
            for key, val in (("idVendor", "18d1"), ("idProduct", "4ee7"), ("serial", "offline"), ("devnum", "1")):
                (port / key).write_text(val)
            monitor = r.USBMonitor(root, root, interval=0.01)
            try:
                monitor.start()
                os.kill(monitor.process.pid, signal.SIGINT)  # Only our fake-file monitor child.
                time.sleep(0.08)  # Simulated blocking serial work, never a device call.
                self.assertTrue(monitor.healthy())
                (port / "devnum").write_text("2")
                end = time.monotonic() + 2
                while time.monotonic() < end:
                    rows = [json.loads(x) for x in monitor.path.read_text().splitlines()]
                    if any(x["snapshot"].get("devnum") == "2" for x in rows):
                        break
                    time.sleep(0.01)
                self.assertGreater(len(rows), 2)
                self.assertTrue(any(x["snapshot"].get("devnum") == "2" for x in rows))
                self.assertEqual([x["seq"] for x in rows], list(range(len(rows))))
            finally:
                result = monitor.stop()
            self.assertEqual(result["exit_code"], 0)
            self.assertFalse(result["forced"])
            self.assertFalse(result["premature"])
            self.assertTrue(result["sampling_verified"])

    def test_recovery_rejects_wrong_port_or_duplicate_fastboot_rows(self):
        class Clock:
            now = 0
            def monotonic(self): return self.now
            def sleep(self, seconds): self.now += seconds
        for rows in (b"offline fastboot usb:1-3\n", b"offline fastboot usb:1-2\noffline fastboot usb:1-2\n"):
            clock = Clock()
            io = object.__new__(r.LiveIO)
            io.serial, io.deadline, io.boot_time, io.recovery_notes = "offline", 1, None, []
            io.save = lambda *args: None
            commands = []
            def command(name, args, **kwargs):
                commands.append(args)
                return {"exit_code": 0, "stdout": rows}
            io.base = mock.Mock()
            io.base.command = command
            with mock.patch.object(r, "usb_snapshot", return_value={"vid": "18d1", "pid": "4ee0", "serial": "offline"}), \
                 mock.patch.object(r.time, "monotonic", side_effect=clock.monotonic), \
                 mock.patch.object(r.time, "sleep", side_effect=clock.sleep), \
                 self.assertRaises(TimeoutError):
                io.recover()
            self.assertFalse(any(x[-1] == "reboot" for x in commands))
            self.assertEqual(io.deadline, 1)


class IntegrityAndCoverageRegressions(unittest.TestCase):
    def test_health_uses_time_since_sample_start(self):
        monitor = object.__new__(r.USBMonitor)
        monitor.drain = lambda: None
        monitor.process = mock.Mock()
        monitor.process.is_alive.return_value = True
        monitor.heartbeat_overflow = False
        monitor.samples = [{"sample_started_ns": 0, "monotonic_ns": 900_000_000}]
        for now, expected in ((1_000_000_000, True), (1_000_000_001, False),
                              (1_800_000_000, False)):
            with self.subTest(now=now), mock.patch.object(r.time, "monotonic_ns", return_value=now):
                self.assertEqual(monitor.healthy(), expected)

    def test_stream_metadata_and_each_applet_status_are_mandatory(self):
        raw = frame(out=b"1234\n", err=b"warning")
        f = r.parse_frame(raw, PREFIX)
        self.assertEqual(f["stdout_length"], 5)
        self.assertEqual(f["stderr_length"], 7)
        self.assertEqual(f["stdout_sha256"], hashlib.sha256(b"1234\n").hexdigest())
        self.assertEqual(f["stderr_sha256"], hashlib.sha256(b"warning").hexdigest())
        self.assertTrue(f["payload_integrity_verified"])
        self.assertFalse(f["authentication_provided"])
        for i in range(7):
            codes = [0] * 7
            codes[i] = 1
            with self.subTest(applet=i), self.assertRaisesRegex(ValueError, "applet failed"):
                r.parse_frame(frame(applet_codes=codes), PREFIX)
        for stream, payload in (("OUT", b"1234\n"), ("ERR", b"warning")):
            digest = hashlib.sha256(payload).hexdigest()
            for changed in (raw.replace(f"{stream}_META_{len(payload)}_".encode(), f"{stream}_META_{len(payload)+1}_".encode()),
                            raw.replace(digest.encode(), b"0" * 64),
                            raw.replace(f"{stream}_META_".encode(), f"{stream}_MISSING_".encode())):
                with self.subTest(stream=stream), self.assertRaises(ValueError):
                    r.parse_frame(changed, PREFIX)
        # Public digests and a nonce are integrity/correlation, not authentication.
        self.assertEqual(r.parse_frame(frame(out=b"9234\n"), PREFIX)["stdout"], b"9234\n")
        self.assertFalse(r.RISK["transport_authentication_provided"])

    def test_combined_read_and_tail_uncertainty_is_not_split_into_two_passes(self):
        rows = [{"seq": 0, "sample_started_ns": 0, "monotonic_ns": 100_000_000},
                {"seq": 1, "sample_started_ns": 200_000_000, "monotonic_ns": 1_100_000_000}]
        result = r.sample_coverage(rows, 0, 2_000_000_000, 0, 2_000_000_000)
        self.assertFalse(result["sampling_verified"])
        self.assertEqual(result["tail_gap_seconds"], 1.8)
        self.assertEqual(result["max_gap_seconds"], 0.2)
        self.assertEqual(result["max_observation_span_seconds"], 1.1)

    def test_head_full_read_duration_and_required_session_bounds(self):
        good = [{"seq": 0, "sample_started_ns": 10_000_000, "monotonic_ns": 20_000_000},
                {"seq": 1, "sample_started_ns": 210_000_000, "monotonic_ns": 220_000_000}]
        self.assertTrue(r.sample_coverage(good, 0, 300_000_000, 0, 250_000_000)["sampling_verified"])
        for rows, start, done, required_start, required_end in (
                (good, -1_000_000_001, 300_000_000, 0, 250_000_000),
                (good, 0, 300_000_000, 0, 400_000_000),
                (good, 0, 300_000_000, 250_000_000, 0),
                ([good[0], {"seq": 1, "sample_started_ns": 210_000_000, "monotonic_ns": 1_220_000_001}], 0, 1_230_000_000, 0, 1_230_000_000)):
            self.assertFalse(r.sample_coverage(rows, start, done, required_start, required_end)["sampling_verified"])

    def test_numeric_stdout_shortened_with_markers_intact_is_rejected(self):
        raw = frame(out=b"1234\n")
        self.assertEqual(r.receipt_result(r.parse_frame(raw, PREFIX), "int")["status"], "OK")
        damaged = raw.replace(b"31 32 33 34 0a", b"33 34 0a")
        with self.assertRaises(ValueError):
            r.parse_frame(damaged, PREFIX)

    def test_stderr_deleted_with_markers_intact_is_rejected(self):
        raw = frame(out=b"0x00\n", err=b"warning")
        self.assertEqual(r.receipt_result(r.parse_frame(raw, PREFIX), "raw")["status"], "INVALID_OUTPUT")
        damaged = raw.replace(b"77 61 72 6e 69 6e 67", b"")
        with self.assertRaises(ValueError):
            r.parse_frame(damaged, PREFIX)

    def test_same_length_stdout_substitution_is_rejected(self):
        raw = frame(out=b"1234\n")
        self.assertEqual(r.parse_frame(raw, PREFIX)["stdout"], b"1234\n")
        with self.assertRaises(ValueError):
            r.parse_frame(raw.replace(b"31 32 33 34 0a", b"39 32 33 34 0a"), PREFIX)

    def fake_monitor(self, directory):
        root = Path(directory)
        port = root / r.PORT
        port.mkdir()
        for key, value in (("idVendor", "18d1"), ("idProduct", "4ee7"), ("serial", "offline"), ("devnum", "1")):
            (port / key).write_text(value)
        monitor = r.USBMonitor(root, root, interval=0.01)
        monitor.start()
        end = time.monotonic() + 2
        while len(monitor.path.read_text().splitlines()) < 3:
            if time.monotonic() >= end:
                self.fail("fake monitor failed to emit three samples")
            time.sleep(0.01)
        return monitor

    def test_sigstop_process_is_alive_but_heartbeat_is_not_healthy(self):
        with tempfile.TemporaryDirectory(prefix="offline-c224-", dir=TEMP_ROOT) as temp:
            monitor = self.fake_monitor(temp)
            try:
                os.kill(monitor.process.pid, signal.SIGSTOP)
                os.waitpid(monitor.process.pid, os.WUNTRACED)
                time.sleep(1.15)
                self.assertTrue(monitor.process.is_alive())
                self.assertFalse(monitor.healthy())
            finally:
                os.kill(monitor.process.pid, signal.SIGCONT)
                monitor.stop()

    def test_sigstop_tail_then_stop_and_resume_cannot_pass_coverage(self):
        with tempfile.TemporaryDirectory(prefix="offline-c224-", dir=TEMP_ROOT) as temp:
            monitor = self.fake_monitor(temp)
            resume = None
            try:
                os.kill(monitor.process.pid, signal.SIGSTOP)
                os.waitpid(monitor.process.pid, os.WUNTRACED)
                time.sleep(1.15)
                # Resume only after stop has requested exit: no fresh final sample.
                def resume_after_stop():
                    deadline = time.monotonic() + 2
                    while monitor.stop_requested_ns is None and time.monotonic() < deadline:
                        time.sleep(0.001)
                    os.kill(monitor.process.pid, signal.SIGCONT)
                resume = threading.Thread(target=resume_after_stop)
                resume.start()
                result = monitor.stop()
                resume.join(2)
                self.assertEqual(result["exit_code"], 0)
                self.assertFalse(result["forced"])
                self.assertFalse(result["sampling_verified"])
            finally:
                if monitor.process.is_alive():
                    os.kill(monitor.process.pid, signal.SIGCONT)
                    monitor.stop()
                if resume is not None:
                    resume.join(2)

    def test_frozen_sampler_stop_is_nonblocking_and_bounded_without_resume(self):
        with tempfile.TemporaryDirectory(prefix="offline-c224-", dir=TEMP_ROOT) as temp:
            monitor = self.fake_monitor(temp)
            try:
                os.kill(monitor.process.pid, signal.SIGSTOP)
                os.waitpid(monitor.process.pid, os.WUNTRACED)
                started = time.monotonic()
                result = monitor.stop()
                self.assertLess(time.monotonic() - started, 2.5)
                self.assertTrue(result["forced"])
                self.assertFalse(result["sampling_verified"])
                self.assertGreaterEqual(result["monitor_done_ns"], result["stop_requested_ns"])
            finally:
                if monitor.process.is_alive():
                    os.kill(monitor.process.pid, signal.SIGKILL)
                    monitor.process.join(1)

    def test_unreadable_real_monitor_log_never_passes(self):
        with tempfile.TemporaryDirectory(prefix="offline-c224-", dir=TEMP_ROOT) as temp:
            root = Path(temp)
            (root / r.PORT).mkdir()  # No idVendor, idProduct, serial or devnum.
            monitor = r.USBMonitor(root, root, interval=0.01)
            try:
                monitor.start()
                time.sleep(0.05)
            finally:
                result = monitor.stop()
            self.assertTrue(result["log_integrity_verified"])
            self.assertFalse(result["observation_verified"])
            self.assertFalse(result["sampling_verified"])
            self.assertGreater(result["unreadable_samples"], 0)

    def test_log_truncation_or_snapshot_change_is_detected_against_heartbeat(self):
        for damage in ("truncate", "snapshot"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory(prefix="offline-c224-", dir=TEMP_ROOT) as temp:
                monitor = self.fake_monitor(temp)
                monitor.drain()
                with tempfile.TemporaryDirectory(prefix="offline-c224-", dir=TEMP_ROOT) as corrupt:
                    copied = Path(corrupt) / "usb-samples.jsonl"
                    lines = monitor.path.read_bytes().splitlines(keepends=True)[:len(monitor.samples)]
                    if damage == "truncate":
                        lines = lines[:-1]
                    else:
                        row = json.loads(lines[0])
                        row["snapshot"]["serial"] = "changed-after-heartbeat"
                        lines[0] = (json.dumps(row) + "\n").encode()
                    copied.write_bytes(b"".join(lines))
                    result = r.verify_usb_log(copied, list(monitor.samples))
                    self.assertFalse(result["log_integrity_verified"])
                    self.assertFalse(result["observation_verified"])
                result = monitor.stop()
                self.assertTrue(result["sampling_verified"])

    def test_session_requires_log_and_observation_and_coverage_proofs(self):
        for key in ("log_integrity_verified", "observation_verified", "session_coverage_verified"):
            io = FakeIO()
            io.monitor_result[key] = False
            result = r.run_session(io)
            self.assertFalse(result["success"])
            self.assertTrue(result["android_return_verified"])
            self.assertEqual(io.session_window, (result["session_range"]["start_ns"], result["session_range"]["end_ns"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
