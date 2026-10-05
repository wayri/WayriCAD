"""Reference checks for the coupled-air RC transient interface."""
import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from quick_therm_plugin.thermal_transient import (
    fan_operating_point, run_saved_board_transient, solve_coupled_transient,
)
from quick_therm_plugin.transient_cli import _temperature_svg


def fixture():
    return {
        "inlet_air_c": 40, "air_topology": "serial_boards",
        "duration_s": 20, "step_s": 1,
        "air_density_kg_m3": 1.2, "air_cp_j_kgk": 1000,
        "fan_curve": [[0, 100], [.02, 0]],
        "system_k_pa_s2_m6": 250000, "bypass_fraction": .1,
        "boards": [{
            "name": f"B{index}", "capacity_j_k": 10,
            "air_conductance_curve": [[0, 1], [.02, 1]],
            "components": [{"reference": "Q1", "capacity_j_k": 2,
                            "r_junction_board_k_w": 1, "fixed_power_w": 2}],
        } for index in range(4)],
    }


class CoupledTransientTests(unittest.TestCase):
    def test_parallel_blade_topology_is_not_run_as_serial(self):
        config = fixture()
        config["air_topology"] = "parallel_passages"
        with self.assertRaisesRegex(ValueError, "air_flow_direction"):
            solve_coupled_transient(config)
        config.update(air_flow_direction="-X", blade_pitch_mm=36,
                      passage_flow_fractions=[.25]*4, fans_parallel=2,
                      passage_flow_allocation="effective_per_blade")
        for board in config["boards"]:
            board["components"][0]["streamwise_x_mm"] = 8
            board["components"].append({"reference": "Q2", "streamwise_x_mm": 2,
                                        "capacity_j_k": 2, "r_junction_board_k_w": 1,
                                        "fixed_power_w": 2,
                                        "package_body": {
                                            "r_junction_body_k_w": 2, "capacity_j_k": 1,
                                            "air_conductance_curve": [[0, .5], [.02, .5]]}})
        result = solve_coupled_transient(config)
        last = result["history"][-1]
        self.assertEqual(result["air_topology"], "parallel_passages")
        self.assertEqual(result["fan_operating_point"]["fans_parallel"], 2)
        self.assertTrue(all(board["inlet_air_c"] == 40 for board in last["boards"]))
        self.assertEqual([stage["x_mm"] for stage in last["boards"][0]["air_stages"]],
                         [8, 2])
        self.assertGreater(last["boards"][0]["air_stages"][1]["inlet_c"], 40)
        self.assertIn("Q2 body", last["boards"][0]["temperatures_c"])
        self.assertGreater(last["mixed_outlet_air_c"], 40)
        self.assertLess(result["max_energy_residual_w"], 1e-9)

    def test_fan_system_intersection_and_downstream_warming(self):
        config = fixture()
        flow = fan_operating_point(config["fan_curve"],
                                   config["system_k_pa_s2_m6"], .1)
        q = flow["total_m3_s"]
        self.assertAlmostEqual(100-5000*q, 250000*q*q, places=9)
        self.assertAlmostEqual(flow["board_channel_m3_s"], .9*q)
        result = solve_coupled_transient(config)
        self.assertEqual(result["status"], "computed_unqualified")
        final = result["history"][-1]["boards"]
        self.assertEqual(len(result["history"]), 20)
        self.assertGreater(final[3]["inlet_air_c"], final[0]["inlet_air_c"])
        self.assertGreater(final[3]["temperatures_c"]["board"],
                           final[0]["temperatures_c"]["board"])
        self.assertLess(result["max_energy_residual_w"], 1e-10)
        svg = _temperature_svg(result)
        self.assertIn("QuickTherm coupled-board transient", svg)
        self.assertIn("B3 air out", svg)

    def test_one_node_rc_analytic_and_step_refinement(self):
        config = fixture()
        # Strong junction-board coupling approximates one 12 J/K node.
        for board in config["boards"]:
            board["components"][0]["r_junction_board_k_w"] = 1e-7
        config["duration_s"] = 6
        coarse = solve_coupled_transient(config)
        config["step_s"] = .01
        fine = solve_coupled_transient(config)
        p, h, c = 2, 1, 12
        expected = 40+p/h*(1-math.exp(-h*6/c))
        fine_value = fine["history"][-1]["boards"][0]["temperatures_c"]["board"]
        coarse_value = coarse["history"][-1]["boards"][0]["temperatures_c"]["board"]
        self.assertLess(abs(fine_value-expected), abs(coarse_value-expected))
        self.assertAlmostEqual(fine_value, expected, places=3)

    def test_r_t_feedback_and_isolated_sink(self):
        config = fixture()
        component = config["boards"][0]["components"][0]
        component["resistive_loss"] = {"current_a": 1, "resistance_ref_ohm": 1,
                                        "alpha_per_k": .01, "reference_c": 40}
        component["isolated_sink"] = {
            "contact_kind": "metal_drain", "drain_net": "VIN",
            "working_voltage_v": 50, "insulation_rating_v": 100,
            "isolation_evidence": "reviewed dielectric contact drawing",
            "capacity_j_k": 5, "r_junction_sink_k_w": .5,
            "air_conductance_curve": [[0, 1], [.02, 1]],
        }
        result = solve_coupled_transient(config)
        first = result["history"][-1]["boards"][0]
        self.assertGreater(first["power_w"], 3)
        self.assertIn("Q1 sink", first["temperatures_c"])
        component["isolated_sink"]["insulation_rating_v"] = 25
        with self.assertRaisesRegex(ValueError, "below the declared"):
            solve_coupled_transient(config)
        component["isolated_sink"]["insulation_rating_v"] = 100
        del component["isolated_sink"]["isolation_evidence"]
        with self.assertRaisesRegex(ValueError, "isolation_evidence"):
            solve_coupled_transient(config)

    def test_fixture_boundary_removes_heat_and_requires_evidence(self):
        config = fixture()
        base = solve_coupled_transient(config)
        config["boards"][0]["fixed_boundary"] = {
            "temperature_c": 10, "contact_r_k_w": 2,
            "contact_evidence": "reviewed fixture thermal contact",
        }
        mounted = solve_coupled_transient(config)
        self.assertGreater(mounted["history"][-1]["boards"][0]["fixture_heat_w"], 0)
        self.assertLess(mounted["history"][-1]["boards"][0]["temperatures_c"]["board"],
                        base["history"][-1]["boards"][0]["temperatures_c"]["board"])
        self.assertLess(mounted["max_energy_residual_w"], 1e-10)
        del config["boards"][0]["fixed_boundary"]["contact_evidence"]
        with self.assertRaisesRegex(ValueError, "contact_evidence"):
            solve_coupled_transient(config)

    def test_missing_actual_dissipation_is_not_a_zero_power_pass(self):
        config = fixture()
        del config["boards"][0]["components"][0]["fixed_power_w"]
        with self.assertRaisesRegex(ValueError, "actual dissipation"):
            solve_coupled_transient(config)

    def test_rejects_missing_fan_coverage_negative_loss_and_source_drift(self):
        config = fixture()
        config["fan_curve"] = [[0, 100], [.001, 99]]
        with self.assertRaisesRegex(ValueError, "intersection"):
            solve_coupled_transient(config)
        config = fixture()
        config["boards"][0]["components"][0]["fixed_power_w"] = -1
        with self.assertRaisesRegex(ValueError, "allowed range"):
            solve_coupled_transient(config)
        with tempfile.TemporaryDirectory() as folder:
            for i, board in enumerate(fixture()["boards"]):
                board["board_path"] = str(Path(folder) / f"b{i}.kicad_pcb")
                Path(board["board_path"]).write_text(f"board {i}")
                if i == 0:
                    board["expected_source_sha256"] = "wrong"
                config["boards"][i] = board
            with self.assertRaisesRegex(ValueError, "changed"):
                run_saved_board_transient(config)

    def test_saved_board_reference_and_hash_contract(self):
        config = fixture()

        class Footprint:
            def GetReference(self):
                return "Q1"

        board = types.SimpleNamespace(GetFootprints=lambda: [Footprint()])
        pcbnew = types.SimpleNamespace(LoadBoard=lambda _: board)
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {"pcbnew": pcbnew}):
            for index, member in enumerate(config["boards"]):
                path = Path(folder) / f"board-{index}.kicad_pcb"
                path.write_text(f"board {index}", encoding="utf-8")
                member["board_path"] = str(path)
            result = run_saved_board_transient(config)
            self.assertEqual(len(result["source_sha256"]), 4)
            config["boards"][0]["components"][0]["reference"] = "U404"
            with self.assertRaisesRegex(ValueError, "not on the saved board"):
                run_saved_board_transient(config)

    def test_parallel_passage_positions_bind_to_saved_footprints(self):
        config = fixture()
        config.update(air_topology="parallel_passages", air_flow_direction="-X",
                      blade_pitch_mm=36, passage_flow_fractions=[.25]*4,
                      passage_flow_allocation="effective_per_blade")

        class Footprint:
            def GetReference(self):
                return "Q1"

            def GetPosition(self):
                return types.SimpleNamespace(x=8)

        board = types.SimpleNamespace(GetFootprints=lambda: [Footprint()])
        pcbnew = types.SimpleNamespace(LoadBoard=lambda _: board, ToMM=lambda x: x)
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {"pcbnew": pcbnew}):
            for index, member in enumerate(config["boards"]):
                path = Path(folder) / f"board-{index}.kicad_pcb"
                path.write_text(f"board {index}", encoding="utf-8")
                member["board_path"] = str(path)
            result = run_saved_board_transient(config)
            self.assertEqual(result["saved_component_x_mm"]["B0"], {"Q1": 8})
            config["boards"][0]["components"][0]["streamwise_x_mm"] = 5
            with self.assertRaisesRegex(ValueError, "differs from the saved footprint"):
                run_saved_board_transient(config)

    def test_prescribed_flow_sensitivity_does_not_invent_fan_curve(self):
        config = fixture()
        config.update(air_topology="parallel_passages", air_flow_direction="-X",
                      blade_pitch_mm=36, passage_flow_fractions=[.25]*4,
                      passage_flow_allocation="effective_per_blade",
                      prescribed_total_flow_m3_s=20*0.00047194745)
        del config["fan_curve"]
        del config["system_k_pa_s2_m6"]
        for board in config["boards"]:
            board["components"][0]["streamwise_x_mm"] = 8
        result = solve_coupled_transient(config)
        self.assertEqual(result["fan_operating_point"]["source"],
                         "prescribed_sensitivity_input")
        self.assertIsNone(result["fan_operating_point"]["pressure_pa"])
        self.assertLess(result["max_energy_residual_w"], 1e-8)
        config["fan_curve"] = [[0, 100], [.02, 0]]
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            solve_coupled_transient(config)


if __name__ == "__main__":
    unittest.main()
