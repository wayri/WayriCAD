import math
import unittest
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copper_balancer.engine import Settings, SHAPES, Cancelled, area, template, generate, clip_rect


class EngineTests(unittest.TestCase):
    def measure(self,b):
        return (b[2]-b[0])*(b[3]-b[1]),0

    def test_every_shape_produces_finite_positive_geometry(self):
        for shape in SHAPES:
            with self.subTest(shape=shape):
                poly = template(Settings(shape=shape,rotation=33))
                self.assertGreater(area(poly),.1)
                self.assertTrue(all(math.isfinite(x) and math.isfinite(y) for x,y in poly))

    def test_deterministic_and_minimum_gap_on_both_lattices(self):
        for lattice in ("Square","Hexagonal"):
            s = Settings(shape="Square",lattice=lattice,rotation=43)
            a = generate(s,(0,0,12,12),lambda p:True,self.measure)
            b = generate(s,(0,0,12,12),lambda p:True,self.measure)
            self.assertEqual(a.shapes,b.shapes)
            centers = [(sum(x for x,y in p)/len(p),sum(y for x,y in p)/len(p)) for p in a.shapes]
            radius = max(math.hypot(x,y) for x,y in template(s))
            for i,c in enumerate(centers):
                for d in centers[i+1:]:
                    self.assertGreaterEqual(math.dist(c,d)+1e-9,2*radius+s.gap)

    def test_targets_account_for_shapes_crossing_tiles(self):
        s = Settings(mode="Local density balance",tile_size=2,size=1.4,gap=.1,target=27)
        plan = generate(s,(0,0,15,15),lambda p:True,self.measure)
        self.assertGreater(len(plan.shapes),0)
        self.assertTrue(all(t.density <= 27+1e-7 for t in plan.tiles.values()))
        self.assertAlmostEqual(sum(t.added_area for t in plan.tiles.values()),plan.added_area)

    def test_existing_dense_tiles_are_not_filled(self):
        def measure(b):
            a = (b[2]-b[0])*(b[3]-b[1])
            return a,a*.8 if b[0] < 5 else 0
        plan = generate(Settings(mode="Local density balance",tile_size=5),(0,0,10,10),lambda p:True,measure)
        self.assertTrue(all(min(x for x,y in p) >= 5 for p in plan.shapes))
        self.assertGreater(len(plan.shapes),0)

    def test_rejected_geometry_never_reaches_output(self):
        plan = generate(Settings(),(0,0,10,10),lambda p:False,self.measure)
        self.assertEqual(plan.shapes,[])
        self.assertGreater(plan.rejected,0)

    def test_region_limits_whole_shapes(self):
        plan = generate(Settings(region=(3,4,9,11)),(0,0,20,20),lambda p:True,self.measure)
        self.assertTrue(all(3<=x<=9 and 4<=y<=11 for p in plan.shapes for x,y in p))
        self.assertAlmostEqual(plan.board_area,42)

    def test_limits_and_cancel(self):
        plan = generate(Settings(max_shapes=3),(0,0,20,20),lambda p:True,self.measure)
        self.assertEqual(len(plan.shapes),3)
        self.assertTrue(plan.limited)
        with self.assertRaises(Cancelled):
            generate(Settings(),(0,0,20,20),lambda p:True,self.measure,lambda f,m:False)

    def test_invalid_settings(self):
        for setting in (Settings(size=0),Settings(gap=-1),Settings(target=float('nan')),Settings(region=(1,1,0,0))):
            with self.assertRaises(ValueError):
                setting.validate()

    def test_rectangle_clip_area(self):
        self.assertAlmostEqual(area(clip_rect(((0,0),(4,0),(4,4),(0,4)),(2,2,5,5))),4)


if __name__ == '__main__':
    unittest.main()
