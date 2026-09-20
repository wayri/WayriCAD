import json
import math
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from planar_magnetics_plugin.analysis import CoilSpec, MagneticsEngine, MagneticCore
from planar_magnetics_plugin.equivalent import equivalent, spice, export_bundle

class EquivalentTests(unittest.TestCase):
    def result(self,secondary=0):
        return MagneticsEngine.analyze(CoilSpec(secondary_turns=secondary))
    def test_core_reluctance_and_field_units(self):
        core=MagneticCore('test','custom','linear',1000.,100.,100.,1.,1.)
        r=MagneticsEngine.analyze(CoilSpec(core_name='test',current_a=.1),{'test':core})
        m=equivalent(r);c=m['core'];expected=(.1/1000.+.001)/(4e-7*math.pi*1e-4)
        self.assertAlmostEqual(c['secant_total_reluctance_A_per_Wb']/expected,1.,12)
        self.assertAlmostEqual(c['differential_total_reluctance_A_per_Wb']/expected,1.,12)
        self.assertAlmostEqual(c['B_T']/(4e-7*math.pi*1000.),c['H_A_per_m'],10)
        self.assertAlmostEqual(m['primary_L_H'],m['primary_turns']**2/expected,12)
    def test_unknown_capacitance_and_secondary_resistance(self):
        m=equivalent(self.result(4));self.assertIsNone(m['primary_C_F'])
        with self.assertRaisesRegex(ValueError,'secondary Rdc'):spice(m)
        m=equivalent(self.result(4),secondary_resistance_ohm=.3,primary_capacitance_f=20e-12)
        net=spice(m);self.assertIn('2e-11',net);self.assertNotIn('Csecondary',net)
        self.assertAlmostEqual(m['primary_short_circuit_leakage_H'],m['primary_L_H']*(1-.9**2))
    def test_passivity_and_signed_coupling(self):
        for k in (1.,-1.,1.01,float('nan')):
            with self.assertRaises(ValueError):equivalent(self.result(4),coupling=k)
        m=equivalent(self.result(4),coupling=-.5,secondary_resistance_ohm=.3)
        self.assertGreater(m['L_matrix_determinant_H2'],0);self.assertLess(m['mutual_H'],0)
        self.assertIn('Lsecondary -0.5',spice(m))
    def test_moving_coil_reciprocal_equivalent(self):
        m=equivalent(self.result(),actuator={'Bl_N_per_A':2,'mass_kg':.01,'damping_Ns_per_m':.5,'spring_N_per_m':20})
        net=spice(m);self.assertIn('Eback emf N VEL 0 2',net);self.assertIn('Fforce 0 VEL Vsense 2',net)
        self.assertIn('Cmass VEL 0 0.01',net);self.assertIn('Rdamping VEL 0 2',net);self.assertIn('Lspring VEL 0 0.05',net)
    def test_dc_motor_uses_rotational_units_and_speed_pin(self):
        m=equivalent(self.result(),actuator={'motion_type':'rotary','Bl_N_per_A':.1,'mass_kg':1e-4,'damping_Ns_per_m':.001,'spring_N_per_m':0})
        net=spice(m);self.assertIn('.subckt WayriCADMagnetic P N OMEGA',net)
        self.assertIn('Eback emf N OMEGA 0 0.1',net);self.assertIn('Fforce 0 OMEGA Vsense 0.1',net)
        self.assertNotIn('Lspring',net);self.assertIn('rotor J',m['actuator']['units'])
    def test_unique_project_report_and_context(self):
        with tempfile.TemporaryDirectory() as folder:
            board=Path(folder)/'sample.kicad_pcb';board.write_text('board sentinel')
            m=equivalent(self.result());a=export_bundle(m,board);b=export_bundle(m,board)
            self.assertNotEqual(a,b);self.assertEqual(board.read_text(),'board sentinel')
            payload=json.loads(Path(a['json']).read_text());self.assertEqual(payload['source']['board_path'],str(board.resolve()))
            self.assertEqual(Path(a['html']).parents[1].name,'wayricad-magnetics')
            self.assertIn('<svg',Path(a['html']).read_text(encoding='utf-8'))
    def test_field_geometry_cannot_inherit_planar_resistance(self):
        field={'L_matrix_H':[[1e-3,2e-4],[2e-4,4e-4]],'primary_field':{'spec':{'turns':100}},'evidence':{}}
        with self.assertRaisesRegex(ValueError,'primary Rdc'):equivalent(self.result(),field_model=field)
        m=equivalent(self.result(),field_model=field,primary_resistance_ohm=.2,secondary_resistance_ohm=.1)
        self.assertEqual(m['primary_L_H'],.001);self.assertAlmostEqual(m['k'],.31622776601683794)
        self.assertEqual(m['primary_turns'],100);self.assertIsNone(m['core'])
        field['L_matrix_H'][1][0]=3e-4
        with self.assertRaisesRegex(ValueError,'reciprocal'):equivalent(self.result(),field_model=field,primary_resistance_ohm=.2)

    def test_maxwell_mapping_preserves_energy_and_manual_override(self):
        evidence={'capacitance_F':2e-12,'maxwell_mapping':True,'C_matrix_F':[[3e-12,-2e-12],[-2e-12,5e-12]],'primary_environment_F':1e-12,'secondary_environment_F':3e-12}
        m=equivalent(self.result(4),secondary_resistance_ohm=.3,interwinding_capacitance_f=2e-12,capacitance_evidence={'interwinding_C_F':evidence})
        net=spice(m);self.assertIn('Cenvironment_primary_C_F P N 1e-12',net);self.assertIn('Cenvironment_secondary_C_F S N 3e-12',net)
        v1,v2=1.2,-.7
        energy=.5*(3e-12*v1*v1-4e-12*v1*v2+5e-12*v2*v2)
        network=.5*(m['interwinding_C_F']*(v1-v2)**2+m['environment_primary_C_F']*v1*v1+m['environment_secondary_C_F']*v2*v2)
        self.assertAlmostEqual(energy/network,1.,13)
        overridden=equivalent(self.result(4),interwinding_capacitance_f=7e-12,capacitance_evidence={'interwinding_C_F':evidence})
        self.assertNotIn('environment_primary_C_F',overridden)
        bad=dict(evidence,secondary_environment_F=9e-12)
        with self.assertRaisesRegex(ValueError,'Maxwell matrix'):equivalent(self.result(4),interwinding_capacitance_f=2e-12,capacitance_evidence={'interwinding_C_F':bad})

if __name__=='__main__':unittest.main()
