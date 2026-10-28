import hashlib
import math
from pathlib import Path
import tempfile
import unittest

from quick_emerge_plugin.model import DEFAULT_CONFIG, config_digest, metrics, source_identity, validate_config


class ModelTests(unittest.TestCase):
    def test_defaults_and_canonical_digest(self):
        self.assertEqual(validate_config({})["points"], 7)
        self.assertEqual(config_digest({}), config_digest(dict(reversed(list(DEFAULT_CONFIG.items())))))
        self.assertNotEqual(config_digest({}), config_digest({"er": 4}))

    def test_invalid_sweeps_and_numbers(self):
        for patch in ({"points": True}, {"points": 1}, {"points": 2.5},
                      {"f_start_hz": float("nan")}, {"f_stop_hz": float("inf")},
                      {"f_start_hz": 2e9}, {"mode": "other"}, {"extra": 1}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_config(patch)

    def test_advanced_controls(self):
        self.assertEqual(validate_config({})['adaptive_steps'], 0)
        for solver in ('SUPERLU', 'PARDISO', 'UMFPACK', 'AASDS', 'CUDSS', 'SPARTA'):
            self.assertEqual(validate_config({'solver': solver})['solver'], solver)
        self.assertEqual(validate_config({'sweep': 'adaptive', 'adaptive_steps': 20,
                                          'convergence': 1, 'max_tets': 100})['max_tets'], 100)
        self.assertEqual(validate_config({'sweep': 'adaptive', 'points': 5})['points'], 5)
        for patch in ({'solver': 'auto'}, {'sweep': 'log'}, {'adaptive_steps': -1},
                      {'sweep': 'adaptive', 'points': 4},
                      {'adaptive_steps': 21}, {'adaptive_steps': 1.5}, {'adaptive_steps': True},
                      {'convergence': 0}, {'convergence': 1.01}, {'convergence': float('nan')},
                      {'max_tets': 99}, {'max_tets': 10000001}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_config(patch)

    def test_geometry_and_field_boundaries(self):
        for patch in ({"patch_width_mm": 101}, {"inset_width_mm": 53},
                      {"inset_length_mm": 52}, {"feed_width_mm": 39},
                      {"field_z_mm": 30}, {"field_grid": 202},
                      {"resolution": 1.01}, {"patch_width_mm": 100},
                      {"mode": "pcb_line", "line_length_mm": 100},
                      {"mode": "pcb_line", "substrate_x_mm": 25, "substrate_y_mm": 200}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_config(patch)
        self.assertEqual(validate_config({"mode": "pcb_line", "substrate_x_mm": 40, "substrate_y_mm": 4})["line_length_mm"], 30)
        self.assertEqual(validate_config({"feed_width_mm": 8})["feed_width_mm"], 8)

    def test_source_bytes(self):
        root = Path(__file__).resolve().parents[2] / '.tmp'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_bytes(b'(kicad_pcb)\r\n')
            identity = source_identity(path)
            self.assertEqual(identity["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(identity["path"], str(path.resolve()))
            with self.assertRaises(ValueError):
                source_identity(Path(__file__))

    def test_reflection_metrics(self):
        result = metrics([1, 2, 3, 4, 5], [0, 1/3, 1, -1, 1.2])
        self.assertEqual(result["resonance_hz"], 1)
        self.assertEqual(result["s11_db"][0], -math.inf)
        self.assertEqual(result["return_loss_db"][0], math.inf)
        self.assertAlmostEqual(result["vswr"][1], 2)
        self.assertEqual(result["vswr"][2:], [None, None, None])
        self.assertAlmostEqual(result["impedance_real_ohm"][1], 100)
        self.assertIsNone(result["impedance_real_ohm"][2])
        self.assertEqual(result["impedance_real_ohm"][3], 0)
        self.assertLess(result["return_loss_db"][4], 0)
        self.assertLess(result["impedance_real_ohm"][4], 0)

    def test_reject_bad_results(self):
        for frequencies, values in (([1, 1], [0, 0]), ([1], []), ([1], [complex(float("nan"))]), ([0], [0])):
            with self.subTest(frequencies=frequencies), self.assertRaises(ValueError):
                metrics(frequencies, values)


if __name__ == "__main__":
    unittest.main()
