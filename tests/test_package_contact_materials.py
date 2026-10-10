"""Analytical and independent quadrature references for physical contacts."""
import copy
import math
import unittest

from wayricad_runtime.package_conduction import normalize_paths
from wayricad_runtime.package_contact_editor import paths_from_rows


def path(**segment):
    return {'id': 'U1-A1', 'reference': 'U1', 'pad_number': 'A1', 'layer_id': 0,
            'segments': [{'shape': 'cylinder', 'length_mm': .2, 'diameter_mm': .4,
                          'rho_ohm_m': 1.3e-7, 'k_w_mk': 50, **segment}]}


class ContactGeometryTests(unittest.TestCase):
    def test_editor_series_roundtrip_preserves_explicit_source_and_uuid(self):
        original=path();original['pad_uuid']='saved-uuid'
        row=['U1-A1','U1','A1','0','source','cylinder','.2','.4','',
             '1.3e-7','50','Test solder','reviewed datasheet Rev A','','']
        edited=paths_from_rows([row,row],physics='electrical',previous=[original])
        self.assertEqual(len(edited),1)
        self.assertEqual(len(edited[0]['segments']),2)
        self.assertEqual(edited[0]['pad_uuid'],'saved-uuid')
        self.assertEqual(edited[0]['segments'][0]['evidence'],'reviewed datasheet Rev A')
        named=list(row);named[3]='B.Cu'
        native=paths_from_rows([named],physics='electrical',layers=[{'name':'B.Cu','id':2}])
        self.assertEqual(native[0]['layer_id'],2)
        self.assertNotIn('pad_uuid',native[0])
        with self.assertRaises(ValueError):
            paths_from_rows([row,[*row[:2],'A2',*row[3:]]],physics='electrical')

    def test_cylinder_series_and_no_mutation(self):
        raw = path()
        raw['segments'].append({'shape': 'rectangular', 'length_mm': 1,
                                'width_mm': .3, 'thickness_mm': .1,
                                'rho_ohm_m': 2e-8, 'k_w_mk': 200})
        raw['additional_thermal_k_per_w'] = 2
        saved = copy.deepcopy(raw)
        solved = normalize_paths([raw], physics='electrical')[0]
        expected = 1000*.2/(math.pi*.2**2)
        self.assertAlmostEqual(solved['electrical_resistance_ohm'], expected*1.3e-7+1000/.03*2e-8, 14)
        self.assertAlmostEqual(solved['thermal_resistance_k_per_w'], expected/50+1000/.03/200+2, 11)
        self.assertEqual(raw, saved)
        self.assertEqual(normalize_paths([solved['definition']], physics='thermal')[0], solved)

    def test_truncated_ball_against_independent_midpoint_quadrature(self):
        solved = normalize_paths([path(shape='spherical_ball', length_mm=.3, diameter_mm=.5)], physics='thermal')[0]
        intervals = 100000
        dz = .3e-3/intervals
        integral = math.fsum(dz/(math.pi*((.25e-3)**2-(-.15e-3+(i+.5)*dz)**2))
                             for i in range(intervals))
        self.assertAlmostEqual(solved['geometric_factor_per_m']/integral, 1, 9)
        self.assertAlmostEqual(solved['thermal_resistance_k_per_w'], integral/50, 7)

    def test_unknown_other_physics_is_preserved(self):
        raw = path()
        del raw['segments'][0]['rho_ohm_m']
        row = normalize_paths([raw], physics='thermal')[0]
        self.assertIsNone(row['electrical_resistance_ohm'])
        with self.assertRaisesRegex(ValueError, 'rho_ohm_m'):
            normalize_paths([raw], physics='electrical')

    def test_bad_geometry_properties_and_ownership(self):
        for bad in (0, -1, float('nan'), float('inf'), True, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_paths([path(k_w_mk=bad)], physics='thermal')
        for change in ({'shape': 'spherical_ball', 'length_mm': .4},
                       {'shape': 'cone'}, {'material': ''}, {'width_mm': 3}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize_paths([path(**change)], physics='thermal')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            normalize_paths([path(), path()], physics='electrical')
        raw = path(); raw['layer_id'] = True
        with self.assertRaises(ValueError):
            normalize_paths([raw], physics='thermal')
        for size in (1e-300, 1e300):
            with self.subTest(size=size), self.assertRaises(ValueError):
                normalize_paths([path(diameter_mm=size)], physics='thermal')


if __name__ == '__main__':
    unittest.main()
