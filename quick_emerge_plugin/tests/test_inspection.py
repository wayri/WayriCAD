import math
import unittest

from quick_emerge_plugin.inspection import FieldInspection, scale_limits


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.field = {'x_mm': [0, 1, 5], 'y_mm': [0, 4], 'z_mm': 2,
                      'frequency_hz': 1e9, 'norm_e_v_m': [[0, None, 7], [3, 2, 9]]}
        self.inspection = FieldInspection(self.field)

    def test_nearest_original_and_unknown(self):
        p = self.inspection.probe(1.3, 0.4)
        self.assertEqual((p['ix'], p['iy'], p['x_mm']), (1, 0, 1))
        self.assertIsNone(p['value_v_m'])
        self.assertTrue(p['unknown'])
        self.assertEqual(self.inspection.probe(3.2, 4)['value_v_m'], 9)
        with self.assertRaises(ValueError):
            self.inspection.probe(-1, 0)

    def test_extrema_and_all_unknown(self):
        e = self.inspection.extrema()
        self.assertEqual((e['min']['value_v_m'], e['max']['value_v_m']), (0, 9))
        self.field['norm_e_v_m'] = [[None] * 3 for _ in range(2)]
        self.assertEqual(FieldInspection(self.field).extrema(), {'min': None, 'max': None})

    def test_line_distances_and_duplicates(self):
        line = self.inspection.line((0, 0), (5, 4), 5)
        self.assertAlmostEqual(line[-1]['distance_mm'], math.sqrt(41))
        self.assertAlmostEqual(line[1]['distance_mm'], math.sqrt(41) / 4)
        self.assertEqual(len(self.inspection.line((0, 0), (0, 0), 3)), 3)
        for count in (True, 1, 2001, 2.5):
            with self.assertRaises(ValueError):
                self.inspection.line((0, 0), (1, 1), count)
        with self.assertRaises(ValueError):
            self.inspection.line((0, 0), (6, 4))

    def test_invalid_fields(self):
        for key, value in [('x_mm', [0, 0, 5]), ('y_mm', [0, float('nan')]),
                           ('z_mm', float('inf')), ('frequency_hz', None), ('frequency_hz', 0),
                           ('norm_e_v_m', [[1], [2]]),
                           ('norm_e_v_m', [[0, -1, 2], [1, 2, 3]]),
                           ('norm_e_v_m', [[0, float('nan'), 2], [1, 2, 3]])]:
            field = dict(self.field, **{key: value})
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                FieldInspection(field)

    def test_scale_limits(self):
        self.assertEqual(scale_limits([None, 0, 2, 5]), (0, 5))
        self.assertEqual(scale_limits([None, 0, 2, 5], 'log'), (2, 5))
        self.assertEqual(scale_limits([0, 2, 5], minimum=1, maximum=4), (1, 4))
        lo, hi = scale_limits([2], 'log')
        self.assertLess(lo, 2)
        self.assertGreater(hi, 2)
        for args in [([None],), ([0, None], 'log'), ([1], 'log', 0, 2),
                     ([1], 'linear', 2, 1), ([1], 'linear', 0, None),
                     ([float('inf')],), ([-1],)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                scale_limits(*args)


if __name__ == '__main__':
    unittest.main()
