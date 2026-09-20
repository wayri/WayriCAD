import json
import math
import unittest

from signal_integrity_advisor_plugin.eye_model import _prbs7, simulate_eye


class EyeModelTests(unittest.TestCase):
    def run_eye(self, **changes):
        inputs = dict(z0_ohm=50, delay_ns=1, source_ohm=50, load_ohm=None,
                      rise_ns=.1, bitrate_mbps=1000, swing_v=1)
        inputs.update(changes)
        return simulate_eye(**inputs)

    def step_at(self, result, t):
        step = result['step_response']
        index = min(range(len(step['time_ns'])), key=lambda i: abs(step['time_ns'][i] - t))
        self.assertAlmostEqual(step['time_ns'][index], t)
        return step['voltage_v'][index]

    def test_source_matched_open_load_receives_full_swing(self):
        result = self.run_eye()
        self.assertEqual(result['echo_count'], 1)
        self.assertAlmostEqual(result['center_opening_v'], 1)
        self.assertAlmostEqual(result['min_v'], 0)
        self.assertAlmostEqual(result['max_v'], 1)
        self.assertAlmostEqual(result['step_response']['voltage_v'][-1], 1)
        self.assertEqual(result['time_ui'][0], 0)
        self.assertEqual(result['time_ui'][-1], 2)
        self.assertEqual(len(result['traces_v']), 127)
        json.dumps(result, allow_nan=False)

    def test_double_termination_halves_thevenin_voltage(self):
        result = self.run_eye(load_ohm=50)
        self.assertAlmostEqual(result['center_opening_v'], .5)
        self.assertAlmostEqual(result['step_response']['voltage_v'][-1], .5)

    def test_short_load_has_zero_voltage(self):
        result = self.run_eye(load_ohm=0, source_ohm=20)
        self.assertEqual(result['center_opening_v'], 0)
        self.assertTrue(all(value == 0 for value in result['step_response']['voltage_v']))

    def test_bounce_steps_match_analytic_reflections(self):
        result = self.run_eye(source_ohm=25)
        ramp = result['ramp_duration_ns']
        self.assertAlmostEqual(result['source_reflection'], -1/3)
        self.assertAlmostEqual(self.step_at(result, 1 + ramp), 4/3)
        self.assertAlmostEqual(self.step_at(result, 3 + ramp), 8/9)
        self.assertAlmostEqual(self.step_at(result, 5 + ramp), 28/27)
        self.assertLess(abs(result['step_response']['voltage_v'][-1] - 1), result['truncation_bound_v'] + 1e-14)

    def test_resistive_dc_limit_is_voltage_divider(self):
        result = self.run_eye(source_ohm=20, load_ohm=100)
        self.assertAlmostEqual(result['step_response']['voltage_v'][-1], 100/120, delta=1e-7)

    def test_rise_definition_and_causality(self):
        result = self.run_eye(rise_ns=.8)
        self.assertEqual(result['ramp_duration_ns'], 1)
        self.assertEqual(self.step_at(result, 1), 0)
        self.assertEqual(self.step_at(result, 2), 1)
        self.assertAlmostEqual(result['center_opening_v'], 0, places=10)
        self.assertTrue(all(v == 0 for t, v in zip(result['step_response']['time_ns'], result['step_response']['voltage_v']) if t < 1))

    def test_pattern_period_balance_and_continuity(self):
        bits = _prbs7()
        self.assertEqual(sum(bits), 64)
        self.assertEqual(len({tuple((bits+bits)[i:i+7]) for i in range(127)}), 127)
        result = self.run_eye(source_ohm=30, delay_ns=.37)
        for index, trace in enumerate(result['traces_v']):
            self.assertAlmostEqual(trace[64], result['traces_v'][(index+1)%127][0], places=10)
            self.assertAlmostEqual(trace[128], result['traces_v'][(index+2)%127][0], places=10)

    def test_ideal_match_delay_changes_alignment_not_opening(self):
        for delay in (.1, 10):
            self.assertAlmostEqual(self.run_eye(delay_ns=delay)['center_opening_v'], 1, places=9)

    def test_nondecaying_and_unbounded_work_rejected(self):
        for changes in ({'source_ohm': 0}, {'source_ohm': 0, 'load_ohm': 0},
                        {'source_ohm': .000001}, {'delay_ns': 101}, {'rise_ns': 9}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.run_eye(**changes)

    def test_invalid_numbers_rejected(self):
        for key in ('z0_ohm', 'delay_ns', 'source_ohm', 'load_ohm', 'rise_ns', 'bitrate_mbps', 'swing_v'):
            for value in (-1, math.nan, math.inf, 'invalid'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.run_eye(**{key: value})

    def test_scale_is_linear(self):
        base = self.run_eye(source_ohm=30, delay_ns=.7)
        scaled = self.run_eye(source_ohm=30, delay_ns=.7, swing_v=3.3)
        self.assertAlmostEqual(scaled['center_opening_v'], 3.3 * base['center_opening_v'])
        self.assertAlmostEqual(scaled['max_v'], 3.3 * base['max_v'])

    def test_extreme_values_have_actionable_bounds(self):
        for changes in ({'swing_v':1e308},{'delay_ns':1e307},
                        {'rise_ns':1e306},{'bitrate_mbps':1e-304},
                        {'source_ohm':1e300}):
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'must be|must not'):
                self.run_eye(**changes)


if __name__ == '__main__':
    unittest.main()
