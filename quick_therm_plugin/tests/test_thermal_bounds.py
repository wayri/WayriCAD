"""Bounds pruning must preserve the original exact polygon predicates."""
import random
import unittest
from quick_therm_plugin.thermal_board_view import _inside
from quick_therm_plugin.thermal_multilayer import _polygon_contains, _polygon_cell_fraction, _clip_ring_to_cell, _ring_area


class ThermalBoundsTests(unittest.TestCase):
    def test_point_pruning_matches_all_ring_predicates_including_boundary(self):
        holes = [[[x,y],[x+.4,y],[x+.4,y+.4],[x,y+.4]] for x in range(1,10) for y in range(1,10)]
        polygon={"outer":[[0,0],[12,0],[12,12],[0,12]],"holes":holes}
        rng=random.Random(319)
        points=[(rng.uniform(-.1,12.1),rng.uniform(-.1,12.1)) for _ in range(200)]
        points += [(x+delta,y+.2) for x in range(1,10) for y in range(1,10) for delta in (-1e-10,0,.4,.4+1e-10)]
        for point in points:
            reference=_inside(point,polygon['outer']) and not any(_inside(point,h) for h in holes)
            self.assertEqual(_polygon_contains(point,polygon),reference)

    def test_clipped_hole_pruning_matches_full_area_sum(self):
        holes = [[[x,y],[x+.4,y],[x+.4,y+.4],[x,y+.4]] for x in range(1,10) for y in range(1,10)]
        polygon={"outer":[[0,0],[12,0],[12,12],[0,12]],"holes":holes}
        for x in (0.8,1,1.4,5.15,10):
            for y in (.8,1,1.4,5.15,10):
                box=(x,y,x+.5,y+.5)
                reference=max(0,min(1,(_ring_area(_clip_ring_to_cell(polygon['outer'],*box))-
                              sum(_ring_area(_clip_ring_to_cell(h,*box)) for h in holes))/.25))
                self.assertAlmostEqual(_polygon_cell_fraction(polygon,*box),reference,places=12)

    def test_reused_mutated_polygons_refresh_between_solves(self):
        from test_thermal_multilayer import inputs
        from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal
        geometry,view,result,settings=inputs()
        import copy
        for layer in geometry['layers']:
            layer['polygons_mm']=copy.deepcopy(layer['polygons_mm'])
        solve_multilayer_thermal(geometry,view,result,settings)
        for layer in geometry['layers']:
            layer['polygons_mm'][0]['outer'][:]=[[0,5.98],[12,5.98],[12,6.02],[0,6.02]]
        changed=solve_multilayer_thermal(geometry,view,result,settings)
        self.assertGreater(changed['mesh']['copper_lateral_edges'],0)
        self.assertLess(changed['mesh']['copper_lateral_edges'],1000)
        self.assertLess(abs(changed['heat_balance']['residual_w']),1e-6)
