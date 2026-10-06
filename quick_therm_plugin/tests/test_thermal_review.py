"""Checks for field-mapped limits and non-extrapolating thermal probes."""

import unittest

from quick_therm_plugin.thermal_review import (
    cursor_readout, evaluate_limits, parse_temperature, sample_probes,
)


class Footprint:
    def __init__(self, reference, fields):
        self.reference = reference
        self.fields = fields

    def GetReference(self):
        return self.reference

    def GetFieldsText(self):
        return self.fields


class Board:
    def GetFootprints(self):
        return [Footprint("U1", {"Tmin": "0 °C", "Tmax": "80 °C"}),
                Footprint("U2", {"Tmin": "20 °C", "Tmax": "30 °C"}),
                Footprint("U3", {"Tmin": "20 °C"})]


class ReviewTests(unittest.TestCase):
    def test_temperature_units_and_limits_are_per_component(self):
        self.assertAlmostEqual(parse_temperature("300 K"), 26.85)
        thermal = {"references": ["U1", "U2", "U3"],
                   "components": [{"reference": "U1", "junction_c": 40},
                                  {"reference": "U2", "junction_c": 35},
                                  {"reference": "U3", "junction_c": 25}]}
        result = evaluate_limits(Board(), thermal, {"minimum_c": "Tmin", "maximum_c": "Tmax"})
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual([row["status"] for row in result["rows"]], ["PASS", "FAIL", "UNKNOWN"])
        self.assertEqual(result["counts"], {"PASS": 1, "FAIL": 1, "UNKNOWN": 1})

    def test_probe_uses_board_model_and_rejects_outside(self):
        view = {"outline_status": "valid", "outline": [{"outer_mm": [[0, 0], [10, 0], [10, 10], [0, 10]], "holes_mm": []}]}
        network = {"board_field": {"x_centers_mm": [2.5, 7.5], "y_centers_mm": [2.5, 7.5],
                                   "values_c": [[30, 35], [32, 36]]}}
        result = sample_probes(view, network, [{"label": "TP1", "x_mm": 2, "y_mm": 2, "side": "top"},
                                                {"label": "TP2", "x_mm": 11, "y_mm": 5, "side": "bottom"}])
        self.assertEqual(result[0]["temperature_c"], 30)
        self.assertEqual(result[0]["source"], "thin_sheet_board_model")
        self.assertEqual(result[1]["status"], "UNKNOWN")

    def test_cursor_uses_true_cell_edges_and_component_hit(self):
        view = {"outline_status": "valid", "outline": [{
            "outer_mm": [[0, 0], [10, 0], [10, 10], [0, 10]], "holes_mm": []}],
            "components": [{"id": "u1", "reference": "U1", "side": "top",
                            "position_mm": [3, 3], "bbox_mm": [2, 2, 4, 4],
                            "junction_c": 54}]}
        network = {"components": [{"reference": "U1", "junction_c": 56}], "layers": [
            {"name": "F.Cu", "x_centers_mm": [1, 5], "y_centers_mm": [2, 7],
             "x_edges_mm": [0, 2, 10], "y_edges_mm": [0, 4, 10],
             "values_c": [[31, 35], [33, 37]]},
            {"name": "B.Cu", "x_centers_mm": [1, 5], "y_centers_mm": [2, 7],
             "x_edges_mm": [0, 2, 10], "y_edges_mm": [0, 4, 10],
             "values_c": [[28, 29], [30, 31]]}]}
        top = cursor_readout(view, network, 2.5, 3, "top")
        self.assertEqual(top["temperature_c"], 35)
        self.assertEqual(top["field_source"], "F.Cu layer model")
        self.assertEqual(top["junction_c"], 54)
        self.assertEqual(top["model_junction_c"], 56)
        self.assertEqual(top["component_id"], "u1")
        bottom = cursor_readout(view, network, 2.5, 3, "bottom")
        self.assertEqual(bottom["temperature_c"], 29)
        self.assertIsNone(bottom["junction_c"])
        self.assertFalse(cursor_readout(view, network, 11, 3, "top")["on_board"])


if __name__ == "__main__":
    unittest.main()
