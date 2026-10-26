"""Independent DC/slab references, conservation and AC rejection contracts."""
import cmath
import copy
import json
import math
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from quick_pi_plugin.ac_analysis import MU0, run_study, validate_study, waveform_harmonics


def study():
    return {'schema': 'wayricad.pi-ac/v1', 'length_mm': 10., 'dc_current_a': 2.,
            'reference_voltage_v': 48., 'mesh_step_mm': .05, 'air_padding_mm': 1.,
            'conductors': [
                {'name': 'Rail', 'x_mm': 0., 'y_mm': .3, 'width_mm': .2,
                 'thickness_mm': .2, 'current_scale': 1.},
                {'name': 'Return', 'x_mm': 0., 'y_mm': -.3, 'width_mm': .2,
                 'thickness_mm': .2, 'current_scale': -1.}],
            'harmonics': [{'frequency_hz': 1000., 'current_rms_a': 3.}]}


class ACReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = study(); cls.result = run_study(cls.base)

    def test_low_frequency_matches_independent_dc_and_rms_loss(self):
        resistance = 2*1.7241e-8*.01/(.0002*.0002)
        result = self.result
        self.assertAlmostEqual(result['dc_resistance_ohm'], resistance, places=12)
        self.assertLess(abs(result['harmonics'][0]['resistance_ohm']/resistance-1), 1e-5)
        self.assertLess(abs(result['total_loss_w']/((2**2+3**2)*resistance)-1), 1e-5)
        self.assertEqual(result['status'], 'CONVERGED')

    def test_current_power_and_independent_density_integration(self):
        r = self.result
        total = sum(c['loss_density_w_mm3']*c['width_mm']*c['height_mm']*
                    self.base['length_mm'] for c in r['cells'])
        self.assertAlmostEqual(total, r['total_loss_w'], places=11)
        self.assertAlmostEqual(sum(c['total_loss_w'] for c in r['conductors']), total, places=11)
        self.assertLess(r['checks']['current_relative_error'], 1e-10)
        self.assertLess(r['checks']['power_relative_error'], 1e-10)
        self.assertAlmostEqual(r['conductors'][0]['total_loss_w'], r['conductors'][1]['total_loss_w'], places=10)
        json.dumps(r, allow_nan=False)

    def test_broad_plate_skin_and_proximity_match_one_sided_slab(self):
        # Infinite-width opposed slabs: uniform field between plates, zero
        # outside. Finite 6-mm width introduces fringing; allow 4% in reactance.
        s = study(); s.update(dc_current_a=0., mesh_step_mm=.08, air_padding_mm=4., max_cells=100000)
        for c in s['conductors']:
            c.update(width_mm=6., thickness_mm=.07, y_mm=.045*c['current_scale'])
        s['harmonics'] = [{'frequency_hz': f, 'current_rms_a': 1.} for f in (1e5, 1e6)]
        r = run_study(s)
        self.assertEqual(r['status'], 'CONVERGED')
        for h in r['harmonics']:
            omega = 2*math.pi*h['frequency_hz']; rho = 1.7241e-8
            k = cmath.sqrt(1j*omega*MU0/rho)
            exact = (2*rho*k/cmath.tanh(k*.00007)+1j*omega*MU0*.00002)*.01/.006
            self.assertLess(abs(h['resistance_ohm']/exact.real-1), .02)
            self.assertLess(abs(h['reactance_ohm']/exact.imag-1), .04)
        self.assertGreater(r['harmonics'][1]['ac_dc_resistance_ratio'], 1.08)

    def test_voltage_context_does_not_change_copper_physics(self):
        s = study(); s['reference_voltage_v'] = 1200.
        r = run_study(s)
        self.assertAlmostEqual(r['total_loss_w'], self.result['total_loss_w'], places=12)
        self.assertAlmostEqual(r['ripple_voltage_ratio']/self.result['ripple_voltage_ratio'], 48/1200)

    def test_high_current_losses_scale_quadratically_without_ampacity_claim(self):
        s = study(); s['dc_current_a'] *= 100.; s['harmonics'][0]['current_rms_a'] *= 100.
        r = run_study(s)
        self.assertAlmostEqual(r['total_loss_w']/self.result['total_loss_w'], 10000., places=7)
        self.assertTrue(any('ampacity' in text for text in r['limitations']))

    def test_resolved_proximity_eddy_loss_in_zero_net_current_shield(self):
        s = study(); s['harmonics'] = [{'frequency_hz': 1e6, 'current_rms_a': 1.}]
        s['conductors'].append({'name': 'Floating copper', 'x_mm': .3, 'y_mm': 0.,
                                'width_mm': .2, 'thickness_mm': .2, 'current_scale': 0.})
        r = run_study(s)
        self.assertGreater(r['conductors'][2]['ac_loss_w'], 0.)
        self.assertEqual(r['conductors'][2]['dc_loss_w'], 0.)
        self.assertLess(r['checks']['current_relative_error'], 1e-8)

    def test_unconverged_is_reported_without_accepting_the_field(self):
        s = study(); s['convergence_tolerance'] = .001
        s['harmonics'][0]['frequency_hz'] = 1e6
        r = run_study(s)
        self.assertEqual(r['status'], 'UNCONVERGED')
        self.assertGreater(r['checks']['mesh_relative_error'], .001)
        self.assertIn('local peak', r['checks']['convergence_scope'])


class ACInputTests(unittest.TestCase):
    def test_rejects_unknowns_missing_returns_and_overlaps(self):
        invalid = []
        s = study(); s['guess_return'] = True; invalid.append(s)
        s = study(); s['conductors'][1]['current_scale'] = 0.; invalid.append(s)
        s = study(); s['conductors'][1]['y_mm'] = .3; invalid.append(s)
        s = study(); s['harmonics'] *= 2; invalid.append(s)
        s = study(); s['dc_current_a'] = float('nan'); invalid.append(s)
        s = study(); s['max_cells'] = True; invalid.append(s)
        s = study(); s['harmonics'][0]['current_rms_a'] = 0.; invalid.append(s)
        for s in invalid:
            with self.subTest(s=s), self.assertRaises(ValueError): validate_study(s)

    def test_mqs_guard_includes_transverse_span(self):
        s = study(); s['length_mm'] = .001
        s['conductors'][1]['y_mm'] = 1000.
        s['harmonics'][0]['frequency_hz'] = 1e7
        with self.assertRaisesRegex(ValueError, 'electrically'): validate_study(s)

    def test_budget_never_coarsens_skin_depth_away(self):
        s = study(); s['max_cells'] = 100
        with self.assertRaisesRegex(ValueError, 'budget|max_cells'): run_study(s)

    def test_overflow_is_actionable(self):
        s = study(); s['dc_current_a'] = 1e200
        with self.assertRaisesRegex(ValueError, 'finite numerical'): run_study(s)

    def test_worker_rejects_stale_or_mutated_study_inputs(self):
        from quick_pi_plugin.service import execute
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'study.json'; source.write_text('{}', encoding='utf-8')
            request = {'action': 'ac', 'study': study(), 'study_input_path': str(source),
                       'study_file_sha256': '0'*64}
            with self.assertRaisesRegex(ValueError, 'changed'): execute(request)
            request.pop('study_file_sha256')
            def mutation(_study):
                source.write_text('{"changed":true}', encoding='utf-8')
                return {}
            with patch('quick_pi_plugin.ac_analysis.run_study', side_effect=mutation):
                with self.assertRaisesRegex(ValueError, 'changed during'): execute(request)

    def test_triangle_parseval_and_pulse_mean_and_rms(self):
        triangle = waveform_harmonics('triangle', 100e3, 12., terms=32, dc_current_a=10.)
        self.assertEqual(triangle['dc_current_a'], 10.)
        self.assertAlmostEqual(triangle['retained_rms_a']**2+triangle['omitted_rms_a']**2, 12., places=10)
        self.assertLess(triangle['omitted_rms_a'], .02)
        pulse = waveform_harmonics('pulse', 50e3, 20., terms=32, duty=.25)
        self.assertEqual(pulse['dc_current_a'], 5.)
        self.assertAlmostEqual(pulse['retained_rms_a']**2+pulse['omitted_rms_a']**2, 75., places=10)
        self.assertGreater(pulse['omitted_rms_a'], 0.)

    def test_stale_waveform_metadata_rejected(self):
        generated = waveform_harmonics('triangle', 1000., 1., terms=3, dc_current_a=2.)
        s = study(); s.update({key: generated[key] for key in ('dc_current_a', 'harmonics', 'waveform')})
        validate_study(s)
        s['harmonics'][0]['current_rms_a'] *= 2
        with self.assertRaisesRegex(ValueError, 'stale'): validate_study(s)


if __name__ == '__main__':
    unittest.main()
