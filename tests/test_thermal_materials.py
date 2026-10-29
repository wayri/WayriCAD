"""Thermal references preserve SI units, uncertainty and explicit application."""
from copy import deepcopy
import importlib.util
import unittest

from wayricad_runtime.thermal_materials import (PROPERTY_UNITS, apply_material_selection,
                                               get_material, list_materials, review_material,
                                               validate_material_selection, matching_material_selections)
from wayricad_runtime.thermal_materials_ui import ThermalMaterialDialog as NativePicker

K = 'thermal_conductivity_w_mk'
CV = 'volumetric_heat_capacity_j_m3k'


class ThermalMaterialTests(unittest.TestCase):
    def test_presets_are_detached_and_unknown_properties_stay_unknown(self):
        material = get_material('isola-370hr'); self.assertEqual(material['properties'][K]['value'], .4)
        self.assertNotIn(CV, material['properties'])
        self.assertIn('not specified', material['properties'][K]['conditions'])
        material['properties'][K]['value'] = 100
        self.assertEqual(get_material('isola-370hr')['properties'][K]['value'], .4)
        self.assertEqual({row['category'] for row in list_materials('laminate')}, {'laminate'})

    def test_measurement_conditions_and_primary_sources_remain_attached(self):
        rogers = get_material('rogers-ro4350b')
        self.assertEqual(rogers['properties'][K]['value'], .69)
        self.assertIn('80 °C', rogers['properties'][K]['conditions'])
        self.assertIn('23 °C', rogers['properties']['density_kg_m3']['conditions'])
        self.assertIn('rogerscorp.com', rogers['source']['url'])
        self.assertNotIn('valid_temperature_range', rogers)

    def test_henkel_si_conversions_and_derived_capacity_match_reference(self):
        props = get_material('henkel-tgp1500')['properties']
        self.assertEqual(props['density_kg_m3']['value'], 2.1 * 1000)
        self.assertEqual(props['specific_heat_j_kgk']['value'], 1.0 * 1000)
        self.assertEqual(props[CV]['value'], props['density_kg_m3']['value'] * props['specific_heat_j_kgk']['value'])
        self.assertEqual(props[CV]['basis'], 'derived_typical')

    def test_inherited_inputs_are_labelled_illustrative(self):
        for identifier in ('fr4-screening', 'copper-screening'):
            material = get_material(identifier)
            self.assertTrue(all(prop['basis'] == 'illustrative' for prop in material['properties'].values()))
            self.assertEqual(material['source']['url'], '')
            self.assertIn('illustrative', material['name'])

    def test_review_is_required_and_unknown_values_cannot_be_applied(self):
        with self.assertRaisesRegex(ValueError, 'Review'): review_material('isola-370hr')
        with self.assertRaisesRegex(ValueError, 'unknown'):
            review_material('isola-370hr', reviewed=True, selected=[CV])
        for invalid in [0, -1, True, float('inf'), float('nan'), '0.4']:
            with self.assertRaises(ValueError):
                review_material('isola-370hr', reviewed=True, overrides={K: invalid})

    def test_explicit_application_changes_only_bound_selected_property(self):
        selection = review_material('isola-370hr', reviewed=True, selected=[K])
        settings = {'dielectric_k_w_mk': None, 'copper_k_w_mk': 385, 'ambient_c': 20,
                    'material_temperature_range_c': [None, None]}
        original = deepcopy(settings)
        updated = apply_material_selection(settings, selection, {K: 'dielectric_k_w_mk'})
        self.assertEqual(settings, original)
        self.assertEqual(updated, {**original, 'dielectric_k_w_mk': .4})
        self.assertEqual(selection['properties'][K]['unit'], PROPERTY_UNITS[K])

    def test_overrides_require_note_and_retain_original_source(self):
        with self.assertRaisesRegex(ValueError, 'review note'):
            review_material('isola-370hr', reviewed=True, overrides={K: .42})
        selection = review_material('isola-370hr', reviewed=True, overrides={K: .42},
                                    review_note='Measured coupon through-plane at 25 °C; laboratory record example.')
        self.assertEqual(selection['properties'][K]['value'], .42)
        self.assertEqual(selection['properties'][K]['basis'], 'user_override')
        self.assertEqual(selection['source'], get_material('isola-370hr')['source'])

    def test_custom_values_and_duplicate_target_rejection(self):
        selection = review_material('custom', reviewed=True, selected=[K, CV], overrides={K: .5, CV: 2e6},
                                    review_note='Explicit illustrative test inputs, no qualification.')
        result = apply_material_selection({}, selection, {K: 'k', CV: 'capacity'})
        self.assertEqual(result, {'k': .5, 'capacity': 2e6})
        with self.assertRaisesRegex(ValueError, 'same setting'):
            apply_material_selection({}, selection, {K: 'k', CV: 'k'})
        with self.assertRaisesRegex(ValueError, 'explicit target'):
            apply_material_selection({}, selection, {K: 'k'})

    def test_unmarked_tampering_or_wrong_units_cannot_claim_manufacturer_data(self):
        selection = review_material('isola-370hr', reviewed=True)
        selection['properties'][K]['value'] = 400
        with self.assertRaisesRegex(ValueError, 'user overrides'): validate_material_selection(selection)
        selection = review_material('isola-370hr', reviewed=True)
        selection['properties'][K]['unit'] = 'mW/(m·K)'
        with self.assertRaisesRegex(ValueError, 'SI'): validate_material_selection(selection)
        selection = review_material('isola-370hr', reviewed=True)
        selection['reviewed'] = False
        with self.assertRaisesRegex(ValueError, 'reviewed'): validate_material_selection(selection)

    def test_provenance_is_retained_only_while_applied_values_match(self):
        selection = review_material('isola-370hr', reviewed=True, selected=[K])
        records = {'dielectric': {'selection': selection, 'bindings': {K: 'dielectric_k_w_mk'}}}
        self.assertEqual(matching_material_selections(records, {'dielectric_k_w_mk': .4}), records)
        self.assertEqual(matching_material_selections(records, {'dielectric_k_w_mk': .42}), {})


@unittest.skipUnless(importlib.util.find_spec('wx'), 'Native wxPython runtime required')
class NativeThermalMaterialTests(unittest.TestCase):
    @staticmethod
    def _reviewed_picker(*args, **kwargs):
        import wx
        kwargs['initial_id'] = 'isola-370hr' if kwargs.get('category') == 'laminate' else 'copper-screening'
        picker = NativePicker(*args, **kwargs)
        picker.reviewed.SetValue(True); picker.selection = picker.selected_record()
        picker.dialog.ShowModal = lambda: wx.ID_OK
        return picker

    def test_native_picker_requires_review_and_preserves_custom_override(self):
        import wx
        from wayricad_runtime.thermal_materials_ui import ThermalMaterialDialog
        app = wx.GetApp() or wx.App(False); parent = wx.Frame(None)
        picker = ThermalMaterialDialog(parent, properties=[K, CV], category='laminate', initial_id='isola-370hr')
        try:
            picker.dialog.Show(); app.Yield()
            self.assertEqual(picker.values[CV].GetValue(), '')
            self.assertIsNone(picker.selection)
            with self.assertRaisesRegex(ValueError, 'Review'): picker.selected_record()
            picker.reviewed.SetValue(True)
            selection = picker.selected_record()
            self.assertEqual(set(selection['properties']), {K})
            picker.values[K].SetValue('.42')
            with self.assertRaisesRegex(ValueError, 'review note'): picker.selected_record()
            picker.review_note.SetValue('Explicit test coupon value at 25 °C.')
            self.assertEqual(picker.selected_record()['properties'][K]['value'], .42)
            self.assertIsNone(picker.selection)  # Reading/editing never applies.
        finally:
            picker.dialog.Destroy(); parent.Destroy(); app.Yield()

    def test_quick_pi_material_button_updates_canonical_config_and_invalidates(self):
        import json
        import wx
        from unittest.mock import patch
        from quick_pi_plugin.electrothermal_ui import ElectrothermalStudyDialog, initial_studies
        from quick_pi_plugin.plot_canvas import FigureCanvasWxAgg, NavigationToolbar2WxAgg
        app = wx.GetApp() or wx.App(False)
        initial = initial_studies({'net': 'VCC', 'source_voltage': 3.3})
        dialog = ElectrothermalStudyDialog(None, initial, lambda *args: None,
                                           (FigureCanvasWxAgg, NavigationToolbar2WxAgg))
        try:
            original = json.loads(dialog.setup.GetValue()); dialog.result = {'old': True}; dialog.export.Enable()
            with patch('wayricad_runtime.thermal_materials_ui.ThermalMaterialDialog', side_effect=self._reviewed_picker):
                dialog._edit_thermal_material('dielectric')
            request = dialog._request(); study = request['study']
            self.assertEqual(study['thermal_settings']['dielectric_k_w_mk'], .4)
            self.assertEqual(study['thermal_settings']['ambient_c'], original['thermal_settings']['ambient_c'])
            self.assertIn('dielectric', study['material_library'])
            self.assertIsNone(dialog.result); self.assertFalse(dialog.export.IsEnabled())
            study['thermal_settings']['dielectric_k_w_mk'] = .42
            dialog.setup.ChangeValue(json.dumps(study)); dialog._changed()
            self.assertEqual(dialog._request()['study']['material_library'], {})
            duplicate = '{"thermal_settings":{},"material_library":{},"value":1,"value":2}'
            dialog.setup.ChangeValue(duplicate); dialog._changed()
            self.assertEqual(dialog.setup.GetValue(), duplicate)
            with self.assertRaisesRegex(ValueError, 'Repeated'): dialog._request()
        finally:
            dialog.Destroy(); app.Yield()

    def test_quicktherm_material_button_changes_only_selected_fields(self):
        import wx
        from unittest.mock import patch
        from quick_therm_plugin.ui import QuickThermFrame
        app = wx.GetApp() or wx.App(False)
        with patch.object(QuickThermFrame, '_inspect'):
            frame = QuickThermFrame(None, 'Example.kicad_pcb')
            app.Yield()
            try:
                capacity = frame.therm_dielectric_capacity.GetValue()
                copper = frame.therm_copper_k.GetValue(); original_ambient = frame.therm_ambient.GetValue()
                frame.thermal_bundle = {'quick_therm': {'old': True}}; frame._buttons()
                with patch('wayricad_runtime.thermal_materials_ui.ThermalMaterialDialog', side_effect=self._reviewed_picker):
                    frame._edit_thermal_material('dielectric')
                self.assertEqual(float(frame.therm_dielectric_k.GetValue()), .4)
                self.assertEqual(frame.therm_dielectric_capacity.GetValue(), capacity)
                self.assertEqual(frame.therm_copper_k.GetValue(), copper)
                self.assertEqual(frame.therm_ambient.GetValue(), original_ambient)
                self.assertIn('dielectric', frame._thermal_materials)
                self.assertFalse(frame.thermal_bundle); self.assertFalse(frame.therm_export.IsEnabled())
                frame.therm_dielectric_k.ChangeValue('.42'); frame._invalidate_thermal()
                self.assertEqual(frame._thermal_materials, {})
            finally:
                frame.Destroy(); app.Yield()


if __name__ == '__main__':
    unittest.main()
