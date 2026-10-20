"""Dissipation diagrams preserve known source watts and coverage gaps."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from quick_therm_plugin.sankey import thermal_sankey_data, thermal_sankey_html, write_sankey
from quick_therm_plugin.report import write_diagnostic_report


def bundle():
    return {'quick_therm': {'model': 'Test thermal screen', 'environment': 'air',
            'ambient_c': 25., 'assumptions': [], 'board_c': None,
            'coverage': {'scoped': 4, 'solved': 3,
                         'excluded': [{'reference': 'U4', 'issues': ['missing power']}]},
            'components': [{'reference': 'U1', 'power_w': 2., 'junction_c': 45.,
                            'resistance_k_per_w': 10., 'rise_above_ambient_k': 20., 'heat_path': 'air'},
                           {'reference': 'U2', 'power_w': 1., 'junction_c': 35.,
                            'resistance_k_per_w': 10., 'rise_above_ambient_k': 10., 'heat_path': 'air'},
                           {'reference': 'U3', 'power_w': 0., 'junction_c': 25.,
                            'resistance_k_per_w': 10., 'rise_above_ambient_k': 0., 'heat_path': 'air'}]}}


class ThermalSankeyTests(unittest.TestCase):
    def test_standalone_export_protects_source_and_rejects_stale_board(self):
        with tempfile.TemporaryDirectory() as directory:
            board = Path(directory) / 'board.kicad_pcb'
            board.write_bytes(b'reviewed board')
            value = bundle()
            value.update(source_sha256=hashlib.sha256(board.read_bytes()).hexdigest(),
                         request={'board_path': str(board)})
            output = Path(directory) / 'flow.html'
            write_sankey(output, value)
            before = output.read_bytes()
            board.write_bytes(b'changed board')
            with self.assertRaises(ValueError):
                write_sankey(output, value)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(board.read_bytes(), b'changed board')

    def test_known_watts_are_conserved_left_to_right_and_zero_is_explicit(self):
        data = thermal_sankey_data(bundle())
        self.assertEqual(data['total_w'], 3.)
        self.assertEqual(sum(link['value'] for link in data['links']), 3.)
        self.assertTrue(all(link['target'] == 'total' for link in data['links']))
        self.assertEqual(data['zero_power'], ['U3'])
        self.assertIn('U4: missing power', data['omitted'])

    def test_joule_sources_count_once_without_contact_flow_or_binding_aggregate(self):
        value = bundle()
        value['thermal_network'] = {
            'components': [{'reference': 'U1', 'power_w': 4.}],
            'copper_loss_sources': [{'id': 'plane', 'power_w': .2},
                                    {'id': 'barrel', 'power_w': .1}],
            'package_joule_sources': [{'id': 'lead', 'power_w': .05}],
            'heat_balance': {'input_w': 5.35, 'component_input_w': 5.,
                             'copper_loss_input_w': .3, 'package_joule_input_w': .05},
            'package_conduction': [{'heat_flow_to_board_w': 4.05, 'electrical_joule_heat_w': .05}]}
        value['request'] = {'copper_loss_binding': {'input_w': .35}}
        saved = copy.deepcopy(value)
        data = thermal_sankey_data(value)
        self.assertAlmostEqual(data['total_w'], 5.35)
        self.assertEqual(len(data['links']), 5)
        self.assertEqual(value, saved)

    def test_invalid_and_duplicate_sources_remain_unresolved(self):
        value = bundle()
        value['quick_therm']['components'] = [
            {'reference': 'U1', 'power_w': 1.}, {'reference': 'U1', 'power_w': 1.},
            {'reference': 'U2', 'power_w': float('nan')}, {'reference': 'U3', 'power_w': -1.},
            {'reference': 'U5', 'power_w': True}]
        value['thermal_network'] = {'copper_loss_sources': [
            {'id': 'same', 'power_w': 1.}, {'id': 'same', 'power_w': 1.}]}
        data = thermal_sankey_data(value)
        self.assertEqual(data['total_w'], 0.)
        self.assertEqual(data['links'], [])
        self.assertTrue(any('ambiguous' in item for item in data['omitted']))
        self.assertTrue(any('invalid' in item for item in data['omitted']))

    def test_offline_html_report_and_native_open_document_have_sankey(self):
        value = bundle()
        value['quick_therm']['coverage']['excluded'][0]['reference'] = '<script>bad()</script>'
        with tempfile.TemporaryDirectory() as directory:
            standalone = write_sankey(Path(directory) / 'flow.html', value).read_text(encoding='utf-8')
            report = write_diagnostic_report(Path(directory) / 'thermal.html', value)
            exported = Path(report['html']).read_text(encoding='utf-8')
        for document in (standalone, exported):
            self.assertIn('Thermal dissipation', document)
            self.assertIn('Total known dissipation: 3 W', document)
            self.assertIn('total incomplete', document)
            self.assertIn('U3', document)
            self.assertNotIn('<script>bad()</script>', document)
            self.assertIn('<svg', document)

    def test_no_sources_is_not_a_claim_of_zero_board_power(self):
        data = thermal_sankey_data({'quick_therm': {'coverage': {'excluded': [
            {'reference': 'U1', 'issues': ['missing power']}]}}})
        self.assertEqual(data['links'], [])
        self.assertEqual(data['omitted'], ['U1: missing power'])

    def test_dense_board_diagram_groups_without_losing_source_details(self):
        value = bundle()
        value['quick_therm']['components'] = [
            {'reference': 'R' + str(index), 'power_w': .01} for index in range(600)]
        self.assertAlmostEqual(thermal_sankey_data(value)['total_w'], 6.)
        document = thermal_sankey_html(value)
        self.assertIn('Other known sources (570)', document)
        self.assertIn('R599', document)
        self.assertIn('All known nonzero heat sources (W)', document)


if __name__ == '__main__':
    unittest.main()
