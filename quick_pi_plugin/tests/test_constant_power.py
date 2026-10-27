"""Analytical, conservative FEM and saved-native-board constant-power checks."""
import hashlib
import json
import math
import unittest

import numpy as np

from quick_pi_plugin.constant_power import high_voltage_solution, solve_power, guard
from quick_pi_plugin.live_current import live_current_eligibility
from quick_pi_plugin.service import execute, sink_requests
from quick_pi_plugin.tests.test_solver import strip
from quick_pi_plugin.tests import test_service_multisink as native_fixture


class ConstantPowerTests(unittest.TestCase):
    def test_two_roots_selects_high_voltage_low_current_branch(self):
        voltage, evidence = high_voltage_solution([10.], [[1.]], [16.])
        self.assertAlmostEqual(voltage[0], 8., 10)
        self.assertAlmostEqual(16./voltage[0], 2., 10)
        self.assertAlmostEqual(evidence['incremental_stability_margin'], .75, 10)
        self.assertNotAlmostEqual(voltage[0], 2.)

    def test_collapse_and_marginal_point_return_no_solution(self):
        for power in (25., 25.0001, 100.):
            with self.subTest(power=power), self.assertRaisesRegex(ValueError, 'collapse'):
                high_voltage_solution([10.], [[1.]], [power])
        voltage, _ = high_voltage_solution([10.], [[1.]], [24.999])
        self.assertAlmostEqual(voltage[0], (10.+math.sqrt(100.-4.*24.999))/2., 8)

    def test_coupled_ports_match_independently_constructed_high_branch(self):
        resistance = np.array([[.4, .1], [.1, .6]])
        expected = np.array([4., 3.])
        power = np.array([2., 1.])
        open_voltage = expected+resistance@(power/expected)
        voltage, evidence = high_voltage_solution(open_voltage, resistance, power)
        np.testing.assert_allclose(voltage, expected, rtol=1e-11)
        self.assertGreater(evidence['incremental_stability_margin'], 0)

    def test_invalid_demands_and_conflicting_modes_rejected(self):
        for value in (0, -1, float('nan'), float('inf'), True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sink_requests({'sink_terminal': 'U1.1', 'load_power_W': value} if value is not None else
                              {'sinks': [{'terminal':'U1.1', 'power_W':None}]})
        for row in ({'current_A':1, 'power_W':2}, {}):
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                sink_requests({'sinks':[{'terminal':'U1.1', **row}]})
        with self.assertRaisesRegex(ValueError, 'not both'):
            sink_requests({'sink_terminal':'U1.1', 'sink_current':1, 'load_power_W':2})
        for settings in ({'action':'transient'}, {'action':'electrothermal'}, {'action':'sweep'}, {'action':'ac'}, {'action':'converge'},
                         {'series':[{}]}, {'package_conduction':[{}]}, {'model_dimension':'3d'},
                         {'load_resistance_ohm':1}):
            with self.subTest(settings=settings), self.assertRaisesRegex(ValueError, 'unsupported'):
                guard({'load_power_W':2, **settings})
        for source in (0, -1, float('nan'), True):
            with self.assertRaises(ValueError):
                guard({'load_power_W':2, 'source_voltage':source})

    def test_uniform_strip_power_current_and_energy_match_closed_form(self):
        mesh, source, sink = strip()
        resistance = 1.724e-8*.01/(.001*.000035)
        voltage_source, power = 1., 20.
        expected = (voltage_source+math.sqrt(voltage_source**2-4*resistance*power))/2
        result = solve_power(mesh, source, [{'id':'load', 'nodes':sink, 'power_W':power}], source_voltage=voltage_source)
        self.assertAlmostEqual(result['sink_voltage_V'], expected, 10)
        self.assertAlmostEqual(result['sink_current_A'], power/expected, 9)
        self.assertAlmostEqual(result['total_power_W'], (power/expected)**2*resistance, 9)
        self.assertAlmostEqual(result['source_power_W'], power+result['total_power_W'], 9)
        self.assertLess(result['current_balance_error_A'], 1e-8)
        self.assertLess(result['power_balance_relative_error'], 1e-10)
        json.dumps(result, allow_nan=False)

    def test_mixed_current_power_shared_copper_and_limits(self):
        mesh, source, sink = strip()
        middle = [j*11+5 for j in range(3)]
        resistance = 1.724e-8*.01/(.001*.000035)
        current, power, vs = 2., 3., 1.
        specs = [{'id':'middle', 'nodes':middle, 'current_A':current},
                 {'id':'far', 'nodes':sink, 'power_W':power, 'min_voltage_V':.999}]
        result = solve_power(mesh, source, specs, source_voltage=vs, source_current_limit=1.)
        open_voltage = vs-current*resistance/2
        expected = (open_voltage+math.sqrt(open_voltage**2-4*resistance*power))/2
        far = power/expected
        self.assertAlmostEqual(result['sinks'][1]['voltage_V'], expected, 10)
        self.assertAlmostEqual(result['sinks'][0]['voltage_V'], vs-(far+current)*resistance/2, 10)
        self.assertAlmostEqual(result['total_power_W'], ((far+current)**2+far**2)*resistance/2, 10)
        self.assertFalse(result['feasibility']['operating_point_valid'])
        self.assertTrue(result['feasibility']['source_current_limit_exceeded'])
        self.assertFalse(result['sinks'][1]['within_voltage_limits'])
        self.assertAlmostEqual(result['sinks'][1]['delivered_power_W'], power, 10)

    def test_power_result_cannot_be_live_current_rescaled(self):
        allowed, reason = live_current_eligibility({'request':{'action':'solve', 'load_power_W':2},
            'mesh':{}, 'result':{'model':'2.5D linear triangular DC conductivity FEM'}})
        self.assertFalse(allowed)
        self.assertIn('nonlinear', reason)


@unittest.skipUnless(native_fixture.NATIVE, 'Requires native KiCad and the Quick PI scientific runtime')
class NativeConstantPowerTests(unittest.TestCase):
    setUp = native_fixture.SavedBoardMultisinkTests.setUp

    def test_native_voltage_collapse_preserves_board_and_request(self):
        request = {**self.request, 'sinks':[{'terminal':'U2.1', 'power_W':10000.}]}
        original = json.dumps(request, sort_keys=True)
        with self.assertRaisesRegex(ValueError, 'collapse'):
            execute(request)
        self.assertEqual(json.dumps(request, sort_keys=True), original)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)

    def test_native_mixed_multiple_power_and_grouped_units_preserve_board(self):
        mixed = {**self.request, 'sinks':[{'terminal':'U1.1', 'current_A':1},
                                       {'terminal':'U2.1', 'power_W':3.3}]}
        multiple = {**self.request, 'sinks':[{'terminal':'U1.1', 'power_W':1.65},
                                          {'terminal':'U2.1', 'power_W':3.3}]}
        grouped = {**self.request, 'sinks':[{'terminals':['U1.1','U2.1'], 'power_W':3.3}]}
        source_group = {**self.request, 'source_terminals':['J1.1','U1.1'],
                        'sinks':[{'terminal':'U2.1', 'power_W':3.3}]}
        source_group.pop('source_terminal')
        singular = {**self.request, 'sink_terminal':'U2.1', 'load_power_W':3.3}
        singular.pop('sinks')
        for request in (mixed, multiple, grouped, source_group, singular):
            with self.subTest(request=request):
                result = execute(request)['result']
                self.assertTrue(result['feasibility']['feasible'])
                for row in result['sinks']:
                    if 'power_W' in row:
                        self.assertAlmostEqual(row['delivered_power_W'], row['power_W'], 8)
                self.assertLess(result['power_balance_relative_error'], 1e-8)
                self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)


if __name__ == '__main__':
    unittest.main()
