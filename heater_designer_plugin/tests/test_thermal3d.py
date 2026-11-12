import copy
import json
import unittest
from heater_designer_plugin.analysis import HeaterEngine,HeaterSpec
from heater_designer_plugin.materials import MATERIALS,custom_sheet
from heater_designer_plugin.thermal3d import build_study,construction_layers,solve_study


class HeaterVolumeTests(unittest.TestCase):
    def heater(self,**kwargs):
        return HeaterEngine.generate(HeaterSpec(width_mm=8,height_mm=6,trace_width_mm=.5,spacing_mm=.5,voltage_v=.05,**kwargs))

    def config(self,form='rigid',**kwargs):
        return dict(cell_mm=2,conductor_k_w_mk=385,layers=construction_layers(form,8),
                    boundary=dict(ambient_c=25,h_w_m2k=10,emissivity=.8),
                    settings=dict(temperature_bounds_c=[20,150],max_cells=50000),**kwargs)

    def test_default_geometry_aligned_grid_is_bounded(self):
        heater=HeaterEngine.generate(HeaterSpec())
        config=self.config();config['layers']=construction_layers('rigid',80)
        request=build_study(heater,config)
        self.assertLessEqual(len(request['material_ids']),50000)
        self.assertEqual(request['provenance']['mesh_mode'],'geometry-aligned')

    def test_rigid_flex_has_local_void_and_continuous_foil(self):
        request=build_study(self.heater(),self.config('rigid-flex'))
        nx,ny,nz=request['provenance']['mesh_shape']
        top=request['material_ids'][(nz-1)*nx*ny:]
        self.assertIn(None,top);self.assertIn('substrate-2',top)
        self.assertEqual(request['provenance']['construction'][1]['role'],'heater')

    def test_sheet_film_uses_physical_thickness(self):
        request=build_study(self.heater(material=custom_sheet(10,.001)),self.config())
        self.assertAlmostEqual(request['materials']['conductor']['resistivity_ohm_m'],10*35e-6)

    def test_nickel_alloy_keeps_temperature_table(self):
        request=build_study(self.heater(material=MATERIALS['inconel600']),self.config())
        self.assertGreater(len(request['materials']['conductor']['temperature_factors']),3)
        self.assertNotIn('tcr_per_k',request['materials']['conductor'])

    def test_three_dimensional_current_heat_and_balance(self):
        report=solve_study(self.heater(),self.config())
        result=report['result']
        self.assertTrue(result['converged']);self.assertGreater(result['electrical_power_w'],0)
        self.assertGreater(max(v for v in result['temperatures_c'] if v is not None),25)
        self.assertLess(abs(result['energy_residual_w']),1e-5)
        self.assertEqual(len(result['coordinates']['shape_xyz']),3)
        json.dumps(report,allow_nan=False)

    def test_excessive_grid_rejected_before_allocation(self):
        config=self.config();config['cell_mm']=1e-100
        with self.assertRaisesRegex(ValueError,'before allocation'):build_study(self.heater(),config)

    def test_seebeck_requires_reference_evidence(self):
        with self.assertRaisesRegex(ValueError,'reference/lead'):build_study(self.heater(),self.config(seebeck_v_k=1e-6))

    def test_unsupported_vias_not_silently_replaced(self):
        with self.assertRaisesRegex(ValueError,'without vias'):build_study(self.heater(layers=2),self.config())
