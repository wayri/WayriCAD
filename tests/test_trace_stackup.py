from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "trace_impedance_plugin" / "measurement.py"
SPEC = importlib.util.spec_from_file_location("wayricad_trace_measurement_test", MODULE_PATH)
measurement = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = measurement
SPEC.loader.exec_module(measurement)


class FakeBoard:
    def __init__(self, path: str):
        self.path = path

    def GetFileName(self):
        return self.path

    def GetFootprints(self):
        return []

    def GetTracks(self):
        return []


class TraceStackupTests(unittest.TestCase):
    def test_kicad_stackup_file_exposes_all_layers_and_reference_spacing(self):
        board_text = """(kicad_pcb (version 20250114)
  (setup (stackup
    (layer "F.Cu" (type "copper") (thickness 0.035))
    (layer "dielectric 1" (type "prepreg") (thickness 0.18) (material "FR4") (epsilon_r 4.1))
    (layer "In1.Cu" (type "copper") (thickness 0.018))
    (layer "dielectric 2" (type "core") (thickness 0.80) (material "FR4") (epsilon_r 4.3))
    (layer "In2.Cu" (type "copper") (thickness 0.018))
    (layer "dielectric 3" (type "prepreg") (thickness 0.18) (material "FR4") (epsilon_r 4.1))
    (layer "B.Cu" (type "copper") (thickness 0.035))
  )))"""
        with tempfile.NamedTemporaryFile("w", suffix=".kicad_pcb", delete=False) as handle:
            handle.write(board_text)
            path = handle.name
        try:
            engine = measurement.TraceMeasurementEngine(FakeBoard(path))
            layers = engine.stackup_layers()
            height, er = engine.dielectric_to_reference("F.Cu", "In1.Cu")
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(7, len(layers))
        self.assertEqual(["F.Cu", "dielectric 1", "In1.Cu", "dielectric 2", "In2.Cu", "dielectric 3", "B.Cu"], [row.name for row in layers])
        self.assertAlmostEqual(0.18, height)
        self.assertAlmostEqual(4.1, er)

    def test_missing_dielectric_is_not_replaced_with_a_physical_guess(self):
        board_text = """(kicad_pcb (version 20250114)
  (setup (stackup
    (layer "F.Cu" (type "copper") (thickness 0.035))
    (layer "B.Cu" (type "copper") (thickness 0.035))
  )))"""
        with tempfile.NamedTemporaryFile("w", suffix=".kicad_pcb", delete=False) as handle:
            handle.write(board_text)
            path = handle.name
        try:
            engine = measurement.TraceMeasurementEngine(FakeBoard(path))
            height, er = engine.dielectric_to_reference("F.Cu", "B.Cu")
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual((0.0, 0.0), (height, er))

    def test_saved_dielectric_without_epsilon_is_unavailable(self):
        board_text = """(kicad_pcb (version 20250114)
  (setup (stackup
    (layer "F.Cu" (type "copper") (thickness 0.035))
    (layer "dielectric 1" (type "core") (thickness 1.5))
    (layer "B.Cu" (type "copper") (thickness 0.035))
  )))"""
        with tempfile.NamedTemporaryFile("w", suffix=".kicad_pcb", delete=False) as handle:
            handle.write(board_text)
            path = handle.name
        try:
            engine = measurement.TraceMeasurementEngine(FakeBoard(path))
            height, er = engine.dielectric_to_reference("F.Cu", "B.Cu")
            dielectric = engine.stackup_layers()[1]
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(0.0, dielectric.relative_permittivity)
        self.assertEqual((0.0, 0.0), (height, er))

    def test_every_saved_dielectric_row_requires_finite_positive_inputs(self):
        cases = (
            '(epsilon_r 4.1)',
            '(thickness -0.1) (epsilon_r 4.1)',
            '(thickness nan) (epsilon_r 4.1)',
            '(thickness 0.1) (epsilon_r nan)',
            '(thickness 0.1) (epsilon_r -2)',
        )
        for invalid_row in cases:
            with self.subTest(invalid_row=invalid_row):
                board_text = f"""(kicad_pcb (version 20250114)
  (setup (stackup
    (layer "F.Cu" (type "copper") (thickness 0.035))
    (layer "dielectric 1" (type "prepreg") (thickness 0.1) (epsilon_r 4.2))
    (layer "dielectric 2" (type "core") {invalid_row})
    (layer "B.Cu" (type "copper") (thickness 0.035))
  )))"""
                with tempfile.NamedTemporaryFile("w", suffix=".kicad_pcb", delete=False) as handle:
                    handle.write(board_text)
                    path = handle.name
                try:
                    engine = measurement.TraceMeasurementEngine(FakeBoard(path))
                    result = engine.dielectric_to_reference("F.Cu", "B.Cu")
                finally:
                    Path(path).unlink(missing_ok=True)
                self.assertEqual((0.0, 0.0), result)

    def test_synthetic_layer_defaults_carry_no_physical_guess(self):
        layer = measurement.StackupLayer("dielectric")
        self.assertEqual((0.0, 0.0), (layer.dielectric_height_mm, layer.relative_permittivity))


if __name__ == "__main__":
    unittest.main()
