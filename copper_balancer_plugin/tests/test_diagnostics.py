import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copper_balancer.engine import Settings, generate

class DiagnosticsTests(unittest.TestCase):
    def test_invalid_numbers(self):
        for kw in ({'size':True},{'size':'1'},{'max_shapes':2.5},{'seed':1.2},{'replace':1},{'region':True}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):Settings(**kw).validate()
        with self.assertRaises(ValueError):generate(Settings(),(0,0,float('inf'),2),lambda p:True,lambda r:(1,0))

    def test_invalid_area_measurements(self):
        for areas in ((-1,0),(1,2),(float('nan'),0),(101,0)):
            with self.subTest(areas=areas),self.assertRaises(ValueError):
                generate(Settings(),(0,0,10,10),lambda p:True,lambda r:areas)

    def test_accounting_and_density_diagnostics(self):
        p=generate(Settings(),(0,0,10,10),lambda poly:False,lambda r:(100,20))
        self.assertEqual(p.rejected,p.candidates)
        self.assertEqual(sum(p.rejection_reasons.values()),p.rejected)
        self.assertGreater(p.rejection_reasons['geometry_clearance'],0)
        d=p.diagnostics(35)
        self.assertEqual(d['tiles_below_target'],1)
        self.assertAlmostEqual(d['deficit_area_mm2'],15)
        p=generate(Settings(mode='Local density balance'),(0,0,10,10),lambda poly:True,lambda r:(100,80))
        self.assertEqual(p.diagnostics(35)['tiles_initially_above_target'],1)
        self.assertGreater(p.rejection_reasons['density_ceiling'],0)
        self.assertFalse(p.shapes)
