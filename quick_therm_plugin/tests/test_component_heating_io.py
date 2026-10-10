import copy
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from quick_therm_plugin.component_model_worker import native_vertex,resolve_model
from quick_therm_plugin.component_storage_inputs import storage_from_rows
from quick_therm_plugin.copper_loss_import import import_losses,validate_layer_binding
from quick_therm_plugin.thermal_review import transient_frame_network,frame_limit_status
from quick_therm_plugin.thermal_playback import transient_temperature_limits
from quick_therm_plugin.tests.test_component_storage import storage_inputs
from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal


def pi_report():
    return {'geometry':{'source_sha256':'board','layers':[{'id':0,'z_mm':.0175,'thickness_mm':.035}]},
            'mesh':{'points_mm':[[0,0,.0175],[1,0,.0175],[0,1,.0175]],'triangles':[[0,1,2]],
                    'triangle_thickness_mm':[.035],'vias':[]},
            'result':{'model':'2.5D linear triangular DC conductivity FEM',
                      'feasibility':{'operating_point_valid':True},'cell_power_W':[.25],
                      'cell_layer':[0],'vias':[],'conductor_power_W':.25,'component_power_W':2}}


class ComponentHeatingIOTests(unittest.TestCase):
    def test_rc_table_explicit_values_surface_and_pad(self):
        values=storage_from_rows([('U1',True,'body','10','.2','', '30','5','.8','EP'),
                                  ('U2',False,'junction','','','')])
        self.assertEqual(values['U1']['contact_pad_number'],'EP')
        self.assertEqual(values['U1']['h_w_m2k'],5)
        self.assertNotIn('initial_c',values['U1'])
        self.assertNotIn('U2',values)
        for row in [('U1',True,'body','','.2',''),('U1',True,'body','10','nan',''),
                    ('U1',True,'body','10','.2','','20','','.8'),
                    ('U1',True,'body','10','.2','','20','0','1.1')]:
            with self.subTest(row=row),self.assertRaises(ValueError):storage_from_rows([row])

    def test_step_relative_variables_and_wrl_twin_without_guessing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'part.step').write_text('STEP')
            self.assertEqual(resolve_model('${KIPRJMOD}/part.wrl',{'KIPRJMOD':str(root)},root),root/'part.step')
            self.assertIsNone(resolve_model('${UNSET}/part.step',{},root))
        self.assertEqual(native_vertex(SimpleNamespace(x=10,y=-20,z=-3),1.6),[10,20,-3])

    def test_loss_import_preserves_conductor_power_and_excludes_load_power(self):
        imported=import_losses(pi_report(),'board')
        self.assertEqual(imported['input_w'],.25)
        self.assertEqual(imported['component_power_excluded_w'],2)
        self.assertEqual(imported['sources'][0]['polygon_mm'],[[0,0],[1,0],[0,1]])
        validate_layer_binding(imported,{'layers':imported['layers']})
        for mutation in ('hash','infeasible','balance','depth','thickness'):
            report=pi_report()
            if mutation=='hash':report['geometry']['source_sha256']='different'
            if mutation=='infeasible':report['result']['feasibility']['operating_point_valid']=False
            if mutation=='balance':report['result']['conductor_power_W']=1
            if mutation=='depth':report['mesh']['points_mm'][0][2]=1
            if mutation=='thickness':report['mesh']['triangle_thickness_mm'][0]=.1
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):import_losses(report,'board')

    def test_via_segment_identity_and_halving_is_owned_by_kernel(self):
        report=pi_report();report['mesh']['vias']=[{'id':'uuid:0-2','top_layer':0,'bottom_layer':2}]
        report['result']['vias']=[{'id':'uuid:0-2','power_W':.1}]
        report['result']['conductor_power_W']=.35
        imported=import_losses(report,'board')
        self.assertEqual(imported['sources'][1]['barrel_id'],'uuid')
        self.assertEqual(imported['sources'][1]['power_w'],.1)
        report['result']['vias'][0]['id']='other'
        with self.assertRaises(ValueError):import_losses(report,'board')

    def test_loss_import_keeps_contact_heat_separate_and_checks_current(self):
        from wayricad_runtime.package_conduction import normalize_paths
        definition={'id':'U1-1','reference':'U1','pad_number':'1','layer_id':0,'port':'source',
            'segments':[{'shape':'cylinder','length_mm':.2,'diameter_mm':.3,
                         'rho_ohm_m':1.3e-7,'k_w_mk':50}]}
        contact=normalize_paths([definition],physics='electrical')[0]
        power=4*contact['electrical_resistance_ohm']
        report=pi_report()
        report['result'].update(package_contacts=[{'definition':definition,'current_A':2,'power_W':power}],
                                package_power_W=power)
        imported=import_losses(report,'board')
        self.assertAlmostEqual(imported['input_w'],.25)
        self.assertAlmostEqual(imported['package_joule_input_w'],power)
        self.assertEqual(imported['package_joule_losses'][0]['id'],'U1-1')
        report['result']['package_contacts'][0]['current_A']=3
        with self.assertRaisesRegex(ValueError,'current/resistance/heat'):
            import_losses(report,'board')

    def test_converged_electrothermal_uses_explicit_mesh_layer_thickness(self):
        report=pi_report()
        coupled={'mode':'steady_electrothermal','converged':True,'mesh':report['mesh'],
                 'hot':report['result'],'bindings':{'source_sha256':'board'},
                 'thermal':{'layers':[{'id':0,'z_mm':.0175,'name':'F.Cu'}]}}
        imported=import_losses({'electrothermal':coupled},'board')
        self.assertEqual(imported['layers'][0]['thickness_mm'],.035)
        self.assertEqual(imported['input_w'],.25)
        coupled['thermal']['layers'].append({'id':2,'z_mm':1.5})
        with self.assertRaisesRegex(ValueError,'explicit thickness'):import_losses(coupled,'board')

    def test_body_frame_uses_stored_state_and_never_implies_junction_limit(self):
        args=storage_inputs(kind='body');args[-1]['component_storage']['U1']['initial_c']=37
        network=solve_multilayer_thermal(*args);before=copy.deepcopy(network)
        frame=transient_frame_network(network,0);part=frame['components'][0]
        self.assertEqual(part['body_c'],37)
        self.assertIsNone(part['junction_c'])
        self.assertEqual(frame_limit_status({'maximum_c':25},part['junction_c']),'UNKNOWN')
        self.assertAlmostEqual(part['contact_heat_w'],(37-20)/2)
        self.assertEqual(network,before)
        self.assertGreaterEqual(transient_temperature_limits(network['transient'])[1],37)


if __name__=='__main__':unittest.main()
