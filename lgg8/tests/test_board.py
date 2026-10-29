#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the board once and check offline boot/USB/display contracts."""
import copy
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
BOOTIMG = ROOT / "lgg8/tools/bootimg.py"
# Load the production parser without creating __pycache__ in the source tree.
boot = types.ModuleType("board_bootimg")
boot.__file__ = str(BOOTIMG)
exec(compile(BOOTIMG.read_bytes(), str(BOOTIMG), "exec"), boot.__dict__)


class BoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tools = {name: shutil.which(name) for name in ("clang", "dtc")}
        missing = [name for name, path in tools.items() if path is None]
        if missing:
            raise unittest.SkipTest("board DTB tests require: " + ", ".join(missing))
        temporary = tempfile.TemporaryDirectory(prefix="lgg8-board-test-")
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        source = ROOT / "arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dts"
        preprocessed, output = directory / "board.dts", directory / "board.dtb"
        includes = (source.parent, ROOT / "arch/arm64/boot/dts",
                    ROOT / "include", ROOT / "scripts/dtc/include-prefixes")
        commands = (
            [tools["clang"], "-E", "-P", "-x", "assembler-with-cpp", "-nostdinc",
             "-undef", "-D__DTS__", *[f"-I{path}" for path in includes],
             str(source), "-o", str(preprocessed)],
            [tools["dtc"], "-q", "-I", "dts", "-O", "dtb", "-@",
             "-i", str(source.parent), "-o", str(output), str(preprocessed)],
        )
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError(f"{Path(command[0]).name} failed:\n{result.stderr}")
        cls.tree = boot.Fdt(output.read_bytes())
        cls.config = dict(line.split("=", 1) for line in
                          (ROOT / "lgg8/configs/lgg8.config").read_text().splitlines()
                          if line.startswith("CONFIG_") and "=" in line)

    @staticmethod
    def strings(value):
        return value.rstrip(b"\0").decode("ascii").split("\0") if value else []

    def cells(self, value):
        self.assertEqual(len(value) % 4, 0, "DT property is not a cell array")
        return struct.unpack(f">{len(value) // 4}I", value)

    def enabled(self, tree, path):
        while True:
            if tree.nodes[path].get("status", b"okay\0") not in (b"okay\0", b"ok\0"):
                return False
            if path == "/":
                return True
            path = path.rsplit("/", 1)[0] or "/"

    def compatible(self, tree, compatible, enabled=True):
        paths = [path for path, props in tree.nodes.items()
                 if compatible in self.strings(props.get("compatible", b""))
                 and (not enabled or self.enabled(tree, path))]
        self.assertEqual(len(paths), 1, f"expected one {compatible}, got {paths}")
        return paths[0]

    def resolve(self, tree, value):
        handle, = self.cells(value)
        self.assertNotEqual(handle, 0, "null phandle")
        paths = [path for path, props in tree.nodes.items()
                 if props.get("phandle") == value]
        self.assertEqual(len(paths), 1, f"unresolved/duplicate phandle {handle:#x}")
        return paths[0]

    def reg(self, tree, path):
        parent = tree.nodes[path.rsplit("/", 1)[0] or "/"]
        ac, = self.cells(parent.get("#address-cells", struct.pack(">I", 2)))
        sc, = self.cells(parent.get("#size-cells", struct.pack(">I", 1)))
        self.assertIn(ac, (1, 2))
        self.assertIn(sc, (1, 2))
        value, stride = tree.nodes[path]["reg"], 4 * (ac + sc)
        self.assertTrue(value)
        self.assertEqual(len(value) % stride, 0)
        return [(int.from_bytes(value[i:i + 4 * ac], "big"),
                 int.from_bytes(value[i + 4 * ac:i + stride], "big"))
                for i in range(0, len(value), stride)]

    def usb(self, tree):
        core = self.compatible(tree, "snps,dwc3")
        return core.rsplit("/", 1)[0], core

    def phys(self, tree, consumer):
        values = self.cells(tree.nodes[consumer]["phys"])
        providers, cursor = [], 0
        while cursor < len(values):
            provider = self.resolve(tree, struct.pack(">I", values[cursor]))
            count, = self.cells(tree.nodes[provider]["#phy-cells"])
            self.assertLessEqual(cursor + 1 + count, len(values), "truncated PHY arguments")
            providers.append(provider)
            cursor += 1 + count
        self.assertTrue(providers, "empty PHY list")
        return providers

    def assert_phys_enabled(self, tree, consumer):
        for provider in self.phys(tree, consumer):
            self.assertTrue(self.enabled(tree, provider), f"disabled PHY provider: {provider}")

    def assert_legacy_usb(self, tree):
        wrapper, core = self.usb(tree)
        compatibles = self.strings(tree.nodes[wrapper]["compatible"])
        self.assertIn("qcom,sm8150-dwc3", compatibles)
        self.assertIn("qcom,dwc3", compatibles)
        self.assertNotIn("qcom,snps-dwc3", compatibles)
        self.assertEqual(self.reg(tree, wrapper), [(0x0a6f8800, 0x400)])
        self.assertEqual(self.reg(tree, core), [(0x0a600000, 0xcd00)])

    def assert_remote(self, tree, endpoint):
        remote = self.resolve(tree, tree.nodes[endpoint]["remote-endpoint"])
        self.assertTrue(self.enabled(tree, remote), f"disabled endpoint: {remote}")
        self.assertEqual(self.resolve(tree, tree.nodes[remote]["remote-endpoint"]), endpoint,
                         f"nonreciprocal graph link: {endpoint} -> {remote}")
        return remote

    def test_usb1_phy_references_enabled_providers(self):
        _, core = self.usb(self.tree)
        self.assert_phys_enabled(self.tree, core)

    def test_usb2_only_peripheral_profile(self):
        wrapper, core = self.usb(self.tree)
        self.assertEqual(self.tree.nodes[wrapper].get("qcom,select-utmi-as-pipe-clk"), b"")
        props = self.tree.nodes[core]
        self.assertEqual(self.strings(props["dr_mode"]), ["peripheral"])
        self.assertEqual(self.strings(props["maximum-speed"]), ["high-speed"])
        self.assertEqual(self.strings(props["phy-names"]), ["usb2-phy"])
        hsphy, = self.phys(self.tree, core)
        self.assertIn("qcom,sm8150-usb-hs-phy",
                      self.strings(self.tree.nodes[hsphy]["compatible"]))

    def test_wrapper_resource_matches_legacy_mapping(self):
        self.assert_legacy_usb(self.tree)
        source = (ROOT / "drivers/usb/dwc3/dwc3-qcom-legacy.c").read_text()
        source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
        self.assertRegex(source, r'\.compatible\s*=\s*"qcom,dwc3"')
        assignments = re.findall(r"\bqscratch_base\s*([+\-]?=)(?!=)\s*([^;]+);", source)
        self.assertEqual(len(assignments), 1, "legacy QSCRATCH must not be rebased after mapping")
        operation, expression = assignments[0]
        self.assertEqual(operation, "=")
        self.assertRegex(expression, r"^devm_platform_ioremap_resource"
                                     r"\(\s*pdev\s*,\s*0\s*\)$")

    def test_selected_drivers_match_usb_compatibles(self):
        _, core = self.usb(self.tree)
        providers = self.phys(self.tree, core)
        self.assertEqual(len(providers), 1)
        driver = (ROOT / "drivers/phy/qualcomm/phy-qcom-snps-femto-v2.c").read_text()
        matches = re.findall(r'\.compatible\s*=\s*"([^"]+)"', driver)
        self.assertTrue(set(matches) & set(self.strings(self.tree.nodes[providers[0]]["compatible"])))
        for option in ("USB_DWC3", "USB_DWC3_QCOM", "USB_DWC3_GADGET",
                       "PHY_QCOM_USB_SNPS_FEMTO_V2"):
            self.assertEqual(self.config.get("CONFIG_" + option), "y", option + " must be built in")
        makefile = (ROOT / "drivers/usb/dwc3/Makefile").read_text()
        self.assertRegex(makefile, r"obj-\$\(CONFIG_USB_DWC3_QCOM\)\s*\+=\s*dwc3-qcom-legacy\.o")
        makefile = (ROOT / "drivers/phy/qualcomm/Makefile").read_text()
        self.assertRegex(makefile, r"obj-\$\(CONFIG_PHY_QCOM_USB_SNPS_FEMTO_V2\)\s*\+=\s*phy-qcom-snps-femto-v2\.o")

    def test_payload_workspace_is_ram_and_avoids_reservations(self):
        ramoops = self.compatible(self.tree, "ramoops")
        (start, size), = self.reg(self.tree, ramoops)
        self.assertGreater(start, boot.LOAD)
        self.assertGreater(size, 0)
        self.assertIn("no-map", self.tree.nodes[ramoops])
        self.tree.memory_contract(boot.LOAD, start)
        with self.assertRaisesRegex(ValueError, "overlaps reserved RAM.*ramoops"):
            self.tree.memory_contract(boot.LOAD, start + boot.PAGE)
        with self.assertRaisesRegex(ValueError, "outside a real FDT RAM bank"):
            self.tree.memory_contract(0, boot.PAGE)

    def test_dpu_dsi_panel_graph_is_reciprocal_with_four_lanes(self):
        tree = self.tree
        panel = self.compatible(tree, "lg,sw43410")
        host = panel.rsplit("/", 1)[0]
        self.assertIn("qcom,sm8150-dsi-ctrl", self.strings(tree.nodes[host]["compatible"]))
        endpoints = [path for path, props in tree.nodes.items()
                     if path.startswith(panel + "/") and "remote-endpoint" in props]
        self.assertEqual(len(endpoints), 1)
        output = self.assert_remote(tree, endpoints[0])
        self.assertTrue(output.startswith(host + "/"))
        self.assertCountEqual(self.cells(tree.nodes[output]["data-lanes"]), range(4))
        dpu = self.compatible(tree, "qcom,sm8150-dpu")
        inputs = [path for path, props in tree.nodes.items()
                  if path.startswith(host + "/") and not path.startswith(panel + "/")
                  and "remote-endpoint" in props
                  and self.resolve(tree, props["remote-endpoint"]).startswith(dpu + "/")]
        self.assertEqual(len(inputs), 1, "DSI must have an input connected to the enabled DPU")
        self.assert_remote(tree, inputs[0])

    def test_display_and_usb_supply_references_resolve(self):
        tree = self.tree
        panel = self.compatible(tree, "lg,sw43410")
        host = panel.rsplit("/", 1)[0]
        self.assert_phys_enabled(tree, host)
        dsi_phy, = self.phys(tree, host)
        _, core = self.usb(tree)
        hsphy, = self.phys(tree, core)
        for path, required in ((panel, ("vddi", "vpnl")), (host, ("vdda",)),
                               (dsi_phy, ("vdds",)),
                               (hsphy, ("vdda-pll", "vdda18", "vdda33"))):
            for name in required:
                self.assertIn(name + "-supply", tree.nodes[path], path)
            for name, value in tree.nodes[path].items():
                if not name.endswith("-supply"):
                    continue
                with self.subTest(consumer=path, supply=name):
                    provider = self.resolve(tree, value)
                    self.assertTrue(self.enabled(tree, provider), f"disabled supply: {provider}")
                    props = tree.nodes[provider]
                    self.assertTrue(any(key.startswith("regulator-") for key in props)
                                    or any("regulator" in item for item in
                                           self.strings(props.get("compatible", b""))), provider)
                    if "regulator-min-microvolt" in props:
                        low, = self.cells(props["regulator-min-microvolt"])
                        high, = self.cells(props["regulator-max-microvolt"])
                        self.assertGreater(low, 0)
                        self.assertLessEqual(low, high)
        for option in ("DRM_MSM_DSI", "DRM_MSM_DSI_7NM_PHY", "DRM_PANEL_LG_SW43410"):
            self.assertEqual(self.config.get("CONFIG_" + option), "y", option + " must be built in")

    def test_rejects_historical_disabled_combo_phy_reference(self):
        tree = copy.deepcopy(self.tree)
        _, core = self.usb(tree)
        combo = self.compatible(tree, "qcom,sm8150-qmp-usb3-dp-phy", enabled=False)
        tree.nodes[combo]["status"] = b"disabled\0"
        tree.nodes[core]["phys"] += tree.nodes[combo]["phandle"] + struct.pack(">I", 0)
        with self.assertRaisesRegex(AssertionError, "disabled PHY provider"):
            self.assert_phys_enabled(tree, core)

    def test_rejects_dangling_phy_reference(self):
        tree = copy.deepcopy(self.tree)
        _, core = self.usb(tree)
        tree.nodes[core]["phys"] = struct.pack(">I", 0xfffffffe)
        with self.assertRaisesRegex(AssertionError, "unresolved/duplicate phandle"):
            self.assert_phys_enabled(tree, core)

    def test_rejects_modern_wrapper_profile_and_doubled_offset(self):
        for modern in (True, False):
            with self.subTest(modern_profile=modern):
                tree = copy.deepcopy(self.tree)
                wrapper, _ = self.usb(tree)
                if modern:
                    tree.nodes[wrapper]["compatible"] = b"qcom,snps-dwc3\0"
                else:
                    tree.nodes[wrapper]["reg"] = struct.pack(">QQ", 0x0a6f8800 + 0xf8800, 0x400)
                with self.assertRaises(AssertionError):
                    self.assert_legacy_usb(tree)

    def test_rejects_nonreciprocal_panel_graph(self):
        tree = copy.deepcopy(self.tree)
        panel = self.compatible(tree, "lg,sw43410")
        endpoint, = [path for path, props in tree.nodes.items()
                     if path.startswith(panel + "/") and "remote-endpoint" in props]
        remote = self.resolve(tree, tree.nodes[endpoint]["remote-endpoint"])
        tree.nodes[remote]["remote-endpoint"] = tree.nodes[remote]["phandle"]
        with self.assertRaisesRegex(AssertionError, "nonreciprocal graph link"):
            self.assert_remote(tree, endpoint)


if __name__ == "__main__":
    unittest.main()
