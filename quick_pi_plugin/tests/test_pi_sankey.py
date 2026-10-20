"""Power diagrams preserve solved unit currents and conservative budgets."""
import copy
import math
import unittest

from quick_pi_plugin.sankey import power_graph, shared_graph, sankey_section
from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests.test_solver import strip


def bundle():
    return {'request': {'source_terminals': ['J1.1', 'J1.2'],
                        'sinks': [{'id': 'IC', 'terminals': ['U1.1', 'U1.2']}]},
            'result': {'source_voltage_V': 5., 'source_current_A': 2.,
                       'sinks': [{'id': 'IC', 'current_A': 2., 'voltage_V': 4.5}],
                       'total_power_W': 1., 'feasibility': {'feasible': True}}}


class PowerFlowTests(unittest.TestCase):
    def test_real_strip_solve_conserves_power(self):
        mesh, source, sink = strip()
        solved = solve(mesh, source, sink, source_voltage=5., sink_current=2.)
        graph = power_graph({'result': solved})
        self.assertEqual(len(graph['links']), 3)
        incoming = math.fsum(row['value'] for row in graph['links'] if row['target'] == 'distribution')
        outgoing = math.fsum(row['value'] for row in graph['links'] if row['source'] == 'distribution')
        self.assertAlmostEqual(incoming, outgoing, places=9)

    def test_multipad_units_are_not_counted_per_pad(self):
        graph = power_graph(bundle())
        self.assertEqual([r['value'] for r in graph['links']], [10., 9., 1.])
        self.assertIn('Each grouped pad unit is counted once', graph['note'])

    def test_multiple_load_powers_use_their_own_voltages(self):
        data = bundle()
        data['result']['sinks'] = [{'id': 'A', 'current_A': .5, 'voltage_V': 4.8},
                                   {'id': 'B', 'current_A': 1.5, 'voltage_V': 4.4}]
        graph = power_graph(data)
        self.assertEqual(len(graph['links']), 4)
        self.assertAlmostEqual(graph['links'][1]['value'], 2.4)
        self.assertAlmostEqual(graph['links'][2]['value'], 6.6)

    def test_missing_invalid_or_unbalanced_evidence_has_no_false_flows(self):
        for field, value in [('source_current_A', None), ('total_power_W', float('nan')),
                             ('source_voltage_V', -1), ('total_power_W', 2.),
                             ('source_current_A', True), ('source_current_A', 3.)]:
            data = bundle(); data['result'][field] = value
            with self.subTest(field=field, value=value):
                graph = power_graph(data)
                self.assertEqual(graph['links'], [])
                self.assertIn('unavailable', graph['note'])

    def test_return_only_gauge_is_not_source_power(self):
        data = bundle(); data['physical_return'] = True
        self.assertEqual(power_graph(data)['links'], [])
        self.assertIn('coupled study', power_graph(data)['note'])

    def test_infeasible_diagnostic_remains_visible(self):
        data = bundle(); data['result']['feasibility']['feasible'] = False
        self.assertIn('INFEASIBLE', power_graph(data)['note'])

    def test_shared_return_counted_once_and_not_invented_per_rail(self):
        cases = {'A': {'electrical': bundle()}, 'B': {'electrical': bundle()}}
        group = {'status': 'COMPLETED', 'supply_loss_W': 2., 'return_loss_W': .2,
                 'loads': [{'case': 'A', 'sink': 'IC', 'load_power_W': 8.9},
                           {'case': 'B', 'sink': 'IC', 'load_power_W': 8.9}]}
        graph = shared_graph(group, cases)
        self.assertEqual(len(graph['links']), 6)
        self.assertEqual(sum(n['label'] == 'Shared return loss (once)' for n in graph['nodes']), 1)
        self.assertAlmostEqual(graph['links'][-1]['value'], .2)
        rendered = sankey_section({'batch': {'cases': [dict(name=k, **v) for k, v in cases.items()],
                                            'shared_returns': [dict(name='Common ground', **group)]}})
        self.assertIn('Shared return loss (once)', rendered)
        self.assertIn('Common ground', rendered)
        bad = copy.deepcopy(group); bad['return_loss_W'] = .4
        with self.assertRaises(ValueError): shared_graph(bad, cases)

    def test_report_contains_offline_diagram_and_watt_values(self):
        html = sankey_section(bundle())
        self.assertIn('<svg', html)
        self.assertIn('Source-to-sink', html)
        self.assertIn('Total modeled loss', html)
        self.assertNotIn('<script src=', html)

    def test_many_loads_are_combined_without_losing_power(self):
        data = bundle(); data['result']['sinks'] = [
            {'id': str(i), 'current_A': .002, 'voltage_V': 4.5} for i in range(1000)]
        graph = power_graph(data)
        self.assertLess(len(graph['nodes']), 500)
        outgoing = math.fsum(row['value'] for row in graph['links'] if row['source'] == 'distribution')
        self.assertAlmostEqual(outgoing, 10.)
        self.assertTrue(any('additional loads' in n['label'] for n in graph['nodes']))

    def test_loop_includes_return_loss_and_failed_case_is_not_promoted(self):
        data = {'batch': {'cases': [{'name': 'Loop', 'status': 'COMPLETED',
                 'loop': {'current_A': 2., 'source_voltage_V': 5.,
                          'delivered_load_voltage_V': 4.4, 'total_loss_W': 1.2,
                          'status': 'COMPLETED'}}]}}
        html = sankey_section(data)
        self.assertIn('Supply and return losses', html)
        self.assertNotIn('Power flow unavailable', html)
        data['batch']['cases'][0]['status'] = 'FAILED'
        html = sankey_section(data)
        self.assertIn('Power flow unavailable: case failed', html)
        self.assertNotIn('Supply and return losses', html)

    def test_nonaccepted_hot_result_is_diagnostic_and_transient_is_not_dc(self):
        data = {'mode': 'steady', 'electrothermal': {'cold': bundle()['result'],
                'hot': bundle()['result'], 'status': 'iteration_limit'}}
        html = sankey_section(data)
        self.assertIn('Operating point not accepted', html)
        self.assertNotIn('Accepted hot', html)
        data['mode'] = 'transient'
        html = sankey_section(data)
        self.assertIn('transient stored energy', html)
        self.assertNotIn('data-probe="', html)


if __name__ == '__main__':
    unittest.main()
