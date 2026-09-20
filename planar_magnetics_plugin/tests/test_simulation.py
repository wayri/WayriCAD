"""Generated SPICE workflows and independent analytic reference checks."""
import cmath
import math
import unittest
from unittest.mock import patch
from planar_magnetics_plugin.analysis import CoilSpec,MagneticsEngine
from planar_magnetics_plugin.equivalent import equivalent
from planar_magnetics_plugin.simulation import run_simulation

class SimulationTests(unittest.TestCase):
    def test_voltage_and_sweep_validation(self):
        model=equivalent(MagneticsEngine.analyze(CoilSpec()))
        for values in ({'voltage_v':float('nan')},{'start_hz':100,'stop_hz':10}):
            with self.assertRaises(ValueError):run_simulation(model,**values)
        transformer=equivalent(MagneticsEngine.analyze(CoilSpec(secondary_turns=4)),secondary_resistance_ohm=.3)
        with self.assertRaises(ValueError):run_simulation(transformer,load_ohm=-1)
    def test_ac_converts_source_current_sign_and_phase(self):
        model=equivalent(MagneticsEngine.analyze(CoilSpec()))
        engine={'vectors':{'frequency':{'real':[100,1000],'imag':[0,0]},'p':{'real':[1,1],'imag':[0,0]},'vdrive#branch':{'real':[-.5,-.2],'imag':[.5,.4]}}}
        with patch('wayricad_runtime.spice_backend.simulate',return_value=engine):r=run_simulation(model)
        self.assertAlmostEqual(r['samples'][0]['input_impedance_real_ohm'],1.)
        self.assertAlmostEqual(r['samples'][0]['input_impedance_imag_ohm'],1.)
        self.assertAlmostEqual(r['samples'][0]['input_impedance_phase_deg'],45.)
    def test_native_engine_rl_frequency_reference(self):
        from wayricad_runtime.spice_backend import discover_library
        from wayricad_runtime.runtime_setup import native_python
        try:
            discover_library();native_python()
        except (ValueError,RuntimeError,FileNotFoundError):self.skipTest('KiCad ngspice or native KiCad Python not installed')
        model=equivalent(MagneticsEngine.analyze(CoilSpec()),primary_resistance_ohm=.2)
        r=run_simulation(model,start_hz=10,stop_hz=1e4)
        self.assertGreaterEqual(len(r['samples']),30)
        for row in r['samples']:
            expected=complex(.2,2*math.pi*row['frequency_Hz']*model['primary_L_H'])
            actual=complex(row['input_impedance_real_ohm'],row['input_impedance_imag_ohm'])
            self.assertLess(abs(actual-expected)/abs(expected),1e-8)
        narrow=run_simulation(model,start_hz=10,stop_hz=10.01)
        self.assertGreaterEqual(len(narrow['samples']),1)
        if len(narrow['samples'])==1:self.assertIn('one frequency',narrow['limits'])

if __name__=='__main__':unittest.main()

