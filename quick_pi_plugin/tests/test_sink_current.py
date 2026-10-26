"""Independent sink updates retain other demands and recompute shared fields."""
import copy
import unittest
from unittest.mock import patch

from quick_pi_plugin.sink_current import SinkCurrentModel
from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests import test_multisink_solver


def fixture():
    helper = test_multisink_solver.MultisinkSolverTests()
    mesh, source, sinks = helper.parallel()
    mesh['terminal_nodes'] = {'src': source, 'a': sinks[0], 'b': sinks[1]}
    geometry = {'net': 'rail', 'terminals': [
        {'id': key, 'label': key, 'net': 'rail'} for key in ('src', 'a', 'b')]}
    mesh['geometry'] = geometry
    request = {'action': 'solve', 'net': 'rail', 'source_terminal': 'src',
               'source_voltage': 3.3, 'sinks': [
                   {'terminal': 'a', 'current_A': 1., 'min_voltage_V': 3.2},
                   {'terminal': 'b', 'current_A': 2.}],
               'options': {'pulse_duration_s': .01}}
    result = solve(mesh, source, source_voltage=3.3, sinks=helper.specs(sinks),
                   options=request['options'])
    # Match saved-terminal identities rather than the helper's numeric IDs.
    for row, key in zip(result['sinks'], ('a', 'b')):
        row['id'] = row['label'] = key
    return dict(mesh=mesh, geometry=geometry, request=request, result=result)


class SinkCurrentTests(unittest.TestCase):
    def test_one_sink_changes_others_retained_and_losses_resolved(self):
        base = fixture()
        before = copy.deepcopy(base['request'])
        model = SinkCurrentModel(base)
        with patch('quick_pi_plugin.mesh.build_mesh', side_effect=AssertionError('remesh')):
            changed = model.update([3., 2.])
        result = changed['result']
        resistance = 1.724e-8 * .01 / (.001 * .000035)
        self.assertEqual([r['current_A'] for r in result['sinks']], [3., 2.])
        self.assertAlmostEqual(result['total_power_W'], 13 * resistance, 11)
        self.assertAlmostEqual(result['sinks'][1]['voltage_V'], base['result']['sinks'][1]['voltage_V'], 11)
        self.assertLess(result['energy_relative_error'], 1e-9)
        self.assertIs(changed['mesh'], base['mesh'])
        self.assertEqual(base['request'], before)
        self.assertEqual([r['current_A'] for r in changed['terminal_units']['loads']], [3., 2.])

    def test_shared_sheet_voltage_redistributes_without_changing_other_demand(self):
        from quick_pi_plugin.tests.test_solver import strip
        mesh, source, edge = strip(length=20, width=2, nx=10, ny=4)
        electrodes = [edge[:2], edge[-2:]]
        mesh['terminal_nodes'] = {'src': source, 'a': electrodes[0], 'b': electrodes[1]}
        geometry = {'net': 'rail', 'terminals': [
            {'id': name, 'label': name} for name in ('src', 'a', 'b')]}
        request = {'action': 'solve', 'net': 'rail', 'source_terminal': 'src', 'source_voltage': 3.3,
                   'sinks': [{'terminal':'a','current_A':1.}, {'terminal':'b','current_A':2.}]}
        loads = [dict(nodes=nodes, id=name, current_A=value) for nodes,name,value in zip(electrodes,('a','b'),(1.,2.))]
        initial = solve(mesh, source, sinks=loads, source_voltage=3.3)
        original_mesh = copy.deepcopy(mesh)
        updated = SinkCurrentModel(dict(mesh=mesh, geometry=geometry, request=request, result=initial)).update([3.,2.])['result']
        self.assertEqual(updated['sinks'][1]['current_A'],2.)
        self.assertLess(updated['sinks'][1]['voltage_V'],initial['sinks'][1]['voltage_V'])
        self.assertLess(updated['energy_relative_error'],1e-9)
        self.assertEqual(mesh,original_mesh)

    def test_invalid_vectors_do_not_solve(self):
        model = SinkCurrentModel(fixture())
        for values in ([1.], [True, 2.], [float('nan'), 2.], [0., 2.], [-1., 2.]):
            with self.subTest(values=values), patch('quick_pi_plugin.solver.solve') as solver:
                with self.assertRaises(ValueError):
                    model.update(values)
                solver.assert_not_called()

    def test_unsupported_temperature_feedback_not_admitted(self):
        base = fixture()
        base['electrothermal'] = {}
        with self.assertRaises(ValueError):
            SinkCurrentModel(base)
