"""Focused numerical and headless lifecycle checks for explicit two-port MQS."""
import copy
import json
import subprocess
import sys
import threading
import unittest
from concurrent.futures import CancelledError
from unittest.mock import patch

import numpy as np
from scipy.sparse.linalg import splu

from quick_pi_plugin import ac_analysis as ac
from quick_pi_plugin import ac_ports as ports
from quick_pi_plugin.ac_ports_ui import example_study


def matrix(result, index=0):
    return np.asarray([[complex(z['real'], z['imag']) for z in row]
                       for row in result['frequencies'][index]['z_ohm']])


class TwoPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.study = example_study()
        cls.study['frequencies_hz'] = [1e-3, 10000.]
        cls.result = ports.run_study(cls.study)

    def test_dc_reference_and_symmetric_reciprocity(self):
        resistance = 1.7241e-8 * .01 / (.4 * .1 * 1e-6)
        np.testing.assert_allclose(self.result['dc_resistance_ohm'], np.eye(2)*2*resistance,
                                   rtol=1e-12, atol=1e-15)
        np.testing.assert_allclose(matrix(self.result).real, self.result['dc_resistance_ohm'],
                                   rtol=1e-6, atol=1e-12)
        for index, row in enumerate(self.result['frequencies']):
            z = matrix(self.result, index)
            np.testing.assert_allclose(z, z.T, rtol=1e-10, atol=1e-13)
            np.testing.assert_allclose(z[0, 0], z[1, 1], rtol=1e-10)
            self.assertGreater(np.linalg.eigvalsh((z+z.conj().T)/2).min(), 0.)
            for key in ('current_relative_error', 'net_current_error_a',
                        'reciprocity_relative_error', 'power_relative_error'):
                self.assertLess(row['checks'][key], 1e-7)
        self.assertEqual(json.loads(json.dumps(self.result, allow_nan=False)), self.result)
        self.assertEqual(self.result['schema'], ports.SCHEMA)
        self.assertEqual(self.result['units']['impedance'], 'ohm')

    def test_flip_port_changes_both_transfer_signs_only(self):
        study = copy.deepcopy(self.study)
        p = study['ports'][1]
        p['positive'], p['negative'] = p['negative'], p['positive']
        result = ports.run_study(study)
        d = np.diag([1., -1.])
        for i in range(2):
            np.testing.assert_allclose(matrix(result, i), d @ matrix(self.result, i) @ d,
                                       rtol=1e-10, atol=1e-13)

    def test_shared_return_dc_and_open_port_constraints(self):
        study = copy.deepcopy(self.study)
        study['ports'][1]['negative'] = 'B'
        result = ports.run_study(study)
        r = 1.7241e-8 * .01 / (.4*.1*1e-6)
        np.testing.assert_allclose(result['dc_resistance_ohm'], np.array([[2, 1], [1, 2]])*r)
        np.testing.assert_allclose(matrix(result).real, result['dc_resistance_ohm'], atol=1e-12)

    def test_one_factorization_and_two_rhs_per_frequency_per_mesh(self):
        rhs_shapes = []

        def factor(matrix):
            lu = splu(matrix)

            class Counted:
                def solve(self, rhs):
                    rhs_shapes.append(rhs.shape)
                    return lu.solve(rhs)
            return Counted()

        study = copy.deepcopy(self.study)
        original = copy.deepcopy(study)
        with patch('scipy.sparse.linalg.splu', side_effect=factor) as count:
            result = ports.run_study(study)
        self.assertEqual(study, original)
        expected = result['work']['meshes'] * len(study['frequencies_hz'])
        self.assertEqual(count.call_count, expected)
        self.assertEqual(result['work']['factorizations'], expected)
        self.assertEqual(result['work']['multi_rhs_solves'], expected)
        self.assertEqual(len(rhs_shapes), expected)
        self.assertTrue(all(shape[1] == 2 for shape in rhs_shapes))
        self.assertLessEqual(result['work']['meshes'], 6)

    def test_single_rhs_backend_equivalence(self):
        _, backend, b = ports.validate_study(self.study)
        rho = 1.7241e-8
        mesh = ac._mesh(backend, rho, 1., 1.)
        frequency = 10000.
        z, _ = ports._frequency(mesh, backend, rho, frequency, b)
        for column in range(2):
            for conductor, scale in zip(backend['conductors'], b[:, column]):
                conductor['current_scale'] = scale
            scalar = ac._frequency(mesh, backend, rho, frequency)
            self.assertAlmostEqual(abs(z[column, column]-scalar['impedance']), 0., places=12)

    def test_electrical_size_guard_and_errors(self):
        mutations = [
            lambda s: s.update(frequencies_hz=[]),
            lambda s: s.update(frequencies_hz=[100.]*33),
            lambda s: s.update(frequencies_hz=[100., 100.]),
            lambda s: s.update(frequencies_hz=[float('nan')]),
            lambda s: s.update(frequencies_hz=[float('inf')]),
            lambda s: s.update(frequencies_hz=[True]),
            lambda s: s.update(frequencies_hz=[-1.]),
            lambda s: s.update(frequencies_hz=[0.]),
            lambda s: s.update(frequencies_hz=[1e12]),
            lambda s: s.update(ports=s['ports'][:1]),
            lambda s: s['ports'][1].update(positive='B', negative='A'),
            lambda s: s['ports'][1].update(positive='A', negative='B'),
            lambda s: s['ports'][1].update(name='P1'),
            lambda s: s['ports'][0].update(negative='A'),
            lambda s: s['ports'][0].update(positive='missing'),
            lambda s: s['ports'][0].update(positive=[]),
            lambda s: s['cross_section']['conductors'][1].update(name='A'),
            lambda s: s['cross_section']['conductors'][1].update(x_mm=-.4, y_mm=.2),
            lambda s: s['cross_section']['conductors'][1].update(thickness_mm=0.),
            lambda s: s['cross_section']['conductors'][1].update(current_scale=1.),
            lambda s: s['cross_section'].update(length_mm=float('inf')),
            lambda s: s['cross_section'].update(harmonics=[]),
            lambda s: s['cross_section'].update(conductors=s['cross_section']['conductors'][:2]),
            lambda s: s['cross_section'].update(conductors=s['cross_section']['conductors']*5),
            lambda s: s.update(unknown=True),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                study = copy.deepcopy(self.study)
                mutate(study)
                with self.assertRaises(ValueError):
                    ports.validate_study(study)

    def test_two_conductors_cannot_define_independent_loops(self):
        study = copy.deepcopy(self.study)
        study['cross_section']['conductors'] = study['cross_section']['conductors'][:2]
        study['ports'][1].update(positive='A', negative='B')
        with self.assertRaisesRegex(ValueError, 'independent'):
            ports.validate_study(study)

    def test_budget_rejection_and_early_cancel(self):
        study = copy.deepcopy(self.study)
        study['cross_section']['max_cells'] = 100
        with self.assertRaisesRegex(ValueError, 'mesh|budget'):
            ports.run_study(study)
        cancel = threading.Event()
        cancel.set()
        with patch('quick_pi_plugin.ac_analysis._mesh') as mesh:
            with self.assertRaises(CancelledError):
                ports.run_study(self.study, cancel=cancel)
            mesh.assert_not_called()

    def test_unconverged_is_provisional_not_pass(self):
        with patch('quick_pi_plugin.ac_ports._difference', return_value=.5):
            result = ports.run_study(self.study)
        self.assertEqual(result['status'], 'PROVISIONAL')
        self.assertEqual(len(result['mesh']['boundary_history']), 4)

    def test_finite_frequency_sort_and_original_units(self):
        study = copy.deepcopy(self.study)
        study['frequencies_hz'].reverse()
        normalized, _, _ = ports.validate_study(study)
        self.assertEqual(normalized['frequencies_hz'], sorted(study['frequencies_hz']))
        self.assertEqual(normalized['cross_section']['length_mm'], 10.)
        self.assertEqual(normalized['cross_section']['conductors'][0]['width_mm'], .4)

    def test_headless_import_boundary(self):
        script = ('import sys; import quick_pi_plugin.ac_ports_ui; '
                  'assert not any(k in sys.modules for k in '
                  '("wx", "matplotlib", "numpy", "scipy"))')
        subprocess.run([sys.executable, '-B', '-c', script], check=True)


class WorkerTests(unittest.TestCase):
    def test_latest_only_cancel_and_closed_guard(self):
        started = threading.Event()
        release = threading.Event()
        dispatched = threading.Event()
        queue = []
        delivered = []
        calls = []

        def solve(study, *, cancel):
            calls.append(study)
            if study == 'old':
                started.set()
                self.assertTrue(release.wait(5))
                self.assertTrue(cancel.is_set())
            return study

        def dispatch(callback, *args):
            queue.append((callback, args))
            if args[1] == 'latest':
                dispatched.set()

        job = ports.LatestRun(dispatch, lambda result, error: delivered.append((result, error)), solve)
        job.submit('old')
        self.assertTrue(started.wait(5))
        job.submit('superseded')
        job.submit('latest')
        worker = job.worker
        release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(dispatched.is_set())
        self.assertEqual(calls, ['old', 'latest'])
        for callback, args in queue:
            callback(*args)
        self.assertEqual(delivered, [('latest', None)])
        delivered.clear()
        job.close()
        for callback, args in queue:
            callback(*args)
        job.submit('closed')
        self.assertEqual(delivered, [])
        self.assertEqual(calls, ['old', 'latest'])

    def test_invalidation_discards_already_queued_result(self):
        queue = []
        result = []
        job = ports.LatestRun(lambda *args: queue.append(args), lambda *args: result.append(args),
                              lambda study, **kwargs: study)
        job.submit({})
        worker = job.worker
        if worker is not None:
            worker.join(5)
        job.invalidate()
        for callback, *args in queue:
            callback(*args)
        self.assertEqual(result, [])
        job.close()


if __name__ == '__main__':
    unittest.main()
