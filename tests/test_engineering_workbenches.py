from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from extract_pins_plugin.core.bringup_packager import c_header, collect_bringup_rows, markdown
from harness_workbench_plugin.analysis import PinRecord, auto_link, harness_svg, validate_links
from manufacturing_readiness_plugin.analysis import BoardMetrics, FabricatorProfile, audit_metrics, build_release
from pdn_decoupling_plugin.analysis import PadNode, analyze_decoupling, infer_regulators
from protocol_constraint_composer_plugin.analysis import detect_protocols, generate_rules, merge_managed_rules
from return_path_auditor_plugin.analysis import CopperSegment, ReferenceRegion, ReturnPathAnalyzer, ViaPoint


ROOT = Path(__file__).resolve().parents[1]
NEW_PACKAGES = (
    "return_path_auditor_plugin", "harness_workbench_plugin", "manufacturing_readiness_plugin",
    "pdn_decoupling_plugin", "protocol_constraint_composer_plugin",
)


class EngineeringWorkbenchTests(unittest.TestCase):
    def test_return_path_flags_transition_without_return_via_and_long_branch(self):
        segments = [CopperSegment("CLK", "F.Cu", (0, 0), (10, 0), 0.2),
                    CopperSegment("CLK", "F.Cu", (10, 0), (20, 0), 0.2),
                    CopperSegment("CLK", "F.Cu", (10, 0), (10, 8), 0.2)]
        result = ReturnPathAnalyzer().audit(
            segments, [ViaPoint("CLK", (10, 0), ("F.Cu", "In1.Cu"))],
            [ReferenceRegion("GND", "In1.Cu", (-1, -1, 21, 1))], 2.0, 5.0,
        )
        checks = {finding.check for finding in result.findings}
        self.assertIn("Layer transition return via", checks)
        self.assertIn("Possible routed stub", checks)

    def test_return_path_flags_differential_skew_and_uncoupling(self):
        result = ReturnPathAnalyzer().audit([
            CopperSegment("USB_P", "F.Cu", (0, 0), (20, 0), 0.15),
            CopperSegment("USB_N", "F.Cu", (0, 0.2), (8, 0.2), 0.15),
            CopperSegment("USB_N", "B.Cu", (8, 0.2), (10, 0.2), 0.15),
        ], [], [], differential_gap_limit_mm=0.5, differential_skew_limit_mm=0.5)
        checks = {finding.check for finding in result.findings}
        self.assertIn("Differential-pair skew", checks)
        self.assertIn("Differential-pair uncoupling", checks)

    def test_harness_wildcard_link_and_voltage_conflict(self):
        sources = [PinRecord("CTRL", "J1", "1", "CTRL_SPI_CLK", voltage="3V3")]
        destinations = [PinRecord("IO", "J2", "8", "IO_SPI_CLK", voltage="5V")]
        links = auto_link(sources, destinations, "CTRL_*", "IO_*")
        self.assertEqual("linked", links[0].status)
        self.assertTrue(any("Voltage mismatch" in issue for issue in validate_links(links)))
        self.assertIn("CTRL_SPI_CLK", harness_svg(links))

    def test_manufacturing_gate_blocks_failed_profile_and_hashes_release(self):
        profile = FabricatorProfile(minimum_track_mm=0.15)
        failed = audit_metrics(BoardMetrics(0.10, 0.2, 0.3, 0.12, 5, 4), profile)
        self.assertEqual("FAIL", failed[0].status)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); source = root / "demo.gbr"; source.write_text("demo", encoding="ascii")
            passing = audit_metrics(BoardMetrics(0.2, 0.2, 0.3, 0.12, 5, 4), profile)
            destination = root / "release.zip"; manifest = build_release(destination, [source], passing, "test")
            self.assertEqual(1, len(manifest["files"]))
            with zipfile.ZipFile(destination) as archive:
                self.assertIn("kiway-release-manifest.json", archive.namelist())

    def test_pdn_requires_capacitor_between_same_rail_and_ground(self):
        pads = [PadNode("U1", "1", "3V3", 0, 0, "MCU"), PadNode("C1", "1", "3V3", 1, 0, "100n"),
                PadNode("C1", "2", "GND", 1, 0.5, "100n"), PadNode("U2", "1", "5V", 10, 0, "LDO")]
        findings = analyze_decoupling(pads, "3V3,5V", "GND", maximum_distance_mm=3)
        self.assertEqual(["pass", "error"], [finding.severity for finding in findings])
        self.assertEqual(["U2"], infer_regulators(pads))

    def test_constraint_detection_and_managed_merge(self):
        assignments = detect_protocols(["USB_D+", "CANH", "STATUS"])
        self.assertEqual({"USB2", "CAN"}, {item.protocol for item in assignments})
        generated = generate_rules(assignments)
        merged = merge_managed_rules("(version 1)\n(rule \"existing\" (constraint clearance (min 0.2mm)))\n", generated)
        self.assertIn('rule "existing"', merged)
        self.assertEqual(1, merged.count("BEGIN KIWAY MANAGED"))
        self.assertEqual(1, merge_managed_rules(merged, generated).count("BEGIN KIWAY MANAGED"))

    def test_bringup_packager_generates_docs_and_firmware_header(self):
        rows = collect_bringup_rows([
            {"reference": "J1", "pin": "1", "net": "SWDIO", "function": "DEBUG_DATA"},
            {"reference": "U1", "pin": "5", "net": "BOOT0", "function": "BOOT_MODE"},
            {"reference": "R1", "pin": "1", "net": "SWCLK"},
        ])
        self.assertEqual(2, len(rows)); self.assertIn("Bring-Up Checklist", markdown(rows))
        self.assertIn("KIWAY_SWD_DEBUG_DATA_PIN", c_header(rows))

    def test_new_pcm_packages_have_runtime_icon_help_and_action(self):
        for folder in NEW_PACKAGES:
            with self.subTest(folder=folder):
                root = ROOT / folder; metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual("swig", metadata["versions"][0]["runtime"])
                self.assertTrue((root / "icon.png").is_file()); self.assertTrue((root / "help.html").is_file())
                self.assertTrue((root / "help-workflow.png").is_file())
                source = (root / f"{folder.removesuffix('_plugin')}_plugin.py").read_text(encoding="utf-8")
                self.assertIn("pcbnew.ActionPlugin", source)
                self.assertIn("show_toolbar_button=True", source.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
