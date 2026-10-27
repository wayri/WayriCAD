"""Independent analytical checks for individual shunt R/ESL/C branches."""
from copy import deepcopy
import json
import unittest

import numpy as np
from scipy.linalg import expm

from quick_pi_plugin.transient import solve_transient, RailStateStepper, TransientError, _request
from quick_pi_plugin.transient_shunts import recommend_step
from quick_pi_plugin.tests.test_transient import request


def branch(identifier, c, r=0., l=0.):
    return dict(id=identifier, capacitance_F=c, esr_ohm=r, esl_H=l)


class ShuntTransientTests(unittest.TestCase):
    def balanced(self, result):
        checks = result['checks']
        self.assertEqual(checks['balance_status'], 'PASSED')
        self.assertEqual(checks['time_refinement']['fine_balance_status'], 'PASSED')
        self.assertLess(checks['energy_relative_error'], 1e-9)
        self.assertLess(checks['charge_relative_error'], 1e-9)
        self.assertLess(checks['max_kvl_residual_V'], 1e-8)
        change = checks['final_stored_energy_J']-checks['initial_stored_energy_J']
        accounted = checks['source_energy_J']-checks['load_energy_J']-checks['resistive_loss_energy_J']-checks['backward_euler_numerical_dissipation_J']
        self.assertAlmostEqual(change, accounted, delta=2e-10)
        self.assertGreaterEqual(checks['backward_euler_numerical_dissipation_J'], 0.)
        for row in result['loads']:
            np.testing.assert_allclose(np.sum([b['current_A'] for b in row['shunt_capacitors']], axis=0), row['capacitor_current_A'], atol=2e-12)
            np.testing.assert_allclose(np.sum([b['esr_loss_W'] for b in row['shunt_capacitors']], axis=0), row['esr_loss_W'], atol=2e-12)
        json.dumps(result, allow_nan=False)

    def test_single_branch_matches_legacy_including_event_and_shared_inductance(self):
        for r, path_l, source_l in [(0.,0.,0.),(.03,0.,0.),(.02,.0001,.0002),(0.,0.,.0001)]:
            with self.subTest(r=r, path_l=path_l, source_l=source_l):
                study=request(duration_s=.004, step_s=.00002, source_inductance_H=source_l)
                study['loads'][0].update(esr_ohm=r,path_inductance_H=path_l)
                original=solve_transient(study)
                study['loads'][0]['shunt_capacitors']=[branch('C1',.002,r)]
                explicit=solve_transient(study)
                for key in ('voltage_V','current_A','capacitor_voltage_V'):
                    np.testing.assert_allclose(explicit['loads'][0][key],original['loads'][0][key],atol=2e-11)
                np.testing.assert_allclose(explicit['stored_energy_J'],original['stored_energy_J'],atol=2e-12)
                self.balanced(explicit)

    def test_parallel_ideal_capacitors_equal_sum_and_split_by_capacitance(self):
        study=request(duration_s=.004,step_s=.00002)
        study['loads'][0]['capacitance_F']=.003
        equivalent=solve_transient(study)
        study['loads'][0]['shunt_capacitors']=[branch('C1',.001),branch('C2',.002)]
        result=solve_transient(study); bank=result['loads'][0]['shunt_capacitors']
        np.testing.assert_allclose(result['loads'][0]['voltage_V'],equivalent['loads'][0]['voltage_V'],atol=2e-11)
        np.testing.assert_allclose(bank[1]['current_A'],2*np.array(bank[0]['current_A']),atol=1e-11)
        np.testing.assert_allclose(bank[0]['capacitor_voltage_V'],bank[1]['capacitor_voltage_V'],atol=2e-12)
        self.balanced(result)

    def test_unlike_rc_branches_match_independent_matrix_exponential(self):
        study=request(duration_s=.004,step_s=2e-6)
        row=study['loads'][0];row.update(step_time_s=0.)
        row['shunt_capacitors']=[branch('C1',.001,.03),branch('C2',.002,.2)]
        result=solve_transient(study)
        # From node KCL and u=v_k+R_k*j_k: R*j=Vs-Rfeed*d-v.
        c=np.diag([.001,.002]); resistance=np.diag([.03,.2])+.5*np.ones((2,2))
        generator=-np.linalg.solve(c,np.linalg.inv(resistance))
        v_dc=np.full(2,4.4); initial=np.full(2,4.9)
        for k in range(1,len(result['times_s']),79):
            exact=v_dc+expm(generator*result['times_s'][k])@(initial-v_dc)
            observed=[b['capacitor_voltage_V'][k] for b in result['loads'][0]['shunt_capacitors']]
            np.testing.assert_allclose(observed,exact,atol=.0007)
        bank=result['loads'][0]['shunt_capacitors']
        self.assertGreater(max(abs(np.array(bank[0]['capacitor_voltage_V'])-bank[1]['capacitor_voltage_V'])),.03)
        self.assertEqual(len(result['checks']['time_refinement']['per_shunt_capacitor']),2)
        self.balanced(result)

    def test_unlike_esl_branches_match_independent_matrix_exponential_and_refine(self):
        study=request(duration_s=.0015,step_s=2e-7)
        row=study['loads'][0];row.update(step_time_s=0., initial_current_A=0., step_current_A=1.)
        row['shunt_capacitors']=[branch('C1',.0001,.02,.00003),branch('C2',.00003,.07,.00012)]
        result=solve_transient(study)
        # Feed is resistive, so branch ESL currents remain zero at the edge,
        # while feed current immediately supplies the new current demand.
        np.testing.assert_allclose(result['loads'][0]['current_A'][:2],[0.,1.],atol=1e-12)
        for b in result['loads'][0]['shunt_capacitors']:
            np.testing.assert_allclose(b['current_A'][:2],[0.,0.],atol=1e-12)
        l=np.diag([.00003,.00012]);c=np.diag([.0001,.00003]);r=np.diag([.02,.07])+.5*np.ones((2,2))
        generator=np.block([[-np.linalg.solve(l,r),-np.linalg.inv(l)],[np.linalg.inv(c),np.zeros((2,2))]])
        steady=np.array([0.,0.,4.5,4.5]);initial=np.array([0.,0.,5.,5.])
        for k in range(1,len(result['times_s']),211):
            exact=steady+expm(generator*result['times_s'][k])@(initial-steady)
            banks=result['loads'][0]['shunt_capacitors']
            observed=[b['current_A'][k] for b in banks]+[b['capacitor_voltage_V'][k] for b in banks]
            np.testing.assert_allclose(observed,exact,atol=.004)
        coarse=deepcopy(study);coarse['step_s']*=4
        coarse_result=solve_transient(coarse)
        self.assertLess(result['checks']['time_refinement']['max_load_voltage_difference_V'],coarse_result['checks']['time_refinement']['max_load_voltage_difference_V'])
        self.balanced(result)

    def test_mixed_esl_bank_preserves_feed_and_shunt_magnetic_state_at_edge(self):
        study=request(duration_s=.003,step_s=2e-6,source_inductance_H=.0001)
        row=study['loads'][0];row['path_inductance_H']=.0002
        row['shunt_capacitors']=[branch('C1',.001,.02),branch('C2',.0001,.07,.00003)]
        result=solve_transient(study);before=result['sample_phase'].index('step_before');after=before+1
        load=result['loads'][0]
        self.assertAlmostEqual(load['current_A'][before],load['current_A'][after],12)
        self.assertAlmostEqual(result['stored_energy_J'][before],result['stored_energy_J'][after],12)
        for bank in load['shunt_capacitors']:
            self.assertEqual(bank['capacitor_voltage_V'][before],bank['capacitor_voltage_V'][after])
        self.assertAlmostEqual(load['shunt_capacitors'][1]['current_A'][before],load['shunt_capacitors'][1]['current_A'][after],12)
        self.balanced(result)

    def test_multiload_mixed_bank_and_legacy_conserve_and_couple(self):
        study=request(duration_s=.003,step_s=.00001,source_inductance_H=.0001)
        first=study['loads'][0];first['shunt_capacitors']=[branch('C1',.001,.02),branch('C2',.0001,.04,.00001)]
        study['loads'].append(dict(id='B',label='Load B',initial_current_A=.3,step_current_A=.3,
            step_time_s=.002,path_resistance_ohm=.1,path_inductance_H=0.,capacitance_F=.001,esr_ohm=.01))
        result=solve_transient(study)
        self.assertGreater(np.ptp(result['loads'][1]['voltage_V']),.05)
        self.balanced(result)

    def test_impulsive_inductor_cutset_is_rejected_but_constant_demand_is_valid(self):
        study=request(duration_s=.003,step_s=.00001,source_inductance_H=.0001)
        row=study['loads'][0];row['shunt_capacitors']=[branch('C1',.001,.01,.00001)]
        with self.assertRaisesRegex(TransientError,'impuls'):
            solve_transient(study)
        row['step_current_A']=row['initial_current_A']
        self.balanced(solve_transient(study))

    def test_explicit_bank_replaces_aggregate_and_normalizes_without_it(self):
        study=request(duration_s=.002,step_s=.00002)
        study['loads'][0]['shunt_capacitors']=[branch('C1',.001,.03)]
        baseline=solve_transient(study)
        study['loads'][0].update(capacitance_F=9000,esr_ohm=9000)
        result=solve_transient(study)
        self.assertEqual(baseline['loads'],result['loads'])
        self.assertNotIn('capacitance_F',result['parameters']['loads'][0])
        self.assertNotIn('esr_ohm',result['parameters']['loads'][0])
        del study['loads'][0]['capacitance_F'];del study['loads'][0]['esr_ohm']
        self.assertEqual(result['loads'],solve_transient(study)['loads'])

    def test_constant_multiload_dc_does_not_normalize_charge_by_roundoff(self):
        study=request(duration_s=.002,step_s=.00001,source_resistance_ohm=.123)
        first=study['loads'][0]
        first.update(initial_current_A=.123,step_current_A=.123,path_resistance_ohm=.234,
                     shunt_capacitors=[branch('C1',.00123,.0234)])
        study['loads'].append(dict(first,id='B',initial_current_A=.234,step_current_A=.234,
                                  shunt_capacitors=[branch('C2',.0004321,.0123)]))
        result=solve_transient(study)
        for row in result['loads']:
            np.testing.assert_allclose(row['voltage_V'],row['voltage_V'][0],atol=1e-12)
        self.balanced(result)

    def test_validation_bounds_identity_and_coupled_rejection(self):
        study=request()
        for bank in ([],[branch('C1',0)], [branch('C1',.001,-1)], [branch('C1',.001,0,-1)],
                     [branch('C1',.001),branch('C1',.002)], [branch('C'+str(k),.001) for k in range(129)]):
            with self.subTest(bank=bank):
                candidate=deepcopy(study);candidate['loads'][0]['shunt_capacitors']=bank
                with self.assertRaises(TransientError): _request(candidate)
        study['loads'][0]['shunt_capacitors']=[branch('C1',.001)]
        with self.assertRaisesRegex(TransientError,'coupled electrothermal'):
            RailStateStepper(study)
        duplicate=deepcopy(study['loads'][0]);duplicate['id']='B';study['loads'].append(duplicate)
        with self.assertRaisesRegex(TransientError,'globally unique'): _request(study)

    def test_trace_memory_bound_and_step_advice_use_individual_branches(self):
        study=request(duration_s=.01,step_s=.000001)
        study['loads'][0]['shunt_capacitors']=[branch('C'+str(k),.0001,.03,.000001) for k in range(32)]
        with self.assertRaisesRegex(TransientError,'scalar trace values'): solve_transient(study)
        study['loads'][0]['shunt_capacitors']=[branch('C1',.001,.03)]
        slow=recommend_step(study)
        study['loads'][0]['shunt_capacitors'].append(branch('C2',1e-9,.01,1e-9))
        fast=recommend_step(study)
        self.assertLess(fast['step_s'],slow['step_s'])
        self.assertFalse(fast['within_budget'])

    def test_modal_advice_is_invariant_to_splitting_an_ideal_capacitor(self):
        study=request(source_inductance_H=.0001)
        other=[branch('X',1e-6,.01),branch('Y',1e-4,.001)]
        study['loads'][0]['shunt_capacitors']=[branch('C',.001)]+other
        reference=recommend_step(study)['step_s']
        for count in (2,8,16,24):
            study['loads'][0]['shunt_capacitors']=[branch('C'+str(k),.001/count) for k in range(count)]+other
            self.assertAlmostEqual(recommend_step(study)['step_s']/reference,1.,delta=1e-7)

    def test_finite_ramp_with_all_esl_and_feed_inductance_matches_augmented_exponential(self):
        study=request(duration_s=.002,step_s=2e-7,source_inductance_H=.0001)
        row=study['loads'][0];row.update(step_time_s=.0005,rise_time_s=.0004,path_inductance_H=.0002)
        row['shunt_capacitors']=[branch('C1',.0001,.02,.00003),branch('C2',.0002,.04,.00007)]
        result=solve_transient(study)
        m=np.diag([.00003,.00007])+.0003*np.ones((2,2));r=np.diag([.02,.04])+.5*np.ones((2,2))
        inverse=np.linalg.inv(m);c_inverse=np.diag([1/.0001,1/.0002]);ones=np.ones(2)
        slope=(1.2-.2)/.0004
        def generator(s):
            matrix=np.zeros((6,6));matrix[:2,:2]=-inverse@r;matrix[:2,2:4]=-inverse
            matrix[:2,4]=-inverse@(.5*ones);matrix[:2,5]=inverse@((5.-.0003*s)*ones)
            matrix[2:4,:2]=c_inverse;matrix[4,5]=s
            return matrix
        during=generator(slope);after=generator(0.)
        initial=np.array([0.,0.,4.9,4.9,.2,1.]);end=expm(during*.0004)@initial
        for k in range(0,len(result['times_s']),137):
            t=result['times_s'][k]
            exact=initial if t<=.0005 else expm(during*(t-.0005))@initial if t<=.0009 else expm(after*(t-.0009))@end
            banks=result['loads'][0]['shunt_capacitors']
            observed=[b['current_A'][k] for b in banks]+[b['capacitor_voltage_V'][k] for b in banks]
            np.testing.assert_allclose(observed,exact[:4],atol=.0015)
            self.assertAlmostEqual(result['loads'][0]['requested_current_A'][k],exact[4],delta=1e-12)
        for time in (.0005,.0005+.0004):
            before=next(k for k,(t,p) in enumerate(zip(result['times_s'],result['sample_phase'])) if t==time and p=='step_before')
            after_index=before+1
            self.assertEqual(result['times_s'][before],result['times_s'][after_index])
            for b in result['loads'][0]['shunt_capacitors']:
                self.assertAlmostEqual(b['current_A'][before],b['current_A'][after_index],12)
                self.assertEqual(b['capacitor_voltage_V'][before],b['capacitor_voltage_V'][after_index])
            self.assertAlmostEqual(result['stored_energy_J'][before],result['stored_energy_J'][after_index],12)
            # Slope changes legitimately jump node voltage through inductances.
            self.assertGreater(abs(result['loads'][0]['voltage_V'][before]-result['loads'][0]['voltage_V'][after_index]),.02)
        coarse=deepcopy(study);coarse['step_s']*=4
        self.assertLess(result['checks']['time_refinement']['max_load_voltage_difference_V'],
                        solve_transient(coarse)['checks']['time_refinement']['max_load_voltage_difference_V'])
        self.balanced(result)

    def test_ramp_decrease_and_zero_start_are_continuous_and_validated(self):
        study=request(duration_s=.002,step_s=1e-6,source_inductance_H=.0001)
        row=study['loads'][0];row.update(initial_current_A=1.2,step_current_A=.2,step_time_s=0.,rise_time_s=.0005)
        row['shunt_capacitors']=[branch('C1',.0001,.02,.00003)]
        result=solve_transient(study)
        self.assertEqual(result['loads'][0]['requested_current_A'][:2],[1.2,1.2])
        self.assertAlmostEqual(result['loads'][0]['requested_current_A'][-1],.2,12)
        self.balanced(result)
        for bad in (-1.,float('nan'),True,.003):
            row['rise_time_s']=bad
            with self.assertRaises(TransientError): _request(study)
        row['rise_time_s']=.0005;del row['shunt_capacitors']
        with self.assertRaisesRegex(TransientError,'requires an explicit'): _request(study)


    def test_dense_45_part_bank_matches_its_exact_symmetric_equivalent(self):
        study=request(duration_s=1e-6,step_s=1e-8,source_resistance_ohm=.1,source_inductance_H=1e-8)
        study['loads'][0].update(initial_current_A=.1,step_current_A=1.,step_time_s=.2e-6,
            rise_time_s=.1e-6,path_resistance_ohm=0.,path_inductance_H=0.,
            shunt_capacitors=[branch('C'+str(i),1e-7,.02,1e-9) for i in range(45)])
        equivalent=deepcopy(study)
        equivalent['loads'][0]['shunt_capacitors']=[branch('Equivalent',45e-7,.02/45,1e-9/45)]
        actual=solve_transient(study);expected=solve_transient(equivalent)
        self.assertEqual(len(actual['loads'][0]['shunt_capacitors']),45)
        np.testing.assert_allclose(actual['loads'][0]['voltage_V'],expected['loads'][0]['voltage_V'],rtol=0,atol=2e-9)
        np.testing.assert_allclose(actual['source_current_A'],expected['source_current_A'],rtol=0,atol=2e-9)
        self.balanced(actual)
        study['loads'][0]['shunt_capacitors']=[branch('C'+str(i),1e-7,.02,1e-9) for i in range(129)]
        with self.assertRaisesRegex(TransientError,'128'):_request(study)


if __name__ == '__main__':
    unittest.main()
