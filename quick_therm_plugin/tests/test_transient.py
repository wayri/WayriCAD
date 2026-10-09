"""Analytical and rejection checks for independent thermal RC transients."""
import copy
import json
import math
import unittest
from unittest.mock import patch

from quick_therm_plugin.transient import solve_transient, TransientCancelled


def request(**changes):
    result = {"duration_s": 100., "step_s": 17., "ambient_c": 25.,
              "components": [{"reference": "U1", "initial_power_W": 0.,
                              "step_power_W": 2., "step_time_s": 0.,
                              "resistance_K_W": 10., "capacitance_J_K": 5.}]}
    result.update(changes)
    return result


class ThermalTransientTests(unittest.TestCase):
    def test_heating_matches_rc_analytical_response_and_endpoint(self):
        result = solve_transient(request())
        row = result["components"][0]
        self.assertEqual(row["id"], "U1")
        self.assertEqual(row["reference"], "U1")
        self.assertEqual(row["time_constant_s"], 50.)
        self.assertEqual(result["times_s"], [0., 17., 34., 51., 68., 85., 100.])
        for t, temperature in zip(result["times_s"], row["temperature_c"]):
            self.assertAlmostEqual(temperature, 25. + 20. * (1 - math.exp(-t / 50)), places=12)
        self.assertEqual(row["power_W"], [2.] * len(result["times_s"]))
        self.assertEqual(row["peak_time_s"], 100.)
        self.assertEqual(row["final_temperature_c"], row["temperature_c"][-1])
        self.assertIsNone(result["limits"]["within_all_specified_limits"])
        self.assertIn("no whole-board", result["notice"])
        json.dumps(result, allow_nan=False)

    def test_non_grid_event_is_exact_and_temperature_continuous(self):
        study = request(duration_s=30., step_s=5., ambient_c=20., initial_temperature_c=30.)
        study["components"][0].update(initial_power_W=1., step_power_W=3., step_time_s=7.3,
                                       resistance_K_W=5., capacitance_J_K=2.)
        result = solve_transient(study)
        row = result["components"][0]
        self.assertIn(7.3, result["times_s"])
        index = result["times_s"].index(7.3)
        event_temperature = 25. + 5. * math.exp(-7.3 / 10.)
        self.assertAlmostEqual(row["temperature_c"][index], event_temperature, places=12)
        self.assertEqual(row["power_W"][index - 1], 1.)
        self.assertEqual(row["power_W"][index], 3.)
        expected_final = 35. + (event_temperature - 35.) * math.exp(-(30. - 7.3) / 10.)
        self.assertAlmostEqual(row["final_temperature_c"], expected_final, places=12)

    def test_cooling_matches_analytical_tail_and_signed_energy(self):
        study = request(ambient_c=20., initial_temperature_c=100.)
        study["components"][0].update(step_power_W=0., resistance_K_W=2., capacitance_J_K=4.)
        result = solve_transient(study)
        row = result["components"][0]
        for t, temperature in zip(result["times_s"], row["temperature_c"]):
            self.assertAlmostEqual(temperature, 20. + 80. * math.exp(-t / 8.), places=12)
        energy = row["energy_balance"]
        self.assertEqual(energy["input_J"], 0.)
        self.assertAlmostEqual(energy["to_ambient_J"], 320. * (1 - math.exp(-12.5)), places=11)
        self.assertLess(energy["stored_change_J"], 0.)
        self.assertLess(abs(energy["relative_residual"]), 1e-14)
        self.assertEqual(row["peak_temperature_c"], 100.)
        self.assertEqual(row["peak_time_s"], 0.)

    def test_initial_temperature_below_ambient_has_inward_heat(self):
        study = request(initial_temperature_c=10.)
        study["components"][0]["step_power_W"] = 0.
        result = solve_transient(study)
        energy = result["energy_balance"]
        self.assertLess(energy["to_ambient_J"], 0.)
        self.assertGreater(energy["stored_change_J"], 0.)
        self.assertAlmostEqual(energy["to_ambient_J"] + energy["stored_change_J"], 0., places=11)

    def test_event_peak_and_limit_are_found_with_a_coarse_output_step(self):
        study = request(duration_s=100., step_s=30., ambient_c=20.)
        study["components"][0].update(initial_power_W=2., step_power_W=0., step_time_s=3.1,
                                       capacitance_J_K=1., limit_c=25.)
        result = solve_transient(study)
        row = result["components"][0]
        expected_peak = 20. + 20. * (1 - math.exp(-.31))
        self.assertAlmostEqual(row["peak_temperature_c"], expected_peak, places=12)
        self.assertEqual(row["peak_time_s"], 3.1)
        self.assertTrue(row["limit_exceeded"])
        self.assertEqual(result["limits"], {"evaluated_components": 1, "exceeded_components": ["U1"],
                                            "within_all_specified_limits": False})
        study["components"][0]["limit_c"] = row["peak_temperature_c"]
        self.assertFalse(solve_transient(study)["components"][0]["limit_exceeded"])

    def test_multiple_components_are_independent_and_events_share_one_grid(self):
        study = request(duration_s=1., step_s=.1)
        row = study["components"][0]
        row.update(id="first", step_time_s=.3, limit_c=100.)
        second = {**row, "id": "second", "reference": "U2", "step_time_s": .7,
                  "step_power_W": 3., "resistance_K_W": 20., "capacitance_J_K": 1.}
        study["components"].append(second)
        result = solve_transient(study)
        self.assertIn(.3, result["times_s"])
        self.assertIn(.7, result["times_s"])
        self.assertFalse(any(0 < b - a < 1e-15 for a, b in zip(result["times_s"], result["times_s"][1:])))
        for source, solved in zip(study["components"], result["components"]):
            singleton = solve_transient({**study, "components": [source]})
            self.assertEqual(solved["final_temperature_c"], singleton["components"][0]["final_temperature_c"])
        self.assertAlmostEqual(result["energy_balance"]["input_J"], 2 * .7 + 3 * .3)
        self.assertEqual(result["limits"]["evaluated_components"], 2)
        self.assertTrue(result["limits"]["within_all_specified_limits"])

    def test_refining_output_step_does_not_change_solution_or_energy(self):
        coarse = request(duration_s=4.9, step_s=.7)
        coarse["components"][0]["step_time_s"] = 1.4
        fine = {**coarse, "step_s": .35}
        left, right = solve_transient(coarse), solve_transient(fine)
        fine_values = dict(zip(right["times_s"], right["components"][0]["temperature_c"]))
        for t, temperature in zip(left["times_s"], left["components"][0]["temperature_c"]):
            match = min(fine_values, key=lambda sample: abs(sample - t))
            self.assertLess(abs(match - t), 1e-14)
            self.assertAlmostEqual(temperature, fine_values[match], places=13)
        self.assertEqual(left["energy_balance"], right["energy_balance"])
        self.assertEqual(left["components"][0]["peak_temperature_c"], right["components"][0]["peak_temperature_c"])
        self.assertTrue(left["numerics"]["step_is_output_sampling"])
        self.assertTrue(left["numerics"]["event_times_included"])

    def test_energy_matches_independent_simpson_integration(self):
        study = request(duration_s=40., step_s=7., ambient_c=20., initial_temperature_c=35.)
        study["components"][0].update(initial_power_W=1., step_power_W=4., step_time_s=13.,
                                       resistance_K_W=3., capacitance_J_K=7.)
        result = solve_transient(study)
        at_event = 23. + 12. * math.exp(-13 / 21.)
        def temperature(t):
            return 23. + 12. * math.exp(-t / 21.) if t <= 13 else 32. + (at_event - 32.) * math.exp(-(t - 13) / 21.)
        def integrate(a, b):
            count = 2000
            step = (b - a) / count
            values = [(temperature(a + i * step) - 20.) / 3. for i in range(count + 1)]
            return step / 3 * (values[0] + values[-1] + 4 * math.fsum(values[1:-1:2]) + 2 * math.fsum(values[2:-1:2]))
        energy = result["energy_balance"]
        self.assertAlmostEqual(energy["to_ambient_J"], integrate(0, 13) + integrate(13, 40), places=10)
        self.assertEqual(energy["input_J"], 13. + 4. * 27.)
        self.assertAlmostEqual(energy["stored_change_J"], 7 * (temperature(40.) - 35.), places=12)
        self.assertLess(abs(energy["relative_residual"]), 1e-13)

    def test_short_heating_and_long_cooling_remain_numerically_stable(self):
        study = request(duration_s=1e-9, step_s=1e-9, ambient_c=0.)
        study["components"][0].update(resistance_K_W=1., capacitance_J_K=1.)
        row = solve_transient(study)["components"][0]
        self.assertAlmostEqual(row["final_temperature_c"] / (2e-9), 1., places=8)
        self.assertAlmostEqual(row["energy_balance"]["to_ambient_J"] / 1e-18, 1., places=8)
        study.update(duration_s=40., step_s=40., initial_temperature_c=100.)
        study["components"][0]["step_power_W"] = 0.
        row = solve_transient(study)["components"][0]
        self.assertGreater(row["final_temperature_c"], 0.)
        self.assertAlmostEqual(row["final_temperature_c"] / (100 * math.exp(-40)), 1., places=14)

    def test_power_step_at_duration_and_step_larger_than_duration(self):
        study = request(duration_s=10., step_s=20.)
        study["components"][0]["step_time_s"] = 10.
        result = solve_transient(study)
        self.assertEqual(result["times_s"], [0., 10.])
        self.assertEqual(result["components"][0]["temperature_c"], [25., 25.])
        self.assertEqual(result["components"][0]["power_W"], [0., 2.])
        self.assertEqual(result["energy_balance"]["input_J"], 0.)

    def test_request_is_not_mutated(self):
        study = request()
        original = copy.deepcopy(study)
        solve_transient(study)
        self.assertEqual(study, original)

    def test_explicit_capacity_and_unambiguous_fields_are_required(self):
        for change in ({"capacitance_J_K": None}, {"shared_board": True}, {"reference": ""},
                       {"capacitance_J_K": 0.}, {"resistance_K_W": -1.}, {"step_time_s": 101.}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                study = request();study["components"][0].update(change);solve_transient(study)
        study = request();study["components"][0].pop("capacitance_J_K")
        with self.assertRaisesRegex(ValueError, "capacitance"):
            solve_transient(study)
        with self.assertRaises(ValueError):
            solve_transient(request(board_model=True))
        study = request();study["components"][0].pop("reference")
        with self.assertRaises(ValueError):
            solve_transient(study)

    def test_duplicates_are_rejected_and_id_only_is_canonical(self):
        study = request();study["components"][0] = {**study["components"][0], "id": "pad-uuid"}
        row = study["components"][0]
        for second in ({**row, "reference": "U2"}, {**row, "id": "different"}):
            with self.subTest(second=second), self.assertRaisesRegex(ValueError, "unique"):
                solve_transient({**study, "components": [row, second]})
        row.pop("reference")
        self.assertEqual(solve_transient(study)["components"][0]["reference"], "pad-uuid")

    def test_finite_values_physical_temperatures_and_nonnegative_power(self):
        for key in ("duration_s", "step_s", "ambient_c", "initial_temperature_c"):
            for invalid in (None, float("nan"), float("inf"), True):
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                    solve_transient(request(**{key: invalid}))
        for key in ("resistance_K_W", "capacitance_J_K", "initial_power_W", "step_power_W", "step_time_s", "limit_c"):
            for invalid in (float("nan"), float("inf"), True):
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                    study = request();study["components"][0][key] = invalid;solve_transient(study)
        for change in ({"ambient_c": -274.}, {"initial_temperature_c": -274.}, {"duration_s": 0.}, {"step_s": 0.}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                solve_transient(request(**change))
        for change in ({"initial_power_W": -1.}, {"step_power_W": -1.}, {"step_time_s": -1.}, {"limit_c": -274.}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                study = request();study["components"][0].update(change);solve_transient(study)

    def test_extreme_units_cannot_return_nonfinite_or_unresolved_results(self):
        for change in ({"resistance_K_W": 1e300, "capacitance_J_K": 1e300},
                       {"resistance_K_W": 1e-300, "capacitance_J_K": 1e-300},
                       {"resistance_K_W": 1e300, "step_power_W": 1e300},
                       {"resistance_K_W": 1., "step_power_W": 1e308}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                study = request(ambient_c=0.);study["components"][0].update(change);solve_transient(study)
        study = request(duration_s=1e-300, step_s=1e-300)
        study["components"][0].update(resistance_K_W=1e300, capacitance_J_K=1., step_power_W=0.)
        with self.assertRaisesRegex(ValueError, "resolution"):
            solve_transient(study)

    def test_resource_limits_are_enforced_before_trace_allocation(self):
        with self.assertRaisesRegex(ValueError, "365 days"):
            solve_transient(request(duration_s=365 * 86400 + 1))
        with self.assertRaisesRegex(ValueError, "samples"):
            solve_transient(request(duration_s=10., step_s=1e-300))
        with patch('quick_therm_plugin.transient.MAX_COMPONENTS', 1), self.assertRaisesRegex(ValueError, "components"):
            row = request()["components"][0]
            solve_transient(request(components=[row, {**row, "reference": "U2"}]))
        with patch('quick_therm_plugin.transient.MAX_COMPONENT_SAMPLES', 5), self.assertRaisesRegex(ValueError, "component/time pairs"):
            solve_transient(request())
        with patch('quick_therm_plugin.transient.MAX_SAMPLES', 6), self.assertRaisesRegex(ValueError, "including power events"):
            row = request()["components"][0]
            solve_transient(request(duration_s=4., step_s=1., components=[
                {**row, "step_time_s": .3}, {**row, "reference": "U2", "step_time_s": .7}]))
        with self.assertRaises(ValueError):
            solve_transient(request(components=[]))

    def test_cancellation_before_and_during_computation_discards_partial_output(self):
        with self.assertRaises(TransientCancelled):
            solve_transient(request(), cancel=lambda: True)
        calls = []
        def cancel():
            calls.append(1)
            return len(calls) >= 6
        with self.assertRaises(TransientCancelled):
            solve_transient(request(duration_s=1000., step_s=1.), cancel=cancel)
        self.assertEqual(len(calls), 6)
        with self.assertRaisesRegex(ValueError, "callable"):
            solve_transient(request(), cancel=True)


if __name__ == '__main__':
    unittest.main()
