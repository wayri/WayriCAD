"""Reference checks for the bounded QuickTherm thermal network."""
import unittest

from quick_pi_plugin.thermal_network import solve_thermal_network


def view(*, sink=False):
    return {
        "outline_status": "valid", "bbox_status": "verified_outline",
        "bbox_mm": [0, 0, 100, 100],
        "outline": [{"outer_mm": [[0, 0], [100, 0], [100, 100], [0, 100]], "holes_mm": []}],
        "components": [{"reference": "U1", "position_mm": [50, 50], "bbox_mm": [47, 47, 53, 53],
                        "side": "top", "on_board": True},
                       {"reference": "U2", "position_mm": [75, 75], "bbox_mm": [71, 71, 79, 79],
                        "side": "bottom", "on_board": True}],
    }


def result(*, sink=False, environment="air"):
    return {"ambient_c": 25, "environment": environment,
            "coverage": {"scoped": 2, "solved": 2, "complete": True},
            "components": [{"reference": "U1", "power_w": 1, "heat_path": "board"},
                           {"reference": "U2", "power_w": .5,
                            "heat_path": "heatsink" if sink else "board"}]}


def settings(**changes):
    return {"board_k_w_mk": 100, "board_thickness_mm": 1.6,
            "board_emissivity": .8, "board_airflow_m_s": 0,
            "sink_airflow_m_s": 0, "grid_cells_long_axis": 8, **changes}


def representative_board():
    """60 × 40 mm, three finite-size heat sources on both sides."""
    board = {"outline_status": "valid", "bbox_status": "verified_outline",
             "bbox_mm": [0, 0, 60, 40],
             "outline": [{"outer_mm": [[0, 0], [60, 0], [60, 40], [0, 40]], "holes_mm": []}],
             "components": [
                 {"reference": "U1", "position_mm": [12, 12], "bbox_mm": [9, 9, 15, 15],
                  "side": "top", "on_board": True},
                 {"reference": "U2", "position_mm": [32, 24], "bbox_mm": [29, 21, 35, 27],
                  "side": "top", "on_board": True},
                 {"reference": "U3", "position_mm": [48, 14], "bbox_mm": [44, 10, 52, 18],
                  "side": "bottom", "on_board": True}]}
    powers = [("U1", 1.0), ("U2", .6), ("U3", .4)]
    result_data = {"ambient_c": 25, "environment": "air",
                   "coverage": {"scoped": 3, "solved": 3, "complete": True},
                   "components": [{"reference": ref, "power_w": power, "heat_path": "board"}
                                  for ref, power in powers]}
    material = {"board_k_w_mk": 35, "board_thickness_mm": 1.6,
                "board_emissivity": .8, "board_airflow_m_s": 1, "sink_airflow_m_s": 0}
    return board, result_data, material


class ThermalNetworkTests(unittest.TestCase):
    def test_refinement_converges_with_footprint_heat_distribution(self):
        board, inputs, material = representative_board()
        coarse, medium, fine = [solve_thermal_network(board, inputs,
            {**material, "grid_cells_long_axis": cells}) for cells in (24, 48, 80)]
        for solved in (coarse, medium, fine):
            self.assertEqual(solved["status"], "converged")
            self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-5)
            self.assertAlmostEqual(solved["heat_balance"]["input_w"], 2.0)
            self.assertTrue(all(row["source_distribution"] == "footprint_bbox_proxy"
                                for row in solved["components"]))
        for index in range(3):
            c = coarse["components"][index]["board_site_c"]
            m = medium["components"][index]["board_site_c"]
            f = fine["components"][index]["board_site_c"]
            self.assertLess(abs(m - f), abs(c - m))
            self.assertLess(abs(m - f), .1)  # A temperature tolerance, not a field blur.
        self.assertGreater(fine["board_field"]["active_cells"], 4000)

    def test_isothermal_limit_matches_convective_energy_balance(self):
        # 100 mm square, two faces: A = 0.02 m². At 10 W/m²/K and 1.5 W,
        # the uniform-board reference is 25 + 1.5/(0.02*10) = 32.5 °C.
        solved = solve_thermal_network(view(), result(),
            settings(board_k_w_mk=1000, board_emissivity=0,
                     board_h_w_m2k=10, grid_cells_long_axis=4))
        temperatures = [value for row in solved["board_field"]["values_c"]
                        for value in row if value is not None]
        self.assertAlmostEqual(sum(temperatures) / len(temperatures), 32.5, places=3)

    def test_board_conduction_convection_radiation_and_balance(self):
        solved = solve_thermal_network(view(), result(), settings())
        self.assertEqual(solved["status"], "converged")
        self.assertGreater(solved["board_field"]["sampled_max_c"], 25)
        self.assertGreater(solved["heat_balance"]["board_convection_w"], 0)
        self.assertGreater(solved["heat_balance"]["board_radiation_w"], 0)
        self.assertAlmostEqual(solved["heat_balance"]["input_w"], 1.5)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-5)
        # Without an explicit package-to-board resistance, a board solve must
        # not claim a junction estimate from unrelated legacy RθJA values.
        self.assertIsNone(solved["components"][0]["junction_c"])

    def test_virtual_airflow_cools_board(self):
        stagnant = solve_thermal_network(view(), result(), settings(board_emissivity=0))
        flowing = solve_thermal_network(view(), result(), settings(board_emissivity=0, board_airflow_m_s=2))
        self.assertLess(flowing["board_field"]["sampled_max_c"],
                        stagnant["board_field"]["sampled_max_c"])
        self.assertAlmostEqual(flowing["heat_balance"]["board_radiation_w"], 0)

    def test_legacy_air_path_enters_board_without_reusing_rja(self):
        input_result = result()
        input_result["components"][0]["heat_path"] = "air"
        input_result["components"][0]["resistance_k_per_w"] = 99
        solved = solve_thermal_network(view(), input_result, settings())
        first = solved["components"][0]
        self.assertEqual(first["heat_path"], "board")
        self.assertEqual(first["source_heat_path"], "air")
        self.assertIsNone(first["junction_c"])
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-5)

    def test_bbox_source_spreads_heat_and_point_fallback_is_explicit(self):
        spread = solve_thermal_network(view(), result(), settings(grid_cells_long_axis=48))
        first = spread["components"][0]
        self.assertEqual(first["source_distribution"], "footprint_bbox_proxy")
        self.assertGreater(first["source_cell_count"], 1)
        self.assertAlmostEqual(first["source_overlap_area_mm2"], 36, places=8)
        self.assertLess(abs(spread["heat_balance"]["residual_w"]), 1e-5)
        no_bbox = view()
        del no_bbox["components"][0]["bbox_mm"]
        point = solve_thermal_network(no_bbox, result(), settings(grid_cells_long_axis=48))
        self.assertEqual(point["components"][0]["source_distribution"], "point_fallback")
        self.assertEqual(point["components"][0]["source_cell_count"], 1)
        self.assertLess(abs(point["heat_balance"]["residual_w"]), 1e-5)

    def test_vacuum_radiation_without_convection(self):
        solved = solve_thermal_network(view(), result(environment="vacuum"), settings())
        self.assertEqual(solved["status"], "converged")
        self.assertAlmostEqual(solved["heat_balance"]["board_convection_w"], 0)
        self.assertAlmostEqual(solved["heat_balance"]["board_radiation_w"], 1.5, places=4)
        with self.assertRaisesRegex(ValueError, "Airflow must be zero"):
            solve_thermal_network(view(), result(environment="vacuum"), settings(board_airflow_m_s=1))

    def test_sink_area_and_airflow_are_explicit(self):
        base = settings(sink_exposed_area_mm2={"U2": 10000},
                        component_to_board_k_per_w={"U1": 4},
                        component_to_sink_k_per_w={"U2": 2})
        stagnant = solve_thermal_network(view(), result(sink=True), base)
        flowing = solve_thermal_network(view(), result(sink=True),
                                        {**base, "sink_airflow_m_s": 3})
        by_ref = {row["reference"]: row for row in flowing["components"]}
        self.assertLess(by_ref["U2"]["sink_c"], stagnant["components"][1]["sink_c"])
        self.assertAlmostEqual(by_ref["U2"]["junction_c"], by_ref["U2"]["sink_c"] + 1)
        self.assertAlmostEqual(by_ref["U1"]["junction_c"], by_ref["U1"]["board_site_c"] + 4)
        self.assertGreater(flowing["heat_balance"]["sink_convection_w"], 0)
        self.assertLess(abs(flowing["heat_balance"]["residual_w"]), 1e-5)
        with self.assertRaisesRegex(ValueError, "sink_exposed_area_mm2"):
            solve_thermal_network(view(), result(sink=True), settings())

    def test_sink_only_zero_board_power_has_balanced_sink_loss(self):
        input_result = result(sink=True)
        input_result["components"] = [input_result["components"][1]]
        solved = solve_thermal_network(view(), input_result,
            settings(board_emissivity=0, board_h_w_m2k=0,
                     sink_exposed_area_mm2={"U2": 10000}))
        self.assertEqual(solved["status"], "converged")
        self.assertAlmostEqual(solved["board_field"]["sampled_min_c"], 25)
        self.assertAlmostEqual(solved["heat_balance"]["board_convection_w"], 0)
        self.assertAlmostEqual(solved["heat_balance"]["board_radiation_w"], 0)
        self.assertAlmostEqual(solved["heat_balance"]["input_w"],
                               solved["heat_balance"]["sink_convection_w"] +
                               solved["heat_balance"]["sink_radiation_w"], places=7)

    def test_requires_verified_geometry_and_heat_rejection(self):
        bad = view()
        bad["outline_status"] = "unavailable"
        with self.assertRaisesRegex(ValueError, "verified"):
            solve_thermal_network(bad, result(), settings())
        with self.assertRaisesRegex(ValueError, "no heat-rejection path"):
            solve_thermal_network(view(), result(environment="vacuum"),
                                  settings(board_emissivity=0))


if __name__ == "__main__":
    unittest.main()
