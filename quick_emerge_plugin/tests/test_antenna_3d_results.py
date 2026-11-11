"""Numerical contracts for visible 3D antenna results."""
import unittest
import numpy as np
from quick_emerge_plugin.research_antennas import example_config
from quick_emerge_plugin.research_studies import solve_rectangular_array_factor
from quick_emerge_plugin.radiation_pattern import prepare_radiation
from quick_emerge_plugin.polarization_view import ellipse, available


class Antenna3DTests(unittest.TestCase):
    def test_new_uniform_default_preserves_historical_hashes(self):
        import hashlib
        import json
        from quick_emerge_plugin.model import config_digest
        config=example_config('verho-2023-aesa-4x4')
        config['advanced'].pop('research_array_taper')
        historical=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        self.assertEqual(config_digest(config),historical)
        config['advanced']['research_array_taper']='binomial'
        self.assertNotEqual(config_digest(config),historical)

    def test_binomial_taper_preserves_steering_and_records_actual_weights(self):
        config=example_config('verho-2023-aesa-4x4')
        config['advanced'].update(scan_theta_deg=30,research_array_taper='binomial')
        result=solve_rectangular_array_factor(np,config,{})
        factor=result['array_factor']
        np.testing.assert_allclose(np.asarray(factor['element_amplitudes']).reshape(4,4),
                                   np.outer([1,3,3,1],[1,3,3,1])/9)
        np.testing.assert_allclose(np.abs([complex(*w) for w in factor['weights_ri']]),factor['element_amplitudes'])
        self.assertLess(abs(factor['scan_error_deg']),.26)
        self.assertEqual(result['publication_comparison']['overall'],'insufficient')

    def test_steered_surface_is_spherical_not_revolved_cut(self):
        config = example_config('verho-2023-aesa-4x4')
        config['advanced']['scan_theta_deg'] = 30
        config['advanced']['scan_phi_deg'] = 40
        result = solve_rectangular_array_factor(np, config, {})
        samples = prepare_radiation(result['radiation'])
        i, j = np.unravel_index(np.argmax(samples.relative), samples.relative.shape)
        # Planar isotropic arrays have an equally strong mirrored back lobe.
        self.assertAlmostEqual(abs(np.sin(samples.theta[i])), .5, places=2)
        self.assertAlmostEqual(np.degrees(samples.phi[j]), 40, delta=2)
        self.assertEqual(samples.relative.shape, (91, 181))
        self.assertIn('not-full-wave', result['radiation']['model'])
        self.assertFalse(available(result))

    def test_polarization_geometry_preserves_saved_jones_vector(self):
        result = {'radiation': {'boresight_polarization': {'ex_ri': [1, 0], 'ey_ri': [0, 1]}}}
        points = ellipse(result)
        np.testing.assert_allclose(np.linalg.norm(points, axis=1), 1/np.sqrt(2))
        self.assertTrue(np.all(points[:, 2] == 0))
        self.assertTrue(available(result))
        self.assertFalse(available({}))
        self.assertFalse(available({'radiation': {'boresight_polarization': {'ex_ri': [0, 0], 'ey_ri': [0, 0]}}}))
