"""Saved Edge.Cuts context preserves concavities/holes without filled geometry."""
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from wayricad_mechanical.config import validate
from wayricad_mechanical.extract import saved_board_outline
from wayricad_mechanical.quick import screen


class OutlineScreenTests(unittest.TestCase):
    def test_outline_is_separate_context_not_clearance_or_nearest_part(self):
        outline = dict(status='available', bounds=[0,-50,1.6,50,0,1.6],
                       polylines=[dict(points=[[0,0,1.6],[50,0,1.6],[50,-50,1.6]], closed=True, hole=False)])
        components = [dict(ref='A',bounds_2d=[1,1,2,2],side='top',dnp=False),
                      dict(ref='B',bounds_2d=[10,1,11,2],side='top',dnp=False)]
        board = dict(thickness=1.6,components=components,outline=outline)
        result = screen(board,validate({'mode':'quick2d'}))
        self.assertEqual(result['board_outline'],outline)
        self.assertEqual({b['ref'] for b in result['bodies']},{'A','B'})
        self.assertEqual(result['findings'],[])
        self.assertEqual(result['proximity'][0]['distance_mm'],8)
        self.assertEqual(set(result['proximity'][0]['nearest_for']),{'A','B'})
        self.assertNotIn('mesh',result['board_outline'])


@unittest.skipUnless(importlib.util.find_spec('pcbnew'), 'Run with KiCad Python for native Edge.Cuts checks')
class NativeOutlineTests(unittest.TestCase):
    def setUp(self):
        import pcbnew as p
        self.p = p
        self.board = p.BOARD()

    def point(self,x,y):
        return self.p.VECTOR2I(self.p.FromMM(x),self.p.FromMM(y))

    def segment(self,a,b):
        shape = self.p.PCB_SHAPE(self.board)
        shape.SetShape(self.p.SHAPE_T_SEGMENT)
        shape.SetLayer(self.p.Edge_Cuts)
        shape.SetStart(self.point(*a)); shape.SetEnd(self.point(*b))
        self.board.Add(shape)

    def polygon(self,points):
        for a,b in zip(points,points[1:]+points[:1]):
            self.segment(a,b)

    def test_concave_contour_and_circle_cutout_remain_separate_unfilled_loops(self):
        self.polygon([(0,0),(30,0),(30,10),(10,10),(10,30),(0,30)])
        circle = self.p.PCB_SHAPE(self.board)
        circle.SetShape(self.p.SHAPE_T_CIRCLE)
        circle.SetLayer(self.p.Edge_Cuts)
        circle.SetStart(self.point(5,5)); circle.SetEnd(self.point(7,5))
        self.board.Add(circle)
        outline = saved_board_outline(self.board)
        self.assertEqual(outline['status'],'available',outline)
        self.assertEqual(len(outline['polylines']),2)
        outside = next(c for c in outline['polylines'] if not c['hole'])
        hole = next(c for c in outline['polylines'] if c['hole'])
        self.assertEqual(len(outside['points']),6)
        self.assertGreater(len(hole['points']),8)
        self.assertIn([10,-10], [point[:2] for point in outside['points']])
        self.assertEqual(outline['bounds'][:2],[0,-30])
        self.assertEqual(outline['bounds'][3:5],[30,0])
        self.assertGreater(outline['curve_tolerance_mm'],0)

    def test_arc_is_tessellated_without_inferred_fill(self):
        arc = self.p.PCB_SHAPE(self.board)
        arc.SetShape(self.p.SHAPE_T_ARC)
        arc.SetLayer(self.p.Edge_Cuts)
        arc.SetArcGeometry(self.point(0,0),self.point(10,10),self.point(20,0))
        self.board.Add(arc)
        self.segment((20,0),(0,0))
        outline = saved_board_outline(self.board)
        self.assertEqual(outline['status'],'available',outline)
        self.assertGreater(len(outline['polylines'][0]['points']),8)
        self.assertLess(outline['bounds'][1],-9.9)
        self.assertNotIn('mesh',outline)

    def test_missing_and_open_edgecuts_do_not_invent_rectangle(self):
        self.assertEqual(saved_board_outline(self.board)['status'],'unavailable')
        self.segment((0,0),(10,0))
        outline = saved_board_outline(self.board)
        self.assertEqual(outline['status'],'unavailable')
        self.assertEqual(outline['polylines'],[])
        self.assertIsNone(outline['bounds'])

    def test_saved_fixture_read_is_immutable_and_uses_cad_coordinates(self):
        path = ROOT/'tests/fixtures/validation-fixture.kicad_pcb'
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        board = self.p.LoadBoard(str(path))
        outline = saved_board_outline(board)
        self.assertEqual(outline['status'],'available',outline)
        self.assertEqual(outline['bounds'],[0,-40,1.6,60,0,1.6])
        self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__': unittest.main()
