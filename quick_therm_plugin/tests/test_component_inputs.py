"""Detached input review: units, unknowns, scope and saved-field provenance."""
import copy
import unittest

from quick_therm_plugin.component_inputs import ComponentInputsModel, restored_temperature_mapping


INVENTORY = {"components": [
    {"reference": "U1", "value": "Controller", "side": "top",
     "properties": {"Power_W": "250 mW", "RthetaJA": "40 K/W",
                    "RthetaJB": "5 °C/W", "MinTj": "-40 °C", "MaxTj": "125"}},
    {"reference": "R1", "value": "10k", "side": "bottom",
     "properties": {"Power_W": "0 W"}},
    {"reference": "U2", "value": "Amplifier", "side": "top", "properties": {}},
]}
MAPPING = {"power_w": "Power_W", "theta_ja_air_k_per_w": "RthetaJA",
           "theta_jb_k_per_w": "RthetaJB"}
LIMITS = {"minimum_c": "MinTj", "maximum_c": "MaxTj"}


class ComponentInputsTests(unittest.TestCase):
    def test_temperature_mapping_preserves_reviewed_choice_and_avoids_ambiguity(self):
        self.assertEqual(restored_temperature_mapping(['Tmin_C','Tmax_C']),
                         {'minimum_c':'Tmin_C','maximum_c':'Tmax_C'})
        self.assertEqual(restored_temperature_mapping(['Tmax_C','MaxTj','ReviewedLimit'],
                         {'maximum_c':'ReviewedLimit'})['maximum_c'],'ReviewedLimit')
        self.assertEqual(restored_temperature_mapping(['Tmax_C','MaxTj'])['maximum_c'],'')

    def model(self, **kwargs):
        return ComponentInputsModel(INVENTORY, MAPPING, limit_field_map=LIMITS, **kwargs)

    def test_scan_prefills_parsed_values_and_keeps_saved_evidence(self):
        model = self.model(selected_references=["U1", "R1"])
        values = model.effective_values()
        self.assertEqual(values["U1"], {"power_w": .25, "theta_ja_air_k_per_w": 40.,
                                        "theta_jb_k_per_w": 5., "minimum_c": -40.,
                                        "maximum_c": 125.})
        self.assertEqual(values["R1"], {"power_w": 0.})
        cell = model.cell("U1", "theta_jb_k_per_w")
        self.assertEqual((cell.source, cell.source_field, cell.source_raw),
                         ("Saved field", "RthetaJB", "5 °C/W"))
        self.assertEqual(model.manual_values(), {})

    def test_all_paths_editable_and_inputs_do_not_mutate_caller(self):
        inventory, existing = copy.deepcopy(INVENTORY), {"U1": {"power_w": .5}}
        expected = copy.deepcopy(inventory)
        model = ComponentInputsModel(inventory, MAPPING, existing, ["U1"])
        for quantity, raw in (("theta_ja_air_k_per_w", "30"),
                              ("theta_jb_k_per_w", "7 K/W"),
                              ("theta_jc_k_per_w", "2")):
            model.set_value("U1", quantity, raw)
        self.assertEqual(model.effective_values()["U1"]["theta_jb_k_per_w"], 7)
        self.assertEqual(model.cell("U1", "theta_jb_k_per_w").source_raw, "5 °C/W")
        self.assertEqual(inventory, expected)
        self.assertEqual(existing, {"U1": {"power_w": .5}})
        exported = model.manual_values()
        exported["U1"]["power_w"] = 999
        self.assertEqual(model.cell("U1", "power_w").value, .5)

    def test_blank_override_masks_saved_value_and_restoration_recovers_it(self):
        model = self.model(selected_references=["U1"])
        model.set_value("U1", "theta_jb_k_per_w", " ")
        cell = model.cell("U1", "theta_jb_k_per_w")
        self.assertIsNone(cell.value)
        self.assertEqual(cell.text, "")
        self.assertEqual(cell.source, "Manual override")
        self.assertEqual(cell.source_raw, "5 °C/W")
        self.assertNotIn("theta_jb_k_per_w", model.effective_values()["U1"])
        self.assertIsNone(model.export_state()["manual_values"]["U1"]["theta_jb_k_per_w"])
        model.restore_saved(["U1"], ["theta_jb_k_per_w"])
        self.assertEqual(model.cell("U1", "theta_jb_k_per_w").value, 5)

    def test_zero_power_valid_zero_resistance_and_invalid_units_rejected(self):
        model = self.model(selected_references=["U2"])
        model.set_value("U2", "power_w", "0 mW")
        self.assertEqual(model.effective_values()["U2"]["power_w"], 0)
        for quantity, raw in (("power_w", "nan"), ("power_w", "-1"),
                              ("power_w", "1 K/W"), ("theta_jb_k_per_w", "0"),
                              ("theta_jb_k_per_w", "-2"),
                              ("theta_jb_k_per_w", "inf"),
                              ("maximum_c", "-274 °C")):
            with self.subTest(quantity=quantity, raw=raw), self.assertRaises(ValueError):
                model.set_value("U2", quantity, raw)
        self.assertNotIn("theta_jb_k_per_w", model.manual_values()["U2"])
        self.assertEqual(model.cell("U2", "theta_jb_k_per_w").text, "")

    def test_search_and_bulk_scope_preserve_hidden_checked_rows_and_edits(self):
        model = self.model(selected_references=["R1"])
        model.set_value("R1", "theta_jb_k_per_w", "12")
        visible = model.visible_references("controller top")
        self.assertEqual(visible, ["U1"])
        model.select_all(visible)
        self.assertEqual(model.selected_references(), ["R1", "U1"])
        self.assertEqual(model.export_state()["manual_values"]["R1"],
                         {"theta_jb_k_per_w": 12.})
        model.select_all()
        self.assertEqual(model.selected_references(), ["R1", "U1", "U2"])
        model.select_all(visible, included=False)
        self.assertEqual(model.selected_references(), ["R1", "U2"])
        self.assertEqual(model.visible_references("", included_only=True), ["R1", "U2"])
        model.select_all(included=False)
        self.assertEqual(model.selected_references(), [])
        self.assertEqual(model.manual_values()["R1"]["theta_jb_k_per_w"], 12)

    def test_changed_mapping_preserves_manual_override_and_original_field(self):
        model = self.model(selected_references=["U1"])
        model.set_value("U1", "power_w", "700 mW")
        model.set_mappings({"power_w": "RthetaJA"}, LIMITS)
        cell = model.cell("U1", "power_w")
        self.assertAlmostEqual(cell.value, .7)
        self.assertEqual((cell.source_raw, cell.source_field), ("40 K/W", "RthetaJA"))
        self.assertAlmostEqual(model.effective_values()["U1"]["power_w"], .7)
        model.restore_saved(["U1"])
        with self.assertRaises(ValueError):
            model.effective_values()

    def test_scanned_invalid_stays_visible_and_chosen_rows_are_validated(self):
        inventory = copy.deepcopy(INVENTORY)
        inventory["components"][2]["properties"]["Power_W"] = "not supplied"
        model = ComponentInputsModel(inventory, MAPPING, selected_references=["U1"])
        cell = model.cell("U2", "power_w")
        self.assertEqual(cell.text, "not supplied")
        self.assertIsNone(cell.value)
        self.assertIn("Expected", cell.issue)
        model.effective_values()  # Invalid unchecked components do not block scope.
        model.set_included("U2", True)
        with self.assertRaisesRegex(ValueError, "U2"):
            model.effective_values()
        model.set_value("U2", "power_w", "")
        self.assertEqual(model.effective_values()["U2"], {})

    def test_temperature_units_and_limits_are_separate_and_not_silently_zero(self):
        model = self.model(selected_references=["U2"])
        model.set_value("U2", "minimum_c", "273.15 K")
        model.set_value("U2", "maximum_c", "100 °C")
        self.assertEqual(model.export_state()["manual_limits"]["U2"],
                         {"minimum_c": 0., "maximum_c": 100.})
        self.assertEqual(model.effective_values(include_limits=False)["U2"], {})
        model.set_value("U2", "minimum_c", "110")
        self.assertIn("exceeds", model.row_status("U2"))
        with self.assertRaisesRegex(ValueError, "minimum Tj exceeds"):
            model.effective_values()

    def test_reference_inventory_compatibility_and_duplicate_rejection(self):
        model = ComponentInputsModel({"component_references": ["U1", "U2", "REF**"]})
        self.assertEqual(model.references, ["U1", "U2"])
        self.assertEqual(model.effective_values(selected_only=False), {"U1": {}, "U2": {}})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            ComponentInputsModel([{"reference": "U1"}, {"reference": "U1"}])


if __name__ == "__main__":
    unittest.main()
