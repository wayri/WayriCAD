"""Conservation and geometry sensitivity checks for the multilayer screen."""
from __future__ import annotations

import copy
import math
import unittest

from quick_therm_plugin.thermal_multilayer import (
    solve_multilayer_thermal, solve_multilayer_thermal_convergence,
)


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
    def test_narrow_copper_strip_survives_half_cell_phase_shift(self):
        geometry, view, result, settings = inputs()
        settings.update(board_h_w_m2k=50, board_emissivity=0, copper_blur_cells=1)
        counts = []
        for center_y in (6, 6.25):
            shifted = copy.deepcopy(geometry)
            strip = {"outer": [[0, center_y-.03], [12, center_y-.03],
                               [12, center_y+.03], [0, center_y+.03]], "holes": []}
            for layer in shifted["layers"]:
                layer["polygons_mm"] = [strip]
            solved = solve_multilayer_thermal(shifted, view, result, settings)
            counts.append(solved["mesh"]["copper_lateral_edges"])
            self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)
        self.assertGreater(min(counts), 0)

    def test_source_aligned_refinement_resolves_small_footprint_and_balances(self):
        geometry, view, result, settings = inputs()
        view["components"][0]["bbox_mm"] = [6.18, 6.18, 6.32, 6.32]
        coarse = solve_multilayer_thermal(geometry, view, result, settings)
        settings["source_refinement_factor"] = 2
        refined = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertGreater(refined["components"][0]["source_cells"],
                           coarse["components"][0]["source_cells"])
        self.assertGreater(refined["mesh"]["active_cells_per_layer"],
                           coarse["mesh"]["active_cells_per_layer"])
        self.assertLess(abs(refined["heat_balance"]["residual_w"]), 1e-6)

    def test_mesh_acceptance_rejects_change_and_underresolved_source(self):
        geometry, view, result, settings = inputs()
        acceptance = {"grid_cells_long_axis": [24, 48],
                      "maximum_change_c": 0, "minimum_source_cells": 1}
        output = solve_multilayer_thermal_convergence(
            geometry, view, result, settings, acceptance)
        self.assertEqual(output["mesh_acceptance"]["status"], "FAIL")
        self.assertGreater(output["mesh_acceptance"]["maximum_change_c"], 0)
        acceptance["maximum_change_c"] = 1e9
        acceptance["minimum_source_cells"] = 1000
        output = solve_multilayer_thermal_convergence(
            geometry, view, result, settings, acceptance)
        self.assertEqual(output["mesh_acceptance"]["status"], "FAIL")
        self.assertEqual(output["mesh_acceptance"]["underresolved_sources"], ["U1"])
        acceptance["minimum_source_cells"] = 1
        output = solve_multilayer_thermal_convergence(
            geometry, view, result, settings, acceptance)
        self.assertEqual(output["mesh_acceptance"]["status"], "PASS")
        acceptance["maximum_field_change_c"] = .1
        output = solve_multilayer_thermal_convergence(
            geometry, view, result, settings, acceptance)
        self.assertEqual(output["mesh_acceptance"]["status"], "FAIL")
        self.assertGreater(output["mesh_acceptance"]["maximum_field_change_c"], .1)

    def test_phase_sensitivity_is_reported_and_can_fail_the_gate(self):
        geometry, view, result, settings = inputs()
        settings.update(board_h_w_m2k=50, board_emissivity=0)
        acceptance = {"grid_cells_long_axis": [24, 48],
                      "maximum_change_c": 1e9, "minimum_source_cells": 1,
                      "phase_offset_fraction": [.5, .5],
                      "maximum_field_change_c": 0}
        output = solve_multilayer_thermal_convergence(
            geometry, view, result, settings, acceptance)
        phase = output["mesh_acceptance"]["phase_sensitivity"]
        self.assertEqual(phase["status"], "FAIL")
        self.assertGreater(phase["maximum_field_change_c"], 0)

    def test_subcell_contact_does_not_pass_on_four_tiny_overlaps(self):
        geometry, view, result, settings = inputs()
        settings.update(board_h_w_m2k=50, board_emissivity=0)
        view["components"][0]["bbox_mm"] = [5.999, 5.999, 6.001, 6.001]
        result["components"][0]["power_w"] = .1
        output = solve_multilayer_thermal_convergence(
            geometry, view, result, settings,
            {"grid_cells_long_axis": [48, 80], "maximum_change_c": 1,
             "minimum_source_cells": 4})
        part = output["components"][0]
        self.assertEqual(part["source_cells"], 4)
        self.assertLess(part["effective_source_cells"], .001)
        self.assertEqual(output["mesh_acceptance"]["status"], "FAIL")
        self.assertEqual(output["mesh_acceptance"]["underresolved_sources"], ["U1"])

    def test_selected_saved_pad_contact_excludes_drilled_copper_void(self):
        geometry, view, result, settings = inputs()
        view["components"][0]["bbox_mm"] = [5, 5, 7, 7]
        geometry["source_contacts"] = [{
            "reference": "U1", "pad_number": "2", "layer_id": 0,
            "net": "DRAIN", "polygons_mm": [{
                "outer": [[5, 5], [7, 5], [7, 7], [5, 7]],
                "holes": [[[5.5, 5.5], [6.5, 5.5], [6.5, 6.5], [5.5, 6.5]]],
            }],
        }]
        settings["source_contact_pad_numbers"] = {"U1": "2"}
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        part = solved["components"][0]
        self.assertEqual(part["source_distribution"], "saved_pad_copper_polygon")
        self.assertEqual(part["source_pad_number"], "2")
        self.assertEqual(part["source_net"], "DRAIN")
        self.assertAlmostEqual(part["source_contact_area_mm2"], 3)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)
        settings["source_contact_pad_numbers"] = {"U1": "3"}
        with self.assertRaisesRegex(ValueError, "no saved copper contact"):
            solve_multilayer_thermal(geometry, view, result, settings)

    def test_annulus_source_stencil_avoids_drilled_cell_centers(self):
        geometry, view, result, settings = inputs()
        hole = [[6+.15*math.cos(2*math.pi*k/32),
                 6+.15*math.sin(2*math.pi*k/32)] for k in range(32)]
        geometry["barrels"] = [{"id": "V1", "x_mm": 6, "y_mm": 6,
                                 "drill_mm": .3, "span_layers": [0, 31],
                                 "outer_diameters_mm": {"0": .6, "31": .6}}]
        geometry["source_contacts"] = [{
            "reference": "U1", "pad_number": "2", "layer_id": 0,
            "net": "DRAIN", "polygons_mm": [{
                "outer": [[5, 5], [7, 5], [7, 7], [5, 7]],
                "holes": [hole],
            }],
        }]
        settings.update(source_contact_pad_numbers={"U1": "2"},
                        grid_cells_long_axis=80)
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        part = solved["components"][0]
        self.assertGreater(part["source_drill_redistributed_mm2"], 0)
        self.assertEqual(part["source_peak_cell"]["center_in_drill_id"], None)
        self.assertGreater(solved["mesh"]["barrel_stencil_edges"],
                           solved["mesh"]["via_vertical_edges"])
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)

    def test_drill_center_peak_is_flagged_not_physical_hotspot(self):
        geometry, view, result, settings = inputs()
        geometry["barrels"] = [{"id": "D1", "x_mm": 6, "y_mm": 6,
                                 "drill_mm": .3, "span_layers": [0, 31]}]
        view["components"][0]["bbox_mm"] = [5.999, 5.999, 6.001, 6.001]
        settings.update(grid_cells_long_axis=80, board_h_w_m2k=50,
                        board_emissivity=0)
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertEqual(solved["components"][0]["source_peak_cell"]["center_in_drill_id"],
                         "D1")
        accepted = solve_multilayer_thermal_convergence(
            geometry, view, result, settings,
            {"grid_cells_long_axis": [48, 80], "maximum_change_c": 1e9,
             "minimum_source_cells": 1})
        self.assertIn("source:U1", accepted["mesh_acceptance"]["drill_center_peaks"])
        self.assertEqual(accepted["mesh_acceptance"]["status"], "FAIL")

    def test_air_energy_conservation_and_distinct_layer_field(self):
        geometry, view, result, settings = inputs()
        events = []
        solved = solve_multilayer_thermal(
            geometry, view, result, settings,
            progress=lambda stage, completed, total, elapsed, eta:
            events.append((stage, completed, total, elapsed, eta)))
        self.assertEqual(solved["status"], "converged")
        self.assertEqual(len(solved["layers"]), 2)
        self.assertAlmostEqual(solved["heat_balance"]["input_w"], 1)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)
        self.assertGreater(solved["layers"][0]["sampled_max_c"],
                           solved["layers"][1]["sampled_max_c"])
        self.assertIsNone(solved["components"][0]["junction_c"])
        self.assertIn(("copper rasterization", 0), [(e[0], e[1]) for e in events])
        self.assertTrue(any(e[0] == "copper rasterization" and e[1] == e[2]
                            for e in events))
        self.assertTrue(any(e[0] == "thermal solve" and e[1] == 1 for e in events))

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
