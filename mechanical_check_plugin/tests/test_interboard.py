"""Native regression for two saved boards in a shared CAD coordinate frame."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from wayricad_mechanical.config import load, validate
from wayricad_mechanical.runner import run
from wayricad_mechanical.report import export
from wayricad_mechanical.runtime import discover

BOARD = ROOT / 'tests/fixtures/validation-fixture.kicad_pcb'


class InterboardConfigTests(unittest.TestCase):
    def test_placement_requires_exact_mode_and_finite_coordinates(self):
        other = dict(path='second.kicad_pcb', translation_mm=[1, -2, 3], rotation_deg=90)
        self.assertEqual(validate({'comparison_board': other})['comparison_board'], other)
        with self.assertRaisesRegex(ValueError, 'Exact 3D'):
            validate({'mode': 'quick2d', 'comparison_board': other})
        for changed in (dict(other, translation_mm=[0, float('nan'), 0]),
                        dict(other, rotation_deg=float('inf')),
                        dict(other, path='')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate({'comparison_board': changed})


@unittest.skipUnless(all(discover().values()), 'KiCad and FreeCAD required')
class InterboardNativeTests(unittest.TestCase):
    def test_collision_sections_and_distant_clearance(self):
        before = hashlib.sha256(BOARD.read_bytes()).hexdigest()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        other = Path(temporary.name) / 'comparison.kicad_pcb'
        other.write_bytes(BOARD.read_bytes())
        config = load(ROOT / 'tests/fixtures/fixture-rules.json')
        config['comparison_board'] = dict(path=str(other), translation_mm=[0, 0, 7], rotation_deg=0)
        result = run(BOARD, config)
        self.assertEqual(before, hashlib.sha256(BOARD.read_bytes()).hexdigest())
        self.assertEqual(result['comparison_board']['translation_mm'], [0, 0, 7])
        self.assertIsNone(result['rules']['comparison_board'])
        self.assertNotIn(str(other), json.dumps(result))
        self.assertEqual(result['coverage']['comparison_models'], 4)
        self.assertFalse(result['coverage']['gaps'])
        collisions = [f for f in result['findings'] if f['rule'] == 'interboard.collision']
        self.assertTrue(collisions)
        self.assertTrue(any('Other:J1' in f['refs'] for f in collisions))
        self.assertTrue(all(f['conflict_mesh']['faces'] for f in collisions))
        self.assertTrue(all(f['sections'][axis]['curves'] for axis in ('X','Y','Z','Custom') for f in collisions))
        reports = export(result, temporary.name)
        html = Path(reports['html']).read_text(encoding='utf-8')
        self.assertIn('section-profile', html)
        self.assertNotIn(str(other), html)
        self.assertNotIn(str(other), Path(reports['json']).read_text(encoding='utf-8'))
        original = next(b for b in result['bodies'] if b['ref'] == 'PCB')
        shifted = next(b for b in result['bodies'] if b['ref'] == 'Other:PCB')
        self.assertAlmostEqual(shifted['bounds'][2] - original['bounds'][2], 7, places=4)
        config['comparison_board']['translation_mm'] = [0, 0, 1.7]
        nearby = run(BOARD, config)
        approaches = [f for f in nearby['findings'] if f['rule'] == 'interboard.clearance']
        self.assertTrue(any(set(f['refs']) == {'PCB', 'Other:PCB'} for f in approaches))
        self.assertTrue(any(f['sections']['Custom']['curves'] for f in approaches))
        config['comparison_board']['translation_mm'] = [0, 0, 1000]
        distant = run(BOARD, config)
        self.assertFalse(any(f['rule'].startswith('interboard.') for f in distant['findings']))
        self.assertEqual(before, hashlib.sha256(BOARD.read_bytes()).hexdigest())
        self.assertEqual(before, hashlib.sha256(other.read_bytes()).hexdigest())
