"""Active report settings distinguish selected physics from stored defaults."""
from copy import deepcopy
import unittest

from quick_emerge_plugin.model import validate_config
from quick_emerge_plugin.report_settings import active_settings


class ReportSettingsTests(unittest.TestCase):
    def result(self, **config):
        if config.get('mode') == 'pcb_region':
            config = {'rule_area_id':'Antenna region', 'signal_net':'SIGNAL', 'reference_net':'GND', 'region_er_reviewed':True, **config}
        return {'config': validate_config(config)}

    def test_recorded_region_dimensions_override_inactive_template(self):
        r = self.result(mode='pcb_region', thickness_mm=9, substrate_x_mm=100, er=4.3)
        r['region'] = {'substrate': {'thickness_mm': 1.53, 'board_thickness_mm': 1.6,
            'outline': [{'outer_mm': [[50,15],[98,15],[98,55],[50,55]], 'holes_mm': []}]}}
        before = deepcopy(r)
        rows = active_settings(r); values = {label: value for _,label,value in rows}
        self.assertEqual(values['Recorded dielectric separation [mm]'], 1.53)
        self.assertEqual(values['Recorded region extent X [mm]'], 48)
        self.assertEqual(values['Recorded region extent Y [mm]'], 40)
        self.assertEqual(values['Relative permittivity at start frequency'], 4.3)
        text = str(rows)
        for inactive in ('Patch width', 'Line width', 'Substrate extent X', 'PML thickness', 'Conductor conductivity', 'Thermal', 'SPARTA compute mode'):
            self.assertNotIn(inactive, text)
        self.assertEqual(before, r)
        self.assertTrue(all(not isinstance(v, (dict,list)) for row in rows for v in row))

    def test_finite_pml_and_active_shunt_parameters(self):
        r = self.result(mode='pcb_line', advanced={'conductor':'finite', 'boundary':'pml', 'shunt_component':'capacitor', 'shunt_value':12})
        values = {label:value for _,label,value in active_settings(r)}
        self.assertEqual(values['Conductor conductivity [S/m]'], 58000000)
        self.assertEqual(values['Shunt value [pF]'], 12)
        self.assertIn('PML thickness [mm]', values)
        self.assertNotIn('Absorbing boundary order', values)

    def test_thermal_only_and_transient_controls(self):
        r = self.result(advanced={'study':'thermal'})
        text = str(active_settings(r))
        for inactive in ('Relative permittivity', 'Sweep start', 'Conductor model', 'Air margin', 'Port 1 RF power', 'Substrate density', 'Transient time step'):
            self.assertNotIn(inactive, text)
        r['config']['advanced']['thermal_time_s'] = 3
        text = str(active_settings(r))
        self.assertIn('Transient time step', text)
        self.assertIn('Substrate density', text)

    def test_coupled_heating_and_waveguide_have_no_inactive_physics(self):
        r = self.result(advanced={'coupled_thermal':True})
        text = str(active_settings(r))
        self.assertIn('Port 1 RF power', text)
        self.assertNotIn('Uniform substrate heating power', text)
        r = self.result(f_start_hz=8e9, f_stop_hz=10e9, advanced={'study':'waveguide'})
        text = str(active_settings(r))
        self.assertIn('Waveguide broad dimension', text)
        self.assertNotIn('Substrate thickness', text)
        self.assertNotIn('Relative permittivity', text)

    def test_missing_recorded_region_never_falls_back_to_template(self):
        r = self.result(mode='pcb_region')
        values = {label:value for _,label,value in active_settings(r)}
        self.assertIsNone(values['Recorded dielectric separation [mm]'])
        self.assertIsNone(values['Recorded region extent X [mm]'])
