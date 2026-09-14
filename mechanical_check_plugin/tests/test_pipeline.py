"""Integration regression tests require installed KiCad and FreeCAD."""
import hashlib
import sys
import unittest
import tempfile
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from wayricad_mechanical.config import load
from wayricad_mechanical.runner import run
from wayricad_mechanical.runtime import discover


@unittest.skipUnless(all(discover().values()),'KiCad and FreeCAD required')
class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board=ROOT/'tests/fixtures/validation-fixture.kicad_pcb'
        cls.before=hashlib.sha256(cls.board.read_bytes()).hexdigest()
        cls.report=run(cls.board,load(ROOT/'tests/fixtures/fixture-rules.json'))

    def test_board_unchanged(self):
        self.assertEqual(self.before,hashlib.sha256(self.board.read_bytes()).hexdigest())

    def test_shared_step_model_instances_keep_references_and_placement(self):
        r=self.report
        self.assertEqual(r['coverage']['imported_models'],4)
        self.assertFalse(r['coverage']['gaps'])
        bodies={b['ref']:b for b in r['bodies'] if b['kind']=='component'}
        self.assertAlmostEqual(bodies['C1']['bounds'][0],24,places=4)
        self.assertAlmostEqual(bodies['C2']['bounds'][0],24.5,places=4)
        self.assertAlmostEqual(bodies['C3']['bounds'][0],39,places=4)

    def test_known_solid_collision_and_height_violation(self):
        rules={(f['rule'],tuple(f['refs'])) for f in self.report['findings']}
        self.assertIn(('solid.collision',('C1','C2')),rules)
        self.assertIn(('height.maximum',('J1',)),rules)
        self.assertNotIn(('solid.collision',('C1','C3')),rules)
        self.assertEqual(self.report['status'],'review_required')

    def test_contact_visualization_is_local_to_intersection(self):
        collision=next(f for f in self.report['findings'] if f['rule']=='solid.collision')
        self.assertTrue(collision['conflict_mesh']['faces'])
        bounds=collision['conflict_bounds']
        self.assertAlmostEqual(bounds[0],24.5,places=4)
        self.assertAlmostEqual(bounds[3],26,places=4)
        self.assertLess(bounds[3]-bounds[0],2)

    def test_hardware_pad_and_plating(self):
        rules={f['rule'] for f in self.report['findings']}
        self.assertTrue({'mount.plating','mount.pad_proximity','mount.hardware_clearance'}<=rules)

    def test_meshes_and_model_fingerprints(self):
        for body in self.report['bodies']:
            self.assertTrue(body['mesh']['vertices'])
            self.assertTrue(body['mesh']['faces'])
        for c in self.report['board']['components']:
            for m in c['models']:
                self.assertEqual(m['sha256'],hashlib.sha256(Path(m['path']).read_bytes()).hexdigest())

    def test_bottom_side_rotated_model_and_height(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bottom.kicad_pcb'
            script="import pcbnew as p,sys;b=p.LoadBoard(sys.argv[1]);f=b.FindFootprintByReference('C3');f.Flip(f.GetPosition(),False);f.SetOrientationDegrees(90);p.SaveBoard(sys.argv[2],b)"
            subprocess.run([discover()['kicad_python'],'-c',script,str(self.board),str(path)],check=True,capture_output=True)
            c=load(ROOT/'tests/fixtures/fixture-rules.json');c['bottom_height_mm']=.5
            report=run(path,c)
            body=next(b for b in report['bodies'] if b['ref']=='C3')
            self.assertEqual(body['side'],'bottom')
            self.assertAlmostEqual(body['bounds'][3]-body['bounds'][0],1.25,places=3)
            self.assertAlmostEqual(body['bounds'][4]-body['bounds'][1],2,places=3)
            self.assertLess(body['bounds'][2],-1.2)
            self.assertTrue(any(f['rule']=='height.maximum' and f['refs']==['C3'] for f in report['findings']))

if __name__=='__main__':unittest.main()
