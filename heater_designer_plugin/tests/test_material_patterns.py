from dataclasses import replace
import json
import unittest
from xml.etree import ElementTree as ET

from heater_designer_plugin.analysis import HeaterEngine, HeaterSpec, ThermalSpec, HeatZone
from heater_designer_plugin.materials import MATERIALS, custom_sheet
from heater_designer_plugin.patterns import PATTERNS
from heater_designer_plugin.foil_export import export_svg


class MaterialPatternIntegrationTests(unittest.TestCase):
    def test_all_fills_form_series_path_and_account_for_power(self):
        for pattern in PATTERNS:
            with self.subTest(pattern=pattern):
                result=HeaterEngine.generate(HeaterSpec(width_mm=80,height_mm=90,pattern=pattern,
                                            trace_width_mm=2,spacing_mm=.4,slot_angle_deg=40,material=MATERIALS['inconel600']))
                for a,b in zip(result.segments,result.segments[1:]):
                    self.assertAlmostEqual(a.x2_mm,b.x1_mm);self.assertAlmostEqual(a.y2_mm,b.y1_mm)
                self.assertAlmostEqual(sum(result.zone_power_w.values()),result.power_w)
                self.assertAlmostEqual(result.power_w,result.current_a**2*result.resistance_ohm)

    def test_bulk_material_and_film_sheet_resistance_change_loading(self):
        spec=HeaterSpec()
        copper=HeaterEngine.generate(spec)
        alloy=HeaterEngine.generate(replace(spec,material=MATERIALS['inconel600']))
        self.assertAlmostEqual(alloy.resistance_ohm/copper.resistance_ohm,1.03e-6/1.724e-8)
        a=HeaterEngine.generate(replace(spec,material=custom_sheet(.05),copper_um=1))
        b=HeaterEngine.generate(replace(spec,material=custom_sheet(.05),copper_um=100))
        self.assertEqual(a.resistance_ohm,b.resistance_ohm)

    def test_unknown_temperature_correction_does_not_abort_thermal_preview(self):
        result=HeaterEngine.generate(HeaterSpec(voltage_v=.1,material=MATERIALS['manganin']))
        thermal=HeaterEngine.simulate(result,ThermalSpec(grid_x=8,grid_y=8,iterations=30),recommend_sensors=False)
        self.assertTrue(any('unavailable' in n for n in thermal.notes))

    def test_foil_constraints_and_metadata_are_explicit(self):
        spec=HeaterSpec(pattern='Circular foil',trace_width_mm=3,spacing_mm=.2)
        for change in ({'layers':2},{'spacing_mm':0},{'zones':(HeatZone('wide',50,50,20,.5),)}):
            with self.assertRaises(ValueError):HeaterEngine.generate(replace(spec,**change))
        result=HeaterEngine.generate(spec)
        root=ET.fromstring(export_svg(result));ns={'s':'http://www.w3.org/2000/svg'}
        metadata=json.loads(root.find('s:metadata',ns).text)
        self.assertEqual(metadata['spec']['material']['key'],'copper')
        self.assertEqual(root.attrib['width'],'80mm')
        self.assertEqual(len(root.findall('.//s:path',ns)),len(result.segments))

    def test_automation_accepts_material_preset_and_serialized_film(self):
        from dataclasses import asdict
        from extract_pins_plugin.automation import _heater_analyze
        preset=_heater_analyze({'spec':{'pattern':'Circular foil','material':'inconel600'}})
        self.assertEqual(preset['spec']['material']['key'],'inconel600')
        film=_heater_analyze({'spec':{'material':asdict(custom_sheet(.1))}})
        self.assertEqual(film['spec']['material']['sheet_resistance_ohm_sq'],.1)


if __name__=='__main__':unittest.main()
