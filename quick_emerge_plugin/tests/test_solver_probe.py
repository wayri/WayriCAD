import importlib.metadata
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np
from quick_emerge_plugin import solver_probe as probe


class SolverProbeTests(unittest.TestCase):
    def test_stable_public_pardiso_solves_complex_column_and_resets(self):
        calls = []
        matrix = np.array([[4+1j, 1-.5j], [1-.5j, 3+2j]])
        expected = np.array([1+2j, -.5+.25j])
        rhs = matrix @ expected
        class PublicPardiso:
            available = True
            def __init__(self, prefix): calls.append(('create', prefix))
            def set_nthreads(self, count): calls.append(('threads', count))
            def initialize(self): calls.append(('initialize',))
            def solve(self, actual_matrix, column, precon):
                np.testing.assert_array_equal(actual_matrix, matrix)
                np.testing.assert_array_equal(column, rhs[:, None])
                self_test.assertIsNone(precon)
                return np.linalg.solve(actual_matrix, column), SimpleNamespace(exit_code=0)
            def reset(self): calls.append(('reset',))
        self_test = self
        fake = SimpleNamespace(solvers=SimpleNamespace(Pardiso=PublicPardiso))
        with patch.object(probe.importlib.metadata, 'version', return_value='3.0.4'), \
                patch.object(probe, '_local_mkl_path', return_value='candidate.dll'), \
                patch.dict(sys.modules, {'emerge': fake}), \
                patch.dict(os.environ, {'EMERGE_PARDISO_PATH': 'original.dll'}):
            result = probe._probe_pardiso(np, matrix, rhs, expected)
            self.assertEqual(os.environ['EMERGE_PARDISO_PATH'], 'original.dll')
        self.assertTrue(result['available'])
        self.assertLess(result['relative_residual'], probe.RESIDUAL_LIMIT)
        self.assertEqual(calls, [('create', 'QuickEMergeProbe'), ('threads', 2),
                                 ('initialize',), ('reset',)])

    def test_stable_failure_reports_and_cleanup_restore_environment(self):
        for failure in ('initialize', 'report', 'solution', 'cleanup'):
            calls = []
            class PublicPardiso:
                available = True
                def __init__(self, prefix): pass
                def set_nthreads(self, count): pass
                def initialize(self):
                    if failure == 'initialize': raise OSError('initialize failed')
                def solve(self, matrix, column, precon):
                    return (np.zeros_like(column) if failure == 'solution' else column), \
                        SimpleNamespace(exit_code=-2 if failure == 'report' else 0)
                def reset(self):
                    calls.append('reset')
                    if failure == 'cleanup': raise OSError('cleanup failed')
            fake = SimpleNamespace(solvers=SimpleNamespace(Pardiso=PublicPardiso))
            with self.subTest(failure=failure), \
                    patch.object(probe.importlib.metadata, 'version', return_value='3.0.4'), \
                    patch.object(probe, '_local_mkl_path', return_value='candidate.dll'), \
                    patch.dict(sys.modules, {'emerge': fake}), \
                    patch.dict(os.environ, {'EMERGE_PARDISO_PATH': 'original.dll'}):
                with self.assertRaises((OSError, RuntimeError, ValueError)):
                    probe._probe_pardiso(np, np.eye(2), np.ones(2), np.ones(2))
                self.assertEqual(calls, ['reset'])
                self.assertEqual(os.environ['EMERGE_PARDISO_PATH'], 'original.dll')

    def test_stable_unavailable_pardiso_has_actionable_diagnostic(self):
        fake = SimpleNamespace(solvers=SimpleNamespace(
            Pardiso=SimpleNamespace(available=False, requires='Intel MKL on x86-64')))
        with patch.object(probe.importlib.metadata, 'version', return_value='3.0.4'), \
                patch.object(probe, '_local_mkl_path', return_value='candidate.dll'), \
                patch.dict(sys.modules, {'emerge': fake}):
            with self.assertRaisesRegex(ImportError, 'Intel MKL.*select SUPERLU'):
                probe._probe_pardiso(np, np.eye(2), np.ones(2), np.ones(2))

    def test_qualified_beta_uses_legacy_interface_and_clears_memory(self):
        calls = []
        class BetaPardiso:
            def __init__(self, nthreads): calls.append(('threads', nthreads))
            def symbolic(self, matrix): calls.append('symbolic'); return 0
            def numeric(self, matrix): calls.append('numeric'); return 0
            def solve(self, matrix, rhs): return rhs, 0
            def clear_memory(self): calls.append('clear')
        fake = SimpleNamespace(PardisoInterface=BetaPardiso)
        with patch.object(probe.importlib.metadata, 'version', return_value='3.0.0b9'), \
                patch.object(probe, '_local_mkl_path', return_value='candidate.dll'), \
                patch.dict(sys.modules, {'emerge._emerge.solve_interfaces.pardiso_interface': fake}):
            result = probe._probe_pardiso(np, np.eye(2), np.ones(2), np.ones(2))
        self.assertTrue(result['available'])
        self.assertEqual(calls, [('threads', 2), 'symbolic', 'numeric', 'clear'])

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
        class BrokenHandle:
            def __init__(self,**kwargs): pass
            def symbolic(self,matrix): return -2
            def clear_memory(self): raise OSError('cleanup failed')
        fake=SimpleNamespace(PardisoInterface=BrokenHandle)
        with patch.object(probe.importlib.metadata,'version',return_value='3.0.0b9'), patch.dict(os.environ,{'EMERGE_PARDISO_PATH':'original.dll'}), patch.object(probe,'_local_mkl_path',return_value='candidate.dll'), patch.dict(sys.modules,{'emerge._emerge.solve_interfaces.pardiso_interface':fake}):
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
