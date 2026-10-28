import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np
from quick_emerge_plugin import solver_probe as probe


class SolverProbeTests(unittest.TestCase):
    def test_complex_reference_rejects_wrong_or_nonfinite_answer(self):
        matrix = np.array([[4+1j, 1-.5j], [1-.5j, 3+2j]])
        expected = np.array([1+2j, -.5+.25j])
        rhs = matrix @ expected
        self.assertTrue(probe._checked_solution(np, matrix, rhs, expected, expected)['available'])
        for actual in ([0,0], expected.real, [complex('nan'),0], [1]):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                probe._checked_solution(np, matrix, rhs, expected, actual)

    def test_missing_mkl_falls_back_to_actual_superlu(self):
        with patch.object(probe.importlib.metadata,'version',return_value='3.0.0b9'), patch.object(probe,'_local_mkl_path',side_effect=ImportError('missing MKL')):
            result = probe.probe_runtime()
        self.assertEqual(result['available'], ['SUPERLU'])
        self.assertEqual(result['preferred'], 'SUPERLU')
        self.assertLess(result['diagnostics']['SUPERLU']['relative_residual'],1e-10)
        self.assertFalse(result['diagnostics']['PARDISO']['available'])
        self.assertIn('missing MKL',result['diagnostics']['PARDISO']['message'])

    def test_false_pardiso_availability_is_not_accepted(self):
        def bad_native(np,matrix,rhs,expected):
            return probe._checked_solution(np,matrix,rhs,expected,np.zeros(2))
        with patch.object(probe.importlib.metadata,'version',return_value='3.0.0b9'), patch.object(probe,'_probe_pardiso',side_effect=bad_native):
            result=probe.probe_runtime()
        self.assertEqual(result['preferred'],'SUPERLU')
        self.assertNotIn('PARDISO',result['available'])

    def test_missing_or_old_emerge_returns_structured_failure(self):
        for error in (importlib.metadata.PackageNotFoundError('emerge'),None):
            with self.subTest(error=error), patch.object(probe.importlib.metadata,'version',side_effect=error,return_value='2.3.0'):
                result=probe.probe_runtime()
            self.assertEqual(result['available'],[])
            self.assertIsNone(result['preferred'])
            self.assertFalse(result['diagnostics']['runtime']['available'])
            json.dumps(result,allow_nan=False)

    def test_existing_override_preserved_after_native_failure(self):
        with patch.dict(os.environ,{'EMERGE_PARDISO_PATH':'configured/missing.dll'}):
            self.assertEqual(probe._local_mkl_path(),'configured/missing.dll')
            with self.assertRaises((ImportError,ModuleNotFoundError,OSError)):
                probe._probe_pardiso(np,np.eye(2),np.ones(2),np.ones(2))
            self.assertEqual(os.environ['EMERGE_PARDISO_PATH'],'configured/missing.dll')

    def test_native_failure_and_cleanup_failure_restore_environment(self):
        from types import SimpleNamespace
        class BrokenHandle:
            def __init__(self,**kwargs): pass
            def symbolic(self,matrix): return -2
            def clear_memory(self): raise OSError('cleanup failed')
        fake=SimpleNamespace(PardisoInterface=BrokenHandle)
        with patch.dict(os.environ,{'EMERGE_PARDISO_PATH':'original.dll'}), patch.object(probe,'_local_mkl_path',return_value='candidate.dll'), patch.dict(sys.modules,{'emerge._emerge.solve_interfaces.pardiso_interface':fake}):
            with self.assertRaisesRegex(OSError,'cleanup failed'):
                probe._probe_pardiso(np,np.eye(2),np.ones(2),np.ones(2))
            self.assertEqual(os.environ['EMERGE_PARDISO_PATH'],'original.dll')

    def test_main_suppresses_import_and_native_chatter(self):
        script = """import importlib.util,os
spec=importlib.util.spec_from_file_location('probe',__import__('sys').argv[1]);p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
def noisy():
 print('python chatter');os.write(1,b'native chatter\\n');os.write(2,b'native warning\\n')
 return dict(schema=1,available=['SUPERLU'],preferred='SUPERLU')
p.probe_runtime=noisy;p.main()
"""
        done=subprocess.run([sys.executable,'-I','-c',script,str(Path(probe.__file__).resolve())],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=20)
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(json.loads(done.stdout)['preferred'],'SUPERLU')
        self.assertEqual(len(done.stdout.splitlines()),1)
        self.assertEqual(done.stderr,'')


if __name__ == '__main__':unittest.main()
