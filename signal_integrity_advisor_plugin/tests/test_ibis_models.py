"""Metadata-only IBIS catalog and native assignment checks."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signal_integrity_advisor_plugin.ibis_models import (
    IBISError, assignment_from_catalog, load_ibis, validate_assignment,
)


DEMO = Path("C:/Program Files/KiCad/10.0/share/kicad/demos/simulation/ibis/ibis_v1_1.ibs")

SAMPLE = """[IBIS Ver] 4.1
[Comment char] #_char
[Component] DeviceA
[Pin] signal_name model_name R_pin L_pin C_pin
1 VDD POWER NA NA NA
2 VSS GND NA NA NA
3 spare NC NA NA NA
4 DIN InputModel NA NA NA # inline comment
5 DOUT DriveSelect NA NA NA
6 DIO Bidirectional NA NA NA
[Model Selector] DriveSelect
DriveA Fast mode
DriveB Slow mode
[Model] InputModel
Model_type Input
[GND_clamp]
0 0 0 0
[Model] DriveA
Model_type Output
[Pullup]
0 0 0 0
[Model] DriveB
Model_type 3-state
[Model] Bidirectional
Model_type I/O
[End]
"""


class IBISModelsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "demo.ibs"
        self.path.write_text(SAMPLE, encoding="ascii")

    def write(self, text):
        self.path.write_text(text, encoding="ascii")

    def test_catalog_keeps_names_and_only_metadata(self):
        catalog = load_ibis(self.path)
        self.assertEqual(catalog["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(catalog["components"]["DeviceA"]["pins"]["5"],
                         {"signal_name": "DOUT", "model_name": "DriveSelect"})
        self.assertEqual(catalog["selectors"]["DriveSelect"]["models"], ["DriveA", "DriveB"])
        self.assertEqual(catalog["models"]["Bidirectional"]["roles"], ["source", "sink"])
        self.assertNotIn("Pullup", json.dumps(catalog))
        self.assertNotIn("GND_clamp", json.dumps(catalog))
        self.assertEqual(catalog["path"], str(self.path.resolve()))

    def test_direct_and_selector_assignment_and_corners(self):
        sha = load_ibis(self.path)["sha256"]
        source = validate_assignment(self.path, "DeviceA", "5", "DriveB", "source",
                                     {"vcc": "min", "rpin": "typ", "lpin": "max", "cpin": "typ"},
                                     expected_sha256=sha)
        self.assertEqual(source["model"], "DriveB")
        self.assertEqual(source["corners"]["lpin"], "max")
        self.assertEqual(source["sha256"], sha)
        sink = validate_assignment(self.path, "DeviceA", "4", "InputModel", "sink", "min")
        self.assertEqual(set(sink["corners"].values()), {"min"})
        self.assertEqual(validate_assignment(self.path, "DeviceA", "6", "Bidirectional", "source")["role"], "source")
        self.assertEqual(validate_assignment(self.path, "DeviceA", "6", "Bidirectional", "sink")["role"], "sink")

    def test_catalog_assignment_matches_file_validator_without_io(self):
        catalog = load_ibis(self.path)
        corner = {"vcc": "min", "rpin": "typ", "lpin": "max", "cpin": "typ"}
        expected = validate_assignment(self.path, "DeviceA", "5", "DriveA", "source",
                                       corner, expected_sha256=catalog["sha256"])
        with patch.object(Path, "open", side_effect=AssertionError("unexpected file read")):
            self.assertEqual(assignment_from_catalog(catalog, "DeviceA", "5",
                                                     "DriveA", "source", corner), expected)
            with self.assertRaises(IBISError):
                assignment_from_catalog(catalog, "DeviceA", "5", "InputModel", "sink")
            with self.assertRaises(IBISError):
                assignment_from_catalog(catalog, "DeviceA", "1", "DriveA", "source")

    def test_rejects_invalid_pin_model_role_and_corner(self):
        bad = [
            ("DeviceB", "4", "InputModel", "sink", "typ"),
            ("DeviceA", "7", "InputModel", "sink", "typ"),
            ("DeviceA", "1", "DriveA", "source", "typ"),
            ("DeviceA", "2", "DriveA", "source", "typ"),
            ("DeviceA", "3", "DriveA", "source", "typ"),
            ("DeviceA", "4", "InputModel", "source", "typ"),
            ("DeviceA", "5", "InputModel", "sink", "typ"),
            ("DeviceA", "5", "DriveSelect", "source", "typ"),
            ("DeviceA", "5", "DriveA", "driver", "typ"),
            ("DeviceA", "5", "DriveA", "source", "slow"),
        ]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(IBISError):
                validate_assignment(self.path, *args)
        with self.assertRaises(IBISError):
            validate_assignment(self.path, "DeviceA", "5", "DriveA", "source",
                                {"vcc": "typ"})

    def test_rejects_changed_file_hash_and_hash_covers_end_trailer(self):
        sha = load_ibis(self.path)["sha256"]
        with self.path.open("a", encoding="ascii") as stream:
            stream.write("# harmless after END\n")
        self.assertNotEqual(load_ibis(self.path)["sha256"], sha)
        with self.assertRaisesRegex(IBISError, "changed"):
            validate_assignment(self.path, "DeviceA", "5", "DriveA", "source",
                                expected_sha256=sha)

    def test_missing_selected_model_is_not_accepted(self):
        self.write(SAMPLE.replace("DriveB Slow mode", "Absent Slow mode"))
        catalog = load_ibis(self.path)
        self.assertEqual(catalog["selectors"]["DriveSelect"]["models"], ["DriveA", "Absent"])
        with self.assertRaisesRegex(IBISError, "missing"):
            validate_assignment(self.path, "DeviceA", "5", "Absent", "source")

    def test_duplicate_and_malformed_names_are_rejected(self):
        variants = [
            SAMPLE.replace("[Model] DriveB", "[Model] drivea"),
            SAMPLE.replace("[Model] DriveB", "[Model] DriveA"),
            SAMPLE.replace("6 DIO Bidirectional", "5 DIO Bidirectional"),
            SAMPLE.replace("[Model] DriveB", "[Model] Bad Name"),
            SAMPLE.replace("[Model] DriveB", "[Model Selector] DriveA\nDriveB alt\n[Model] DriveB"),
            SAMPLE.replace("DriveB Slow mode", "DriveA Slow mode"),
            SAMPLE.replace("Model_type Output", "Model_type Output\nModel_type Input"),
        ]
        for variant in variants:
            with self.subTest(variant=variant[-150:]), self.assertRaises(IBISError):
                self.write(variant)
                load_ibis(self.path)

    def test_bounded_file_and_line(self):
        self.path.write_bytes(b"x" * 257)
        with patch("signal_integrity_advisor_plugin.ibis_models.MAX_FILE_BYTES", 256):
            with self.assertRaisesRegex(IBISError, "exceeds"):
                load_ibis(self.path)
        with patch("signal_integrity_advisor_plugin.ibis_models.MAX_LINE_BYTES", 64):
            with self.assertRaisesRegex(IBISError, "line exceeds"):
                load_ibis(self.path)

    def test_same_comment_character_can_be_redeclared(self):
        self.write(SAMPLE.replace("[Component] DeviceA", "[Comment char] #_char\n[Component] DeviceA"))
        self.assertIn("DeviceA", load_ibis(self.path)["components"])

    @unittest.skipUnless(DEMO.is_file(), "KiCad 10.0 native IBIS demo is not installed")
    def test_installed_kicad_native_demo(self):
        catalog = load_ibis(DEMO)
        self.assertEqual(catalog["components"]["Virtual"]["pins"]["3"]["model_name"], "Input")
        self.assertEqual(catalog["components"]["Virtual"]["pins"]["4"]["model_name"], "Output")
        self.assertEqual(catalog["models"]["Input"]["roles"], ["sink"])
        self.assertEqual(catalog["models"]["Output"]["roles"], ["source"])
        validate_assignment(DEMO, "Virtual", "3", "Input", "sink",
                            expected_sha256=catalog["sha256"])
        validate_assignment(DEMO, "Virtual", "4", "Output", "source",
                            expected_sha256=catalog["sha256"])


if __name__ == "__main__":
    unittest.main()
