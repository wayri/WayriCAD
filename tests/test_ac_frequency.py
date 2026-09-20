import math
import unittest
from trace_impedance_plugin.rlc_model import slab_skin_factor,via_barrel,ac_resistance_per_m
from trace_impedance_plugin.frequency_analysis import sweep

class FrequencyTests(unittest.TestCase):
    def test_dc_and_skin_asymptotes(self):
        self.assertEqual(slab_skin_factor(0,.035),1)
        self.assertAlmostEqual(slab_skin_factor(.000001,.035),1,places=8)
        one=slab_skin_factor(10000,.035,1);two=slab_skin_factor(10000,.035,2)
        self.assertAlmostEqual(one/two,2,places=6)
        self.assertAlmostEqual(slab_skin_factor(40000,.035)/one,2,places=6)

    def test_via_ac_resistance_increases_and_dc_preserved(self):
        dc=via_barrel(1.6,.3);ac=via_barrel(1.6,.3,frequency_mhz=1000)
        self.assertEqual(dc['resistance_ohm'],dc['resistance_ac_ohm'])
        self.assertEqual(dc['resistance_ohm'],ac['resistance_ohm'])
        self.assertGreater(ac['resistance_ac_ohm'],ac['resistance_ohm'])

    def test_sweep_includes_vias_and_keeps_unknown_inductance(self):
        via=via_barrel(1.6,.3)
        path={'segments':[dict(kind='via',length_mm=1.6,plating_mm=.025,**{k:via[k] for k in ('resistance_ohm','inductance_nh')})]}
        result=sweep(path,1,1000,5)
        self.assertAlmostEqual(result['rows'][-1]['resistance_one_face_ohm'],via_barrel(1.6,.3,frequency_mhz=1000)['resistance_ac_ohm'])
        path['segments'][0]['inductance_nh']=None
        self.assertIsNone(sweep(path)['rows'][0]['series_magnitude_ohm'])

    def test_bad_frequency_and_workload_rejected(self):
        for kwargs in ({'minimum_mhz':0},{'maximum_mhz':math.inf},{'points':1000}):
            with self.assertRaises(ValueError):sweep({'segments':[]},**kwargs)
        for value in (-1,math.nan,math.inf):
            with self.assertRaises(ValueError):slab_skin_factor(value,.035)

    def test_transition_is_smooth_not_skin_depth_cutoff(self):
        values=[ac_resistance_per_m(f,.3,.035) for f in (.01,.1,1,10,100)]
        self.assertEqual(values,sorted(values))
        self.assertGreater(values[1],values[0])
