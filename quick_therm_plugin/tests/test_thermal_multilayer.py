"""Conservation and geometry sensitivity checks for the multilayer screen."""
from __future__ import annotations

import copy
import unittest

from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal


def rectangle(x0=0, x1=12):
    return {"outer": [[x0, 0], [x1, 0], [x1, 12], [x0, 12]], "holes": []}


def inputs(environment="air"):
    shape = rectangle()
    geometry = {
        "outline_status": "valid", "outline": [{"outer_mm": shape["outer"], "holes_mm": []}],
        "bbox_mm": [0, 0, 12, 12],
        "layers": [
            {"id": 0, "name": "F.Cu", "z_mm": .0175, "thickness_mm": .035, "polygons_mm": [shape]},
            {"id": 31, "name": "B.Cu", "z_mm": 1.5825, "thickness_mm": .035, "polygons_mm": [shape]},
        ],
        "barrels": [], "mounting_holes": [{"id": "MH1", "x_mm": 6, "y_mm": 6, "plated": True}],
    }
    view = {"components": [{"reference": "U1", "position_mm": [6, 6],
                            "bbox_mm": [5, 5, 7, 7], "side": "top", "on_board": True}]}
    result = {"ambient_c": 20, "environment": environment,
              "components": [{"reference": "U1", "power_w": 1, "heat_path": "board"}]}
    settings = {"dielectric_k_w_mk": .3, "via_plating_mm": .025,
                "grid_cells_long_axis": 24, "board_emissivity": .85}
    return geometry, view, result, settings


class MultilayerThermalTests(unittest.TestCase):
    def test_air_energy_conservation_and_distinct_layer_field(self):
        geometry, view, result, settings = inputs()
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertEqual(solved["status"], "converged")
        self.assertEqual(len(solved["layers"]), 2)
        self.assertAlmostEqual(solved["heat_balance"]["input_w"], 1)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)
        self.assertGreater(solved["layers"][0]["sampled_max_c"],
                           solved["layers"][1]["sampled_max_c"])
        self.assertIsNone(solved["components"][0]["junction_c"])

    def test_via_reduces_hotspot_against_bottom_fixture(self):
        geometry, view, result, settings = inputs("vacuum")
        settings.update(board_emissivity=0, mount_boundaries=[
            {"id": "MH1", "side": "bottom", "temperature_c": 20, "contact_r_k_w": 0}])
        plain = solve_multilayer_thermal(geometry, view, result, settings)
        geometry["barrels"] = [{"id": "V1", "kind": "via", "net": "GND",
                                 "x_mm": 6, "y_mm": 6, "drill_mm": .3,
                                 "span_layers": [0, 31], "contact_layers": [0, 31]}]
        with_via = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertGreater(plain["components"][0]["board_site_c"],
                           with_via["components"][0]["board_site_c"])
        self.assertEqual(with_via["mesh"]["via_vertical_edges"], 1)
        self.assertAlmostEqual(with_via["mounts"][0]["heat_flux_w"], 1, places=5)
        self.assertLess(abs(with_via["heat_balance"]["residual_w"]), 1e-6)

    def test_four_layer_barrel_connects_all_adjacent_stackup_intervals(self):
        geometry, view, result, settings = inputs("vacuum")
        geometry["layers"].insert(1, {"id": 1, "name": "In1.Cu", "z_mm": .4,
                                      "thickness_mm": .035, "polygons_mm": []})
        geometry["layers"].insert(2, {"id": 2, "name": "In2.Cu", "z_mm": 1.0,
                                      "thickness_mm": .035, "polygons_mm": []})
        geometry["barrels"] = [{"id": "V1", "x_mm": 6, "y_mm": 6,
                                 "drill_mm": .3, "span_layers": [0, 1, 2, 31],
                                 "contact_layers": [0, 31]}]
        settings.update(board_emissivity=0, mount_boundaries=[
            {"id": "MH1", "side": "bottom", "temperature_c": 20, "contact_r_k_w": 0}])
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertEqual(len(solved["layers"]), 4)
        self.assertEqual(solved["mesh"]["via_vertical_edges"], 3)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)

    def test_virtual_sink_node_and_optional_board_shunt(self):
        geometry, view, result, settings = inputs()
        view["components"].append({"reference": "U2", "position_mm": [8, 8],
                                   "bbox_mm": [7, 7, 9, 9], "side": "top", "on_board": True})
        result["components"].append({"reference": "U2", "power_w": 2, "heat_path": "heatsink"})
        settings.update(sink_exposed_area_mm2={"U2": 5000}, component_to_sink_k_per_w={"U2": 2})
        independent = solve_multilayer_thermal(geometry, view, result, settings)
        sink = next(row for row in independent["components"] if row["reference"] == "U2")
        self.assertAlmostEqual(sink["junction_c"], sink["sink_c"]+4)
        self.assertGreater(independent["heat_balance"]["sink_convection_w"]+
                           independent["heat_balance"]["sink_radiation_w"], 0)
        self.assertLess(abs(independent["heat_balance"]["residual_w"]), 1e-6)
        settings["sink_to_board_k_per_w"] = {"U2": 1}
        coupled = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertLess(abs(coupled["heat_balance"]["residual_w"]), 1e-6)
        self.assertNotAlmostEqual(coupled["components"][0]["board_site_c"],
                                  independent["components"][0]["board_site_c"], places=2)

    def test_virtual_sink_requires_exposed_area(self):
        geometry, view, result, settings = inputs()
        result["components"][0]["heat_path"] = "heatsink"
        with self.assertRaisesRegex(ValueError, "sink_exposed_area_mm2"):
            solve_multilayer_thermal(geometry, view, result, settings)

    def test_sink_only_vacuum_keeps_unpowered_board_at_ambient(self):
        geometry, view, result, settings = inputs("vacuum")
        result["components"][0]["heat_path"] = "heatsink"
        settings.update(board_emissivity=0, sink_emissivity=.85,
                        sink_exposed_area_mm2={"U1": 5000},
                        component_to_sink_k_per_w={"U1": 2})
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertEqual(solved["mesh"]["unexcited_regions_anchored_at_ambient"], 1)
        self.assertAlmostEqual(solved["layers"][0]["sampled_max_c"], 20)
        self.assertGreater(solved["components"][0]["sink_c"], 20)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)

    def test_finite_contact_mount_flux_is_signed(self):
        geometry, view, result, settings = inputs("vacuum")
        settings.update(board_emissivity=0, mount_boundaries=[
            {"id": "MH1", "temperature_c": 20, "contact_r_k_w": 3}])
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertAlmostEqual(solved["mounts"][0]["heat_flux_w"], 1, places=5)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)
        settings["board_emissivity"] = .85
        settings["mount_boundaries"][0]["temperature_c"] = 400
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        # With another loss route, a hot fixture can inject heat into the board.
        self.assertLess(solved["mounts"][0]["heat_flux_w"], 0)

    def test_supersampling_does_not_bridge_separate_copper_islands(self):
        geometry, view, result, settings = inputs()
        islands = [rectangle(0, 5.8), rectangle(6.2, 12)]
        geometry["layers"][0]["polygons_mm"] = islands
        geometry["layers"][1]["polygons_mm"] = islands
        settings["copper_blur_cells"] = 1
        split = solve_multilayer_thermal(geometry, view, result, settings)
        full = copy.deepcopy(geometry)
        full["layers"][0]["polygons_mm"] = [rectangle()]
        full["layers"][1]["polygons_mm"] = [rectangle()]
        joined = solve_multilayer_thermal(full, view, result, settings)
        self.assertGreater(joined["mesh"]["copper_lateral_edges"],
                           split["mesh"]["copper_lateral_edges"])
        self.assertGreater(split["components"][0]["board_site_c"],
                           joined["components"][0]["board_site_c"])

    def test_mesh_refinement_stabilizes_source_temperature(self):
        geometry, view, result, settings = inputs()
        values = []
        for resolution in (24, 36, 48):
            settings["grid_cells_long_axis"] = resolution
            solved = solve_multilayer_thermal(geometry, view, result, settings)
            values.append(solved["components"][0]["board_site_c"])
            self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)
        self.assertLess(abs(values[2]-values[1]), abs(values[1]-values[0]))
        self.assertLess(abs(values[2]-values[1])/values[2], .01)

    def test_missing_material_and_vacuum_convection_rejected(self):
        geometry, view, result, settings = inputs("vacuum")
        del settings["dielectric_k_w_mk"]
        with self.assertRaises(ValueError):
            solve_multilayer_thermal(geometry, view, result, settings)
        settings["dielectric_k_w_mk"] = .3
        settings["board_h_w_m2k"] = 1
        with self.assertRaises(ValueError):
            solve_multilayer_thermal(geometry, view, result, settings)

    def test_npth_requires_explicit_mechanical_contact(self):
        geometry, view, result, settings = inputs("vacuum")
        geometry["mounting_holes"][0]["plated"] = False
        settings.update(board_emissivity=0, mount_boundaries=[
            {"id": "MH1", "temperature_c": 20, "contact_r_k_w": 0}])
        with self.assertRaisesRegex(ValueError, "NPTH"):
            solve_multilayer_thermal(geometry, view, result, settings)
        settings["mount_boundaries"][0]["mechanical_contact"] = True
        self.assertEqual(solve_multilayer_thermal(geometry, view, result, settings)["status"], "converged")


if __name__ == "__main__":
    unittest.main()
