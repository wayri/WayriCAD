"""Analytical checks for the intentionally bounded QuickTherm model."""
import json
import unittest

from quick_therm_plugin.quick_therm import (
    analyze_board, analyze_manual_board, extract_mapped_components, parse_field_quantity,
    simulate_steady_state,
)


class Footprint:
    def __init__(self, reference, fields):
        self.reference = reference
        self.fields = fields

    def GetReference(self):
        return self.reference

    def GetFieldsText(self):
        return self.fields


class Board:
    def __init__(self, footprints):
        self.footprints = footprints

    def GetFootprints(self):
        return self.footprints


class QuickThermTests(unittest.TestCase):
    def setUp(self):
        self.board = Board([
            Footprint('U1', {'Dissipation': '500mW', 'Theta JA': '40 °C/W', 'Theta JB': '10 K/W',
                             'Theta JC': '3 K/W'}),
            Footprint('U2', {'Dissipation': '1 W', 'Theta JA': '20 K/W', 'Theta JB': '5 K/W'}),
        ])
        self.map = {'power_w': 'Dissipation', 'theta_ja_air_k_per_w': 'Theta JA',
                    'theta_jb_k_per_w': 'Theta JB', 'theta_jc_k_per_w': 'Theta JC'}

    def test_air_analytical_and_energy_accounting(self):
        result = analyze_board(self.board, self.map, environment='air', ambient_c=25)
        self.assertTrue(result['coverage']['complete'])
        self.assertIsNone(result['board_c'])
        self.assertAlmostEqual(result['total_scoped_power_w'], 1.5)
        by_ref = {row['reference']: row for row in result['components']}
        self.assertAlmostEqual(by_ref['U1']['junction_c'], 45)
        self.assertAlmostEqual(by_ref['U2']['junction_c'], 45)
        json.dumps(result, allow_nan=False)

    def test_manual_inputs_screen_without_saved_thermal_fields(self):
        bare = Board([Footprint('U1', {}), Footprint('U2', {})])
        result = analyze_manual_board(bare, {
            'U1': {'power_w': '500mW', 'theta_ja_air_k_per_w': '40 K/W'},
            'U2': {'power_w': '1 W', 'theta_ja_air_k_per_w': '20 K/W'},
        }, environment='air', ambient_c=25, references=['U1', 'U2'])
        self.assertEqual(result['coverage']['solved'], 2)
        self.assertEqual({row['junction_c'] for row in result['components']}, {45})
        self.assertEqual(result['manual_values']['U1']['power_w'], .5)
        self.assertIn('Explicit values', result['input_source'])

    def test_manual_inputs_require_complete_explicit_values(self):
        bare = Board([Footprint('U1', {})])
        for values in ({}, {'U1': {'power_w': '1'}},
                       {'U1': {'power_w': 'NaN', 'theta_ja_air_k_per_w': '10'}}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                analyze_manual_board(bare, values, environment='air', ambient_c=20,
                                     references=['U1'])
        with self.assertRaisesRegex(ValueError, 'absent from saved board'):
            analyze_manual_board(bare, {'U42': {'power_w': '1',
                                 'theta_ja_air_k_per_w': '10'}}, environment='air',
                                 ambient_c=20, references=['U42'])

    def test_vacuum_shared_board_analytical_and_ranking(self):
        result = analyze_board(self.board, self.map, environment='vacuum', ambient_c=20,
                               vacuum_board_to_environment_k_per_w=30)
        self.assertAlmostEqual(result['board_c'], 65)  # 20 + (0.5 + 1) * 30
        by_ref = {row['reference']: row for row in result['components']}
        self.assertAlmostEqual(by_ref['U1']['junction_c'], 70)
        self.assertAlmostEqual(by_ref['U2']['junction_c'], 70)
        self.assertEqual(result['environment'], 'vacuum')

    def test_air_partial_coverage_is_explicit(self):
        self.board.footprints.append(Footprint('R1', {'Dissipation': 'not a number'}))
        result = analyze_board(self.board, self.map, environment='air', ambient_c=25)
        self.assertEqual(result['coverage']['solved'], 2)
        self.assertEqual(result['coverage']['scoped'], 3)
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(result['coverage']['excluded'][0]['reference'], 'R1')

    def test_vacuum_rejects_missing_power_to_avoid_underestimating_board(self):
        self.board.footprints.append(Footprint('U3', {'Theta JB': '10 K/W'}))
        with self.assertRaisesRegex(ValueError, 'complete power'):
            analyze_board(self.board, self.map, environment='vacuum', ambient_c=25,
                          vacuum_board_to_environment_k_per_w=30)
        scoped = analyze_board(self.board, self.map, environment='vacuum', ambient_c=25,
                               references=['U1', 'U2'], vacuum_board_to_environment_k_per_w=30)
        self.assertEqual(scoped['coverage']['scoped'], 2)

    def test_vacuum_requires_real_environment_sink(self):
        with self.assertRaisesRegex(ValueError, 'finite'):
            analyze_board(self.board, self.map, environment='vacuum', ambient_c=25)
        with self.assertRaisesRegex(ValueError, 'positive'):
            analyze_board(self.board, self.map, environment='vacuum', ambient_c=25,
                          vacuum_board_to_environment_k_per_w=0)

    def test_units_invalid_values_and_unknown_reference(self):
        self.assertAlmostEqual(parse_field_quantity('250 µW', 'power_w'), .00025)
        self.assertAlmostEqual(parse_field_quantity('10 °C/W', 'theta_jb_k_per_w'), 10)
        for bad in ('NaN', '-1 W', '1 A', 'infinity', '1e999 W'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_field_quantity(bad, 'power_w')
        with self.assertRaisesRegex(ValueError, 'absent'):
            extract_mapped_components(self.board, self.map, references=['U42'])
        with self.assertRaisesRegex(ValueError, 'at least'):
            simulate_steady_state([{'reference': 'U1', 'values': {'power_w': 1,
                'theta_ja_air_k_per_w': 10}}], environment='air', ambient_c=-274)

    def test_air_heatsink_independent_path_and_shape_is_visual_only(self):
        sink = {'U1': {'shape': 'straight_fin', 'width_mm': 20, 'height_mm': 12,
                       'depth_mm': 15, 'contact_k_per_w': 1,
                       'theta_sa_air_k_per_w': 8}}
        result = analyze_board(self.board, self.map, environment='air', ambient_c=25,
                               heatsinks=sink)
        by_ref = {row['reference']: row for row in result['components']}
        self.assertAlmostEqual(by_ref['U1']['junction_c'], 31)  # 25 + .5*(3+1+8)
        self.assertAlmostEqual(by_ref['U2']['junction_c'], 45)
        self.assertEqual(by_ref['U1']['heat_path'], 'heatsink')
        self.assertEqual(result['board_path_power_w'], 1)
        plate = {**sink['U1'], 'shape': 'plate', 'width_mm': 100}
        result_plate = analyze_board(self.board, self.map, environment='air', ambient_c=25,
                                     heatsinks={'U1': plate})
        self.assertAlmostEqual(result_plate['components'][0]['junction_c'],
                               result['components'][0]['junction_c'])

    def test_vacuum_heatsink_does_not_double_count_board_heat(self):
        sink = {'U1': {'shape': 'resistance_only', 'contact_k_per_w': 2,
                       'theta_sa_vacuum_k_per_w': 25}}
        result = analyze_board(self.board, self.map, environment='vacuum', ambient_c=20,
                               vacuum_board_to_environment_k_per_w=30, heatsinks=sink)
        by_ref = {row['reference']: row for row in result['components']}
        self.assertAlmostEqual(result['board_path_power_w'], 1)
        self.assertAlmostEqual(result['board_c'], 50)  # U2 alone heats shared board
        self.assertAlmostEqual(by_ref['U1']['junction_c'], 35)  # 20 + .5*(3+2+25)
        self.assertAlmostEqual(by_ref['U2']['junction_c'], 55)
        only_sink = analyze_board(self.board, {'power_w': 'Dissipation',
            'theta_jc_k_per_w': 'Theta JC'}, environment='vacuum', ambient_c=20,
            references=['U1'], heatsinks=sink)
        self.assertIsNone(only_sink['board_c'])
        self.assertAlmostEqual(only_sink['components'][0]['junction_c'], 35)

    def test_heatsink_requires_explicit_model_and_scoped_reference(self):
        base = {'shape': 'plate', 'width_mm': 10, 'height_mm': 2, 'depth_mm': 10,
                'contact_k_per_w': 1, 'theta_sa_air_k_per_w': 8}
        for change in ({'contact_k_per_w': 0}, {'theta_sa_air_k_per_w': None},
                       {'width_mm': None}, {'shape': 'unknown'}, {'depth_mm': float('nan')}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                analyze_board(self.board, self.map, environment='air', ambient_c=25,
                              heatsinks={'U1': {**base, **change}})
        with self.assertRaisesRegex(ValueError, 'absent from thermal scope'):
            analyze_board(self.board, self.map, environment='air', ambient_c=25,
                          references=['U2'], heatsinks={'U1': base})
        with self.assertRaisesRegex(ValueError, 'theta_jc'):
            analyze_board(self.board, {'power_w': 'Dissipation'}, environment='air',
                          ambient_c=25, references=['U1'], heatsinks={'U1': base})
        all_sink = analyze_board(self.board, {'power_w': 'Dissipation',
            'theta_jc_k_per_w': 'Theta JC'}, environment='air', ambient_c=25,
            references=['U1'], heatsinks={'U1': base})
        self.assertTrue(all_sink['coverage']['complete'])


if __name__ == '__main__':
    unittest.main()
