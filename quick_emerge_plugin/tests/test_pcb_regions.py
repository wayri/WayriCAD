"""Native geometry acceptance checks; skipped without KiCad pcbnew."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import subprocess
import json
import tempfile
import unittest
try:
    import pcbnew as p
except ImportError:
    p = None
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pcb_regions import collect_regions


@unittest.skipUnless(p is not None, 'Native KiCad pcbnew is required')
class RegionTests(unittest.TestCase):
    fixture = ROOT / 'tests/fixtures/region_coupon.kicad_pcb'

    def test_saved_list_clip_and_immutable(self):
        before = self.fixture.read_bytes()
        listing = collect_regions(self.fixture)
        self.assertEqual(listing['areas'][0]['name'], 'Coupon ROI')
        result = collect_regions(self.fixture, listing['areas'][0]['id'])
        self.assertAlmostEqual(result['substrate']['thickness_mm'], 1.53)
        self.assertTrue(any(c['layer'] == 'B.Cu' and c['net'] == 'GND' for c in result['copper']))
        self.assertEqual(result['unsupported'], [])  # outside via is irrelevant
        self.assertEqual(result['source']['sha256'], hashlib.sha256(before).hexdigest())
        trace = next(c for c in result['copper'] if c['net'] == 'SIGNAL')
        points = [v for poly in trace['polygons'] for v in poly['outer_mm']]
        self.assertAlmostEqual(min(v[0] for v in points), 10)
        self.assertAlmostEqual(max(v[0] for v in points), 30)
        self.assertEqual(before, self.fixture.read_bytes())

    def test_isolated_worker_and_source_protection(self):
        before = self.fixture.read_bytes()
        with tempfile.TemporaryDirectory(dir=str(ROOT / 'tests')) as directory:
            output = Path(directory) / 'result.json'
            command = [sys.executable, '-I', str(ROOT / 'region_worker.py'), '--board', str(self.fixture), '--output']
            run = subprocess.run(command + [str(output)], capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr.decode(errors='replace'))
            self.assertEqual(json.loads(output.read_text())['schema'], 1)
            run = subprocess.run(command + [str(self.fixture)], capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(self.fixture.read_bytes(), before)
            run = subprocess.run(command + [str(Path(directory) / 'invalid.txt')], capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse((Path(directory) / 'invalid.txt').exists())

    def edited(self, points, hole=None, via_inside=False):
        directory = tempfile.TemporaryDirectory(dir=str(ROOT / 'tests'))
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / 'coupon.kicad_pcb'
        b = p.LoadBoard(str(self.fixture)); z = next(z for z in b.Zones() if z.GetIsRuleArea())
        poly = p.SHAPE_POLY_SET(); poly.NewOutline()
        for x, y in points: poly.Append(p.FromMM(x), p.FromMM(y))
        if hole:
            poly.NewHole()
            for x,y in hole: poly.Append(p.FromMM(x),p.FromMM(y),0,0)
        z.SetOutline(poly)
        if via_inside:
            v = next(t for t in b.GetTracks() if isinstance(t,p.PCB_VIA))
            v.SetPosition(p.VECTOR2I(p.FromMM(20),p.FromMM(10)))
        p.SaveBoard(str(target),b)
        return collect_regions(target, z.m_Uuid.AsString())

    def test_concave_not_bounding_box(self):
        r = self.edited([(10,5),(30,5),(30,8),(15,8),(15,15),(10,15)])
        pts = [v for c in r['copper'] if c['net'] == 'SIGNAL' for poly in c['polygons'] for v in poly['outer_mm']]
        self.assertLessEqual(max(v[0] for v in pts),15)

    def test_hole_splits_trace(self):
        r = self.edited([(10,5),(30,5),(30,15),(10,15)], [(18,8),(18,12),(22,12),(22,8)])
        trace = next(c for c in r['copper'] if c['net'] == 'SIGNAL')
        self.assertEqual(len(trace['polygons']),2)
        self.assertEqual(len(r['substrate']['outline'][0]['holes_mm']),1)

    def test_board_intersection_and_inside_via(self):
        r = self.edited([(-10,5),(30,5),(30,15),(-10,15)], via_inside=True)
        self.assertTrue(any('via' in issue for issue in r['unsupported']))
        self.assertEqual(min(v[0] for poly in r['substrate']['outline'] for v in poly['outer_mm']),0)


if __name__ == '__main__':
    unittest.main()

