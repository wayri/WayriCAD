import json
import math
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from planar_magnetics_plugin.analysis import MagneticCore,CoilSpec,MagneticsEngine,load_core_catalog
from planar_magnetics_plugin.magnetic_circuit import MU0,operating_point,current_sweep,transformer_flux_swing,validate_core,saturation_current


class CircuitTests(unittest.TestCase):
    def setUp(self):self.core=MagneticCore('Custom','Custom','test',1000,100,100,1,.3)

    def test_linear_circuit_matches_reluctance_and_gap_force(self):
        point=operating_point(self.core,100,1)
        reluctance=(.1/1000+.001)/(MU0*100e-6)
        self.assertAlmostEqual(point['flux_density_t'],100/reluctance/100e-6)
        self.assertAlmostEqual(point['differential_inductance_h'],100**2/reluctance)
        self.assertAlmostEqual(point['ideal_gap_force_n'],point['flux_density_t']**2*100e-6/(2*MU0))

    def test_nonlinear_knee_reduces_incremental_inductance(self):
        core=replace(self.core,gap_mm=0,bh_points=((0,0),(.1,100),(.3,2100)))
        low=operating_point(core,100,.05);high=operating_point(core,100,.5)
        self.assertAlmostEqual(low['flux_density_t'],.05)
        self.assertAlmostEqual(high['flux_density_t'],.14)
        self.assertAlmostEqual(low['differential_inductance_h']/high['differential_inductance_h'],10)
        self.assertIsNone(low['ideal_gap_force_n'])

    def test_outside_table_rejected(self):
        core=replace(self.core,bh_points=((0,0),(.3,300)))
        with self.assertRaisesRegex(ValueError,'B-H data'):operating_point(core,100,10)

    def test_signed_current_and_no_fake_saturation_plateau(self):
        negative=operating_point(self.core,100,-1);positive=operating_point(self.core,100,1)
        self.assertEqual(negative['flux_density_t'],-positive['flux_density_t'])
        high=operating_point(self.core,100,20)
        self.assertGreater(high['flux_density_t'],self.core.saturation_t)
        self.assertFalse(high['model_valid']);self.assertIsNone(high['ideal_gap_force_n'])

    def test_threshold_current_uses_actual_bh(self):
        core=replace(self.core,bh_points=((0,0),(.3,3000)))
        current=saturation_current(core,100)
        self.assertAlmostEqual(operating_point(core,100,current)['flux_density_t'],.3)

    def test_volt_seconds(self):self.assertAlmostEqual(transformer_flux_swing(self.core,10,10,10),.1)

    def test_invalid_tables_and_inputs(self):
        for points in (((.1,0),(.3,300)),((0,0),(.3,-1)),((0,0),(.2,200)),((0,0),(.3,float('nan')))):
            with self.subTest(points=points),self.assertRaises(ValueError):validate_core(replace(self.core,bh_points=points))
        for value in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):current_sweep(self.core,10,value)
        with self.assertRaises(ValueError):current_sweep(self.core,10,1,1002)

    def test_sweep_includes_endpoints(self):
        samples=current_sweep(self.core,10,1)
        self.assertEqual(len(samples),101);self.assertEqual(samples[0]['current_a'],0);self.assertEqual(samples[-1]['current_a'],1)

    def test_catalog_bom_array_and_bad_top_level(self):
        from dataclasses import asdict
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cores.json';path.write_text(json.dumps([asdict(self.core)]),encoding='utf-8-sig')
            self.assertIn('Custom',load_core_catalog(path))
            path.write_text('42',encoding='utf-8')
            with self.assertRaises(ValueError):load_core_catalog(path)

    def test_analysis_rejects_false_linear_saturation(self):
        spec=CoilSpec(core_name='Custom',current_a=100)
        with self.assertRaisesRegex(ValueError,'saturation'):MagneticsEngine.analyze(spec,{'Custom':self.core})

    def test_analysis_uses_differential_bh_at_operating_current(self):
        core=replace(self.core,gap_mm=0,bh_points=((0,0),(.1,100),(.3,2100)))
        spec=CoilSpec(core_name='Custom',current_a=2)
        result=MagneticsEngine.analyze(spec,{'Custom':core})
        expected=operating_point(core,spec.turns*spec.layers,spec.current_a)
        self.assertAlmostEqual(result.inductance_uh,expected['differential_inductance_h']*1e6)
        self.assertAlmostEqual(result.field_center_mt,expected['flux_density_t']*1e3)


if __name__=='__main__':unittest.main()
