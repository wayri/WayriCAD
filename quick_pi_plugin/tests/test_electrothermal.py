"""Steady fixed-point references use the actual FEM and finite-volume kernels."""
import copy
import json
import unittest
from quick_pi_plugin.electrothermal import solve_electrothermal, ElectrothermalError
from quick_pi_plugin.tests.test_solver import strip, combine


def request(alpha=.00393, current=5, resolution=24):
    a, sa, ta = strip(length=10,width=10,nx=2,ny=2,z=0)
    b, sb, tb = strip(length=10,width=10,nx=2,ny=2,z=1.6)
    mesh,n = combine(a,b)
    mesh['triangle_layer'] = [0]*len(a['triangles'])+[31]*len(b['triangles'])
    polygon = dict(outer=[[0,0],[10,0],[10,10],[0,10]], holes=[])
    return dict(schema_version=1, mesh=mesh, source_nodes=sa+[i+n for i in sb],
                sinks=[dict(id='load',nodes=ta+[i+n for i in tb],current_A=current)], source_voltage_V=3.3,
                thermal_geometry=dict(outline_status='valid',outline=[dict(outer_mm=polygon['outer'],holes_mm=[])],
                    bbox_mm=[0,0,10,10],layers=[dict(id=0,name='F.Cu',z_mm=0,thickness_mm=.035,polygons_mm=[polygon]),
                                               dict(id=31,name='B.Cu',z_mm=1.6,thickness_mm=.035,polygons_mm=[polygon])],
                    barrels=[],mounting_holes=[]),
                thermal_view=dict(components=[]),thermal_result=dict(environment='air',components=[]),
                thermal_settings=dict(ambient_c=20,dielectric_k_w_mk=.3,via_plating_mm=.025,
                                      grid_cells_long_axis=resolution,board_h_w_m2k=5,board_emissivity=0),
                electrical_options=dict(temperature_coefficient=alpha),
                coupling=dict(material_temperature_range_c=[0,300],temperature_cap_c=250,
                              temperature_tolerance_c=1e-6,loss_relative_tolerance=1e-8,max_iterations=100,relaxation=.7))


class ElectrothermalTests(unittest.TestCase):
    def test_unplated_drilled_void_cannot_report_converged_coupling(self):
        study = request()
        study['thermal_geometry']['mounting_holes'] = [
            dict(id='NPTH-1', x_mm=5., y_mm=5., drill_mm=6., plated=False)]
        before = copy.deepcopy(study)
        with self.assertRaisesRegex((ElectrothermalError, ValueError), 'unplated drilled voids'):
            solve_electrothermal(study)
        self.assertEqual(study, before)

    def test_uniform_two_face_thermal_path_closed_form(self):
        study=request()
        result=solve_electrothermal(study)
        self.assertEqual(result['status'],'converged')
        resistance=1.724e-8*.01/(.01*.000035)/2
        rtheta=1/(2*5*.0001)
        a=25*resistance*rtheta
        rise=a/(1-.00393*a)
        self.assertAlmostEqual(result['thermal']['layers'][0]['sampled_max_c'],20+rise,5)
        self.assertAlmostEqual(result['hot']['total_power_W'],rise/rtheta,9)
        self.assertLess(abs(result['transfer_balance']['residual_w']),1e-12)
        self.assertLess(abs(result['thermal']['heat_balance']['residual_w']),1e-9)
        self.assertLess(result['hot']['energy_relative_error'],1e-10)
        self.assertGreater(result['hot']['voltage_drop_V'],result['cold']['voltage_drop_V'])
        json.dumps(result,allow_nan=False)

    def test_zero_alpha_and_mesh_refinement(self):
        values=[]
        for resolution in (24,36):
            result=solve_electrothermal(request(alpha=0,resolution=resolution))
            self.assertTrue(result['converged'])
            self.assertAlmostEqual(result['hot']['total_power_W'],result['cold']['total_power_W'],13)
            values.append(result['thermal']['layers'][0]['sampled_max_c'])
        self.assertAlmostEqual(values[0],values[1],7)

    def test_electrical_and_thermal_meshes_refine_independently_with_feedback(self):
        values=[]
        for nx,resolution in ((2,24),(4,24),(4,36)):
            with self.subTest(electrical=nx,thermal=resolution):
                study=request(resolution=resolution)
                a,sa,ta=strip(length=10,width=10,nx=nx,ny=nx,z=0)
                b,sb,tb=strip(length=10,width=10,nx=nx,ny=nx,z=1.6)
                mesh,n=combine(a,b)
                mesh['triangle_layer']=[0]*len(a['triangles'])+[31]*len(b['triangles'])
                study.update(mesh=mesh,source_nodes=sa+[i+n for i in sb])
                study['sinks'][0]['nodes']=ta+[i+n for i in tb]
                solved=solve_electrothermal(study)
                self.assertTrue(solved['converged'])
                self.assertLess(abs(solved['transfer_balance']['residual_w']),1e-10)
                values.append((solved['hot']['voltage_drop_V'],solved['thermal']['layers'][0]['sampled_max_c']))
        for voltage,temperature in values[1:]:
            self.assertAlmostEqual(voltage,values[0][0],9)
            self.assertAlmostEqual(temperature,values[0][1],5)

    def test_unstable_linear_reference_does_not_converge(self):
        result=solve_electrothermal(request(current=40))
        self.assertFalse(result['converged'])
        self.assertIn(result['status'],('material_range_exceeded','temperature_cap','iteration_limit'))
        self.assertIsNone(result['hot'])
        self.assertFalse(result['limits']['operating_point_valid'])

    def test_cap_iteration_budget_and_cancellation(self):
        study=request()
        study['coupling']['max_iterations']=1
        self.assertEqual(solve_electrothermal(study)['status'],'iteration_limit')
        study=request()
        study['coupling']['temperature_cap_c']=21
        self.assertEqual(solve_electrothermal(study)['status'],'temperature_cap')
        with self.assertRaises(InterruptedError):
            solve_electrothermal(request(),cancel=lambda:True)
        study=request()
        study['source_current_limit_A']=1
        result=solve_electrothermal(study)
        self.assertTrue(result['converged'])
        self.assertFalse(result['limits']['operating_point_valid'])

    def test_missing_cooling_and_source_binding(self):
        study=request()
        study['thermal_settings']['board_h_w_m2k']=0
        with self.assertRaises(ElectrothermalError) as caught:
            solve_electrothermal(study)
        self.assertEqual(caught.exception.code,'missing_cooling')
        study=request()
        study['mesh']['source_sha256']='a'
        study['thermal_geometry']['source_sha256']='b'
        with self.assertRaises(ElectrothermalError) as caught:
            solve_electrothermal(study)
        self.assertEqual(caught.exception.code,'source_mismatch')

    def test_series_via_conserves_axial_heat_and_rejects_unmapped(self):
        study=request(alpha=0,current=2)
        mesh=study['mesh']
        a,sa,ta=strip(length=10,width=10,nx=2,ny=2,z=0)
        n=len(a['points_mm'])
        sb=[i+n for i in sa]
        tb=[i+n for i in ta]
        study['source_nodes']=sa
        study['sinks'][0]['nodes']=tb
        mesh['vias']=[dict(id='V1',top_nodes=ta,bottom_nodes=sb,length_mm=1.6,drill_mm=.3,plating_mm=.025)]
        with self.assertRaises(ElectrothermalError) as caught:
            solve_electrothermal(study)
        self.assertEqual(caught.exception.code,'missing_mapping')
        study['via_heat_mappings']={'V1':dict(x_mm=5,y_mm=5,top_layer=0,bottom_layer=31,policy='uniform_axial')}
        solved=solve_electrothermal(study)
        self.assertTrue(solved['converged'])
        via_heat=[row for row in solved['thermal']['distributed_sources'] if row['kind']=='via']
        self.assertAlmostEqual(sum(row['power_w'] for row in via_heat),solved['hot']['via_power_W'],12)
        self.assertAlmostEqual(solved['temperatures']['via_c'][0],sum(row['temperature_c'] for row in via_heat)/2,5)
        study['via_heat_mappings']['V1']['top_layer']=31
        study['via_heat_mappings']['V1']['bottom_layer']=0
        with self.assertRaises(ElectrothermalError) as caught:
            solve_electrothermal(study)
        self.assertEqual(caught.exception.code,'source_mismatch')

    def test_branch_contact_and_duplicate_component_heat(self):
        study=request(alpha=0,current=1)
        a,sa,ta=strip(length=10,width=10,nx=2,ny=2,z=0)
        n=len(a['points_mm'])
        study['source_nodes']=sa
        study['sinks'][0]['nodes']=[i+n for i in ta]
        study['mesh']['lumped_branches']=[dict(id='R1',top_nodes=ta,bottom_nodes=[i+n for i in sa],resistance_ohm=.01)]
        with self.assertRaises(ElectrothermalError) as caught:
            solve_electrothermal(study)
        self.assertEqual(caught.exception.code,'missing_mapping')
        study['branch_heat_mappings']={'R1':dict(layer_id=0,polygon_mm=[[4,4],[6,4],[6,6],[4,6]])}
        solved=solve_electrothermal(study)
        self.assertTrue(solved['converged'])
        self.assertAlmostEqual(solved['transfer_balance']['branch_w'],.01,12)
        study['thermal_result']['components']=[dict(reference='R1',power_w=.01)]
        with self.assertRaises(ElectrothermalError) as caught:
            solve_electrothermal(study)
        self.assertEqual(caught.exception.code,'duplicate_power')

    def test_layer_geometry_ownership_is_exact(self):
        study=request()
        study['thermal_geometry']['layers'][0]['z_mm']=.1
        with self.assertRaises(ElectrothermalError) as caught:
            solve_electrothermal(study)
        self.assertEqual(caught.exception.code,'source_mismatch')
