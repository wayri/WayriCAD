import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]/'src'))
from wayricad_mechanical.inspection_state import InspectionState, measurement_text, valid_measurement
from wayricad_mechanical.inspection_picking import SceneIndex, TriangleIndex
from wayricad_runtime.picking import pick_meshes


class RulerStateTests(unittest.TestCase):
    def test_point_ruler_is_euclidean_not_nearest_part_claim(self):
        state = InspectionState(); state.set_mode('points')
        self.assertIsNone(state.click(dict(reference='U1', position=[1, 2, 3])))
        record = state.click(dict(reference='U2', position=[4, 6, 15]))
        self.assertEqual(record['distance_mm'], 13)
        self.assertEqual(record['evidence'], 'picked surface points')
        self.assertIn('ΔZ 12', measurement_text(record))
        state.clear(); self.assertIsNone(state.active); self.assertEqual(state.rulers, [])

    def test_part_picking_does_not_accept_same_part_twice(self):
        state = InspectionState(); state.set_mode('parts')
        hit = dict(reference='U1', position=[0, 0, 0])
        self.assertIsNone(state.click(hit)); self.assertIsNone(state.click(hit))
        self.assertEqual(state.click(dict(hit, reference='U2')), ('U1', 'U2'))

    def test_nearest_requires_proven_nearest_for_and_finite_geometry(self):
        record = dict(refs=['A', 'B'], distance_mm=.2, points=[[0, 0, 0], [.2, 0, 0]],
                      evidence='exact STEP surfaces', nearest_for=['A'])
        state = InspectionState({'proximity': [record]})
        self.assertIs(state.nearest['A'], record); self.assertNotIn('B', state.nearest)
        self.assertIs(state.pairs[frozenset(['B', 'A'])], record)
        self.assertFalse(valid_measurement(dict(record, distance_mm=math.nan)))
        self.assertFalse(valid_measurement(dict(record, points=[[0, 0, math.inf], [1, 0, 0]])))
        point_ruler=dict(record,type='point_ruler')
        state.reset({'measurements':[point_ruler]})
        self.assertEqual(state.pairs,{});self.assertEqual(state.nearest,{})
        self.assertNotIn('contact',measurement_text(dict(point_ruler,distance_mm=0)))
        state.reset({}); self.assertEqual(state.nearest, {})


class PickingTests(unittest.TestCase):
    def test_large_mesh_ray_picks_match_brute_force_with_fewer_tests(self):
        vertices, faces = [], []
        for x in range(80):
            for y in range(80):
                n = len(vertices)
                vertices.extend([[x, y, 0], [x+.8, y, 0], [x, y+.8, 0]])
                faces.append([n, n+1, n+2])
        body = dict(ref='U1', kind='component', bounds=[0, 0, 0, 80, 80, 0],
                    mesh=dict(vertices=vertices, faces=faces))
        index = SceneIndex([body]); index.prepare()
        rng = random.Random(7)
        for _ in range(8):
            origin = [rng.randrange(80)+.15, rng.randrange(80)+.15, 10]
            actual = index.pick(origin, [0, 0, -1])
            expected = pick_meshes(origin, [0, 0, -1], [body])
            self.assertEqual(actual, expected)
            self.assertLess(index.tests, 30)
        self.assertEqual(len(index.prepared[0][1]), len(faces)*18)

    def test_clipped_front_surface_does_not_hide_retained_back_surface(self):
        mesh = dict(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0],
                              [0, 0, 2], [1, 0, 2], [0, 1, 2]], faces=[[0, 1, 2], [3, 4, 5]])
        tree = TriangleIndex(mesh)
        self.assertEqual(tree.pick([.2, .2, -1], [0, 0, 1], lambda p: p[2] > 1)['position'][2], 2)
        self.assertIsNone(tree.pick([2, 2, -1], [0, 0, 1]))
