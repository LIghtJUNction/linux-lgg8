#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Mutate the real compiled LG G8 DTB; never write the source DTB or cache."""
import copy
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "lgg8/tools/check_gpio_contract.py"
DTB = ROOT / "out/lgg8/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb"
m = types.ModuleType("gpio_contract_under_test")
m.__file__ = str(TOOL)
exec(compile(TOOL.read_bytes(), str(TOOL), "exec"), m.__dict__)


def words(*values):
    return struct.pack(f">{len(values)}I", *values)


class GPIOContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DTB.is_file():
            raise unittest.SkipTest(f"requires existing compiled board DTB: {DTB}")
        cls.original = m.Fdt(DTB.read_bytes())
        cls.tlmm = next(path for path, props in cls.original.nodes.items()
                        if props.get("compatible") == b"qcom,sm8150-pinctrl\0")
        cls.handle = cls.original.nodes[cls.tlmm]["phandle"]
        cls.i2c7 = "/soc@0/geniqup@8c0000/i2c@89c000"
        cls.panel = "/soc@0/display-subsystem@ae00000/dsi@ae94000/panel@0"
        cls.ufs = "/soc@0/ufshc@1d84000"

    def setUp(self):
        self.tree = copy.deepcopy(self.original)

    def reject(self, *messages):
        # Exercise production serialization/parser as well as contract checking.
        with self.assertRaises(ValueError) as caught:
            m.check(m.Fdt(self.tree.encode()))
        for message in messages:
            self.assertIn(message, str(caught.exception))

    def test_current_profile_panel_and_ufs_pass(self):
        result = m.check(self.tree)
        self.assertEqual(set(result["reserved"]), set(range(92, 96)) |
                         set(range(98, 102)) | set(range(126, 130)))
        self.assertIn((self.panel, "reset-gpios", self.tlmm, 6), result["uses"])
        self.assertIn((self.ufs, "reset-gpios", self.tlmm, 175), result["uses"])

    def test_missing_firmware_protection_rejected(self):
        for value in (None, words(126, 4), words(92, 3, 98, 4, 126, 4)):
            with self.subTest(value=value):
                self.tree = copy.deepcopy(self.original)
                props = self.tree.nodes[self.tlmm]
                if value is None:
                    del props["gpio-reserved-ranges"]
                else:
                    props["gpio-reserved-ranges"] = value
                self.reject(self.tlmm, "gpio-reserved-ranges", "GPIO95")

    def test_reenabled_i2c7_rejected_with_exact_path_and_pins(self):
        self.tree.nodes[self.i2c7]["status"] = b"okay\0"
        self.reject(self.i2c7, "pinctrl-0", "qup-i2c7-default-state", "GPIO98", "GPIO99")

    def test_disabled_ancestor_ignores_even_enabled_child(self):
        self.tree.nodes[self.i2c7]["status"] = b"okay\0"
        self.tree.nodes[m.parent(self.i2c7)]["status"] = b"disabled\0"
        m.check(self.tree)

    def test_mainline_status_values(self):
        for status in (b"disabled\0", b"reserved\0", b"fail\0", b"disable\0", b""):
            with self.subTest(status=status):
                self.tree.nodes[self.i2c7]["status"] = status
                m.check(self.tree)
        for status in (None, b"ok\0", b"okay\0"):
            with self.subTest(status=status):
                self.tree.nodes[self.i2c7].pop("status", None)
                if status is not None:
                    self.tree.nodes[self.i2c7]["status"] = status
                self.reject(self.i2c7, "GPIO98")

    def test_direct_gpio_arrays_holes_and_exact_provider(self):
        # Same pin number on PMIC is not TLMM; parse mixed provider strides.
        pmic = next(props["phandle"] for props in self.tree.nodes.values()
                    if b"qcom,pm8150-gpio" in props.get("compatible", b"").split(b"\0"))
        self.tree.nodes[self.panel]["test-gpios"] = words(0) + pmic + words(98, 0)
        m.check(self.tree)
        self.tree.nodes[self.panel]["test-gpios"] += self.handle + words(93, 0)
        self.reject(self.panel, "test-gpios", "GPIO93")

    def test_direct_reserved_and_disabled_consumer(self):
        for prop in ("reset-gpios", "reset-gpio", "gpios"):
            with self.subTest(prop=prop):
                self.tree = copy.deepcopy(self.original)
                self.tree.nodes[self.panel][prop] = self.handle + words(127, 0)
                self.reject(self.panel, prop, "GPIO127")
                self.tree.nodes[self.panel]["status"] = b"disabled\0"
                m.check(self.tree)

    def test_referenced_nested_mux_conf_and_unused_definition(self):
        state = self.tlmm + "/contract-test-state"
        self.tree.nodes[state] = {"phandle": words(0x7f001)}
        self.tree.nodes[state + "/mux"] = {"pins": b"gpio92\0", "function": b"gpio\0"}
        self.tree.nodes[state + "/conf"] = {}
        self.tree.nodes[state + "/conf/deep"] = {"groups": b"gpio100\0", "bias-disable": b""}
        m.check(self.tree)  # Merely defining a state is not a request.
        self.tree.nodes[self.panel]["pinctrl-0"] = words(0x7f001)
        self.reject(self.panel, "pinctrl-0", state + "/mux", "GPIO92", "GPIO100")
        self.tree.nodes[state + "/mux"]["status"] = b"disabled\0"
        self.tree.nodes[state + "/conf"]["status"] = b"disabled\0"
        m.check(self.tree)

    def test_referenced_sleep_state_and_legacy_range(self):
        node = self.tree.nodes[self.i2c7]
        node["status"] = b"okay\0"
        node["pinctrl-0"] = b""  # Valid dummy default state.
        state = self.tlmm + "/qup-i2c2-default-state"
        node["pinctrl-1"] = self.tree.nodes[state]["phandle"]
        node["pinctrl-names"] = b"default\0sleep\0"
        self.reject(self.i2c7, "pinctrl-1", "GPIO126", "GPIO127")
        # Linux stops at the first absent state index, rather than reading ID 1.
        del node["pinctrl-0"]
        m.check(self.tree)

    def test_legacy_linux_phandle_and_duplicate_rejection(self):
        props = self.tree.nodes[self.tlmm]
        props["linux,phandle"] = props.pop("phandle")
        m.check(self.tree)
        self.tree.nodes[self.panel]["phandle"] = self.handle
        self.reject("duplicate phandle")

    def test_bad_ranges_or_specifier_fail_clearly(self):
        for value in (b"x", words(92), words(92, 0), words(175, 2)):
            with self.subTest(value=value):
                self.tree = copy.deepcopy(self.original)
                self.tree.nodes[self.tlmm]["gpio-reserved-ranges"] = value
                self.reject(self.tlmm)
        self.tree = copy.deepcopy(self.original)
        self.tree.nodes[self.panel]["reset-gpios"] = self.handle + words(6)
        self.reject(self.panel, "truncated GPIO specifier")

    def test_gpio_hog_uses_parent_relative_cells(self):
        path = self.tlmm + "/contract-test-hog"
        self.tree.nodes[path] = {"gpio-hog": b"", "gpios": words(6, 0), "output-low": b""}
        m.check(self.tree)
        self.tree.nodes[path]["gpios"] = words(101, 0)
        self.reject(path, "GPIO101")

    def test_profile_is_explicit_and_generic_parser_unchanged(self):
        self.tree.nodes["/"]["compatible"] = b"test,generic\0"
        parsed = m.Fdt(self.tree.encode())  # Generic FDT parser accepts it.
        with self.assertRaisesRegex(ValueError, "LG G8"):
            m.check(parsed)

    def test_isolated_cli_pass_and_failure_exit(self):
        with tempfile.TemporaryDirectory(prefix="lgg8-gpio-contract-") as folder:
            path = Path(folder) / "board.dtb"
            for bad in (False, True):
                if bad:
                    self.tree.nodes[self.i2c7]["status"] = b"okay\0"
                path.write_bytes(self.tree.encode())
                result = subprocess.run([sys.executable, "-I", "-B", str(TOOL), "--dtb", str(path)],
                                        cwd=folder, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, int(bad), result.stderr)
                if bad:
                    self.assertIn(self.i2c7, result.stderr)
                    self.assertIn("GPIO98", result.stderr)
                else:
                    self.assertIn("PASS:", result.stdout)
            self.assertEqual(list(Path(folder).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
