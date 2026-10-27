"""Explicit PI setup, DC-resistance provenance and lumped PDN references."""
from copy import deepcopy
import cmath
import json
import math
import unittest

from quick_pi_plugin.ac_setup import PRESETS,quick_loop
from quick_pi_plugin.transient_inputs import (initial_study,dc_path_resistance,
    engineering_from_study,engineering_to_study,recommend_step)
from quick_pi_plugin.decoupling.impedance import initial_model,validate,impedance_at,analyze


def transient():
    return dict(source_voltage_V=3.3,source_resistance_ohm=.01,source_inductance_H=5e-9,
                duration_s=100e-6,step_s=.1e-6,loads=[dict(id='U1.1',initial_current_A=.1,step_current_A=1.,
                  step_time_s=10e-6,path_resistance_ohm=.005,path_inductance_H=1e-9,capacitance_F=100e-6,esr_ohm=.01)])


class SetupGuideTests(unittest.TestCase):
    def test_ac_presets_are_balanced_explicit_loops(self):
        from quick_pi_plugin.tests.test_ac_workflow import example
        original=example();before=deepcopy(original)
        for preset in PRESETS:
            model=quick_loop(original,preset,2.,.07,.3,100.,1.2)
            self.assertAlmostEqual(sum(row['current_scale'] for row in model['conductors']),0)
            self.assertEqual(model['harmonics'],[{'frequency_hz':100000.,'current_rms_a':1.2}])
            self.assertLessEqual(model['mesh_step_mm'],.035)
        self.assertEqual(original,before)
        for value in (0,-1,float('nan')):
            with self.assertRaises(ValueError):quick_loop(original,PRESETS[0],value,.07,.3,100,1)

    def test_only_matching_single_dc_path_seeds_a_total_resistor(self):
        request=dict(net='VCC',source_terminal='A',source_voltage=3.3,sinks=[dict(terminal='B',current_A=1.)])
        bundle=dict(request=deepcopy(request),result=dict(sinks=[dict(current_A=1.,voltage_drop_V=.02)],feasibility={'feasible':True}))
        self.assertAlmostEqual(dc_path_resistance(request,bundle),.02)
        seeded=initial_study(request,bundle=bundle)
        self.assertAlmostEqual(seeded['source_resistance_ohm'],.02)
        self.assertEqual(seeded['loads'][0]['path_resistance_ohm'],0)
        self.assertIsNone(seeded['loads'][0]['capacitance_F'])
        changed=deepcopy(request);changed['sinks'][0]['current_A']=2
        self.assertIsNone(dc_path_resistance(changed,bundle))
        for key,value in [('physical_return',{}),('electrothermal',{'model':True})]:
            bad=deepcopy(bundle);bad[key]=value or {'enabled':True}
            self.assertIsNone(dc_path_resistance(request,bad))
        bad=deepcopy(bundle);bad['result']['sinks']*=2
        self.assertIsNone(dc_path_resistance(request,bad))
        bad=deepcopy(bundle);bad['result']['components']=[{'forward_drop_V':.7}]
        self.assertIsNone(dc_path_resistance(request,bad))

    def test_unknown_values_stay_unknown_and_group_labels_remain_readable(self):
        request=dict(source_terminals=['a','b'],sinks=[dict(terminals=['c','d'],current_A=2.)])
        value=initial_study(request,[dict(id='c',label='J2.1'),dict(id='d',label='J2.2')])
        self.assertIsNone(value['source_resistance_ohm'])
        self.assertEqual(value['loads'][0]['id'],'J2.1 + J2.2')
        self.assertEqual(value['loads'][0]['step_current_A'],2)
        with self.assertRaisesRegex(ValueError,'prescribed-current'):
            initial_study({'sinks':[{'terminal':'c','power_W':5.}]})

    def test_engineering_units_round_trip_and_required_capacitance(self):
        study=transient();parameters,rows=engineering_from_study(study)
        self.assertEqual(float(parameters['source_resistance_ohm']),10.)
        self.assertEqual(float(rows[0][5]),1.)
        self.assertEqual(float(rows[0][6]),100.)
        result=engineering_to_study(parameters,rows)
        self.assertAlmostEqual(result['loads'][0]['capacitance_F'],100e-6)
        rows[0][6]=''
        with self.assertRaisesRegex(ValueError,'Effective C'):engineering_to_study(parameters,rows)

    def test_timestep_uses_explicit_modes_and_respects_interval_budget(self):
        study=transient();suggestion=recommend_step(study)
        self.assertTrue(suggestion['within_budget'])
        self.assertLess(suggestion['step_s'],study['step_s'])
        # Pure RC branch pole is -1/(RC), so dt <= RC/20.
        study['source_inductance_H']=0;study['loads'][0].update(path_inductance_H=0,esr_ohm=0)
        rc=(.01+.005)*100e-6
        self.assertLessEqual(recommend_step(study)['step_s'],rc/20*(1+1e-12))
        study['duration_s']=1.
        self.assertFalse(recommend_step(study)['within_budget'])

    def test_lumped_pdn_matches_independent_complex_circuit(self):
        model=initial_model();frequency=10000.;omega=2*math.pi*frequency
        source=.02+1j*omega*5e-9
        capacitor=.01+1j*omega*1e-9+1/(1j*omega*100e-6)
        expected=source*capacitor/(source+capacitor)
        self.assertAlmostEqual(impedance_at(model,frequency).real,expected.real,places=14)
        self.assertAlmostEqual(impedance_at(model,frequency).imag,expected.imag,places=14)
        model['source_resistance_ohm']=10000.;model['source_inductance_H']=0
        resonance=1/(2*math.pi*math.sqrt(1e-9*100e-6))
        self.assertAlmostEqual(abs(impedance_at(model,resonance)),.01,delta=1e-7)
        model['capacitors'][0]['quantity']=4
        self.assertAlmostEqual(abs(impedance_at(model,resonance)),.0025,delta=1e-8)

    def test_target_status_samples_resonance_and_exports_finite_json(self):
        result=analyze(initial_model())
        self.assertEqual(result['target_ohm'],.05)
        self.assertEqual(result['effective_capacitance_F'],100e-6)
        self.assertGreaterEqual(result['sample_count'],401)
        self.assertIn(result['status'],('SAMPLED_TARGET_MET','SAMPLED_TARGET_EXCEEDED','REFINE_REQUIRED'))
        json.dumps(result,allow_nan=False)
        bad=initial_model();bad['allowed_ripple_V']=1e-6
        self.assertEqual(analyze(bad)['status'],'SAMPLED_TARGET_EXCEEDED')

    def test_coarse_high_q_antiresonance_is_seeded_and_capacitive_limit_agrees(self):
        model=initial_model();model.update(source_resistance_ohm=1000.,source_inductance_H=0.,start_Hz=2e6,stop_Hz=30e6,points=21,allowed_ripple_V=10.)
        model['capacitors']=[dict(name='Bulk',capacitance_F=1e-6,esr_ohm=.001,esl_H=1e-9,quantity=1),
                             dict(name='Local',capacitance_F=100e-9,esr_ohm=.001,esl_H=1e-9,quantity=1)]
        resonance=math.sqrt((1/1e-6+1/100e-9)/(2e-9))/(2*math.pi)
        expected=abs(impedance_at(model,resonance));coarse=analyze(model)
        self.assertGreater(coarse['peak']['impedance_ohm'],expected*.99)
        model['points']=2001;fine=analyze(model)
        self.assertAlmostEqual(coarse['peak']['impedance_ohm'],fine['peak']['impedance_ohm'],delta=expected*.01)
        # At a frequency far below SRF, high source R leaves |Z|≈1/(ωC).
        model=initial_model();model.update(source_resistance_ohm=1e9,source_inductance_H=0.)
        model['capacitors'][0].update(esr_ohm=0.,esl_H=0.)
        expected=1/(2*math.pi*100*100e-6)
        self.assertAlmostEqual(abs(impedance_at(model,100)),expected,delta=expected*1e-9)

    def test_pdn_invalid_physical_inputs_are_rejected(self):
        for key,value in [('points',0),('source_resistance_ohm',0),('current_step_A',0),('stop_Hz',float('nan'))]:
            model=initial_model();model[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate(model)
        for key,value in [('quantity',1.5),('capacitance_F',0),('esr_ohm',-1),('esl_H',float('inf'))]:
            model=initial_model();model['capacitors'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate(model)


if __name__=='__main__':unittest.main()
