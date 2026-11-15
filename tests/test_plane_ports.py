"""Analytical and bounded-solve tests; synthetic grids are test fixtures only."""
import copy
import json
import math
import subprocess
import sys
import threading
import unittest
from concurrent.futures import CancelledError
from unittest.mock import patch

import numpy as np
from scipy.sparse.linalg import splu

from quick_pi_plugin import plane_ports as plane


def rectangle(nx=8, ny=4, length=100., width=50.):
    vertices = [[length*i/nx, width*j/ny] for j in range(ny+1) for i in range(nx+1)]
    triangles = []
    for j in range(ny):
        for i in range(nx):
            a = j*(nx+1)+i
            triangles.extend([[a, a+1, a+nx+2], [a, a+nx+2, a+nx+1]])
    left = [j*(nx+1) for j in range(ny+1)]
    right = [i+nx for i in left]
    weights = [(.5 if j in (0, ny) else 1.)/ny for j in range(ny+1)]
    return {'schema': plane.SCHEMA, 'vertices_mm': vertices, 'triangles': triangles,
            'reference_plane': 'ideal', 'dielectric_height_mm': .2, 'epsr': 4.,
            'tandelta': .01, 'copper_thickness_mm': .035, 'resistivity_ohm_m': 1.7241e-8,
            'ports': [{'name': 'P1', 'nodes': left, 'weights': weights},
                      {'name': 'P2', 'nodes': right, 'weights': weights}],
            'frequencies_hz': [1e4, 1e8, 7.5e8, 1e9]}


def z_matrix(row):
    return np.asarray([[complex(z['real'], z['imag']) for z in entries] for entries in row['z_ohm']])


class PlanePortsTests(unittest.TestCase):
    def test_low_frequency_capacitance_with_ideal_return(self):
        study = rectangle(4, 2)
        study['frequencies_hz'] = [1e4]
        result = plane.run_study(study)
        capacitance = plane.EPS0*4*.1*.05/.0002
        self.assertAlmostEqual(result['total_capacitance_f']/capacitance, 1., places=12)
        self.assertAlmostEqual(result['area_m2'], .1*.05, places=12)
        expected = 1/(2*math.pi*1e4*capacitance*(.01+1j))
        np.testing.assert_allclose(z_matrix(result['frequencies'][0]), np.full((2, 2), expected), rtol=2e-6)
        self.assertTrue(np.all(z_matrix(result['frequencies'][0]).imag < 0))
        for current in result['frequencies'][0]['reference_plane_current_a']:
            self.assertAlmostEqual(current['real'], -1., places=7)
            self.assertAlmostEqual(current['imag'], 0., places=7)
        self.assertEqual(result['status'], 'MODELLED')
        self.assertEqual(result['convergence']['status'], 'NOT_EVALUATED')

    def test_rectangular_first_resonance_scan(self):
        study = rectangle(24, 12)
        analytic = 1/(2*.1*math.sqrt(plane.MU0*plane.EPS0*4))
        study['frequencies_hz'] = np.linspace(.94*analytic, 1.06*analytic, 81).tolist()
        result = plane.run_study(study)
        heights = [abs(z_matrix(row)[0, 0]) for row in result['frequencies']]
        peak_index = int(np.argmax(heights))
        peak = result['frequencies'][peak_index]['frequency_hz']
        self.assertLess(abs(peak/analytic-1), .02)
        self.assertGreater(peak_index, 0)
        self.assertLess(peak_index, len(heights)-1)
        self.assertGreater(max(heights), 4*max(heights[0], heights[-1]))
        self.assertTrue(math.isfinite(max(heights)))

    def test_reciprocity_passivity_current_residual_and_json(self):
        study = rectangle()
        result = plane.run_study(study)
        for row in result['frequencies']:
            z = z_matrix(row)
            np.testing.assert_allclose(z, z.T, rtol=1e-7, atol=1e-10)
            self.assertGreaterEqual(np.linalg.eigvalsh((z+z.conj().T)/2).min(), -1e-9*np.linalg.norm(z))
            for key in ('residual_relative_error', 'current_relative_error', 'net_current_error_a',
                        'reciprocity_relative_error', 'power_relative_error'):
                self.assertLess(row['checks'][key], 1e-7)
        self.assertEqual(result, json.loads(json.dumps(result, allow_nan=False)))
        self.assertEqual(result['schema'], plane.SCHEMA)
        self.assertEqual(result['units']['impedance'], 'ohm')
        self.assertEqual(result['study']['dielectric_height_mm'], .2)

    def test_orientation_rigid_motion_and_port_order(self):
        study = rectangle(6, 3)
        study['frequencies_hz'] = [1e8, 8e8]
        baseline = plane.run_study(study)
        changed = copy.deepcopy(study)
        changed['triangles'] = [t[::-1] if i % 2 else t for i, t in enumerate(changed['triangles'])]
        angle = .37
        changed['vertices_mm'] = [[math.cos(angle)*x-math.sin(angle)*y+123.,
                                   math.sin(angle)*x+math.cos(angle)*y-77.]
                                  for x, y in changed['vertices_mm']]
        changed['ports'].reverse()
        result = plane.run_study(changed)
        for before, after in zip(baseline['frequencies'], result['frequencies']):
            np.testing.assert_allclose(z_matrix(after), z_matrix(before)[::-1, ::-1], rtol=1e-10, atol=1e-10)

    def test_assembly_units_lumped_mass_and_no_boundary_sink(self):
        study = plane.validate_study(rectangle(2, 1))
        k, capacitance, b, area = plane._assemble(study)
        np.testing.assert_allclose(k.toarray(), k.T.toarray(), atol=1e-14)
        np.testing.assert_allclose(k @ np.ones(k.shape[0]), 0., atol=1e-14)
        self.assertAlmostEqual(area, .005, places=14)
        self.assertAlmostEqual(capacitance.sum(), plane.EPS0*4*.005/.0002, places=20)
        np.testing.assert_allclose(b.sum(axis=0), [1, 1])
        self.assertTrue(np.all(capacitance > 0))
        scaled = copy.deepcopy(study)
        scaled['vertices_mm'] = (np.asarray(scaled['vertices_mm'])*2).tolist()
        k2, c2, _, area2 = plane._assemble(scaled)
        np.testing.assert_allclose(k2.toarray(), k.toarray(), atol=1e-14)
        np.testing.assert_allclose(c2, 4*capacitance, rtol=1e-14)
        self.assertAlmostEqual(area2, 4*area, places=14)

    def test_one_lu_and_two_rhs_per_frequency(self):
        shapes = []

        def factor(y):
            lu = splu(y)

            class Counter:
                def solve(self, rhs):
                    shapes.append(rhs.shape)
                    return lu.solve(rhs)
            return Counter()

        study = rectangle(4, 2)
        original = copy.deepcopy(study)
        with patch('scipy.sparse.linalg.splu', side_effect=factor) as calls:
            result = plane.run_study(study)
        count = len(study['frequencies_hz'])
        self.assertEqual(calls.call_count, count)
        self.assertEqual(shapes, [(16, 2)]*count)
        self.assertEqual(result['work']['factorizations'], count)
        self.assertEqual(result['work']['multi_rhs_solves'], count)
        self.assertEqual(study, original)

    def test_temperature_and_sheet_resistance_approximation(self):
        study = rectangle(4, 2)
        study['temperature_c'] = 100.
        result = plane.run_study(study)
        rho = study['resistivity_ohm_m']*(1+.00393*80)
        self.assertAlmostEqual(result['resistivity_at_temperature_ohm_m'], rho)
        for row in result['frequencies']:
            expected = max(rho/.000035, math.sqrt(math.pi*row['frequency_hz']*plane.MU0*rho))
            self.assertAlmostEqual(row['sheet_resistance_ohm_per_square']/expected, 1., places=14)

    def test_lossless_dielectric_still_has_copper_loss(self):
        study = rectangle(4, 2)
        study['tandelta'] = 0.
        study['frequencies_hz'] = [1e8]
        row = plane.run_study(study)['frequencies'][0]
        self.assertGreater(z_matrix(row)[0, 0].real, 0)

    def test_stabilized_system_matches_direct_admittance_at_rf(self):
        from scipy import sparse
        study = plane.validate_study(rectangle(6, 3))
        study['frequencies_hz'] = [1e8, 8e8]
        k, c, b, _ = plane._assemble(study)
        result = plane.run_study(study)
        for row in result['frequencies']:
            omega = 2*math.pi*row['frequency_hz']
            zs = row['sheet_resistance_ohm_per_square']+1j*omega*plane.MU0*.0002
            y = k/zs+sparse.diags(omega*(.01+1j)*c, format='csc')
            direct = b.T @ splu(y.tocsc()).solve(b.astype(complex))
            np.testing.assert_allclose(z_matrix(row), direct, rtol=1e-10, atol=1e-10)

    def test_input_rejection(self):
        mutations = [
            lambda s: s.update(schema='wayricad.pi-ac-ports/v1'),
            lambda s: s.update(reference_plane='inferred'),
            lambda s: s.update(unknown=True),
            lambda s: s.update(frequencies_hz=[0.]),
            lambda s: s.update(frequencies_hz=[9999.]),
            lambda s: s.update(frequencies_hz=[1e10+1]),
            lambda s: s.update(frequencies_hz=[float('inf')]),
            lambda s: s.update(frequencies_hz=[float('nan')]),
            lambda s: s.update(frequencies_hz=[True]),
            lambda s: s.update(frequencies_hz=[1e8, 1e8]),
            lambda s: s.update(frequencies_hz=[1e8]*513),
            lambda s: s.update(frequencies_hz=[]),
            lambda s: s.update(dielectric_height_mm=0.),
            lambda s: s.update(dielectric_height_mm=10., frequencies_hz=[1e10]),
            lambda s: s.update(epsr=float('nan')),
            lambda s: s.update(tandelta=-.01),
            lambda s: s.update(resistivity_ohm_m=0.),
            lambda s: s.update(copper_thickness_mm=True),
            lambda s: s.update(vertices_mm=[[0., 0.]]*50001),
            lambda s: s.update(triangles=[[0, 1, 2]]*100001),
            lambda s: s['vertices_mm'][0].__setitem__(0, float('inf')),
            lambda s: s['vertices_mm'].__setitem__(0, s['vertices_mm'][1]),
            lambda s: s['triangles'].__setitem__(0, [0, 0, 1]),
            lambda s: s['triangles'].__setitem__(0, [0, 1, 999]),
            lambda s: s['triangles'].__setitem__(0, [0, 1, True]),
            lambda s: s['triangles'].__setitem__(0, [0., 1, 2]),
            lambda s: s['triangles'].append(s['triangles'][0][::-1]),
            lambda s: s['vertices_mm'].append([123., 456.]),
            lambda s: s['ports'][1].update(nodes=s['ports'][0]['nodes'], weights=s['ports'][0]['weights']),
            lambda s: s['ports'][0].update(weights=[.5]),
            lambda s: s['ports'][0].update(nodes=[0, 0], weights=[.5, .5]),
            lambda s: s['ports'][0].update(nodes=[0, 1], weights=[1., 0.]),
            lambda s: s['ports'][0].update(nodes=[0, 1], weights=[1.1, -.1]),
            lambda s: s['ports'][0].update(nodes=[0], weights=[.9]),
            lambda s: s['ports'][0].update(nodes=[999], weights=[1.]),
            lambda s: s['ports'][1].update(name='P1'),
            lambda s: s.update(ports=s['ports'][:1]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                study = rectangle(2, 1)
                mutate(study)
                with self.assertRaises(ValueError):
                    plane.validate_study(study)

    def test_degenerate_disconnected_nonmanifold_meshes(self):
        fixtures = [
            ([[0, 0], [1, 0], [2, 0]], [[0, 1, 2]]),
            ([[0, 0], [1, 0], [0, 1], [2, 0], [3, 0], [2, 1]], [[0, 1, 2], [3, 4, 5]]),
            ([[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1]], [[0, 1, 2], [0, 3, 4]]),
            ([[0, 0], [1, 0], [0, 1], [0, -1], [.5, 2]], [[0, 1, 2], [1, 0, 3], [0, 1, 4]]),
            ([[0, 0], [1, 0], [0, 1], [.5, 2]], [[0, 1, 2], [0, 1, 3]]),
        ]
        for vertices, triangles in fixtures:
            with self.subTest(triangles=triangles):
                study = rectangle(2, 1)
                study.update(vertices_mm=vertices, triangles=triangles)
                with self.assertRaises(ValueError):
                    plane.validate_study(study)

    def test_corrupted_solve_rejected_and_cancellation(self):
        class BadLU:
            def solve(self, rhs):
                return rhs.astype(complex)
        with patch('scipy.sparse.linalg.splu', return_value=BadLU()):
            with self.assertRaises(RuntimeError):
                plane.run_study(rectangle())
        cancel = threading.Event()
        cancel.set()
        with patch('quick_pi_plugin.plane_ports._assemble') as assemble:
            with self.assertRaises(CancelledError):
                plane.run_study(rectangle(), cancel=cancel)
            assemble.assert_not_called()

    def test_headless_import(self):
        script = ('import sys; import quick_pi_plugin.plane_ports; '
                  'assert not any(k in sys.modules for k in ("wx","matplotlib","scipy","numpy"))')
        subprocess.run([sys.executable, '-B', '-c', script], check=True)

    def test_frequency_limit_and_finite_output_rejection(self):
        study = rectangle(2, 1)
        study['frequencies_hz'] = [1e4+i*1e4 for i in range(512)][::-1]
        normalized = plane.validate_study(study)
        self.assertEqual(len(normalized['frequencies_hz']), 512)
        self.assertEqual(normalized['frequencies_hz'], sorted(study['frequencies_hz']))

        class NonfiniteLU:
            def solve(self, rhs):
                return np.full(rhs.shape, complex(float('nan'), 0))

        with patch('scipy.sparse.linalg.splu', return_value=NonfiniteLU()):
            with self.assertRaisesRegex(RuntimeError, 'Nonfinite'):
                plane.run_study(rectangle(2, 1))


if __name__ == '__main__':
    unittest.main()
