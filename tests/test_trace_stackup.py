from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "trace_impedance_plugin" / "measurement.py"
SPEC = importlib.util.spec_from_file_location("kiway_trace_measurement_test", MODULE_PATH)
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


if __name__ == "__main__":
    unittest.main()
