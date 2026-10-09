"""Analytical and conservation checks for explicit lumped rail transients."""
from copy import deepcopy
import json
import math
import unittest
from unittest import mock

import numpy as np
from scipy.linalg import expm

from quick_pi_plugin.transient import solve_transient, TransientError


def request(**updates):
    result = dict(duration_s=.01, step_s=.00001, source_voltage_V=5.,
                  source_resistance_ohm=.2, source_inductance_H=0., loads=[
                      dict(id='A', label='Load A', initial_current_A=.2,
                           step_current_A=1.2, step_time_s=.001,
                           path_resistance_ohm=.3, path_inductance_H=0.,
                           capacitance_F=.002, esr_ohm=0.)])
    result.update(updates)
    return result


class TransientTests(unittest.TestCase):
    def assert_balanced(self, result):
        checks = result['checks']
        self.assertEqual(checks['balance_status'], 'PASSED')
        self.assertLess(checks['energy_relative_error'], 1e-10)
        self.assertLess(checks['charge_relative_error'], 1e-10)
        self.assertLess(checks['max_kvl_residual_V'], 1e-8)
        self.assertEqual(checks['time_refinement']['fine_balance_status'], 'PASSED')
        # BE heat is explicitly separate from its purely numerical damping.
        self.assertGreaterEqual(checks['backward_euler_numerical_dissipation_J'], 0.)
        change = checks['final_stored_energy_J'] - checks['initial_stored_energy_J']
        accounted = (checks['source_energy_J'] - checks['load_energy_J'] -
                     checks['resistive_loss_energy_J'] - checks['backward_euler_numerical_dissipation_J'])
        self.assertAlmostEqual(change, accounted, delta=1e-11)
        json.dumps(result, allow_nan=False)

    def test_rc_droop_and_recovery_match_the_analytical_solution(self):
        for initial, final in [(.2, 1.2), (1.2, .2)]:
            with self.subTest(initial=initial):
                inputs=request();load=inputs['loads'][0]
                load.update(initial_current_A=initial, step_current_A=final)
                result=solve_transient(inputs);row=result['loads'][0]
                times=np.array(result['times_s']);elapsed=np.maximum(times-load['step_time_s'],0)
                total_r=.5;tau=total_r*load['capacitance_F']
                expected=5-total_r*final+total_r*(final-initial)*np.exp(-elapsed/tau)
                expected[times<load['step_time_s']]=5-total_r*initial
                np.testing.assert_allclose(row['voltage_V'],expected,atol=.001)
                np.testing.assert_allclose(row['voltage_V'],row['capacitor_voltage_V'],atol=1e-12)
                self.assertAlmostEqual(row['voltage_V'][-1],5-total_r*final,delta=.0001)
                self.assert_balanced(result)

    def test_esr_jump_is_exact_and_capacitor_voltage_is_continuous(self):
        inputs=request();inputs['loads'][0]['esr_ohm']=.1
        result=solve_transient(inputs);row=result['loads'][0]
        before=result['sample_phase'].index('step_before');after=before+1
        self.assertEqual(result['times_s'][before],.001)
        self.assertEqual(result['times_s'][before],result['times_s'][after])
        self.assertEqual(row['capacitor_voltage_V'][before],row['capacitor_voltage_V'][after])
        self.assertAlmostEqual(row['voltage_V'][after]-row['voltage_V'][before],-.5*.1/.6,12)
        self.assertAlmostEqual(row['current_A'][after],.2+.1/.6,12)
        self.assertEqual(row['requested_current_A'][before:after+1],[.2,1.2])
        self.assert_balanced(result)

    def test_rlc_step_matches_state_space_and_rings(self):
        inputs=request(duration_s=.002,step_s=5e-7,source_resistance_ohm=.1,source_inductance_H=.0004)
        load=inputs['loads'][0]
        load.update(initial_current_A=0.,step_current_A=1.,step_time_s=0.,
                    path_resistance_ohm=.1,path_inductance_H=.0006,capacitance_F=.0001,esr_ohm=.02)
        result=solve_transient(inputs);row=result['loads'][0]
        matrix=np.array([[-.22/.001,-1/.001],[1/.0001,0.]])
        steady=np.array([1.,4.8]);initial=np.array([0.,5.])
        for index in range(1,len(result['times_s']),203):
            state=steady+expm(matrix*result['times_s'][index])@(initial-steady)
            self.assertAlmostEqual(row['current_A'][index],state[0],delta=.006)
            self.assertAlmostEqual(row['capacitor_voltage_V'][index],state[1],delta=.015)
        self.assertGreater(max(row['current_A']),1.8)
        self.assertLess(min(row['voltage_V']),2.)
        self.assertGreater(max(row['voltage_V'][100:]),5.5)
        self.assertEqual(row['current_A'][:2],[0.,0.])
        self.assertEqual(row['capacitor_voltage_V'][:2],[5.,5.])
        self.assertAlmostEqual(row['voltage_V'][1],4.98,12)
        self.assert_balanced(result)

    def test_shared_source_couples_multisink_rails(self):
        inputs=request(duration_s=.02,step_s=.00005)
        first=inputs['loads'][0];first.update(initial_current_A=.1,step_current_A=1.,step_time_s=.001)
        second=dict(first,id='B',label='Load B',initial_current_A=.4,step_current_A=.4,
                    path_resistance_ohm=.1,capacitance_F=.001,step_time_s=.002)
        inputs['loads'].append(second)
        result=solve_transient(inputs)
        np.testing.assert_allclose(result['source_current_A'],
                                   np.sum([row['current_A'] for row in result['loads']],axis=0),atol=1e-12)
        self.assertAlmostEqual(result['source_current_A'][-1],1.4,delta=.00001)
        self.assertAlmostEqual(result['source_voltage_V'][-1],5-.2*1.4,delta=.00001)
        self.assertAlmostEqual(result['loads'][0]['voltage_V'][-1],5-.2*1.4-.3,delta=.00001)
        self.assertAlmostEqual(result['loads'][1]['voltage_V'][-1],5-.2*1.4-.04,delta=.00001)
        self.assertLess(result['loads'][1]['voltage_V'][-1],result['loads'][1]['voltage_V'][0]-.15)
        self.assert_balanced(result)

    def test_zero_path_r_l_and_esr_parallel_caps_have_physical_current_split(self):
        inputs=request(duration_s=.001,step_s=.00001)
        first=inputs['loads'][0]
        first.update(initial_current_A=0,step_current_A=1,step_time_s=0,
                     path_resistance_ohm=0,path_inductance_H=0,esr_ohm=0,capacitance_F=.001)
        inputs['loads'].append(dict(first,id='B',label='B',step_current_A=0,capacitance_F=.003))
        result=solve_transient(inputs);a,b=result['loads']
        np.testing.assert_allclose(a['voltage_V'],b['voltage_V'],atol=1e-12)
        self.assertAlmostEqual(a['current_A'][1],.75,12)
        self.assertAlmostEqual(b['current_A'][1],-.75,12)
        self.assertAlmostEqual(result['source_current_A'][1],0.,12)
        np.testing.assert_allclose(np.array(b['capacitor_current_A']),3*np.array(a['capacitor_current_A']),atol=1e-10)
        self.assert_balanced(result)

    def test_shared_inductor_with_zero_path_inductors_preserves_source_current(self):
        inputs=request(duration_s=.001,step_s=.000001,source_inductance_H=.0001)
        first=inputs['loads'][0];first.update(initial_current_A=0,step_current_A=1,step_time_s=0,
                                             path_resistance_ohm=0,esr_ohm=0,capacitance_F=.001)
        inputs['loads'].append(dict(first,id='B',label='B',step_current_A=.5,capacitance_F=.002))
        result=solve_transient(inputs);a,b=result['loads']
        self.assertAlmostEqual(result['source_current_A'][1],0.,12)
        np.testing.assert_allclose(a['voltage_V'],b['voltage_V'],atol=1e-12)
        np.testing.assert_allclose(result['source_voltage_V'],a['voltage_V'],atol=1e-10)
        self.assert_balanced(result)

    def test_event_times_are_exact_with_before_after_and_no_coarse_rounding_interval(self):
        inputs=request(step_s=.0002)
        inputs['loads'][0]['step_time_s']=.00323
        result=solve_transient(inputs)
        self.assertEqual(result['times_s'].count(.00323),2)
        self.assertEqual(result['times_s'][-1],.01)
        self.assertLessEqual(result['checks']['max_interval_s'],.0002+1e-15)
        inputs=request(duration_s=1.,step_s=.1)
        inputs['loads'][0]['step_time_s']=.3
        result=solve_transient(inputs)
        self.assertEqual(result['times_s'].count(.3),2)
        self.assertNotIn(.30000000000000004,result['times_s'])
        self.assert_balanced(result)

    def test_step_at_final_time_has_jump_without_invented_integrated_duration(self):
        inputs=request();inputs['loads'][0].update(step_time_s=.01,esr_ohm=.1)
        result=solve_transient(inputs)
        self.assertEqual(result['times_s'][-2:],[.01,.01])
        self.assertEqual(result['sample_phase'][-2:],['step_before','step_after'])
        self.assertAlmostEqual(result['checks']['source_energy_J'],.01*5*.2,12)
        self.assert_balanced(result)

    def test_current_budget_is_diagnostic_and_never_changes_waveforms(self):
        inputs=request();baseline=solve_transient(inputs)
        inputs['source_current_limit_A']=.1;limited=solve_transient(inputs)
        self.assertEqual(limited['source_current_A'],baseline['source_current_A'])
        self.assertEqual(limited['loads'],baseline['loads'])
        self.assertTrue(limited['feasibility']['source_current_limit_exceeded'])
        self.assertFalse(limited['feasibility']['operating_point_valid'])
        self.assertEqual(limited['feasibility']['source_current_limit_mode'],'diagnostic_only')
        self.assertIn('CV/CC regulation is not simulated',limited['notice'])
        inputs['source_current_limit_A']=max(baseline['source_current_A'])
        self.assertTrue(solve_transient(inputs)['feasibility']['feasible'])

    def test_voltage_bounds_include_esr_event_jump_and_negative_initial_state(self):
        inputs=request();inputs['loads'][0].update(esr_ohm=.1,min_voltage_V=4.86,max_voltage_V=4.95)
        result=solve_transient(inputs);row=result['loads'][0]
        self.assertFalse(row['within_voltage_limits'])
        minimum=next(item for item in row['violations'] if item['kind']=='minimum_voltage')
        self.assertEqual(minimum['observed_V'],row['min_voltage_V'])
        self.assertFalse(result['feasibility']['feasible'])
        inputs=request(source_voltage_V=.1)
        result=solve_transient(inputs)
        self.assertAlmostEqual(result['initialization']['loads'][0]['voltage_V'],0.,12)
        self.assertTrue(result['initialization']['feasible'])
        inputs['source_voltage_V']=.01
        result=solve_transient(inputs)
        self.assertFalse(result['initialization']['feasible'])
        self.assertIn('pre-step DC state already violates',result['notice'])
        self.assertTrue(any(item['kind']=='negative_voltage' for item in result['loads'][0]['violations']))

    def test_half_step_evidence_reduces_first_order_rc_error_without_certification(self):
        coarse=request(step_s=.0001);fine=deepcopy(coarse);fine['step_s']=.00005
        a=solve_transient(coarse);b=solve_transient(fine)
        self.assertGreater(a['checks']['time_refinement']['max_load_voltage_difference_V'],0.)
        self.assertLess(b['checks']['time_refinement']['max_load_voltage_difference_V'],
                        a['checks']['time_refinement']['max_load_voltage_difference_V']*.6)
        self.assertEqual(a['checks']['time_refinement']['status'],'CHECKED_NOT_CERTIFIED')
        self.assertEqual(a['checks']['time_refinement']['comparison_samples'],len(a['times_s']))

    def test_power_traces_and_charge_sign_are_consistent(self):
        inputs=request();inputs['loads'][0]['esr_ohm']=.1
        result=solve_transient(inputs);row=result['loads'][0]
        current=np.array(row['current_A']);demand=np.array(row['requested_current_A'])
        np.testing.assert_allclose(row['capacitor_current_A'],current-demand,atol=1e-12)
        np.testing.assert_allclose(row['path_loss_W'],.3*current**2)
        np.testing.assert_allclose(row['esr_loss_W'],.1*(current-demand)**2)
        np.testing.assert_allclose(row['load_power_W'],np.array(row['voltage_V'])*demand)
        np.testing.assert_allclose(result['total_resistive_loss_W'],
                                   np.array(result['source_resistive_loss_W'])+row['path_loss_W']+np.array(row['esr_loss_W']))
        self.assertLess(min(row['capacitor_current_A']),0.)
        self.assert_balanced(result)

    def test_input_is_not_modified(self):
        inputs=request();original=deepcopy(inputs)
        solve_transient(inputs)
        self.assertEqual(inputs,original)

    def test_cancellation_is_checked_before_initialization_and_during_integration(self):
        with self.assertRaises(InterruptedError):solve_transient(request(),cancel=lambda:True)
        calls=0
        def cancel():
            nonlocal calls
            calls+=1
            return calls>=5
        with self.assertRaises(InterruptedError):solve_transient(request(),cancel=cancel)
        self.assertEqual(calls,5)

    def test_request_and_state_output_bounds_reject_before_large_allocations(self):
        with self.assertRaisesRegex(TransientError,'intervals'):
            solve_transient(request(duration_s=1,step_s=1e-8))
        inputs=request();inputs['loads']=[dict(inputs['loads'][0],id=str(index)) for index in range(65)]
        with self.assertRaisesRegex(TransientError,'64'):solve_transient(inputs)
        with mock.patch('quick_pi_plugin.transient.MAX_TRACE_VALUES',10),self.assertRaisesRegex(TransientError,'trace values'):
            solve_transient(request())

    def test_invalid_explicit_values_identities_and_unsupported_states_are_rejected(self):
        for key,value in [('source_voltage_V',float('nan')),('source_voltage_V',True),
                          ('source_resistance_ohm',0),('source_inductance_H',-1),
                          ('duration_s',0),('step_s',float('inf')),('source_current_limit_A',-1),
                          ('initial_capacitor_voltage_V',5),('loads',[])]:
            with self.subTest(key=key,value=value),self.assertRaises(TransientError):
                solve_transient(request(**{key:value}))
        for key,value in [('initial_current_A',-1),('step_current_A',float('inf')),
                          ('path_resistance_ohm',-1),('path_inductance_H',-1),
                          ('capacitance_F',0),('esr_ohm',-1),('step_time_s',.02),
                          ('id',''),('label',2),('initial_voltage_V',0)]:
            with self.subTest(key=key,value=value):
                inputs=request();inputs['loads'][0][key]=value
                with self.assertRaises(TransientError):solve_transient(inputs)
        inputs=request();inputs['loads'].append(deepcopy(inputs['loads'][0]))
        with self.assertRaisesRegex(TransientError,'Repeated'):solve_transient(inputs)
        inputs=request();inputs['loads'][0].update(min_voltage_V=5,max_voltage_V=4)
        with self.assertRaisesRegex(TransientError,'maximum'):solve_transient(inputs)
        inputs=request();inputs['loads'][0].pop('path_inductance_H')
        with self.assertRaises(TransientError):solve_transient(inputs)


if __name__=='__main__':unittest.main()
