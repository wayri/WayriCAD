"""Independent references for persistent lumped electrothermal coupling."""
from copy import deepcopy
import json
import math
import unittest
from unittest.mock import patch

import numpy as np
from scipy.integrate import solve_ivp

from quick_pi_plugin.electrothermal_transient import solve_electrothermal_transient
from quick_pi_plugin.transient import RailStateStepper, TransientError, solve_transient
from wayricad_runtime.thermal_rc import advance_thermal_rc


def request(alpha=.00393, **updates):
    result = dict(duration_s=.01,step_s=.0001,exchange_step_s=.001,
        source_voltage_V=5.,source_resistance_ohm=.2,source_inductance_H=0.,
        ambient_c=20.,loads=[dict(id='A',label='Load A',initial_current_A=.2,
            step_current_A=1.2,step_time_s=.001,path_resistance_ohm=.3,
            path_inductance_H=0.,capacitance_F=.002,esr_ohm=.02)],
        thermal_nodes=[dict(id='rail',label='Conductors',resistance_K_W=20.,
            capacitance_J_K=.01,initial_temperature_c=20.,initial_power_W=0.,
            step_power_W=0.,step_time_s=.003,max_temperature_c=100.)],
        resistance_mappings=[dict(element_id=element,thermal_node_id='rail',
            reference_temperature_c=20.,alpha_per_K=alpha,min_temperature_c=-40.,
            max_temperature_c=150.) for element in ('source','path:A','esr:A')])
    result.update(updates)
    return result


def rail_request(value):
    return {key:item for key,item in value.items() if key not in
            {'exchange_step_s','ambient_c','thermal_nodes','resistance_mappings','coupling'}}


class ThermalStateTests(unittest.TestCase):
    def test_exact_heating_cooling_and_inward_ambient_energy(self):
        for initial,power in ((20.,2.),(60.,0.),(5.,0.)):
            with self.subTest(initial=initial,power=power):
                output = advance_thermal_rc(initial,20.,10.,.2,power,.7)
                expected = 20.+10.*power+(initial-20.-10.*power)*math.exp(-.7/2.)
                self.assertAlmostEqual(output['temperature_c'],expected,12)
                self.assertLess(output['relative_residual'],1e-14)
                self.assertAlmostEqual(output['input_J']-output['to_ambient_J'],output['stored_change_J'],12)
                if initial < 20: self.assertLess(output['to_ambient_J'],0.)

    def test_thermal_state_advances_once_and_composes(self):
        first = advance_thermal_rc(20.,20.,7.,.4,3.,.03)
        second = advance_thermal_rc(first['temperature_c'],20.,7.,.4,3.,.07)
        whole = advance_thermal_rc(20.,20.,7.,.4,3.,.1)
        self.assertAlmostEqual(second['temperature_c'],whole['temperature_c'],13)
        for key in ('input_J','to_ambient_J','stored_change_J'):
            self.assertAlmostEqual(first[key]+second[key],whole[key],13)

    def test_tiny_interval_energy_and_explicit_invalid_scales(self):
        output = advance_thermal_rc(25.,25.,10.,.1,1.,1e-10)
        self.assertLess(output['relative_residual'],1e-14)
        self.assertAlmostEqual(output['stored_change_J'],1e-10,delta=1e-18)
        for args in ((25,25,0,.1,1,.1),(25,25,1,0,1,.1),
                     (25,25,1,.1,-1,.1),(25,25,1,.1,1,0),
                     (-300,25,1,.1,1,.1),(25,25,True,.1,1,.1)):
            with self.subTest(args=args), self.assertRaises(ValueError): advance_thermal_rc(*args)


class RailStateTests(unittest.TestCase):
    def test_persistent_steps_reproduce_legacy_trajectory_without_dc_reset(self):
        value = rail_request(request(0,duration_s=.001))
        value['loads'][0].update(step_time_s=0.,path_inductance_H=.001)
        model = RailStateStepper(value); state = model.initial_state()
        state = model.project_state(state,[1.2])
        first,_,_ = model.advance(state,.0001)
        second,q,ledger = model.advance(first,.0001)
        legacy = solve_transient(value)
        index = legacy['times_s'].index(.0002)
        self.assertAlmostEqual(second['current_A'][0],legacy['loads'][0]['current_A'][index],13)
        self.assertAlmostEqual(second['capacitor_voltage_V'][0],legacy['loads'][0]['capacitor_voltage_V'][index],13)
        self.assertNotEqual(second['capacitor_voltage_V'],model.initial_state()['capacitor_voltage_V'])
        self.assertEqual(first['requested_current_A'],[1.2])
        self.assertLess(abs(ledger['energy_residual_J']),1e-14)
        self.assertEqual(q['current'][0],second['current_A'][0])

    def test_resistance_update_preserves_inductive_and_capacitor_state(self):
        value = rail_request(request(0,duration_s=.001))
        value['loads'][0].update(step_time_s=0.,path_inductance_H=.001)
        cold = RailStateStepper(value); start = cold.project_state(cold.initial_state(),[1.2])
        state,_,_ = cold.advance(start,.0001); original = deepcopy(state)
        hot = RailStateStepper(value,{'source':.4,'path:A':.6,'esr:A':.04})
        projected = hot.project_state(state)
        self.assertEqual(projected,state)
        self.assertEqual(state,original)
        end,_,ledger = hot.advance(projected,.0001)
        # Independent elimination of the one-branch BE equations.
        L=.001; C=.002; h=.0001; R=1.04; d=1.2
        current=(L*state['current_A'][0]/h+5.+.04*d-state['capacitor_voltage_V'][0]+h*d/C)/(L/h+R+h/C)
        self.assertAlmostEqual(end['current_A'][0],current,13)
        self.assertAlmostEqual(end['capacitor_voltage_V'][0],state['capacitor_voltage_V'][0]+h*(current-d)/C,13)
        self.assertLess(abs(ledger['energy_residual_J']),1e-14)

    def test_persistent_state_shape_and_override_validation(self):
        model = RailStateStepper(rail_request(request()))
        state = model.initial_state()
        for bad in ({},{**state,'current_A':[float('nan')]},{**state,'current_A':[]},
                    {**state,'requested_current_A':[-1]}):
            with self.subTest(bad=bad),self.assertRaises(TransientError): model.advance(bad,.001)
        for overrides in ({'unknown':1.},{'source':0.},{'path:A':-1.}):
            with self.subTest(overrides=overrides),self.assertRaises(TransientError): RailStateStepper(rail_request(request()),overrides)
        other=rail_request(request()); other['loads'][0]['capacitance_F'] *= 2
        with self.assertRaisesRegex(TransientError,'different load identities'):
            RailStateStepper(other).advance(state,.001)


class ElectrothermalTests(unittest.TestCase):
    def assert_balanced(self,result):
        self.assertEqual(result['status'],'completed',result.get('issues'))
        self.assertTrue(result['checks']['coupling_converged'])
        for name in ('baseline','coupled'):
            checks=result[name]['checks']
            self.assertEqual(checks['balance_status'],'PASSED')
            self.assertLess(checks['electrical']['energy_relative_error'],1e-10)
            self.assertLess(checks['thermal']['relative_residual'],1e-10)
            self.assertLess(checks['combined_energy_relative_error'],1e-10)
            self.assertLess(abs(checks['transfer_residual_J']),1e-12)
            self.assertAlmostEqual(checks['thermal']['resistor_input_J'],checks['electrical']['resistive_loss_energy_J'],13)
        json.dumps(result,allow_nan=False)

    def test_zero_alpha_matches_legacy_and_one_way_exact_heat(self):
        value=request(0); result=solve_electrothermal_transient(value); legacy=solve_transient(rail_request(value))
        lookup={(time,phase):index for index,(time,phase) in enumerate(zip(result['coupled']['times_s'],result['coupled']['sample_phase']))}
        for index,(time,phase) in enumerate(zip(legacy['times_s'],legacy['sample_phase'])):
            key=(time,phase)
            if key not in lookup: key=(time,'step_before')
            match=lookup[key]
            self.assertAlmostEqual(result['coupled']['loads'][0]['voltage_V'][match],legacy['loads'][0]['voltage_V'][index],12)
        self.assertEqual(result['baseline']['loads'],result['coupled']['loads'])
        self.assertEqual(result['baseline']['thermal_nodes'],result['coupled']['thermal_nodes'])
        self.assertTrue(all(row['iterations']==1 for row in result['coupled']['checks']['exchange_history']))
        self.assert_balanced(result)

    def test_constant_current_coupled_heating_matches_closed_form(self):
        value=request(.00393,duration_s=.05,step_s=.0001,exchange_step_s=.0005)
        value['loads'][0].update(initial_current_A=2.,step_current_A=2.,step_time_s=0.,
                                 path_resistance_ohm=0.,esr_ohm=0.,capacitance_F=1e-10)
        value['thermal_nodes'][0].update(resistance_K_W=10.,capacitance_J_K=.01,step_time_s=0.)
        value['resistance_mappings']=value['resistance_mappings'][:1]
        result=solve_electrothermal_transient(value)
        A=4.*.2*10.; steady_rise=A/(1-.00393*A); rate=(4.*.2*.00393-.1)/.01
        expected=20.+steady_rise*(1-math.exp(rate*.05))
        self.assertAlmostEqual(result['coupled']['thermal_nodes'][0]['temperature_c'][-1],expected,delta=2e-5)
        self.assertGreater(result['coupled']['thermal_nodes'][0]['temperature_c'][-1],result['baseline']['thermal_nodes'][0]['temperature_c'][-1])
        self.assert_balanced(result)

    def test_rlc_coupling_matches_independent_high_accuracy_ode(self):
        value=request(.02,duration_s=.005,step_s=.000005,exchange_step_s=.0001)
        value['loads'][0].update(initial_current_A=0.,step_current_A=1.,step_time_s=0.,
                                 path_inductance_H=.0006,capacitance_F=.0001,esr_ohm=.05)
        value['source_inductance_H']=.0004
        value['thermal_nodes'][0].update(capacitance_J_K=.002,step_time_s=0.)
        for law in value['resistance_mappings']: law['min_temperature_c']=0.
        result=solve_electrothermal_transient(value)
        def derivative(t,state):
            current,capacitor,temperature=state; factor=1+.02*(temperature-20.)
            rs=.2*factor; rp=.3*factor; esr=.05*factor
            return [(5.-(rs+rp+esr)*current-capacitor+esr)/.001,
                    (current-1.)/.0001,
                    ((rs+rp)*current**2+esr*(current-1.)**2-(temperature-20.)/20.)/.002]
        reference=solve_ivp(derivative,(0,.005),[0.,5.,20.],method='DOP853',rtol=1e-11,atol=1e-12,dense_output=True)
        self.assertTrue(reference.success)
        curve=result['coupled']; errors=[]
        for index,time in enumerate(curve['times_s']):
            state=reference.sol(time)
            errors.append([abs(curve['loads'][0]['current_A'][index]-state[0]),
                           abs(curve['loads'][0]['capacitor_voltage_V'][index]-state[1]),
                           abs(curve['thermal_nodes'][0]['temperature_c'][index]-state[2])])
        self.assertLess(np.max(errors,axis=0)[0],.04)
        self.assertLess(np.max(errors,axis=0)[1],.11)
        self.assertLess(np.max(errors,axis=0)[2],.06)
        self.assert_balanced(result)

    def test_external_power_heating_cooling_and_exact_event_continuity(self):
        value=request(0,duration_s=.03,exchange_step_s=.002)
        value['loads'][0].update(initial_current_A=0.,step_current_A=0.,step_time_s=.00323)
        value['thermal_nodes'][0].update(initial_power_W=2.,step_power_W=0.,step_time_s=.01231)
        result=solve_electrothermal_transient(value); curve=result['coupled']; node=curve['thermal_nodes'][0]
        self.assertEqual(curve['times_s'].count(.01231),2)
        before=curve['sample_phase'].index('step_before',curve['times_s'].index(.01231)); after=before+1
        self.assertEqual(node['temperature_c'][before],node['temperature_c'][after])
        rise=40*(1-math.exp(-.01231/.2))
        expected=20+rise*math.exp(-(.03-.01231)/.2)
        self.assertAlmostEqual(node['temperature_c'][-1],expected,12)
        self.assertAlmostEqual(curve['checks']['thermal']['external_input_J'],2*.01231,13)
        self.assertEqual(curve['checks']['thermal']['resistor_input_J'],0.)
        self.assert_balanced(result)

    def test_esr_energy_maps_separately_and_storage_damping_are_not_heat(self):
        value=request(0)
        value['thermal_nodes'].append(dict(value['thermal_nodes'][0],id='capacitor',label='Capacitor ESR'))
        value['resistance_mappings'][2]['thermal_node_id']='capacitor'
        result=solve_electrothermal_transient(value); curve=result['coupled']
        self.assertGreater(curve['thermal_nodes'][1]['max_temperature_c'],20.)
        self.assertGreater(curve['checks']['electrical']['backward_euler_numerical_dissipation_J'],0.)
        total_loss=curve['checks']['electrical']['resistive_loss_energy_J']
        self.assertAlmostEqual(total_loss,curve['checks']['thermal']['resistor_input_J'],13)
        expected_esr=sum((right-left)*loss for left,right,loss in zip(
            curve['times_s'],curve['times_s'][1:],curve['loads'][0]['esr_loss_W'][1:]))
        self.assertAlmostEqual(curve['thermal_nodes'][1]['energy_balance']['resistor_input_J'],expected_esr,13)
        self.assertAlmostEqual(curve['checks']['resistor_energy_J']['esr:A'],expected_esr,13)
        self.assert_balanced(result)

    def test_multisink_shared_heating_and_diagnostic_budget_do_not_clip(self):
        value=request(); value['loads'].append(dict(value['loads'][0],id='B',step_current_A=.4,step_time_s=.00231))
        for element in ('path:B','esr:B'):
            value['resistance_mappings'].append(dict(value['resistance_mappings'][1],element_id=element))
        baseline=solve_electrothermal_transient(value); value['source_current_limit_A']=.1
        limited=solve_electrothermal_transient(value)
        self.assertEqual(limited['coupled']['source_current_A'],baseline['coupled']['source_current_A'])
        self.assertFalse(limited['feasibility']['feasible'])
        self.assertEqual(limited['feasibility']['source_current_limit_mode'],'diagnostic_only')
        np.testing.assert_allclose(limited['coupled']['source_current_A'],np.sum([row['current_A'] for row in limited['coupled']['loads']],axis=0),atol=1e-12)
        self.assert_balanced(limited)

    def test_independent_refinement_evidence_and_temperature_voltage_limits(self):
        value=request(); value['thermal_nodes'][0]['max_temperature_c']=20.01
        value['loads'][0]['min_voltage_V']=4.99
        result=solve_electrothermal_transient(value)
        self.assertFalse(result['feasibility']['feasible'])
        self.assertTrue(result['coupled']['thermal_nodes'][0]['violations'])
        self.assertTrue(result['coupled']['loads'][0]['violations'])
        self.assertFalse(result['coupled']['initialization']['feasible'])
        refinement=result['checks']['refinement']
        self.assertEqual(refinement['exchange']['status'],'CHECKED_NOT_CERTIFIED')
        self.assertGreater(refinement['exchange']['max_temperature_difference_c'],0.)
        self.assertGreater(refinement['integration']['max_load_voltage_difference_V'],0.)
        self.assertEqual(refinement['exchange']['reference_balance_status'],'PASSED')
        self.assert_balanced(result)

    def test_exchange_refinement_holds_actual_electrical_grid_fixed(self):
        result=solve_electrothermal_transient(request(0,step_s=.001,exchange_step_s=.001))
        checks=result['checks']['refinement']['exchange']
        self.assertEqual(checks['control_electrical_grid'],checks['reference_electrical_grid'])
        self.assertGreater(checks['additional_control_intervals'],0)
        self.assertLess(checks['max_source_current_difference_A'],1e-12)
        self.assertLess(checks['max_load_voltage_difference_V'],1e-12)
        self.assertGreater(checks['max_temperature_difference_c'],0.)
        self.assert_balanced(result)

    def test_electrical_refinement_halves_actual_exchange_bounded_substeps(self):
        result=solve_electrothermal_transient(request(0,step_s=.01,exchange_step_s=.001))
        checks=result['checks']['refinement']['integration']
        self.assertEqual(checks['reference_electrical_grid']['intervals'],2*checks['control_electrical_grid']['intervals'])
        self.assertAlmostEqual(checks['reference_electrical_grid']['max_interval_s'],checks['control_electrical_grid']['max_interval_s']/2,14)
        self.assertEqual(checks['control_exchange_grid'],checks['reference_exchange_grid'])
        self.assertGreater(checks['max_source_current_difference_A'],.01)
        self.assert_balanced(result)

    def test_shared_inductor_and_ideal_parallel_capacitors_retain_states(self):
        value=request(duration_s=.002,step_s=.00001,exchange_step_s=.0002,
                      source_inductance_H=.0001)
        value['loads'][0].update(initial_current_A=0.,step_current_A=1.,step_time_s=0.,
                                 path_resistance_ohm=0.,esr_ohm=0.,capacitance_F=.001)
        value['loads'].append(dict(value['loads'][0],id='B',step_current_A=0.,capacitance_F=.003))
        value['resistance_mappings']=value['resistance_mappings'][:1]
        value['thermal_nodes'][0]['step_time_s']=.0005
        result=solve_electrothermal_transient(value); curve=result['coupled']
        np.testing.assert_allclose(curve['loads'][0]['voltage_V'],curve['loads'][1]['voltage_V'],atol=1e-12)
        self.assertAlmostEqual(curve['source_current_A'][1],0.,12)
        self.assertEqual(curve['loads'][0]['capacitor_voltage_V'][:2],[5.,5.])
        self.assert_balanced(result)

    def test_dynamic_material_failure_and_nonconvergence_return_no_partial_pair(self):
        value=request(); value['thermal_nodes'][0].update(step_power_W=100.,step_time_s=0.)
        for law in value['resistance_mappings']: law['max_temperature_c']=20.1
        result=solve_electrothermal_transient(value)
        self.assertEqual(result['status'],'failed'); self.assertIsNone(result['coupled']); self.assertIsNone(result['baseline'])
        self.assertFalse(result['feasibility']['feasible'])
        self.assertEqual(result['checks']['failure_code'],'MATERIAL_RANGE_EXCEEDED')
        value=request(); value['coupling']={'max_iterations':1}
        result=solve_electrothermal_transient(value)
        self.assertEqual(result['checks']['failure_code'],'COUPLING_NOT_CONVERGED')
        self.assertFalse(result['checks']['coupling_converged'])

    def test_input_preservation_cancellation_and_work_bounds(self):
        value=request(); original=deepcopy(value); solve_electrothermal_transient(value)
        self.assertEqual(value,original)
        first=solve_electrothermal_transient(request(0))
        repeated=solve_electrothermal_transient(first['parameters'])
        self.assertEqual(first['coupled'],repeated['coupled'])
        with self.assertRaises(InterruptedError): solve_electrothermal_transient(value,cancel=lambda:True)
        count=0
        def cancel():
            nonlocal count
            count+=1
            return count==8
        with self.assertRaises(InterruptedError): solve_electrothermal_transient(value,cancel)
        self.assertEqual(count,8)
        with patch('quick_pi_plugin.electrothermal_transient.MAX_WORK_STEPS',1),self.assertRaisesRegex(TransientError,'work exceeds'):
            solve_electrothermal_transient(value)
        with patch('quick_pi_plugin.electrothermal_transient.MAX_TRACE_VALUES',1),self.assertRaisesRegex(TransientError,'trace bound'):
            solve_electrothermal_transient(value)

    def test_invalid_mappings_thermal_properties_laws_and_options(self):
        mutations=[lambda v:v['resistance_mappings'].pop(),
                   lambda v:v['resistance_mappings'][1].update(element_id='source'),
                   lambda v:v['resistance_mappings'][0].update(thermal_node_id='missing'),
                   lambda v:v['resistance_mappings'][0].update(alpha_per_K=-1.),
                   lambda v:v['resistance_mappings'][0].update(min_temperature_c=21.),
                   lambda v:v['thermal_nodes'][0].update(capacitance_J_K=0.),
                   lambda v:v['thermal_nodes'][0].update(initial_power_W=-1.),
                   lambda v:v['thermal_nodes'][0].update(step_time_s=1.),
                   lambda v:v.update(exchange_step_s=0.),lambda v:v.update(ambient_c=float('nan')),
                   lambda v:v.update(coupling={'max_iterations':True}),
                   lambda v:v.update(coupling={'relaxation':1.1}),
                   lambda v:v['thermal_nodes'].append(deepcopy(v['thermal_nodes'][0]))]
        for mutation in mutations:
            value=request(); mutation(value)
            with self.subTest(value=value),self.assertRaises(TransientError): solve_electrothermal_transient(value)


if __name__=='__main__': unittest.main()
