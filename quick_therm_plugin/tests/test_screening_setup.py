"""The first board screen needs known power, not invented package properties."""
import unittest
from quick_therm_plugin.component_inputs import ComponentInputsModel
from quick_therm_plugin.screening_setup import STARTING_VALUES,requires_multilayer,missing_power_message


class ScreeningSetupTests(unittest.TestCase):
    def test_include_known_power_is_explicit_and_does_not_replace_unknown_with_zero(self):
        model=ComponentInputsModel({'components':[
            {'reference':'U1','properties':{'Power_W':'1 W'}},
            {'reference':'R1','properties':{'Power_W':'0 W'}},
            {'reference':'U2','properties':{}},
            {'reference':'U3','properties':{'Power_W':'invalid'}}]}, {'power_w':'Power_W'})
        self.assertEqual(model.include_known_power(),['R1','U1'])
        self.assertIsNone(model.cell('U2','power_w').value)
        self.assertEqual(model.manual_values(),{})
        self.assertEqual(set(model.effective_values()),{'U1','R1'})

    def test_advanced_physics_selects_layered_model_but_simple_air_does_not(self):
        self.assertFalse(requires_multilayer('air'))
        self.assertFalse(requires_multilayer('vacuum'))
        for environment in ('forced_air','potting','sealed'):
            self.assertTrue(requires_multilayer(environment))
        for option in ('transient','storage','contacts','copper_losses'):
            self.assertTrue(requires_multilayer('air',**{option:True}))

    def test_starting_assumptions_are_explicit_not_package_resistances(self):
        self.assertEqual(STARTING_VALUES['dielectric_k_w_mk'],.3)
        self.assertEqual(STARTING_VALUES['via_plating_mm'],.025)
        self.assertFalse(any('theta' in name or 'power' in name for name in STARTING_VALUES))
        self.assertIn('Unknown power is not zero',missing_power_message(['U2']))
