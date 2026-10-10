"""Physical references for explicit component storage in the spatial board graph."""
import copy
import json
import math
import unittest
import hashlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy.linalg import expm
from scipy.sparse import csr_matrix

from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal
from quick_therm_plugin.thermal_spatial_transient import evolve
from quick_therm_plugin.tests.test_thermal_multilayer import inputs


def service_study(args, **options):
    """Exercise the real service and kernels with a read-only saved-board fixture."""
    from quick_therm_plugin.service import execute
    from quick_therm_plugin.tests.test_quick_therm import Board, Footprint
    geometry,view,result,settings=args
    board=Board([Footprint(row['reference'],{}) for row in result['components']])
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'board.kicad_pcb';path.write_bytes(b'unchanged board fixture')
        request=dict(action='quick_therm',board_path=str(path),environment=result['environment'],
            ambient_c=result['ambient_c'],references=[row['reference'] for row in result['components']],
            input_mode='manual',manual_values={row['reference']:{'power_w':row['power_w']} for row in result['components']},
            thermal_model_kind='multilayer',thermal_network_settings=settings)
        if settings.get('copper_loss_sources'):
            request['copper_loss_binding']={'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'layers':[{key:layer[key] for key in ('id','z_mm','thickness_mm')} for layer in geometry['layers']]}
        request.update(options)
        with patch.dict(sys.modules,{'pcbnew':SimpleNamespace(LoadBoard=lambda _:board)}), \
             patch('quick_therm_plugin.thermal_board_view.build_board_thermal_view',return_value=view), \
             patch('quick_therm_plugin.thermal_geometry.collect_thermal_geometry',return_value=geometry), \
             patch('quick_therm_plugin.thermal_review.evaluate_limits',return_value={}), \
             patch('quick_therm_plugin.thermal_review.sample_probes',return_value=[]):
            output=execute(request)
        assert path.read_bytes()==b'unchanged board fixture'
        return output


def storage_inputs(kind='junction', *, duration=2, step=.025):
    geometry, view, result, settings = inputs('vacuum')
    # One exact contact cell shares the explicitly fixed mounting fixture.
    view['components'][0].update(position_mm=[5.75,5.75], bbox_mm=[5.5,5.5,6,6])
    result['components'][0]['power_w'] = 2
    settings.update(board_emissivity=0, mount_boundaries=[{
        'id':'MH1', 'temperature_c':20, 'contact_r_k_w':0}],
        component_storage={'U1':{'capacity_j_k':.5, 'resistance_k_per_w':2,
                                  'temperature_kind':kind}},
        transient_settings={'duration_s':duration, 'timestep_s':step,
                            'copper_volumetric_capacity_j_m3k':3.45e6,
                            'dielectric_volumetric_capacity_j_m3k':1.8e6})
    return geometry, view, result, settings


class ComponentStorageTests(unittest.TestCase):
    def test_service_copper_only_has_no_fictitious_component_power(self):
        args=inputs();args[1]['components']=[];args[2]['components']=[]
        args[-1]['copper_loss_sources']=[{'id':'copper:p','layer_id':0,
            'polygon_mm':[[1,1],[3,1],[1,3]],'power_w':2}]
        output=service_study(args)
        self.assertEqual(output['quick_therm']['components'],[])
        self.assertEqual(output['thermal_network']['components'],[])
        self.assertAlmostEqual(output['thermal_network']['heat_balance']['input_w'],2,12)

    def test_service_rc_sink_air_and_forced_air_preserve_contact_resistance(self):
        for environment in ('air','forced_air'):
            args=inputs(environment)
            args[-1].update(board_h_w_m2k=15,sink_h_w_m2k=10,sink_emissivity=0,
                sink_exposed_area_mm2={'U1':10000},component_storage={'U1':{
                    'capacity_j_k':.5,'resistance_k_per_w':2,'temperature_kind':'junction'}})
            sink={'shape':'resistance_only','contact_k_per_w':3,'theta_sa_air_k_per_w':7}
            with self.subTest(environment=environment):
                output=service_study(args,heatsinks={'U1':sink})
                part=output['thermal_network']['components'][0]
                self.assertAlmostEqual(part['junction_c']-part['sink_c'],2,10)
                self.assertAlmostEqual(output['thermal_network']['heat_balance']['input_w'],1,12)

    def test_service_storage_surface_split_exports_actual_contact_rise(self):
        args=storage_inputs();args[2]['environment']='air'
        args[-1]['component_storage']['U1'].update(exposed_area_mm2=10000,h_w_m2k=50,emissivity=0)
        output=service_study(args)
        part=output['quick_therm']['components'][0]
        self.assertAlmostEqual(part['junction_c'],22,10)
        self.assertAlmostEqual(part['rise_local_k'],2,10)

    def test_service_body_storage_retains_unknown_junction(self):
        args=storage_inputs(kind='body')
        output=service_study(args)
        part=output['quick_therm']['components'][0]
        self.assertIsNone(part['junction_c'])
        self.assertIsNone(part['rise_local_k'])
        self.assertAlmostEqual(part['body_c'],24,10)

    def test_actual_board_kernel_single_rc_analytical_and_time_refinement(self):
        exact = 20+4*(1-math.exp(-2))  # P=2 W, R=2 K/W, C=.5 J/K.
        errors=[]
        for step in (.1,.025,.00625):
            solved=solve_multilayer_thermal(*storage_inputs(step=step))
            part=solved['components'][0]
            transient=solved['transient']; definition=transient['components'][0]
            ni=definition['storage_node']
            self.assertAlmostEqual(part['junction_c'],24,10)
            self.assertAlmostEqual(part['board_site_c'],20,10)
            self.assertAlmostEqual(part['contact_heat_w'],2,10)
            self.assertAlmostEqual(solved['heat_balance']['input_w'],2,12)
            self.assertEqual(definition['temperature_kind'],'junction')
            self.assertNotIn('junction_resistance_k_per_w',definition)
            errors.append(abs(transient['final_temperatures_c'][ni]-exact))
            self.assertLess(transient['max_energy_residual_w'],1e-8)
            self.assertAlmostEqual(sum(row['input_energy_j'] for row in transient['energy_balance']),4,11)
            json.dumps(solved,allow_nan=False)
        self.assertLess(errors[2],errors[1]);self.assertLess(errors[1],errors[0])
        self.assertLess(errors[2],.004)

    def test_step_event_is_continuous_component_state_and_no_double_heating(self):
        args=storage_inputs(duration=2,step=.01)
        settings=args[-1]
        settings['transient_settings'].update(schedule_interpolation='step',power_schedules={'U1':[[0,1],[.5,0]]})
        solved=solve_multilayer_thermal(*args)
        transient=solved['transient']; ni=transient['components'][0]['storage_node']
        event=next(row for row in transient['frames'] if row['time_s']==.5)
        expected_event=20+4*(1-math.exp(-.5))
        expected_end=20+(expected_event-20)*math.exp(-1.5)
        self.assertAlmostEqual(event['temperatures_c'][ni],expected_event,delta=.007)
        self.assertGreater(event['temperatures_c'][ni],21.5)
        self.assertAlmostEqual(transient['final_temperatures_c'][ni],expected_end,delta=.003)
        energy=transient['energy_balance']
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in energy),1,12)
        self.assertAlmostEqual(sum(row['input_energy_j']-row['boundary_energy_j'] for row in energy),
                               .5*(transient['final_temperatures_c'][ni]-20),10)

    def test_long_time_agrees_with_same_steady_graph(self):
        solved=solve_multilayer_thermal(*storage_inputs(duration=20,step=.1))
        ni=solved['transient']['components'][0]['storage_node']
        self.assertAlmostEqual(solved['transient']['final_temperatures_c'][ni],
                               solved['components'][0]['component_temperature_c'],delta=1e-6)

    def test_body_does_not_imply_junction_even_when_legacy_resistance_present(self):
        args=storage_inputs(kind='body')
        args[-1]['component_to_board_k_per_w']={'U1':50}
        args[-1]['component_storage']['U1']['initial_c']=37
        solved=solve_multilayer_thermal(*args)
        part=solved['components'][0]; definition=solved['transient']['components'][0]
        self.assertEqual(part['temperature_kind'],'body')
        self.assertEqual(part['body_c'],part['component_temperature_c'])
        self.assertIsNone(part['junction_c'])
        self.assertIsNone(part['junction_peak_proxy_c'])
        self.assertEqual(solved['transient']['frames'][0]['temperatures_c'][definition['storage_node']],37)
        self.assertEqual(definition['initial_c'],37)
        self.assertNotIn('junction_resistance_k_per_w',definition)

    def test_two_capacity_reference_and_unequal_initial_states_conserve_energy(self):
        # Two isolated thermal masses: d(T1-T2)/dt=-G*(1/C1+1/C2)*(T1-T2).
        initial=np.array([40.,20.]); capacity=np.array([2.,3.]); conductance=.5
        graph=csr_matrix([[conductance,-conductance],[-conductance,conductance]])
        solved=evolve(graph,capacity,{},[0,0],[0,0],[0,0],20,[0,0],[0,0],{},
                      {'duration_s':2,'timestep_s':.002},initial_temperatures_c=initial)
        exact=expm(-np.diag(1/capacity)@graph.toarray()*2)@initial
        np.testing.assert_allclose(solved['final_temperatures_c'],exact,atol=.002)
        self.assertAlmostEqual(np.dot(capacity,solved['final_temperatures_c']),np.dot(capacity,initial),9)
        self.assertLess(solved['max_energy_residual_w'],1e-9)
        np.testing.assert_array_equal(initial,[40,20])

    def test_full_board_component_storage_energy_is_capacity_weighted(self):
        geometry,view,result,settings=inputs()
        result['components'][0]['power_w']=0
        settings.update(board_emissivity=0, component_storage={'U1':{
            'capacity_j_k':2,'resistance_k_per_w':3,'temperature_kind':'body','initial_c':50}},
            transient_settings={'duration_s':1,'timestep_s':.01,
                                'copper_volumetric_capacity_j_m3k':3.45e6,
                                'dielectric_volumetric_capacity_j_m3k':1.8e6})
        solved=solve_multilayer_thermal(geometry,view,result,settings)
        transient=solved['transient']; definition=transient['components'][0]; nboard=definition['storage_node']
        first=transient['frames'][0]['temperatures_c']; last=transient['final_temperatures_c']
        cell_capacity=(.5e-3)**2*(.035e-3*3.45e6+(.001565-.000035)/2*1.8e6)
        change=cell_capacity*sum(last[i]-first[i] for i in range(nboard))+2*(last[nboard]-first[nboard])
        self.assertAlmostEqual(change,sum(row['stored_energy_change_j'] for row in transient['energy_balance']),9)
        self.assertAlmostEqual(change,-sum(row['boundary_energy_j'] for row in transient['energy_balance']),9)
        self.assertLess(last[nboard],50)
        self.assertGreater(max(last[:nboard]),20)

    def test_sink_path_receives_component_heat_once(self):
        geometry,view,result,settings=inputs()
        result['components'][0]['heat_path']='heatsink'
        settings.update(sink_exposed_area_mm2={'U1':5000},sink_emissivity=0,
            component_to_sink_k_per_w={'U1':100},
            component_storage={'U1':{'capacity_j_k':.5,'resistance_k_per_w':2,'temperature_kind':'junction'}},
            transient_settings={'duration_s':2,'timestep_s':.025,
                                'sink_capacity_j_k':{'U1':1},
                                'copper_volumetric_capacity_j_m3k':3.45e6,
                                'dielectric_volumetric_capacity_j_m3k':1.8e6})
        solved=solve_multilayer_thermal(geometry,view,result,settings)
        part=solved['components'][0]; definition=solved['transient']['components'][0]
        self.assertAlmostEqual(part['junction_c']-part['sink_c'],2,10)
        self.assertEqual(len(definition['nodes']),1)
        self.assertNotEqual(definition['nodes'][0][0],definition['storage_node'])
        self.assertAlmostEqual(solved['heat_balance']['input_w'],1,12)
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in solved['transient']['energy_balance']),2,12)
        self.assertLess(solved['transient']['max_energy_residual_w'],1e-8)

    def test_empty_mapping_preserves_legacy_fields_and_results(self):
        args=inputs();args[-1]['component_to_board_k_per_w']={'U1':2}
        baseline=solve_multilayer_thermal(*copy.deepcopy(args))
        args[-1]['component_storage']={}
        explicit=solve_multilayer_thermal(*args)
        self.assertEqual(explicit,baseline)
        self.assertNotIn('storage_node',explicit['components'][0])

    def test_bad_storage_inputs_reject_instead_of_filling_defaults(self):
        valid={'capacity_j_k':1,'resistance_k_per_w':2,'temperature_kind':'body'}
        bad=[None,[],{'unknown':valid},{'U1':{}},{'U1':{**valid,'capacity_j_k':0}},
             {'U1':{**valid,'resistance_k_per_w':float('inf')}},
             {'U1':{**valid,'capacity_j_k':True}}, {'U1':{**valid,'initial_c':-300}},
             {'U1':{**valid,'initial_c':float('nan')}}, {'U1':{**valid,'temperature_kind':'case'}},
             {'U1':{**valid,'invented':1}}]
        for value in bad:
            args=inputs();args[-1]['component_storage']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                solve_multilayer_thermal(*args)

    def test_initial_vector_validation_and_fixed_boundary_override(self):
        args=(csr_matrix((1,1)),[1],{},[1],[1],[0],20,[0],[0],{},
              {'duration_s':1,'timestep_s':.1})
        for initial in ([float('nan')],[-300],[],[20,30]):
            with self.subTest(initial=initial),self.assertRaises(ValueError):
                evolve(*args,initial_temperatures_c=initial)
        changed=list(args);changed[-2]={0:25}
        solved=evolve(*changed,initial_temperatures_c=[40])
        self.assertEqual(solved['frames'][0]['temperatures_c'],[25])
        self.assertEqual(solved['final_temperatures_c'],[25])

    def test_unpowered_steady_display_anchor_is_not_a_transient_heat_sink(self):
        geometry,view,result,settings=inputs('vacuum')
        result['components'][0]['power_w']=0
        settings.update(board_emissivity=0, component_storage={'U1':{
            'capacity_j_k':2,'resistance_k_per_w':3,'temperature_kind':'body','initial_c':50}},
            transient_settings={'duration_s':2,'timestep_s':.025,
                                'copper_volumetric_capacity_j_m3k':3.45e6,
                                'dielectric_volumetric_capacity_j_m3k':1.8e6})
        solved=solve_multilayer_thermal(geometry,view,result,settings)
        self.assertEqual(solved['mesh']['unexcited_regions_anchored_at_ambient'],1)
        transient=solved['transient'];ni=transient['components'][0]['storage_node']
        self.assertLess(transient['final_temperatures_c'][ni],50)
        self.assertGreater(max(transient['final_temperatures_c'][:ni]),20)
        self.assertAlmostEqual(sum(row['boundary_energy_j'] for row in transient['energy_balance']),0,12)
        self.assertAlmostEqual(sum(row['stored_energy_change_j'] for row in transient['energy_balance']),0,9)

    def test_mixed_storage_and_legacy_sources_keep_stable_node_ownership(self):
        geometry,view,result,settings=inputs()
        view['components'].append({'reference':'U2','position_mm':[8,8],
                                   'bbox_mm':[7,7,9,9],'side':'bottom','on_board':True})
        view['components'].append({'reference':'U3','position_mm':[3,3],
                                   'bbox_mm':[2,2,4,4],'side':'top','on_board':True})
        result['components'].extend([{'reference':'U2','power_w':2,'heat_path':'board'},
                                     {'reference':'U3','power_w':3,'heat_path':'board'}])
        settings['component_storage']={
            'U2':{'capacity_j_k':1,'resistance_k_per_w':2,'temperature_kind':'junction'},
            'U1':{'capacity_j_k':1,'resistance_k_per_w':2,'temperature_kind':'body'}}
        settings['transient_settings']={'duration_s':.5,'timestep_s':.1,
                                        'copper_volumetric_capacity_j_m3k':3.45e6,
                                        'dielectric_volumetric_capacity_j_m3k':1.8e6}
        solved=solve_multilayer_thermal(geometry,view,result,settings)
        rows={row['reference']:row for row in solved['transient']['components']}
        self.assertLess(rows['U1']['storage_node'],rows['U2']['storage_node'])
        self.assertNotIn('storage_node',rows['U3'])
        self.assertIn('junction_resistance_k_per_w',rows['U3'])
        self.assertAlmostEqual(solved['heat_balance']['input_w'],6,12)
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in solved['transient']['energy_balance']),3,12)
        settings['component_storage']=dict(reversed(list(settings['component_storage'].items())))
        reordered=solve_multilayer_thermal(geometry,view,result,settings)
        self.assertEqual(solved['transient']['components'],reordered['transient']['components'])

    def test_explicit_component_surface_air_parallel_path_analytical(self):
        args=storage_inputs(kind='body',duration=3,step=.01)
        args[2]['environment']='air'
        spec=args[-1]['component_storage']['U1']
        spec.update(exposed_area_mm2=10000,h_w_m2k=50,emissivity=0)
        solved=solve_multilayer_thermal(*args)
        # Rcontact=2 -> .5 W/K; hA=.5 W/K; P=2 W, C=.5 J/K.
        part=solved['components'][0]
        self.assertAlmostEqual(part['body_c'],22,10)
        self.assertAlmostEqual(part['contact_heat_w'],1,10)
        self.assertAlmostEqual(part['convection_w'],1,10)
        balance=solved['heat_balance']
        self.assertAlmostEqual(balance['component_convection_w'],1,10)
        self.assertEqual(balance['sink_convection_w'],0)
        transient=solved['transient'];ni=transient['components'][0]['storage_node']
        exact=20+2*(1-math.exp(-6))
        self.assertAlmostEqual(transient['final_temperatures_c'][ni],exact,delta=.0005)
        self.assertLess(transient['max_energy_residual_w'],1e-8)

    def test_explicit_vacuum_component_radiation_is_separate_and_balanced(self):
        from scipy.optimize import brentq
        args=storage_inputs(kind='body')
        args[-1]['component_storage']['U1'].update(exposed_area_mm2=10000,h_w_m2k=0,emissivity=.9)
        solved=solve_multilayer_thermal(*args)
        expected=brentq(lambda t: .5*(t-20)+.01*.9*5.670374419e-8*((t+273.15)**4-293.15**4)-2,20,30)
        part=solved['components'][0]
        self.assertAlmostEqual(part['body_c'],expected,9)
        self.assertEqual(part['convection_w'],0)
        self.assertGreater(part['radiation_w'],0)
        self.assertEqual(solved['heat_balance']['sink_radiation_w'],0)
        self.assertAlmostEqual(part['contact_heat_w']+part['radiation_w'],2,10)
        self.assertLess(solved['transient']['max_energy_residual_w'],1e-8)

    def test_incomplete_or_invalid_component_surface_properties_rejected(self):
        surface={'exposed_area_mm2':100,'h_w_m2k':0,'emissivity':.8}
        for update in ({'exposed_area_mm2':100},{'h_w_m2k':0,'emissivity':.8},
                       {**surface,'exposed_area_mm2':0},{**surface,'h_w_m2k':-1},
                       {**surface,'emissivity':1.1},{**surface,'h_w_m2k':1},
                       {**surface,'emissivity':True},{**surface,'exposed_area_mm2':float('nan')}):
            args=storage_inputs();args[-1]['component_storage']['U1'].update(update)
            with self.subTest(update=update),self.assertRaises(ValueError):
                solve_multilayer_thermal(*args)

    def test_sink_storage_may_reject_heat_through_component_surface_only(self):
        args=inputs();args[2]['components'][0]['heat_path']='heatsink'
        args[-1].update(sink_exposed_area_mm2={'U1':100},sink_h_w_m2k=0,sink_emissivity=0,
            component_storage={'U1':{'capacity_j_k':.5,'resistance_k_per_w':2,
                'temperature_kind':'body','exposed_area_mm2':10000,'h_w_m2k':100,'emissivity':0}})
        solved=solve_multilayer_thermal(*args)
        self.assertAlmostEqual(solved['components'][0]['body_c'],21,10)
        self.assertAlmostEqual(solved['components'][0]['sink_c'],21,10)
        self.assertAlmostEqual(solved['heat_balance']['component_convection_w'],1,10)
        self.assertEqual(solved['heat_balance']['sink_convection_w'],0)
        args[-1]['component_storage']['U1']['h_w_m2k']=0
        with self.assertRaisesRegex(ValueError,'no convection, radiation or fixture path'):
            solve_multilayer_thermal(*args)

    def test_planar_copper_watts_conserved_on_declared_layer_and_schedule(self):
        args=inputs();args[2]['components']=[];args[1]['components']=[]
        args[-1].update(board_emissivity=0,copper_loss_sources=[{
            'id':'copper:triangle0','layer_id':31,'polygon_mm':[[1,1],[3,1],[1,3]],'power_w':2}],
            transient_settings={'duration_s':1,'timestep_s':.1,'schedule_interpolation':'step',
                                'power_schedules':{'copper:triangle0':[[0,1],[.25,0]]},
                                'copper_volumetric_capacity_j_m3k':3.45e6,
                                'dielectric_volumetric_capacity_j_m3k':1.8e6})
        solved=solve_multilayer_thermal(*args)
        loss=solved['copper_loss_sources'][0];ncell=solved['mesh']['active_cells_per_layer']
        self.assertEqual(loss['area_mm2'],2)
        self.assertAlmostEqual(loss['mapped_area_mm2'],2,12)
        self.assertAlmostEqual(sum(w for _,w in loss['nodes']),1,12)
        self.assertTrue(all(ncell<=ni<2*ncell for ni,_ in loss['nodes']))
        self.assertAlmostEqual(solved['heat_balance']['input_w'],2,12)
        self.assertEqual(solved['heat_balance']['component_input_w'],0)
        self.assertEqual(solved['heat_balance']['copper_loss_input_w'],2)
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in solved['transient']['energy_balance']),.5,12)
        self.assertEqual(solved['transient']['components'],[])
        self.assertLess(solved['transient']['max_energy_residual_w'],1e-8)

    def test_copper_mapping_rejects_lost_area_copper_gaps_and_drills(self):
        record={'id':'copper:p','layer_id':0,'polygon_mm':[[1,1],[3,1],[3,3],[1,3]],'power_w':1}
        for failure in ('outside','cutout','copper_gap','drill','slot'):
            args=inputs();args[-1]['copper_loss_sources']=[copy.deepcopy(record)]
            if failure=='outside':args[-1]['copper_loss_sources'][0]['polygon_mm']=[[-1,1],[1,1],[1,3],[-1,3]]
            elif failure=='cutout':args[0]['outline'][0]['holes_mm']=[[[1.5,1.5],[2.5,1.5],[2.5,2.5],[1.5,2.5]]]
            elif failure=='copper_gap':args[0]['layers'][0]['polygons_mm'][0]['holes']=[[[1.5,1.5],[2.5,1.5],[2.5,2.5],[1.5,2.5]]]
            else:args[0]['mounting_holes'].append({'id':'void','x_mm':2,'y_mm':2,'drill_mm':.3,
                **({'drill_size_mm':[1.5,.3],'drill_angle_deg':37} if failure=='slot' else {})})
            with self.subTest(failure=failure),self.assertRaisesRegex(ValueError,'supported|drill void'):
                solve_multilayer_thermal(*args)

    def test_bad_copper_records_do_not_fall_back_to_component_sources(self):
        valid={'id':'copper:p','layer_id':0,'polygon_mm':[[1,1],[3,1],[1,3]],'power_w':1}
        invalid=[None,{},[dict(valid,id='p')],[valid,valid], [dict(valid,power_w=-1)],
                 [dict(valid,power_w=True)],[dict(valid,power_w=float('nan'))],
                 [dict(valid,layer_id=7)], [dict(valid,polygon_mm=[[1,1],[2,2],[3,3]])],
                 [dict(valid,polygon_mm=[[1,1],[3,1],[2,1.5],[3,3],[1,3]])],
                 [dict(valid,polygon_mm=[[float('inf'),1],[3,1],[1,3]])]]
        for record in invalid:
            args=inputs();args[-1]['copper_loss_sources']=record
            with self.subTest(record=record),self.assertRaises(ValueError):
                solve_multilayer_thermal(*args)

    def test_via_loss_reuses_resolved_barrel_stencil_and_rejects_unknown_contacts(self):
        args=inputs();g,v,r,s=args
        land={'outer':[[5,5],[7,5],[7,7],[5,7]],'holes':[]}
        g['barrels']=[{'id':'V1','x_mm':6,'y_mm':6,'drill_mm':.3,'span_layers':[0,31],
                        'outer_diameters_mm':{'0':2,'31':2},'land_polygons_mm':{'0':[land],'31':[land]}}]
        s['copper_loss_sources']=[{'id':'copper:via:V1:0-31','barrel_id':'V1','top_layer':0,'bottom_layer':31,'power_w':.2}]
        solved=solve_multilayer_thermal(*args);loss=solved['copper_loss_sources'][0]
        ncell=solved['mesh']['active_cells_per_layer']
        self.assertAlmostEqual(sum(w for ni,w in loss['nodes'] if ni<ncell),.5,12)
        self.assertAlmostEqual(sum(w for ni,w in loss['nodes'] if ni>=ncell),.5,12)
        self.assertAlmostEqual(loss['mapped_power_w'],.2,12)
        self.assertAlmostEqual(solved['heat_balance']['input_w'],1.2,12)
        g['barrels'][0]['land_polygons_mm']={}
        with self.assertRaisesRegex(ValueError,'resolved barrel contact'):
            solve_multilayer_thermal(*args)
        g['barrels'][0]['land_polygons_mm']={'0':[land],'31':[land]};s['barrel_contact_mode']='nearest_cell'
        with self.assertRaisesRegex(ValueError,'resolved barrel contact'):
            solve_multilayer_thermal(*args)
