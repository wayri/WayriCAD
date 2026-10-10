"""Physical-contact network references, heat reversal and conservation."""
import copy
import json
import math
import unittest

from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal
from quick_therm_plugin.thermal_review import transient_frame_network
from quick_therm_plugin.tests.test_thermal_multilayer import inputs
from quick_therm_plugin.tests.test_component_storage import service_study
from wayricad_runtime.package_conduction import normalize_paths


def physical_inputs(*, power=2, second_temperature=20, transient=False):
    geometry, view, result, settings=inputs('vacuum')
    result['components'][0]['power_w']=power
    geometry['source_contacts']=[]
    paths=[]
    mounts=[]
    for index, x in enumerate((5.5, 6)):
        pad=str(index+1)
        polygon={'outer': [[x,5.5],[x+.5,5.5],[x+.5,6],[x,6]], 'holes': []}
        geometry['source_contacts'].append({'reference':'U1','pad_number':pad,'pad_uuid':'pad'+pad,
            'layer_id':0,'net':'PWR' if index==0 else 'GND','polygons_mm':[polygon]})
        geometry['mounting_holes'].append({'id':'fixed'+pad,'x_mm':x+.25,'y_mm':5.75,'plated':True})
        mounts.append({'id':'fixed'+pad,'temperature_c':20 if index==0 else second_temperature,
                       'contact_r_k_w':0})
        paths.append({'id':'U1-'+pad,'reference':'U1','pad_number':pad,'layer_id':0,
            'segments':[{'shape':'cylinder','length_mm':.2,'diameter_mm':.3,
                         'k_w_mk':50,'rho_ohm_m':1.3e-7,'material':'explicit test solder'}]})
    settings.update(board_emissivity=0,mount_boundaries=mounts,package_conduction=paths,
                    component_storage={'U1':{'temperature_kind':'body','resistance_k_per_w':0}})
    if transient:
        settings['component_storage']['U1']['capacity_j_k']=.5
        settings['transient_settings']={'duration_s':2,'timestep_s':.002,
            'copper_volumetric_capacity_j_m3k':3.45e6,'dielectric_volumetric_capacity_j_m3k':1.8e6}
    return geometry,view,result,settings


class PhysicalThermalTests(unittest.TestCase):
    def test_parallel_contacts_are_solved_with_conservative_net_heat(self):
        args=physical_inputs()
        solved=solve_multilayer_thermal(*args)
        part=solved['components'][0]
        r=1000*.2/(50*math.pi*.15**2)
        self.assertAlmostEqual(part['body_c'],20+2*r/2,9)
        self.assertIsNone(part['junction_c'])
        self.assertAlmostEqual(part['contact_heat_w'],2,10)
        self.assertAlmostEqual(sum(row['heat_flow_to_board_w'] for row in solved['package_conduction']),2,10)
        for row in solved['package_conduction']:
            self.assertAlmostEqual(row['heat_flow_to_board_w'],1,10)
            self.assertIsNone(row['electrical_joule_heat_w'])
        self.assertLess(abs(solved['heat_balance']['residual_w']),1e-8)
        json.dumps(solved,allow_nan=False)

    def test_hot_board_can_heat_package_at_zero_dissipation(self):
        args=physical_inputs(power=0,second_temperature=40)
        args[-1]['package_conduction'][1]['segments'][0]['length_mm']=.4
        solved=solve_multilayer_thermal(*args)
        # R2=2 R1, G1=2 G2. This checks sharing against unequal pad temperatures.
        self.assertAlmostEqual(solved['components'][0]['body_c'],(2*20+40)/3,9)
        flows=[row['heat_flow_to_board_w'] for row in solved['package_conduction']]
        self.assertGreater(flows[0],0);self.assertLess(flows[1],0)
        self.assertAlmostEqual(sum(flows),0,10)
        self.assertAlmostEqual(solved['components'][0]['source_peak_c'],40,9)
        self.assertEqual(solved['components'][0]['source_peak_cell']['layer_id'],0)

    def test_contact_transient_analytical_capacity_and_frame_readout(self):
        args=physical_inputs(transient=True)
        solved=solve_multilayer_thermal(*args)
        data=solved['transient'];ni=data['components'][0]['storage_node']
        r=1000*.2/(50*math.pi*.15**2)/2
        expected=20+2*r*(1-math.exp(-2/(r*.5)))
        self.assertAlmostEqual(data['final_temperatures_c'][ni],expected,delta=.001)
        self.assertLess(data['max_energy_residual_w'],1e-8)
        frame=transient_frame_network(solved,len(data['frames'])-1)
        self.assertAlmostEqual(frame['components'][0]['body_c'],data['final_temperatures_c'][ni],10)
        self.assertAlmostEqual(frame['components'][0]['contact_heat_w'],
                               sum(row['heat_flow_to_board_w'] for row in frame['package_conduction']),10)

    def test_reject_double_counts_ambiguous_missing_and_oversize_contacts(self):
        for problem in ('RthetaJB','RC','missing','ambiguous','duplicate','oversize','capacity'):
            args=physical_inputs()
            g,v,r,s=args
            if problem=='RthetaJB':s['component_to_board_k_per_w']={'U1':5}
            if problem=='RC':s['component_storage']['U1']['resistance_k_per_w']=5
            if problem=='missing':g['source_contacts'].pop()
            if problem=='ambiguous':g['source_contacts'].append(copy.deepcopy(g['source_contacts'][0]))
            if problem=='duplicate':s['package_conduction'].append({**copy.deepcopy(s['package_conduction'][0]),'id':'same-pad'})
            if problem=='oversize':s['package_conduction'][0]['segments'][0]['diameter_mm']=1
            if problem=='capacity':
                s['transient_settings']={'duration_s':1,'timestep_s':.1}
            with self.subTest(problem=problem),self.assertRaises(ValueError):
                solve_multilayer_thermal(*args)

    def test_service_preserves_physical_temperature_and_source_immutability(self):
        args=physical_inputs()
        args[-1]['component_storage']['U1']['temperature_kind']='junction'
        solved=service_study(args)
        row=solved['quick_therm']['components'][0]
        model=solved['thermal_network']['components'][0]
        self.assertAlmostEqual(row['junction_c'],model['component_temperature_c'],10)
        self.assertAlmostEqual(row['rise_local_k'],model['component_temperature_c']-model['board_site_c'],10)

    def test_joint_joule_heat_heats_package_and_board_once(self):
        args=physical_inputs(power=0,transient=True)
        settings=args[-1]
        sources=[]
        for path in settings['package_conduction']:
            row=normalize_paths([path],physics='electrical')[0]
            sources.append({'id':path['id'],'definition':row['definition'],'current_a':2,
                            'power_w':4*row['electrical_resistance_ohm']})
        settings['package_joule_losses']=sources
        solved=solve_multilayer_thermal(*args)
        r=1000*.2/(50*math.pi*.15**2)
        q=sources[0]['power_w']
        self.assertAlmostEqual(solved['components'][0]['body_c'],20+q*r/2,10)
        self.assertAlmostEqual(solved['components'][0]['contact_heat_w'],0,10)
        self.assertAlmostEqual(solved['heat_balance']['input_w'],2*q,13)
        self.assertAlmostEqual(solved['heat_balance']['package_joule_input_w'],2*q,13)
        for row in solved['package_conduction']:
            self.assertAlmostEqual(row['heat_flow_to_board_w'],q,11)
            self.assertAlmostEqual(row['heat_flow_from_package_w'],0,11)
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in solved['transient']['energy_balance']),4*q,12)
        frame=transient_frame_network(solved,len(solved['transient']['frames'])-1)
        for row in frame['package_conduction']:
            self.assertAlmostEqual(row['heat_flow_to_board_w']-row['heat_flow_from_package_w'],q,12)

    def test_series_joint_heat_uses_thermal_resistance_midpoints(self):
        args=physical_inputs(power=0)
        path=args[-1]['package_conduction'][0]
        path['segments'].insert(0,{'shape':'cylinder','length_mm':1,'diameter_mm':.2,
            'k_w_mk':385,'rho_ohm_m':1.724e-8})
        data=normalize_paths([path],physics='electrical')[0]
        q=[4*row['electrical_resistance_ohm'] for row in data['segments']]
        rt=[row['thermal_resistance_k_per_w'] for row in data['segments']]
        args[-1]['package_joule_losses']=[{'id':path['id'],'definition':data['definition'],
            'current_a':2,'power_w':sum(q)}]
        solved=solve_multilayer_thermal(*args)
        actual=solved['package_conduction'][0]
        expected=q[0]*(rt[0]/2)/sum(rt)+q[1]*(rt[0]+rt[1]/2)/sum(rt)
        self.assertAlmostEqual(actual['joule_into_board_w'],expected,13)
        self.assertAlmostEqual(actual['joule_into_package_w']+actual['joule_into_board_w'],sum(q),13)
        self.assertNotAlmostEqual(actual['joule_into_board_w'],sum(q)/2,8)
        self.assertLess(abs(solved['heat_balance']['residual_w']),1e-8)

    def test_reject_joint_heat_without_matching_geometry_or_known_location(self):
        for change in ('identity','geometry','current','lumped'):
            args=physical_inputs(power=0)
            path=args[-1]['package_conduction'][0]
            electrical=normalize_paths([path],physics='electrical')[0]
            loss={'id':path['id'],'definition':electrical['definition'],'current_a':2,
                  'power_w':4*electrical['electrical_resistance_ohm']}
            if change=='identity':loss['id']='missing'
            if change=='geometry':loss['definition']['segments'][0]['length_mm']=.3
            if change=='current':loss['current_a']=3
            if change=='lumped':path['additional_thermal_k_per_w']=1
            args[-1]['package_joule_losses']=[loss]
            with self.subTest(change=change),self.assertRaises(ValueError):
                solve_multilayer_thermal(*args)


if __name__=='__main__':unittest.main()
