"""Contract rejection tests and opt-in real EMerge advanced workflow checks."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from quick_emerge_plugin.advanced import ADVANCED_FIELDS, verify_step, check_mesh_budget
from quick_emerge_plugin.model import validate_config, config_digest


class AdvancedContractTests(unittest.TestCase):
    def test_normalized_defaults_and_digest(self):
        c = validate_config({})
        self.assertEqual(c['advanced']['study'], 'driven')
        self.assertEqual(validate_config(c), c)
        self.assertNotEqual(config_digest(c), config_digest(dict(c, advanced={'loss_tangent': .01})))
        self.assertEqual(len({f['key'] for f in ADVANCED_FIELDS}), len(ADVANCED_FIELDS))
        self.assertIn('thermal_time_s', {f['key'] for f in ADVANCED_FIELDS})

    def test_reject_unknown_nonfinite_bool_ranges_and_unavailable_transient(self):
        for advanced in ({'script':'print(1)'}, {'loss_tangent':float('nan')}, {'solver_threads':True},
                         {'solver_threads':65}, {'abc_order':3}, {'loss_tangent':-1},
                         {'conductor_thickness_um':0}, {'thermal_time_s':1, 'thermal_step_s':2},
                         {'study':'scattering','step_path':'x.step'}, {'optimize_evaluations':31}):
            with self.subTest(advanced=advanced), self.assertRaises(ValueError):
                validate_config(dict(advanced=advanced))

    def test_periodic_does_not_validate_unused_feed_inset(self):
        c = validate_config(dict(substrate_x_mm=20, substrate_y_mm=10, patch_width_mm=5,
                                 patch_length_mm=4, advanced={'study':'periodic'}))
        self.assertEqual(c['advanced']['study'], 'periodic')
        with self.assertRaisesRegex(ValueError, 'diffraction'):
            validate_config(dict(c, f_start_hz=20e9, f_stop_hz=30e9))

    def test_external_patch_feed_bounds_scope_and_digest(self):
        base = dict(substrate_x_mm=40, substrate_y_mm=40, patch_width_mm=20,
                    patch_length_mm=20, feed_width_mm=2, inset_width_mm=3, inset_length_mm=5)
        original = validate_config(base)
        self.assertEqual(original['advanced']['patch_feed_extension_mm'], 0)
        edge = validate_config(dict(base, advanced={'patch_feed_extension_mm':10}))
        self.assertNotEqual(config_digest(original), config_digest(edge))
        for value in (-1, float('nan'), True, 10.001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_config(dict(base, advanced={'patch_feed_extension_mm':value}))
        for study in ('periodic','scattering','thermal','waveguide','array'):
            with self.subTest(study=study), self.assertRaisesRegex(ValueError,'External patch feed'):
                validate_config(dict(base, advanced={'study':study, 'patch_feed_extension_mm':1}))
        with self.assertRaisesRegex(ValueError,'External patch feed'):
            validate_config(dict(base, mode='pcb_line', advanced={'patch_feed_extension_mm':1}))

    def test_signed_patch_offset_and_combined_feed_bounds(self):
        base = dict(substrate_x_mm=80, substrate_y_mm=80, patch_width_mm=41.3,
                    patch_length_mm=31.9, feed_width_mm=3, inset_width_mm=1, inset_length_mm=10)
        c = validate_config(dict(base, advanced={'patch_feed_extension_mm':24.5,'patch_offset_y_mm':.45}))
        self.assertEqual(c['advanced']['patch_offset_y_mm'], .45)
        validate_config(dict(base, advanced={'patch_offset_y_mm':-10}))
        for advanced in ({'patch_offset_y_mm':24.051}, {'patch_offset_y_mm':-24.051},
                         {'patch_feed_extension_mm':24.5,'patch_offset_y_mm':.449},
                         {'patch_offset_y_mm':float('inf')}, {'patch_offset_y_mm':True}):
            with self.subTest(advanced=advanced), self.assertRaises(ValueError):
                validate_config(dict(base,advanced=advanced))
        with self.assertRaisesRegex(ValueError,'offset require'):
            validate_config(dict(base,mode='pcb_line',advanced={'patch_offset_y_mm':1}))

    def test_step_custody_and_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'fixture.step'
            path.write_text('ISO-10303-21;\nEND-ISO-10303-21;')
            a = validate_config({'advanced':dict(study='scattering',step_path=str(path),
                    step_sha256=hashlib.sha256(path.read_bytes()).hexdigest())})['advanced']
            self.assertEqual(verify_step(a)['coordinate_scale_m'], .001)
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                verify_step(a)

    def test_mesh_budget_before_factorization(self):
        from types import SimpleNamespace
        model = SimpleNamespace(mesh=SimpleNamespace(n_tets=101))
        with self.assertRaisesRegex(ValueError, 'reviewed limit'):
            check_mesh_budget(model, dict(max_tets=100))

    def test_typed_element_units_and_waveguide_cutoff(self):
        from quick_emerge_plugin.advanced import element_impedance
        self.assertEqual(element_impedance('resistor',50,1e9),50)
        self.assertAlmostEqual(element_impedance('capacitor',1,1e9).imag,-159.15494309189535)
        self.assertAlmostEqual(element_impedance('inductor',1,1e9).imag,6.283185307179586)
        with self.assertRaisesRegex(ValueError,'cutoff'):
            validate_config(dict(advanced={'study':'waveguide'}))

    def test_future_transient_uses_public_api_and_checks_actual_terminal_time(self):
        from types import SimpleNamespace
        from unittest.mock import patch, Mock
        from quick_emerge_plugin.advanced_thermal import run_transient
        frames=[SimpleNamespace(time=0.,T=[293.]),SimpleNamespace(time=1.1,T=[294.])]
        data=SimpleNamespace(field=SimpleNamespace(iter=lambda:iter(frames)))
        hc=SimpleNamespace(run_transient=Mock(return_value=data))
        with patch('quick_emerge_plugin.advanced_thermal.importlib.metadata.version',return_value='3.1.0'):
            actual,meta=run_transient(hc,1.1,.3)
            self.assertIs(actual,data)
            self.assertEqual(meta['time_s'][-1],1.1)
            frames[-1].time=.9
            with self.assertRaisesRegex(RuntimeError,'terminal time'):
                run_transient(hc,1.1,.3)
        self.assertEqual(hc.run_transient.call_count,2)

    def test_zero_port_never_exports_a_touchstone(self):
        from quick_emerge_plugin.backend import write_touchstone
        with tempfile.TemporaryDirectory() as folder:
            write_touchstone(folder, dict(port_count=0, config={'mode':'patch'}, frequencies_hz=[]))
            self.assertEqual(list(Path(folder).iterdir()), [])


@unittest.skipUnless(os.environ.get('QUICK_EMERGE_REAL_TESTS') == '1', 'requires explicit real EMerge runtime')
class AdvancedRealSolverTests(unittest.TestCase):
    def test_real_advanced_workflows_and_thermal_reference(self):
        from quick_emerge_plugin.backend import solve
        from quick_emerge_plugin.qualification import advanced_smoke_configs, check_result
        for name, c in advanced_smoke_configs():
            with self.subTest(study=name):
                result = solve(c, qualifying=True)
                check_result(result, c)
                json.dumps(result, allow_nan=False)
                if c['advanced']['study'] == 'thermal' and not c['advanced']['thermal_time_s']:
                    t = result['thermal']
                    self.assertAlmostEqual(t['z_mm'], -c['thickness_mm']*1e-6)
                    self.assertLess(abs(t['peak_k']-t['reference_peak_k']), 1e-3)
                if c['advanced']['study'] == 'optimization':
                    self.assertEqual(len(result['optimization']['samples']), 3)
                    self.assertEqual(result['config_sha256'], config_digest(c))
                if 'field' in result:
                    f = result['field']
                    self.assertEqual(len(f['e_real_v_m']), 3)
                    self.assertEqual(len(f['h_real_a_m'][0]), c['field_grid'])
                    if c['advanced']['field_layers'] > 1:
                        self.assertEqual(len(f['volume']['norm_e_v_m']), c['advanced']['field_layers'])
                        self.assertEqual(f['volume']['z_mm'][-1], c['field_z_mm'])

    def test_transient_refinement_equilibrium_and_exact_terminal_time(self):
        from quick_emerge_plugin.backend import solve
        from quick_emerge_plugin.qualification import smoke_configs
        base = dict(smoke_configs()[0][1], points=2)
        errors = []
        for dt in (.5, .25):
            result = solve(dict(base, advanced=dict(study='thermal', thermal_time_s=2.1, thermal_step_s=dt)), qualifying=True)
            t = result['thermal']
            history = t['transient']
            self.assertEqual(history['time_s'][-1], 2.1)
            self.assertTrue(all(y >= x-1e-9 for x, y in zip(history['peak_k'], history['peak_k'][1:])))
            self.assertLess(t['peak_k'], t['reference_peak_k'])
            errors.append(abs(t['peak_k']-t['reference_transient_peak_k']))
        self.assertLess(errors[1], errors[0])
        self.assertLess(errors[1], .3)
        t = solve(dict(base, advanced=dict(study='thermal', thermal_time_s=1.1, thermal_step_s=.3, thermal_power_w=0)), qualifying=True)['thermal']
        self.assertAlmostEqual(t['peak_k'], base['advanced']['ambient_k'], places=7)

    def test_dielectric_rf_heating_power_scaling(self):
        from quick_emerge_plugin.backend import solve
        from quick_emerge_plugin.qualification import smoke_configs
        base = dict(smoke_configs()[0][1], points=2)
        rises = []
        for power in (1., 2.):
            result = solve(dict(base, advanced=dict(loss_tangent=.02, coupled_thermal=True, rf_input_power_w=power)), qualifying=True)
            t = result['thermal']
            self.assertIn('conductor surface heating excluded', t['coupling'])
            self.assertNotIn('reference_peak_k', t)
            rises.append(t['peak_k']-result['config']['advanced']['ambient_k'])
        self.assertGreater(rises[0], 0)
        self.assertAlmostEqual(rises[1]/rises[0], 2., places=5)

    def test_coherent_array_phase_and_incident_power(self):
        from quick_emerge_plugin.backend import solve
        from quick_emerge_plugin.qualification import smoke_configs
        base = dict(smoke_configs()[1][1],points=2,substrate_x_mm=60,substrate_y_mm=40)
        peaks=[]
        for phase in (0,180):
            result=solve(dict(base,advanced=dict(study='array',array_count_x=2,array_count_y=1,
                 array_pitch_x_mm=25,array_pitch_y_mm=25,array_phase_x_deg=phase,array_power_w=2)),qualifying=True)
            self.assertAlmostEqual(sum(abs(complex(*v))**2 for v in result['array']['excitation_weights']),2.)
            self.assertEqual(result['port_count'],2)
            self.assertEqual(set(result['s_parameters']),{'S11','S12','S21','S22'})
            self.assertLess(result['array']['superposition_relative_error'],1e-10)
            peaks.append(max(result['radiation']['norm_e'][0]))
        self.assertGreater(peaks[0],0)
        # Do not demand an ideal-array null from an unqualified coarse open-region mesh.
        # The independent per-port field integration above verifies the coherent sum.
        self.assertGreater(abs(peaks[1]-peaks[0]),.05*peaks[0])

    def test_real_step_import_and_custody(self):
        import gmsh
        from quick_emerge_plugin.backend import solve
        from quick_emerge_plugin.qualification import smoke_configs
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'cube.step'
            if not gmsh.isInitialized():
                gmsh.initialize()
            gmsh.clear()
            gmsh.model.add('qualification-step')
            gmsh.model.occ.addBox(-2,-2,-2,4,4,4)
            gmsh.model.occ.synchronize()
            gmsh.write(str(path))
            gmsh.clear()
            c = validate_config(dict(smoke_configs()[0][1], points=2, advanced=dict(study='scattering',
                      step_path=str(path),step_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),step_unit_m=.001)))
            result = solve(c, qualifying=True)
            json.dumps(result, allow_nan=False)
            self.assertEqual(result['import_source']['sha256'], c['advanced']['step_sha256'])
            bounds = result['scene_geometry']['bounds']
            for value, expected in zip(bounds, [-2,-2,-2,2,2,2]):
                self.assertAlmostEqual(value, expected, places=3)
            self.assertTrue(result['scene_geometry']['triangles'])
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                solve(c, qualifying=True)

    def test_real_region_loss_and_thermal(self):
        from quick_emerge_plugin.backend import solve
        from quick_emerge_plugin.region_backend import qualification_region
        from quick_emerge_plugin.qualification import smoke_configs
        region = qualification_region()
        base = dict(smoke_configs()[0][1], mode='pcb_region', rule_area_id='qualification-coupon',
                    signal_net='SIGNAL', reference_net='GND', region_er_reviewed=True, points=2)
        for a in (dict(study='thermal'), dict(conductor='finite',loss_tangent=.02)):
            result = solve(dict(base, advanced=a), qualifying=True, region=region)
            self.assertEqual(result['region_sha256'], __import__('quick_emerge_plugin.region_backend', fromlist=['region_digest']).region_digest(region))
            json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
