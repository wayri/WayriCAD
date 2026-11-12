"""Independent analytical/reference checks for the shared steady 3D kernel."""
import copy
import json
import inspect
import unittest
from unittest.mock import patch

import numpy as np

from wayricad_runtime.thermoelectric3d import solve_thermoelectric3d


def bar(axis="x", electrical=True):
    edges = {d: [0, 1] for d in "xyz"}
    edges[axis] = [0, 1, 2, 3]
    material = {"thermal_conductivity_w_mk": 10,
                "resistivity_ohm_m": 1e-3 if electrical else None}
    return {"schema_version": 1, "grid": {"edges_mm": edges},
            "materials": {"bar": material}, "material_ids": ["bar"]*3,
            "fixed_voltage_v": {"0": 0.1, "2": 0} if electrical else {},
            "fixed_temperature_c": {"0": 20, "2": 20},
            "settings": {"relaxation": 1, "temperature_bounds_c": [-200, 1000]}}


class Thermoelectric3DTests(unittest.TestCase):
    def _check_cg_tolerance_api(self, legacy):
        from scipy.sparse.linalg import cg as actual_cg
        from wayricad_runtime import thermoelectric3d as kernel
        actual_key = 'rtol' if 'rtol' in inspect.signature(actual_cg).parameters else 'tol'
        calls = []

        def call(a, b, x0, relative, maxiter, preconditioner, callback, atol):
            calls.append(relative)
            return actual_cg(a, b, x0=x0, **{actual_key: relative}, maxiter=maxiter,
                             M=preconditioner, callback=callback, atol=atol)

        def old_cg(A, b, x0=None, tol=1e-5, maxiter=None, M=None, callback=None, atol=None):
            return call(A, b, x0, tol, maxiter, M, callback, atol)

        def modern_cg(A, b, x0=None, *, rtol=1e-5, maxiter=None, M=None, callback=None, atol=0.):
            return call(A, b, x0, rtol, maxiter, M, callback, atol)

        request = bar()
        request['settings'].update(relaxation=.5, linear_tolerance=3e-11)
        with patch('scipy.sparse.linalg.cg', old_cg if legacy else modern_cg), \
             patch.object(kernel.inspect, 'signature', wraps=inspect.signature) as signature:
            result = solve_thermoelectric3d(request)
        signature.assert_called_once()
        self.assertGreater(len(calls), 1)
        self.assertTrue(all(value == 3e-11 for value in calls))
        self.assertAlmostEqual(result['electrical_power_w'], .005)
        self.assertTrue(result['converged'])

    def test_scipy_110_111_tol_signature(self):
        self._check_cg_tolerance_api(legacy=True)

    def test_modern_scipy_rtol_signature(self):
        self._check_cg_tolerance_api(legacy=False)

    def test_backend_typeerror_is_not_retried_as_a_compatibility_failure(self):
        calls = []

        def broken(A, b, x0=None, *, rtol=1e-5, **kwargs):
            calls.append(rtol)
            raise TypeError('backend implementation failure')

        with patch('scipy.sparse.linalg.cg', broken), \
             self.assertRaisesRegex(TypeError, 'backend implementation failure'):
            solve_thermoelectric3d(bar())
        self.assertEqual(len(calls), 1)

    def test_closed_form_ohmic_bar_each_axis(self):
        # Centre-to-centre L=2 mm, A=1 mm2, R=rho*L/A=2 ohm.
        for axis in "xyz":
            with self.subTest(axis=axis):
                result = solve_thermoelectric3d(bar(axis))
                np.testing.assert_allclose(result["potential_v"], [.1, .05, 0], atol=1e-12)
                self.assertAlmostEqual(result["terminal_current_a"]["0"], .05)
                self.assertAlmostEqual(result["electrical_power_w"], .005)
                self.assertAlmostEqual(sum(result["joule_heat_w"]), .005)
                self.assertAlmostEqual(result["heat_out_w"], .005)
                self.assertAlmostEqual(result["energy_residual_w"], 0, places=12)
                # Middle node: .0025 W / (2*.01 W/K).
                self.assertAlmostEqual(result["temperatures_c"][1], 20.125)
                np.testing.assert_allclose(np.array(result["current_density_a_m2"])[:, "xyz".index(axis)], 50000)
                json.dumps(result, allow_nan=False)

    def test_through_thickness_insulating_conduction(self):
        r = bar("z", electrical=False)
        r["fixed_temperature_c"] = {"0": 20, "2": 80}
        out = solve_thermoelectric3d(r)
        np.testing.assert_allclose(out["temperatures_c"], [20, 50, 80])
        self.assertAlmostEqual(out["fixed_temperature_heat_out_w"]["0"], .3)
        self.assertAlmostEqual(out["fixed_temperature_heat_out_w"]["2"], -.3)
        self.assertEqual(out["potential_v"], [None]*3)

    def test_nonuniform_interface_and_anisotropy(self):
        r = bar(electrical=False)
        r["grid"]["edges_mm"]["x"] = [0, 1, 3, 6]
        r["materials"]["bar"]["thermal_conductivity_w_mk"] = [2, 9, 17]
        r["materials"]["other"] = {"thermal_conductivity_w_mk": [4, 7, 11]}
        r["material_ids"] = ["bar", "other", "other"]
        r["fixed_temperature_c"] = {"0": 10, "2": 90}
        # R01=(.0005/2+.001/4)/1e-6=500 K/W;
        # R12=(.001/4+.0015/4)/1e-6=625 K/W.
        result = solve_thermoelectric3d(r)
        self.assertAlmostEqual(result["temperatures_c"][1], 10+80*500/1125)
        self.assertAlmostEqual(result["fixed_temperature_heat_out_w"]["0"], 80/1125)

    def test_electrical_material_interface(self):
        r = bar()
        r["materials"]["other"] = {"thermal_conductivity_w_mk": 20, "resistivity_ohm_m": 3e-3}
        r["material_ids"][2] = "other"
        result = solve_thermoelectric3d(r)
        # Edge resistances 1 and 2 ohm.
        self.assertAlmostEqual(result["terminal_current_a"]["0"], .1/3)
        self.assertAlmostEqual(result["potential_v"][1], .1*2/3)

    def test_seebeck_open_circuit(self):
        r = bar()
        r["materials"]["bar"]["seebeck_v_k"] = 200e-6
        r["fixed_temperature_c"] = {"0": 20, "2": 80}
        r["fixed_voltage_v"] = {"0": 0}
        result = solve_thermoelectric3d(r)
        np.testing.assert_allclose(result["potential_v"], [0, -.006, -.012], atol=1e-12)
        np.testing.assert_allclose(result["faces"]["current_a"], 0, atol=1e-14)

    def test_peltier_reversal_and_edge_energy(self):
        r = bar()
        r["materials"]["bar"]["seebeck_v_k"] = .002
        r["fixed_temperature_c"] = {str(i): 20 for i in range(3)}
        positive = solve_thermoelectric3d(r)
        r["fixed_voltage_v"]["0"] = -.1
        negative = solve_thermoelectric3d(r)
        # At the left clamp: half-edge Joule .00125 W - S*T*I.
        p = positive["fixed_temperature_heat_out_w"]["0"]
        m = negative["fixed_temperature_heat_out_w"]["0"]
        self.assertAlmostEqual(p, .00125-.002*293.15*.05)
        self.assertAlmostEqual(m, .00125+.002*293.15*.05)
        for out in (positive, negative):
            self.assertAlmostEqual(out["heat_out_w"], out["electrical_power_w"])
            self.assertAlmostEqual(out["energy_residual_w"], 0, places=12)

    def test_temperature_dependent_seebeck_energy(self):
        r = bar()
        r["fixed_temperature_c"] = {"0": 20, "1": 35, "2": 80}
        r["materials"]["bar"].update(seebeck_v_k=.001, seebeck_slope_v_k2=1e-5)
        out = solve_thermoelectric3d(r)
        self.assertAlmostEqual(out["energy_residual_w"], 0, places=12)
        self.assertNotAlmostEqual(sum(out["joule_heat_w"]), out["electrical_power_w"])

    def test_table_interpolates_not_linear_fit(self):
        r = bar()
        r["materials"]["bar"].update(temperature_factors=[[20, 1], [40, 2], [80, 8]],
                                      tcr_per_k=.9)
        r["fixed_temperature_c"] = {str(i): 60 for i in range(3)}
        out = solve_thermoelectric3d(r)
        # factor(60)=5, two edges at 5 ohm => .01 A.
        self.assertAlmostEqual(out["terminal_current_a"]["0"], .01)
        self.assertAlmostEqual(out["electrical_power_w"], .001)

    def test_tcr(self):
        r = bar()
        r["materials"]["bar"]["tcr_per_k"] = .01
        r["fixed_temperature_c"] = {str(i): 120 for i in range(3)}
        self.assertAlmostEqual(solve_thermoelectric3d(r)["terminal_current_a"]["0"], .025)

    def test_multiple_dirichlet_terminal_cells(self):
        r = bar()
        r["fixed_voltage_v"] = {}
        r["terminals"] = {"supply": {"cells": [0, 1], "voltage_v": .1},
                          "return": {"cells": [2], "voltage_v": 0}}
        out = solve_thermoelectric3d(r)
        self.assertAlmostEqual(out["terminal_currents_a"]["supply"], .1)
        self.assertAlmostEqual(sum(out["terminal_currents_a"].values()), 0)

    def test_convection_no_fixed_temperature_and_no_source(self):
        r = bar(electrical=False)
        r["fixed_temperature_c"] = {}
        r["boundary"] = {"ambient_c": 30, "h_w_m2k": 10}
        out = solve_thermoelectric3d(r)
        np.testing.assert_allclose(out["temperatures_c"], 30)

    def test_radiation_energy(self):
        r = bar(electrical=False)
        r["fixed_temperature_c"] = {}
        r["boundary"] = {"ambient_c": 20, "emissivity": .8}
        r["heat_w"] = [.001]*3
        r["settings"]["relaxation"] = .5
        out = solve_thermoelectric3d(r)
        self.assertAlmostEqual(out["heat_out_w"], .003, places=8)

    def test_void_and_true_3d_flux(self):
        r = bar(electrical=False)
        r["grid"]["edges_mm"] = {d: [0, 1, 2] for d in "xyz"}
        r["material_ids"] = ["bar"]*7+[None]
        # T = 20+x+2y+3z at centres; leave node 0 free. Its 3 neighbours
        # supply .01*(1+2+3)=.06 W, balanced by external cooling.
        r["fixed_temperature_c"] = {str(i): 20+(i % 2)+2*((i//2) % 2)+3*(i//4) for i in range(1, 7)}
        r["heat_w"] = [-.06]+[0]*7
        out = solve_thermoelectric3d(r)
        self.assertAlmostEqual(out["temperatures_c"][0], 20)
        self.assertIsNone(out["temperatures_c"][7])
        self.assertEqual(out["coordinates"]["shape_xyz"], [2, 2, 2])

    def test_no_sink_even_without_source_rejected(self):
        r = bar(electrical=False)
        r["fixed_temperature_c"] = {}
        with self.assertRaisesRegex(ValueError, "thermal.*floating"):
            solve_thermoelectric3d(r)

    def test_floating_conductor_rejected(self):
        r = bar()
        r["fixed_voltage_v"] = {}
        with self.assertRaisesRegex(ValueError, "electrical.*floating"):
            solve_thermoelectric3d(r)

    def test_disconnected_island_rejected(self):
        r = bar()
        r["material_ids"][1] = None
        r["fixed_voltage_v"] = {"0": 0}
        with self.assertRaisesRegex(ValueError, "electrical.*floating"):
            solve_thermoelectric3d(r)

    def test_cancel(self):
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            solve_thermoelectric3d(bar(), cancel=lambda: True)

    def test_nonconvergence_is_not_success(self):
        r = bar()
        r["settings"].update(max_iterations=1, relaxation=.5)
        with self.assertRaisesRegex(RuntimeError, "nonconvergence"):
            solve_thermoelectric3d(r)

    def test_invalid_input_matrix(self):
        variations = [
            ("grid", {"edges_mm": {"x": [0, 0, 2, 3], "y": [0, 1], "z": [0, 1]}}),
            ("grid", {"edges_mm": {"x": [0, float("nan")], "y": [0, 1], "z": [0, 1]}}),
            ("settings", {"max_cells": 50001}),
            ("settings", {"max_cells": 2}),
            ("settings", {"relaxation": 0}),
            ("settings", {"temperature_bounds_c": [-274, 20]}),
            ("fixed_temperature_c", {"0": -274}),
            ("fixed_temperature_c", {"0": 1001}),
            ("fixed_voltage_v", {"3": 0}),
            ("heat_w", [float("inf"), 0, 0]),
            ("boundary", {"emissivity": 1.1}),
            ("material_ids", ["bar", "missing", "bar"]),
        ]
        for key, value in variations:
            with self.subTest(key=key, value=value):
                r = bar(); r[key] = value
                with self.assertRaises(ValueError):
                    solve_thermoelectric3d(r)

    def test_material_table_and_range_rejections(self):
        cases = [
            {"temperature_factors": [[20, 1], [10, 2]]},
            {"temperature_factors": [[20, 2], [40, 3]]},
            {"temperature_factors": [[20, 1], [40, 0]]},
            {"temperature_factors": [[20, 1], [40, 2]], "material_temperature_range_c": [50, 60]},
            {"material_temperature_range_c": [30, 50]},
            {"thermal_conductivity_w_mk": 0},
            {"resistivity_ohm_m": -1},
        ]
        for material in cases:
            with self.subTest(material=material):
                r = bar(); r["materials"]["bar"].update(material)
                with self.assertRaises(ValueError):
                    solve_thermoelectric3d(r)
        r = bar()
        r["materials"]["bar"]["temperature_factors"] = [[20, 1], [40, 2]]
        r["fixed_temperature_c"]["2"] = 41
        with self.assertRaisesRegex(ValueError, "no extrapolation"):
            solve_thermoelectric3d(r)

    def test_input_not_mutated_and_aliases(self):
        r = bar()
        r["edges_mm"] = r.pop("grid")["edges_mm"]
        r["materials"]["bar"]["rho_ohm_m"] = r["materials"]["bar"].pop("resistivity_ohm_m")
        before = copy.deepcopy(r)
        solve_thermoelectric3d(r)
        self.assertEqual(r, before)

    def test_report_result_contract(self):
        r = bar()
        r.update(properties={"source": "heater"}, provenance={"material": "table"})
        out = solve_thermoelectric3d(r)
        self.assertEqual(out["grid"], r["grid"])
        self.assertEqual(out["material_ids"], r["material_ids"])
        self.assertEqual(out["temperature_c"], out["temperatures_c"])
        for key in ("temperature_c", "potential_v", "joule_heat_w", "current_density_a_m2"):
            self.assertEqual(len(out[key]), 3)
        for key, value in out["energy_balance"].items():
            self.assertEqual(value, out[key])
        json.dumps(out, allow_nan=False)

    def test_nonlinear_table_heating(self):
        r = bar()
        r["materials"]["bar"]["temperature_factors"] = [[20, 1], [40, 2], [100, 8]]
        r["settings"].update(relaxation=.5, temperature_tolerance_c=1e-10,
                             residual_tolerance_w=1e-12, linear_tolerance=1e-13)
        out = solve_thermoelectric3d(r)
        t = out["temperatures_c"][1]
        factor = 1+(t-20)/20
        resistance = .5+.5*factor
        current = .1/(2*resistance)
        # Half of each edge's I^2 R reaches the free centre.
        self.assertAlmostEqual(t, 20+current**2*resistance/.02, places=7)
        self.assertAlmostEqual(out["terminal_current_a"]["0"], current, places=10)

    def test_3d_interior_linear_manufactured_solution(self):
        shape = (5, 4, 3)
        r = bar(electrical=False)
        r["grid"]["edges_mm"] = {d: list(range(s+1)) for d, s in zip("xyz", shape)}
        r["material_ids"] = ["bar"]*60
        fixed = {}
        expected = []
        for z in range(3):
            for y in range(4):
                for x in range(5):
                    value = 20+x+2*y+3*z
                    expected.append(value)
                    if x in (0, 4) or y in (0, 3) or z in (0, 2):
                        fixed[str(z*20+y*5+x)] = value
        r["fixed_temperature_c"] = fixed
        out = solve_thermoelectric3d(r)
        np.testing.assert_allclose(out["temperatures_c"], expected, atol=1e-9)
        self.assertLess(abs(out["energy_residual_w"]), 1e-10)

    def test_oversized_grid_rejected_before_cell_allocation(self):
        r = bar()
        r["grid"]["edges_mm"] = {d: list(range(51)) for d in "xyz"}
        r["settings"]["max_cells"] = 50000
        with self.assertRaisesRegex(ValueError, "exceeds max_cells"):
            solve_thermoelectric3d(r)

    def test_malformed_containers(self):
        for key in ("settings", "grid", "materials", "boundary"):
            r = bar(); r[key] = []
            with self.subTest(key=key), self.assertRaises(ValueError):
                solve_thermoelectric3d(r)
        r = bar(); r["material_ids"][0] = {}
        with self.assertRaises(ValueError):
            solve_thermoelectric3d(r)

    def test_cancellation_during_iteration(self):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            return calls > 5

        r = bar(); r["settings"]["relaxation"] = .5
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            solve_thermoelectric3d(r, cancel)

    def test_heating_beyond_table_rejected(self):
        r = bar()
        r["materials"]["bar"]["temperature_factors"] = [[20, 1], [20.01, 2]]
        with self.assertRaisesRegex(ValueError, "no extrapolation"):
            solve_thermoelectric3d(r)

    def test_linear_iteration_cap_failure(self):
        r = bar()
        r["grid"]["edges_mm"]["x"] = list(range(6))
        r["material_ids"] = ["bar"]*5
        r["fixed_voltage_v"] = {"0": .1, "4": 0}
        r["fixed_temperature_c"] = {"0": 20, "4": 20}
        r["settings"]["max_linear_iterations"] = 1
        with self.assertRaisesRegex(RuntimeError, "linear solve failed"):
            solve_thermoelectric3d(r)

    def test_joule_profile_under_mesh_refinement(self):
        # Keep contact centres at x=0,4 mm while refining the interior.
        # J=25000 A/m2, rho=1e-3, k=10 => analytic rise qv*x*(L-x)/(2k).
        for cells in (5, 9, 17):
            with self.subTest(cells=cells):
                dx = 4/(cells-1)
                r = bar()
                r["grid"]["edges_mm"]["x"] = [(i-.5)*dx for i in range(cells+1)]
                r["material_ids"] = ["bar"]*cells
                r["fixed_voltage_v"] = {"0": .1, str(cells-1): 0}
                r["fixed_temperature_c"] = {"0": 20, str(cells-1): 20}
                out = solve_thermoelectric3d(r)
                x = np.arange(cells)*dx*.001
                expected = 20+625000*x*(.004-x)/20
                np.testing.assert_allclose(out["temperature_c"], expected, atol=1e-9)
                self.assertAlmostEqual(out["electrical_power_w"], .0025)


if __name__ == "__main__":
    unittest.main()
