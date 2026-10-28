"""Connector label parsing, explicit numbering and native annotation custody."""

from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from uuid import UUID


SOURCE = Path(__file__).resolve().parents[1] / "core" / "connector_labels.py"
SPEC = importlib.util.spec_from_file_location("connector_labels", SOURCE)
assert SPEC and SPEC.loader
labels = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(labels)


class LabelListTests(unittest.TestCase):
    def test_plain_lines_header_is_never_silently_removed(self):
        self.assertEqual(labels.parse_pin_text("NAME\nGND\nDATA"), [
            {"pin": "1", "label": "NAME"}, {"pin": "2", "label": "GND"},
            {"pin": "3", "label": "DATA"}])
        self.assertEqual(labels.parse_pin_text("NAME\nGND\nDATA", header=True), [
            {"pin": "1", "label": "GND"}, {"pin": "2", "label": "DATA"}])

    def test_csv_tsv_semicolon_and_quoted_names(self):
        for text in ('\ufeffA1,"SPI, DATA"\r\nB2,GND\r\n',
                     'A1\t"SPI, DATA"\r\nB2\tGND\r\n',
                     'A1;"SPI, DATA"\r\nB2;GND\r\n'):
            with self.subTest(text=text):
                self.assertEqual(labels.parse_pin_text(text), [
                    {"pin": "A1", "label": "SPI, DATA"}, {"pin": "B2", "label": "GND"}])
        self.assertEqual(labels.parse_pin_text('"A,B"\n"C,D"', columns="labels"), [
            {"pin": "1", "label": "A,B"}, {"pin": "2", "label": "C,D"}])

    def test_one_column_uses_the_exact_reviewed_pin_order(self):
        self.assertEqual(labels.parse_pin_text("GND\nSPI_CLK", pin_numbers=["B2", "A1"]), [
            {"pin": "B2", "label": "GND"}, {"pin": "A1", "label": "SPI_CLK"}])
        with self.assertRaisesRegex(ValueError, "exactly match"):
            labels.parse_pin_text("GND", pin_numbers=["1", "2"])
        with self.assertRaisesRegex(ValueError, "cannot also"):
            labels.parse_pin_text("1,GND", pin_numbers=["1"])

    def test_numbering_sequences_include_sparse_final_row(self):
        self.assertEqual(labels.numbering(6, "row-major"), ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(labels.numbering(6, "column-major"), ["1", "4", "2", "5", "3", "6"])
        self.assertEqual(labels.numbering(6, "odd-even"), ["1", "3", "5", "2", "4", "6"])
        self.assertEqual(labels.numbering(6, "serpentine"), ["1", "2", "4", "3", "5", "6"])
        self.assertEqual(labels.numbering(5, "column-major"), ["1", "4", "2", "5", "3"])
        self.assertEqual(labels.numbering(4, start=10, step=-2), ["10", "8", "6", "4"])
        self.assertEqual(labels.parse_pin_text("A\nB\nC\nD", sequence="serpentine"), [
            {"pin": "1", "label": "A"}, {"pin": "2", "label": "B"},
            {"pin": "4", "label": "C"}, {"pin": "3", "label": "D"}])

    def test_invalid_rows_and_duplicates_are_not_silently_dropped(self):
        for text in ("", "1,A\n2", "1,A,B", "1,A\n1,B", "1,", '1,"line\nbreak"',
                     '1,"unfinished', "1,A\x00B"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                labels.parse_pin_text(text)
        self.assertEqual(labels.parse_pin_text("\n\nGND\n\nDATA\n"), [
            {"pin": "1", "label": "GND"}, {"pin": "2", "label": "DATA"}])

    def test_bounds_and_impossible_numbering(self):
        for kwargs in ({"count": 0}, {"count": 2001}, {"count": True},
                       {"count": 3, "start": 1, "step": -1},
                       {"count": 3, "step": 0}, {"count": 3, "columns": 0},
                       {"count": 3, "sequence": "guess"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                labels.numbering(**kwargs)
        with self.assertRaisesRegex(ValueError, "2000"):
            labels.parse_pin_text("A\n" * 2001)


class ModifierTests(unittest.TestCase):
    def test_templates_preserve_originals_and_inputs(self):
        rows = [{"pin": "A1", "label": "spi_clk", "x_mm": 2}]
        before = copy.deepcopy(rows)
        result = labels.format_labels(rows, prefix="MAIN_", suffix="_P", template="{ref}_{pin}_{label}",
                                      case="upper", ref="J2")
        self.assertEqual(result[0]["label"], "MAIN_J2_A1_SPI_CLK_P")
        self.assertEqual(result[0]["original_label"], "spi_clk")
        self.assertEqual(result[0]["x_mm"], 2)
        self.assertEqual(rows, before)

    def test_templates_cannot_traverse_objects_or_execute_format_fields(self):
        for template in ("{label.__class__}", "{pin[0]}", "{label!r}", "{label:>1000000}",
                         "{}", "{missing}", "{label", "", "{label}\nX"):
            with self.subTest(template=template), self.assertRaises(ValueError):
                labels.format_labels([{"pin": "1", "label": "DATA"}], template=template)
        self.assertEqual(labels.format_labels([{"pin": "1", "label": "DATA"}],
                                             template="{{{label}}}")[0]["label"], "{DATA}")

    def test_duplicate_labels_are_allowed_and_explained(self):
        rows = labels.parse_pin_text("1,GND\n2,GND\n3,DATA")
        warnings = labels.label_warnings(rows)
        self.assertEqual(len(warnings), 1)
        self.assertIn("pins 1, 2", warnings[0])
        self.assertIn("connect", warnings[0])


class SchematicTests(unittest.TestCase):
    def test_native_objects_are_scoped_and_each_copy_has_fresh_ids(self):
        rows = [{"pin": "1", "label": 'SPI_"CLK"\\A'}, {"pin": "2", "label": "GND"}]
        for kind, token in (("global", "global_label"), ("local", "label"), ("hierarchical", "hierarchical_label")):
            with self.subTest(kind=kind):
                first = labels.schematic_labels(rows, kind=kind)
                second = labels.schematic_labels(rows[:1], kind=kind)
                self.assertEqual(first.count("(" + token + " "), 2)
                self.assertEqual(second.count("(" + token + " "), 1)
                self.assertIn('SPI_\\"CLK\\"\\\\A', first)
                ids = re.findall(r'\(uuid "([^"]+)"\)', first + second)
                self.assertEqual(len(ids), 3)
                self.assertEqual(len(set(ids)), 3)
                for value in ids:
                    self.assertEqual(UUID(value).version, 4)
                self.assertNotIn("(wire", first)
                self.assertNotIn("(symbol ", first)
                self.assertNotIn("(lib_symbols", first)

    def test_rotated_pitch_and_input_validation(self):
        rows = [{"pin": "1", "label": "A"}, {"pin": "2", "label": "B"}]
        self.assertIn("(at 12.54 20 90)", labels.schematic_labels(rows, orientation=90, origin=(10, 20)))
        self.assertIn("(at 10 22.54 180)", labels.schematic_labels(rows, orientation=180, origin=(10, 20)))
        for kwargs in ({"pitch_mm": float("nan")}, {"pitch_mm": 0}, {"text_size_mm": 0},
                       {"orientation": 45}, {"origin": (0,)}, {"kind": "power"},
                       {"shape": "anything"}, {"origin": (float("inf"), 0)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                labels.schematic_labels(rows, **kwargs)

    @unittest.skipUnless(os.environ.get("WAYRICAD_TEST_KICAD_CLI"), "Set WAYRICAD_TEST_KICAD_CLI for native schematic export")
    def test_native_kicad_exports_each_kind_without_rewriting_objects(self):
        executable = os.environ["WAYRICAD_TEST_KICAD_CLI"]
        with tempfile.TemporaryDirectory(prefix="connector-label-native-") as directory:
            root = Path(directory)
            for kind in labels.KINDS:
                source = root / (kind + ".kicad_sch")
                source.write_text(labels.full_schematic([
                    {"pin": "1", "label": 'SPI_"CLK"\\A'}, {"pin": "2", "label": "GND"}], kind=kind), encoding="utf-8")
                before = source.read_bytes()
                result = subprocess.run([executable, "sch", "export", "svg", "--output", str(root / kind), str(source)],
                                        capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(source.read_bytes(), before)
                output = list((root / kind).glob("*.svg"))
                self.assertEqual(len(output), 1)
                self.assertGreater(output[0].stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()
