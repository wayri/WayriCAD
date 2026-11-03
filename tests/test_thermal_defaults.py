"""Known starting inputs populate together without replacing edits or unknowns."""
from copy import deepcopy
import importlib.util
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wayricad_runtime.thermal_defaults import populate_settings, screening_defaults
from wayricad_runtime.thermal_materials import material_form_state, review_material
from wayricad_runtime.thermal_materials_ui import ThermalMaterialDialog


K='thermal_conductivity_w_mk'
CV='volumetric_heat_capacity_j_m3k'


class ThermalDefaultsTests(unittest.TestCase):
    def test_known_material_and_temperature_fields_are_populated_together(self):
        values=screening_defaults(37)
        self.assertEqual(values['ambient_c'],37)
        self.assertEqual(values['initial_temperature_c'],37)
        self.assertEqual(values['enclosure_temperature_c'],37)
        self.assertEqual(values['fixed_lower_face_c'],37)
        self.assertEqual(values['dielectric_k_w_mk'],.3)
        self.assertEqual(values['copper_k_w_mk'],385)
        self.assertEqual(values['dielectric_volumetric_capacity_j_m3k'],1800000)
        self.assertEqual(values['copper_volumetric_capacity_j_m3k'],3450000)
        self.assertNotIn('density_kg_m3',values)
        self.assertNotIn('material_temperature_range_c',values)
        values['dielectric_k_w_mk']=99
        self.assertEqual(screening_defaults()['dielectric_k_w_mk'],.3)

    def test_missing_only_preserves_loaded_values_invalid_text_and_unknown_properties(self):
        current={'ambient_c':55,'dielectric_k_w_mk':'','copper_k_w_mk':400,
                 'board_h_w_m2k':'not reviewed','density_kg_m3':None,
                 'material_temperature_range_c':[None,None]}
        before=deepcopy(current)
        updated,changed=populate_settings(current)
        self.assertEqual(current,before)
        self.assertEqual(changed,['dielectric_k_w_mk'])
        self.assertEqual(updated,{**before,'dielectric_k_w_mk':.3})

    def test_explicit_replace_uses_selected_ambient_but_never_adds_unexposed_inputs(self):
        current={'ambient_c':50,'initial_temperature_c':None,'board_emissivity':.2,'density_kg_m3':None}
        updated,changed=populate_settings(current,ambient_c=25,replace_existing=True)
        self.assertEqual(updated,{'ambient_c':25.,'initial_temperature_c':25.,'board_emissivity':.9,'density_kg_m3':None})
        self.assertEqual(set(changed),{'ambient_c','initial_temperature_c','board_emissivity'})
        self.assertNotIn('via_plating_mm',updated)

    def test_invalid_ambient_never_supplies_defaults(self):
        for value in (True,None,'cold',float('nan'),float('inf'),-273.15,10001):
            with self.subTest(value=value),self.assertRaises(ValueError):screening_defaults(value)

    def test_temperature_only_replace_preserves_reviewed_materials_and_unknowns(self):
        current={'ambient_c':'20','initial_temperature_c':'20','enclosure_temperature_c':'35',
                 'fixed_lower_face_c':'18','copper_k_w_mk':'400',
                 'dielectric_k_w_mk':'','board_emissivity':.7,'density_kg_m3':None}
        before=deepcopy(current)
        updated,changed=populate_settings(current,ambient_c=42,replace_temperatures=True)
        self.assertEqual(current,before)
        for key in ('ambient_c','initial_temperature_c','enclosure_temperature_c','fixed_lower_face_c'):
            self.assertEqual(updated[key],42.)
            self.assertIn(key,changed)
        self.assertEqual(updated['copper_k_w_mk'],'400')
        self.assertEqual(updated['board_emissivity'],.7)
        self.assertEqual(updated['dielectric_k_w_mk'],.3)
        self.assertIsNone(updated['density_kg_m3'])

    def test_material_form_selects_all_known_supported_properties(self):
        state=material_form_state('fr4-screening',[K,CV])
        self.assertEqual(state['selected'],[K,CV])
        self.assertEqual(state['values'],{K:.3,CV:1800000})
        state=material_form_state('isola-370hr',[K,CV])
        self.assertEqual(state['selected'],[K]);self.assertIsNone(state['values'][CV])
        state=material_form_state('henkel-tgp1500',[K,CV,'density_kg_m3','specific_heat_j_kgk'])
        self.assertEqual(state['values'][CV],state['values']['density_kg_m3']*state['values']['specific_heat_j_kgk'])
        self.assertEqual(len(state['selected']),4)

    def test_reopening_a_material_preserves_selected_properties_and_override_note(self):
        selection=review_material('fr4-screening',selected=[K],overrides={K:.45},reviewed=True,
                                  review_note='Measured illustrative coupon at room temperature.')
        original=deepcopy(selection)
        state=material_form_state('fr4-screening',[K,CV],selection)
        self.assertEqual(state['selected'],[K])
        self.assertEqual(state['values'][K],.45)
        self.assertEqual(state['review_note'],selection['review_note'])
        self.assertEqual(selection,original)
        self.assertEqual(material_form_state('copper-screening',[K,CV],selection)['values'][K],385)

    def test_native_picker_population_logic_needs_no_window(self):
        class Control:
            def SetValue(self,value):self.value=value
            def SetLabel(self,value):self.value=value
        picker=ThermalMaterialDialog.__new__(ThermalMaterialDialog)
        from wayricad_runtime.thermal_materials import get_material
        picker.records=[get_material('fr4-screening')]
        picker.choice=SimpleNamespace(GetSelection=lambda:0)
        picker.allowed=[K,CV];picker.initial_selection=None
        picker.values={key:Control() for key in picker.allowed}
        picker.checks={key:Control() for key in picker.allowed}
        picker.evidence=Control();picker.reviewed=Control();picker.review_note=Control();picker.status=Control()
        picker._choose()
        self.assertEqual(picker.values[K].value,'0.3')
        self.assertEqual(picker.values[CV].value,'1800000.0')
        self.assertTrue(picker.checks[K].value);self.assertTrue(picker.checks[CV].value)
        self.assertFalse(picker.reviewed.value)


@unittest.skipUnless(importlib.util.find_spec('wx'),'Native wx runtime required for module imports')
class DefaultsControllerTests(unittest.TestCase):
    def test_native_temperature_only_option_applies_ambient_without_replacing_materials(self):
        import wx
        from wayricad_runtime.thermal_defaults_ui import choose_defaults
        app=wx.GetApp() or wx.App(False)
        current={'ambient_c':'20','initial_temperature_c':'20','copper_k_w_mk':'400'}
        original=deepcopy(current)
        def accept(dialog):
            controls=dialog.GetChildren()
            ambient=next(control for control in controls if isinstance(control,wx.TextCtrl)
                         and not control.GetWindowStyleFlag() & wx.TE_MULTILINE)
            temperatures=next(control for control in controls if isinstance(control,wx.CheckBox)
                              and control.GetLabel().startswith('Apply starting ambient'))
            temperatures.SetValue(True)
            ambient.SetValue('42')
            temperatures.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_CHECKBOX.typeId,temperatures.GetId()))
            apply=next(control for control in controls if isinstance(control,wx.Button)
                       and control.GetLabel()=='Apply starting values')
            apply.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,apply.GetId()))
            return wx.ID_OK
        with patch.object(wx.Dialog,'ShowModal',accept),patch.object(wx.Dialog,'EndModal'):
            result=choose_defaults(None,current)
        self.assertEqual(current,original)
        self.assertEqual(result['values'],{'ambient_c':42.,'initial_temperature_c':42.,'copper_k_w_mk':'400'})
        self.assertEqual(result['changed'],['ambient_c','initial_temperature_c'])

    def test_native_defaults_preview_cancel_does_not_change_inputs_or_show_window(self):
        import wx
        from wayricad_runtime.thermal_defaults_ui import choose_defaults
        app=wx.GetApp() or wx.App(False)
        current={'ambient_c':'37','dielectric_k_w_mk':'','copper_k_w_mk':'400'}
        original=deepcopy(current)
        with patch.object(wx.Dialog,'ShowModal',return_value=wx.ID_CANCEL):
            self.assertIsNone(choose_defaults(None,current))
        self.assertEqual(current,original)

    def test_pi_feedback_population_fills_thermal_inputs_without_inventing_validity(self):
        import json
        try:
            from quick_pi_plugin.electrothermal_ui import ElectrothermalStudyDialog, feedback_studies
        except ImportError as exc:self.skipTest(str(exc))
        class Control:
            def __init__(self,value=''):self.value=value
            def GetValue(self):return self.value
            def ChangeValue(self,value):self.value=value
            def SetLabel(self,value):self.value=value
        initial=feedback_studies({'net':'VCC','source_terminal':'J1.1','sink_terminal':'U1.1'})['steady']
        initial['thermal_settings']['ambient_c']=42
        initial['thermal_settings']['copper_k_w_mk']=400
        calls=[]
        frame=SimpleNamespace(_busy=False,_kind=lambda:'steady',setup=Control(json.dumps(initial)),
                              status=Control(),_changed=lambda:calls.append('invalidate'))
        def choose(parent,current):
            values,changed=populate_settings(current)
            return {'values':values,'changed':changed}
        with patch('wayricad_runtime.thermal_defaults_ui.choose_defaults',side_effect=choose):
            ElectrothermalStudyDialog._populate_thermal_defaults(frame)
        result=json.loads(frame.setup.value)
        self.assertEqual(result['thermal_settings']['ambient_c'],42)
        self.assertEqual(result['thermal_settings']['copper_k_w_mk'],400)
        self.assertEqual(result['thermal_settings']['dielectric_k_w_mk'],.3)
        self.assertEqual(result['thermal_settings']['board_h_w_m2k'],20)
        self.assertEqual(result['thermal_settings']['board_emissivity'],.9)
        self.assertEqual(result['coupling']['material_temperature_range_c'],[None,None])
        self.assertEqual(result['electrical']['options']['resistivity_ohm_m'],None)
        self.assertEqual(calls,['invalidate'])

    def test_quicktherm_population_retains_user_ambient_and_fills_layered_inputs(self):
        try:
            from quick_therm_plugin.ui import QuickThermFrame
        except ImportError as exc:self.skipTest(str(exc))
        class Control:
            def __init__(self,value=''):self.value=value
            def GetValue(self):return self.value
            def ChangeValue(self,value):self.value=value
            def SetLabel(self,value):self.value=value
        attributes=('therm_ambient','therm_time_initial','therm_ccx_bottom','therm_enclosure_c',
                    'therm_k','therm_dielectric_k','therm_copper_k','therm_dielectric_capacity',
                    'therm_copper_capacity','therm_emissivity','therm_air_board','therm_air_sink',
                    'therm_explicit_h','therm_potting_k','therm_potting_thickness','therm_potting_outer_h','therm_plating')
        calls=[]
        frame=SimpleNamespace(_busy=False,therm_status=Control(),_invalidate_thermal=lambda:calls.append('invalidate'),
                              **{attribute:Control() for attribute in attributes})
        frame.therm_ambient.value='42';frame.therm_copper_k.value='400'
        def choose(parent,current):
            values,changed=populate_settings(current)
            return {'values':values,'changed':changed}
        with patch('wayricad_runtime.thermal_defaults_ui.choose_defaults',side_effect=choose):
            QuickThermFrame._populate_thermal_defaults(frame)
        self.assertEqual(frame.therm_ambient.value,'42')
        self.assertEqual(frame.therm_time_initial.value,'42.0')
        self.assertEqual(frame.therm_copper_k.value,'400')
        self.assertEqual(frame.therm_dielectric_k.value,'0.3')
        self.assertEqual(frame.therm_plating.value,'0.025')
        self.assertEqual(calls,['invalidate'])
