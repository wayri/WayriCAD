"""Analytical package-to-board networks and saved-pad binding rejection."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from quick_pi_plugin.package_contacts import attach
from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests.test_solver import strip, combine


def path(identifier, reference, port, resistance=.01, layer=0, **extra):
    # A 1 mm by .25 mm² prism: factor = 4000 / m.
    return dict(id=identifier, reference=reference, pad_number='1', layer_id=layer,
                port=port, segments=[dict(shape='rectangular', length_mm=1,
                width_mm=.5, thickness_mm=.5, rho_ohm_m=resistance/4000)], **extra)


def fixture():
    first,sa,ta=strip()
    second,sb,tb=strip(z=1)
    mesh,n=combine(first,second)
    sb=[i+n for i in sb];tb=[i+n for i in tb]
    pads=[dict(id='a',reference='J1',pad_number='1',net='VCC'),
          dict(id='b',reference='J2',pad_number='1',net='VCC'),
          dict(id='load',reference='U1',pad_number='1',net='VCC')]
    for pad in pads:
        pad['polygons']={'0':[{'outer':[[0,0],[1,0],[1,1],[0,1]],'holes':[]}]}
    geometry=dict(net='VCC',terminals=pads,pad_catalog=copy.deepcopy(pads))
    mesh.update(terminal_nodes={'a':sa,'b':sb,'load':ta+tb},
                terminal_nodes_by_layer={'a':{'0':sa},'b':{'0':sb},'load':{'0':ta+tb}},geometry=geometry)
    sinks=[dict(id='load',label='U1.1',terminal='U1.1',nodes=ta+tb,current_A=3)]
    return mesh,geometry,sinks


class PackageNetworkTests(unittest.TestCase):
    def run_paths(self, paths, **limits):
        mesh,geometry,sinks=fixture()
        network,source,loads=attach(mesh,geometry,paths,'a',sinks)
        result=solve(network,source,sinks=loads,source_voltage=1,**limits)
        return network,result

    def test_unequal_parallel_contacts_solve_currents_and_conserve_power(self):
        network,result=self.run_paths([path('one','J1','source',.01),path('two','J2','source',.02)])
        board=1.724e-8*.01/(.001*.000035)
        r1,r2=.01+board,.02+board
        equivalent=1/(1/r1+1/r2)
        self.assertAlmostEqual(result['voltage_drop_V'],3*equivalent,11)
        self.assertAlmostEqual(result['package_contacts'][0]['current_A'],3*r2/(r1+r2),10)
        self.assertAlmostEqual(result['package_contacts'][1]['current_A'],3*r1/(r1+r2),10)
        self.assertAlmostEqual(sum(r['current_A'] for r in result['package_contacts']),3,10)
        self.assertAlmostEqual(result['total_power_W'],9*equivalent,11)
        self.assertAlmostEqual(result['package_power_W'],sum(r['current_A']**2*r['resistance_ohm'] for r in result['package_contacts']),12)
        self.assertLess(result['energy_relative_error'],1e-9)
        self.assertLess(result['max_nodal_residual_A'],1e-8)
        self.assertLess(result['analytics']['losses']['accounting_error_W'],1e-11)
        self.assertEqual(result['components'],[])
        self.assertEqual(len(network['points_mm']),67)
        json.dumps(result,allow_nan=False)

    def test_bga_ball_and_lead_segments_are_series_inside_each_path(self):
        import math
        contacts=[path('one','J1','source'),path('two','J2','source')]
        diameter,length=.5,.3
        factor=4/(math.pi*diameter*1e-3)*math.atanh(length/diameter)
        for contact in contacts:
            contact['segments'].append(dict(shape='spherical_ball',length_mm=length,
                                           diameter_mm=diameter,rho_ohm_m=.02/factor))
        _,result=self.run_paths(contacts)
        for row in result['package_contacts']:
            self.assertAlmostEqual(row['resistance_ohm'],.03,12)
            self.assertAlmostEqual(row['current_A'],1.5,10)
            self.assertEqual(len(row['segments']),2)
            self.assertAlmostEqual(sum(segment['power_W'] for segment in row['segments']),row['power_W'],12)
        self.assertAlmostEqual(result['package_power_W'],2*1.5**2*.03,11)

    def test_equal_parallel_sharing_is_solved(self):
        _,result=self.run_paths([path('one','J1','source'),path('two','J2','source')])
        for row in result['package_contacts']:self.assertAlmostEqual(row['current_A'],1.5,10)

    def test_contact_neck_is_bounded_by_saved_copper_including_holes(self):
        mesh,geometry,sinks=fixture()
        geometry['terminals'][0]['polygons']['0'][0]['holes']=[[[0,0],[.9,0],[.9,.9],[0,.9]]]
        with self.assertRaisesRegex(ValueError,'end neck exceeds'):
            attach(mesh,geometry,[path('lead','J1','source')],'a',sinks)
        geometry['terminals'][0]['polygons']={}
        with self.assertRaisesRegex(ValueError,'saved pad copper area'):
            attach(mesh,geometry,[path('lead','J1','source')],'a',sinks)

    def test_sink_package_voltage_includes_contact_drop_and_sets_limits(self):
        _,result=self.run_paths([path('one','J1','source'),path('two','J2','source'),
                                 path('sink','U1','sink:U1.1',.02)],source_current_limit=2)
        sink=result['package_contacts'][2]
        self.assertAlmostEqual(sink['current_A'],-3,10)
        self.assertAlmostEqual(sink['package_voltage_V'],result['sinks'][0]['voltage_V'],12)
        self.assertAlmostEqual(sink['board_voltage_V']-sink['package_voltage_V'],.06,11)
        self.assertEqual(sink['definition']['port'],'sink:load')
        self.assertFalse(result['feasibility']['feasible'])
        mesh,geo,sinks=fixture();sinks[0]['min_voltage_V']=.95
        net,src,loads=attach(mesh,geo,[path('sink','U1','sink:load',.1)],'a',sinks)
        self.assertFalse(solve(net,src,sinks=loads)['sinks'][0]['within_voltage_limits'])

    def test_single_face_attachment_retains_plated_barrel_resistance(self):
        mesh,geo,sinks=fixture()
        top=mesh['terminal_nodes']['a'];bottom=mesh['terminal_nodes']['b']
        mesh['terminal_nodes']['a']=top+bottom
        mesh['terminal_nodes_by_layer']['a']['31']=bottom
        mesh['vias']=[dict(id='pth',top_nodes=top,bottom_nodes=bottom,
                           length_mm=1.6,drill_mm=.3,plating_mm=.025)]
        sinks[0]['nodes']=mesh['terminal_nodes']['load'][3:]
        mesh['terminal_nodes']['load']=sinks[0]['nodes']
        net,src,loads=attach(mesh,geo,[path('lead','J1','source')],'a',sinks)
        result=solve(net,src,sinks=loads)
        self.assertAlmostEqual(result['vias'][0]['current_A'],3,9)
        self.assertGreater(result['via_power_W'],0)
        self.assertLess(result['energy_relative_error'],1e-9)

    def test_no_contact_preserves_legacy_mesh_and_source(self):
        mesh,geo,sinks=fixture()
        network,source,loads=attach(mesh,geo,[],'a',sinks)
        self.assertIs(network,mesh);self.assertIs(loads,sinks)
        self.assertEqual(source,mesh['terminal_nodes']['a'])

    def test_attachment_does_not_mutate_inputs(self):
        mesh,geo,sinks=fixture();before=copy.deepcopy((mesh,geo,sinks))
        attach(mesh,geo,[path('lead','J1','source')],'a',sinks)
        self.assertEqual((mesh,geo,sinks),before)

    def test_rejects_ambiguous_cross_net_wrong_layer_and_duplicate_binding(self):
        cases=[]
        mesh,geo,sinks=fixture();geo['pad_catalog'].append({**geo['pad_catalog'][0],'id':'other'})
        cases.append((mesh,geo,sinks,[path('lead','J1','source')],'ambiguous'))
        mesh,geo,sinks=fixture();geo['pad_catalog'][0]['net']='GND'
        cases.append((mesh,geo,sinks,[path('lead','J1','source')],'different net'))
        mesh,geo,sinks=fixture()
        cases.append((mesh,geo,sinks,[path('lead','J1','source',layer=31)],'declared pad face'))
        cases.append((mesh,geo,sinks,[path('lead','J1','source'),path('second','J1','source')],'ownership'))
        cases.append((mesh,geo,sinks,[path('lead','J1','sink:unknown')],'Unknown package port'))
        for mesh,geo,sinks,paths,message in cases:
            with self.subTest(message=message),self.assertRaisesRegex(ValueError,message):attach(mesh,geo,paths,'a',sinks)

    def test_unknown_contact_voltage_current_and_segment_heat_remain_unknown(self):
        from quick_pi_plugin.package_contacts import ledger,details_text
        mesh,geo,sinks=fixture()
        network,src,loads=attach(mesh,geo,[path('lead','J1','source')],'a',sinks)
        result=solve(network,src,sinks=loads)
        contact=result['package_contacts'][0]
        branch={key:contact[key] for key in ('id','resistance_ohm','connected','voltage_drop_V')}
        branch.update(current_A=None,power_W=None,voltage_before_V=None,voltage_after_V=None)
        result['components']=[branch]
        result['potential_V'][network['package_endpoint_nodes']['source']]=None
        ledger(network,result)
        row=result['package_contacts'][0]
        self.assertIsNone(row['current_A']);self.assertIsNone(row['package_voltage_V'])
        self.assertIsNone(row['segments'][0]['power_W'])
        self.assertIsNone(result['package_port_currents_A']['source'])
        self.assertIn('unknown',details_text(result))

    def test_uuid_disambiguates_but_never_overrides_reference(self):
        mesh,geo,sinks=fixture();geo['pad_catalog'].append({**geo['pad_catalog'][0],'id':'other'})
        attach(mesh,geo,[path('lead','J1','source',pad_uuid='a')],'a',sinks)
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            attach(mesh,geo,[path('lead','J2','source',pad_uuid='a')],'a',sinks)

    def test_unsupported_modes_fail_before_board_io(self):
        from quick_pi_plugin.service import execute
        for change in [dict(action='sweep'),dict(action='transient'),dict(action='electrothermal'),
                       dict(model_dimension='3d'),dict(series=[{}]),dict(load_resistance_ohm=2)]:
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'unsupported'):
                execute({'action':'solve','package_conduction':[path('lead','J1','source')],**change})

    def test_cli_intake_keeps_explicit_paths_and_rejects_unsupported_mode(self):
        from quick_pi_plugin.cli import main
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'paths.json';source.write_text(json.dumps([path('lead','J1','source')]))
            response={'result':{'feasibility':{'feasible':True}}}
            with patch('quick_pi_plugin.service.run_job',return_value=response) as worker,redirect_stdout(io.StringIO()):
                code=main(['example.kicad_pcb','--net','VCC','--source','J1.1','--sink','U1.1','--package-conduction',str(source)])
            self.assertEqual(code,0)
            self.assertEqual(worker.call_args.args[0]['package_conduction'][0]['id'],'lead')
            with patch('quick_pi_plugin.service.run_job') as worker,redirect_stdout(io.StringIO()):
                code=main(['example.kicad_pcb','--net','VCC','--source','J1.1','--sink','U1.1','--package-conduction',str(source),'--sweep','1','2','3'])
            self.assertEqual(code,2);worker.assert_not_called()


if __name__=='__main__':unittest.main()
