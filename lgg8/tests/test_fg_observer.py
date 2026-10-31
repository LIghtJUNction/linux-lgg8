"""Run the complete, unmodified observer .c with host kernel API substitutes.

This tests actual probe/get_property/sysfs behavior, not Linux regmap, devres,
power_supply core or PMIC hardware semantics. No device access; builds are small,
kept under lgg8/tests and removed on exit. No /tmp or kernel-source edits.
"""
import hashlib
import os
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent


def disable_core():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class FgObserverTest(unittest.TestCase):
    def test_actual_driver(self):
        source = ROOT / "drivers/power/supply/qcom_fg_observer.c"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        pmic_header = (ROOT / "include/soc/qcom/qcom-spmi-pmic.h").read_text()
        pmic_subtype = re.search(r"^#define PM8150B_SUBTYPE\s+(0x[0-9a-fA-F]+)",
                                 pmic_header, re.MULTILINE).group(1)
        with tempfile.TemporaryDirectory(prefix="test-fg-observer-", dir=TESTS) as temp:
            directory = Path(temp)
            for header in ("linux/math64.h", "linux/module.h", "linux/platform_device.h",
                           "linux/power_supply.h", "linux/property.h", "linux/regmap.h",
                           "linux/unaligned.h", "soc/qcom/qcom-spmi-pmic.h"):
                path = directory / header
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#include "test_fg_observer_shim.h"\n')
            env = {**os.environ, "TMPDIR": temp, "TMP": temp, "TEMP": temp,
                   "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                   "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
            for mode, flags in (("strict", ["-O2"]),
                                ("sanitizers", ["-O1", "-g", "-fsanitize=address,undefined",
                                                "-fno-omit-frame-pointer"])):
                with self.subTest(mode=mode):
                    binary = directory / mode
                    subprocess.run([
                        os.environ.get("CC", "cc"), "-pipe", "-std=gnu11", "-Wall", "-Wextra",
                        "-Werror", "-Wno-unused-parameter", "-DTEST_FG_OBSERVER_OFFLINE=1",
                        f"-DPM8150B_SUBTYPE={pmic_subtype}",
                        "-I", str(directory), "-I", str(TESTS), *flags,
                        str(TESTS / "test_fg_observer_source.c"), "-o", str(binary),
                    ], check=True, env=env)
                    subprocess.run([str(binary)], check=True, timeout=10, env=env,
                                   preexec_fn=disable_core)
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
