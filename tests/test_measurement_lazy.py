"""Inspecting nets stays lightweight; first analysis uses the exact existing model."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def direct_measurement(name='lazy_direct_measurement'):
    spec=importlib.util.spec_from_file_location(name,ROOT/'trace_impedance_plugin/measurement.py')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def engine(module):
    result=module.TraceMeasurementEngine(None)
    result._stackup_cache=[module.StackupLayer('F.Cu','copper',.035),
        module.StackupLayer('dielectric','core',.2,.2,4),module.StackupLayer('B.Cu','copper',.035)]
    return result


class DeferredMeasurementTests(unittest.TestCase):
    def test_package_inspection_does_not_import_scipy_before_analysis(self):
        code='''import sys,json
sys.path.insert(0,sys.argv[1])
from signal_integrity_advisor_plugin import measurement as m
assert not any(n=='scipy' or n.startswith('scipy.') for n in sys.modules)
assert m._rlc._module is None
assert m.TraceMeasurementEngine(None)._geometry_cache is None
assert m.mm(1000000)==1
print(json.dumps({'cold_inspection_without_scipy':True}))
'''
        result=subprocess.run([sys.executable,'-I','-c',code,str(ROOT)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_direct_loader_first_calculation_matches_fixed_baseline_and_constants(self):
        module=direct_measurement()
        self.assertIsNone(module._rlc._module)
        result=engine(module)._screening_section('track','F.Cu',100,.15,.035)
        self.assertEqual(result['screening_delay_ns'],0.5483721112156544)
        self.assertEqual(result['screening_z0_ohm'],80.52383563969636)
        self.assertEqual(result['screening_status'],'APPROXIMATE')
        backend=module._rlc._module
        self.assertIsNotNone(backend)
        for name in ('EPS0','MU0','COPPER_RESISTIVITY'):
            self.assertEqual(getattr(module,name),getattr(backend,name))
            self.assertIn(name,dir(module));self.assertIn(name,module.__all__)
        namespace={};exec('from '+module.__name__+' import *',namespace)
        self.assertEqual(namespace['EPS0'],backend.EPS0)
        with self.assertRaises(AttributeError):getattr(module,'NONEXISTENT_CONSTANT')

    def test_existing_backend_monkeypatching_contract_is_preserved(self):
        module=direct_measurement('lazy_patched_measurement')
        expected={'propagation_delay_ns':.75,'z0_ohm':42.0}
        with patch.object(module._rlc,'solve',return_value=expected) as solve:
            result=engine(module)._screening_section('track','F.Cu',100,.15,.035)
            solve.assert_called_once_with(.15,.2,.035,4.0,100,0.0,'microstrip')
            self.assertEqual(result['screening_delay_ns'],.75)
            self.assertEqual(result['screening_z0_ohm'],42.0)
        self.assertEqual(engine(module)._screening_section('track','F.Cu',100,.15,.035)['screening_z0_ohm'],80.52383563969636)

    def test_si_copy_remains_identical_to_canonical_rlc_measurement(self):
        self.assertEqual((ROOT/'trace_impedance_plugin/measurement.py').read_bytes(),
                         (ROOT/'signal_integrity_advisor_plugin/measurement.py').read_bytes())


if __name__=='__main__':unittest.main()
