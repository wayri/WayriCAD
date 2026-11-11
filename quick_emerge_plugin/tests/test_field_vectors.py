"""Reference checks for Re{phasor exp(j phase)} at original coordinates."""
import unittest
import numpy as np
from quick_emerge_plugin.field_vectors import sample_vectors


class FieldVectorTests(unittest.TestCase):
    def field(self):
        return {'x_mm':[2, 4], 'y_mm':[-1, 1], 'z_mm':3,
                'e_real_v_m':[[[1, 1],[1, 1]], [[0, 0],[0, 0]], [[0, 0],[0, 0]]],
                'e_imag_v_m':[[[0, 0],[0, 0]], [[1, 1],[1, 1]], [[0, 0],[0, 0]]]}

    def test_phase_quadrature_and_reversal(self):
        field = self.field()
        zero, quarter, half = [sample_vectors(field, phase_deg=p) for p in (0, 90, 180)]
        np.testing.assert_allclose(zero['vectors'][0], [1, 0, 0])
        np.testing.assert_allclose(quarter['vectors'][0], [0, -1, 0], atol=1e-15)
        np.testing.assert_allclose(half['vectors'], -zero['vectors'], atol=1e-15)
        np.testing.assert_array_equal(zero['positions'], [[2,-1,3],[4,-1,3],[2,1,3],[4,1,3]])
        self.assertEqual(zero['arrow_scale_mm_per_unit'], quarter['arrow_scale_mm_per_unit'])

    def test_missing_components_do_not_create_waves(self):
        with self.assertRaisesRegex(ValueError, 'complex vector'):
            sample_vectors({'norm_e_v_m':[[1]], 'x_mm':[0], 'y_mm':[0], 'z_mm':0})
        with self.assertRaises(ValueError): sample_vectors(self.field(), 'Power-flow magnitude')

    def test_slice_uses_original_volume_phasors(self):
        field = self.field()
        field['volume'] = dict(field, z_mm=[5, 8])
        for key in ('e_real_v_m', 'e_imag_v_m'):
            field['volume'][key] = np.repeat(np.asarray(field[key])[:, None], 2, axis=1).tolist()
        sampled = sample_vectors(field, z_index=1)
        self.assertTrue(np.all(sampled['positions'][:, 2] == 8))
