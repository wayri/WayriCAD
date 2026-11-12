"""Analytical references and transfer/iteration rejection tests."""
import copy
import json
import tempfile
import unittest
import shutil
import subprocess
import sys
import threading
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

from planar_magnetics_plugin.analysis import CoilSpec, MagneticsEngine, WindingSegment
from planar_magnetics_plugin.thermal_coupling import (
    ThermalDrive, main, rectangular_profile, require_fresh, solve_thermal_study,
)


class ThermalCouplingTests(unittest.TestCase):
    def setUp(self):
        self.result = MagneticsEngine.analyze(CoilSpec(turns=1, layers=1,
                                                     frequency_khz=0))
        # Uniform full-face trace gives an exact lumped convection reference.
        self.result.segments = [WindingSegment(-5, 0, 5, 0, 10, 0)]
        self.result.vias = []
        self.geometry = rectangular_profile(10, 10, 2, 1.6, 35)
        self.settings = dict(ambient_c=20, dielectric_k_w_mk=.3,
                             copper_k_w_mk=385, via_plating_mm=.025,
                             board_h_w_m2k=10, board_emissivity=0,
                             grid_cells_long_axis=24)
        self.drive = ThermalDrive(value=10, copper_alpha_per_k=0)

    def solve(self, **kwargs):
        args = dict(result=self.result, geometry=self.geometry, settings=self.settings,
                    drive=self.drive, layer_map=[0])
        args.update(kwargs)
        return solve_thermal_study(**args)

    def test_cancellation_at_entry_preparation_and_thermal_backend(self):
        with self.assertRaises(InterruptedError):
            self.solve(cancel=lambda: True)
        cancel = lambda: False
        for backend in ('prepare_distributed_sources', 'solve_multilayer_thermal'):
            def cancelled_backend(*args, **kwargs):
                self.assertIs(kwargs['cancel'], cancel)
                raise InterruptedError('Backend cancelled')
            with self.subTest(backend=backend), patch(
                    'planar_magnetics_plugin.thermal_coupling.'+backend,
                    side_effect=cancelled_backend), self.assertRaises(InterruptedError):
                self.solve(cancel=cancel)

    def test_legacy_backend_without_cancel_discards_output_before_next_iteration(self):
        from planar_magnetics_plugin.thermal_coupling import solve_multilayer_thermal
        cancelled = threading.Event()
        def legacy(geometry, view, result, settings, *, distributed_sources, prepared_sources):
            value = solve_multilayer_thermal(geometry, view, result, settings,
                distributed_sources=distributed_sources, prepared_sources=prepared_sources)
            cancelled.set()
            return value
        # A real function signature represents an older backend without cancel.
        with patch('planar_magnetics_plugin.thermal_coupling.solve_multilayer_thermal',
                   new=legacy), self.assertRaises(InterruptedError):
            self.solve(cancel=cancelled.is_set)

    def test_uniform_convection_and_vertical_drop(self):
        study = self.solve()
        power = study['trace_loss_w']
        # Two faces, top source, explicit dielectric vertical conductance.
        face_g = 10*1e-4
        vertical_g = .3*1e-4/(.0016-.000035)
        expected = power/(face_g+face_g*vertical_g/(face_g+vertical_g))
        self.assertAlmostEqual(study['winding_mean_c']-20, expected, places=6)
        balance = study['thermal']['heat_balance']
        self.assertAlmostEqual(balance['input_w'], power, places=12)
        self.assertLess(abs(balance['residual_w']), 1e-8)
        self.assertIsNone(study['core_contact_power_w'])
        self.assertIsNone(study['magnetic_core_loss_estimate_w'])

    def test_current_and_voltage_feedback_against_analytic_fixed_point(self):
        cold = self.solve()
        r0 = cold['resistance_ohm']
        theta = (cold['winding_mean_c']-20)/cold['trace_loss_w']
        alpha = .00393
        current = self.solve(drive=replace(self.drive, copper_alpha_per_k=alpha,
                                          tolerance_c=1e-7))
        expected = theta*100*r0/(1-theta*100*r0*alpha)
        self.assertAlmostEqual(current['winding_mean_c']-20, expected, places=5)
        voltage = self.solve(drive=replace(self.drive, mode='voltage', value=10*r0,
                                          copper_alpha_per_k=alpha, tolerance_c=1e-7))
        expected_v = (-1+(1+4*alpha*theta*100*r0)**.5)/(2*alpha)
        self.assertAlmostEqual(voltage['winding_mean_c']-20, expected_v, places=5)
        self.assertLess(voltage['trace_loss_w'], cold['trace_loss_w'])
        self.assertGreater(current['trace_loss_w'], cold['trace_loss_w'])

    def test_core_contact_is_explicit_and_conservative(self):
        contact = dict(power_w=.1, layer_id=1,
                       polygon_mm=[[-2,-2],[2,-2],[2,2],[-2,2]])
        study = self.solve(core_contact=contact)
        self.assertAlmostEqual(study['thermal']['heat_balance']['input_w'],
                               study['trace_loss_w']+.1, places=12)
        with self.assertRaises(ValueError):
            self.solve(core_contact={**contact, 'layer_id': 9})

    def test_staleness(self):
        study = self.solve()
        require_fresh(study, self.result, self.geometry, self.settings, self.drive, [0])
        changed = {**self.settings, 'ambient_c': 21}
        with self.assertRaisesRegex(ValueError, 'stale'):
            require_fresh(study, self.result, self.geometry, changed, self.drive, [0])
        altered = copy.deepcopy(self.result)
        altered.segments[0] = replace(altered.segments[0], width_mm=9)
        with self.assertRaisesRegex(ValueError, 'stale'):
            require_fresh(study, altered, self.geometry, self.settings, self.drive, [0])

    def test_invalid_geometry_and_drive(self):
        for kwargs in [dict(layer_map=[9]), dict(origin_mm=(20,0)),
                       dict(drive=replace(self.drive, value=float('nan'))),
                       dict(drive=replace(self.drive, mode='voltage', resistance_model='legacy_ac')),
                       dict(drive=replace(self.drive, max_iterations=1)),
                       dict(drive=replace(self.drive, maximum_c=20))]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.solve(**kwargs)
        with self.assertRaises(ValueError):
            rectangular_profile(10, 10, 2, .01, 35)
        hole = copy.deepcopy(self.geometry)
        hole['outline'][0]['holes_mm'] = [[[-1,-1],[1,-1],[1,1],[-1,1]]]
        with self.assertRaises(ValueError):
            self.solve(geometry=hole)
        bad = copy.deepcopy(self.geometry)
        bad['layers'][0]['thickness_mm'] = .07
        with self.assertRaisesRegex(ValueError, 'thickness'):
            self.solve(geometry=bad)
        malformed = copy.deepcopy(self.result)
        malformed.segments[0] = replace(malformed.segments[0], layer=-1)
        with self.assertRaisesRegex(ValueError, 'layer'):
            self.solve(result=malformed)

    def test_independent_bundled_runtime_import_and_solve(self):
        import wayricad_runtime.thermal_multilayer as kernel
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='magnetics-isolation-') as folder:
            package = Path(folder)/'planar_magnetics_plugin'
            package.mkdir()
            for name in ('__init__.py', 'analysis.py', 'magnetic_circuit.py', 'thermal_coupling.py'):
                shutil.copy2(source/name, package/name)
            runtime = package/'wayricad_runtime'
            runtime.mkdir()
            (runtime/'__init__.py').touch()
            shutil.copy2(kernel.__file__, runtime/'thermal_multilayer.py')
            shutil.copy2(source/'thermal_example.json', Path(folder)/'input.json')
            code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                    "from planar_magnetics_plugin.thermal_coupling import main; "
                    "main([sys.argv[1]+'/input.json','--output',sys.argv[1]+'/result.json'])")
            completed = subprocess.run([sys.executable, '-I', '-c', code, folder],
                                       cwd=folder, capture_output=True, text=True, timeout=90)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads((Path(folder)/'result.json').read_text())['status'], 'converged')

    def test_generated_winding_and_cli(self):
        result = MagneticsEngine.analyze(CoilSpec(turns=1, layers=2))
        geometry = rectangular_profile(45, 45, 2, 1.6, 35)
        study = self.solve(result=result, geometry=geometry, layer_map=[0,1],
                           origin_mm=(-17.5,-17.5), drive=ThermalDrive())
        self.assertEqual(study['status'], 'converged')
        self.assertGreaterEqual(study['winding_peak_c'], study['winding_segment_peak_c'])
        from dataclasses import asdict
        with tempfile.TemporaryDirectory(prefix='magnetics-thermal-') as folder:
            path = Path(folder)
            data = dict(coil=asdict(result.spec), geometry=geometry, settings=self.settings,
                        drive=asdict(ThermalDrive()), layer_map=[0,1], origin_mm=[-17.5,-17.5])
            (path/'input.json').write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(main([str(path/'input.json'), '--output', str(path/'result.json')]), 0)
            self.assertEqual(json.loads((path/'result.json').read_text())['status'], 'converged')
            with self.assertRaises(FileExistsError):
                main([str(path/'input.json'), '--output', str(path/'result.json')])


if __name__ == '__main__':
    unittest.main()
