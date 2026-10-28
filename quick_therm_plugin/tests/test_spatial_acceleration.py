"""Exact broad-phase pruning and sparse-work reuse preserve numerical support."""
import copy
import math
import random
import unittest
from unittest.mock import patch

from quick_therm_plugin import thermal_multilayer as thermal
from quick_therm_plugin.thermal_board_view import _inside


def perforated():
    outer = [[6+6*math.cos(i*math.tau/128), 6+6*math.sin(i*math.tau/128)] for i in range(128)]
    holes = [[[x-.12,y-.12],[x+.12,y-.12],[x+.12,y+.12],[x-.12,y+.12]]
             for x in range(2,11) for y in range(2,11) if math.hypot(x-6,y-6)<4.5]
    return {'outer': outer, 'holes': holes}


def exhaustive_candidates(polygon, box):
    return [i for i,b in enumerate(thermal._polygon_ring_bounds(polygon))
            if b[2]>=box[0] and b[0]<=box[2] and b[3]>=box[1] and b[1]<=box[3]]


class SpatialBroadPhaseTests(unittest.TestCase):
    def setUp(self):self.token=thermal._RING_INDICES.set({})

    def tearDown(self):thermal._RING_INDICES.reset(self.token)

    def test_point_membership_matches_full_rings_at_edges_holes_and_random_sites(self):
        polygon=perforated();rng=random.Random(21028)
        points=[(rng.uniform(-.1,12.1),rng.uniform(-.1,12.1)) for _ in range(2000)]
        for ring in [polygon['outer'],*polygon['holes']]:
            for a,b in zip(ring,ring[1:]+ring[:1]):
                points.extend([a,((a[0]+b[0])/2,(a[1]+b[1])/2)])
        for point in points:
            expected=_inside(point,polygon['outer']) and not any(_inside(point,hole) for hole in polygon['holes'])
            self.assertEqual(thermal._polygon_contains(point,polygon),expected,point)

    def test_cell_and_face_candidates_keep_exact_original_order(self):
        polygon=perforated();rng=random.Random(1028)
        for _ in range(1000):
            x0,x1=sorted((rng.uniform(-1,13),rng.uniform(-1,13)))
            y0,y1=sorted((rng.uniform(-1,13),rng.uniform(-1,13)))
            box=(x0,y0,x1,y1)
            self.assertEqual(thermal._candidate_rings(polygon,box),exhaustive_candidates(polygon,box))

    def test_assembler_matches_unindexed_matrix_rhs_and_complete_field(self):
        try:
            import numpy as np
            from scipy.sparse.linalg import spsolve
        except ImportError:
            self.skipTest('NumPy/SciPy numerical runtime required')
        from quick_therm_plugin.tests.test_thermal_multilayer import inputs
        geometry,view,result,settings=inputs()
        for layer in geometry['layers']:layer['polygons_mm']=[perforated()]
        captured=[]
        def recording(matrix,rhs):
            captured.append((matrix.copy(),rhs.copy()))
            return spsolve(matrix,rhs)
        with patch('scipy.sparse.linalg.spsolve',side_effect=recording):
            indexed=thermal.solve_multilayer_thermal(copy.deepcopy(geometry),view,result,settings)
        indexed_matrices=captured[:];captured.clear()
        with patch.object(thermal,'_candidate_rings',side_effect=exhaustive_candidates), \
             patch.object(thermal,'_indexed_inside',side_effect=lambda point,ring,scan:_inside(point,ring)), \
             patch.object(thermal,'_cell_polygon_candidates',return_value=None), \
             patch('scipy.sparse.linalg.spsolve',side_effect=recording):
            reference=thermal.solve_multilayer_thermal(copy.deepcopy(geometry),view,result,settings)
        self.assertEqual(len(indexed_matrices),len(captured))
        for (a,b),(c,d) in zip(indexed_matrices,captured):
            self.assertEqual((a-c).nnz,0)
            np.testing.assert_array_equal(b,d)
        self.assertEqual(indexed['layers'],reference['layers'])
        self.assertEqual(indexed['components'],reference['components'])
        self.assertEqual(indexed['heat_balance'],reference['heat_balance'])

    def test_revised_geometry_rebuilds_run_local_index(self):
        from quick_therm_plugin.tests.test_thermal_multilayer import inputs
        try:import scipy
        except ImportError:self.skipTest('SciPy numerical runtime required')
        geometry,view,result,settings=inputs()
        shape=perforated();geometry['layers'][0]['polygons_mm']=[shape]
        thermal.solve_multilayer_thermal(geometry,view,result,settings)
        self.assertNotIn('_thermal_ring_index',shape)
        self.assertEqual(thermal._RING_INDICES.get(),{})
        shape['holes'].append([[.2,.2],[.4,.2],[.4,.4],[.2,.4]])
        thermal.solve_multilayer_thermal(geometry,view,result,settings)
        self.assertNotIn('_thermal_ring_index',shape)
        self.assertEqual(thermal._RING_INDICES.get(),{})
        self.assertFalse(thermal._polygon_contains((.3,.3),shape))


if __name__=='__main__':unittest.main()
