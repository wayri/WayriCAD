"""Analytical independent DC supply/return loops, gauge and unsupported modes."""
import copy
import unittest
from quick_pi_plugin.power_loop import return_request,summarize_loop
from quick_pi_plugin.tests import test_batch as fixtures
case=fixtures.case
from quick_pi_plugin.tests.test_solver import strip
from quick_pi_plugin.solver import solve


class PowerLoopTests(unittest.TestCase):
    def setUp(self):
        self.electrical=case()['electrical']
        self.definition={'net':'GND','source_terminal':'U1.2','sink_terminal':'J1.2'}
        self.a,self.sa,self.ta=strip(length=10,width=1,nx=4,ny=2)
        self.b,self.sb,self.tb=strip(length=10,width=.5,nx=4,ny=2)

    def solved(self,request,returned=False):
        mesh,source,sink=(self.b,self.sb,self.tb) if returned else (self.a,self.sa,self.ta)
        current=request.get('sink_current',request.get('sinks',[{}])[0].get('current_A'))
        spec=copy.deepcopy(request.get('sinks',[{'current_A':current}])[0]);spec.pop('terminal',None)
        spec.update(id='load',nodes=sink)
        return solve(mesh,source,sinks=[spec],source_voltage=request['source_voltage'],
                     source_current_limit=request.get('source_current_limit'))

    def test_loop_matches_series_resistors_joule_loss_and_load_voltage(self):
        before=copy.deepcopy(self.electrical)
        request=return_request(self.electrical,self.definition)
        self.assertEqual(request['sink_current'],1)
        self.assertEqual(request['source_terminal'],'U1.2')
        self.assertEqual(request['sink_terminal'],'J1.2')
        supply=self.solved(self.electrical);returned=self.solved(request,True)
        result=summarize_loop(self.electrical,supply,returned,self.definition)
        resistance=1.724e-8*.01/(.001*.000035)
        self.assertAlmostEqual(result['supply_resistance_ohm'],resistance,10)
        self.assertAlmostEqual(result['return_resistance_ohm'],2*resistance,10)
        self.assertAlmostEqual(result['total_loss_W'],3*resistance,10)
        self.assertAlmostEqual(result['delivered_load_voltage_V'],3.3-3*resistance,10)
        self.assertTrue(result['feasible'])
        gauge=result['return_voltage_reference']
        self.assertAlmostEqual(returned['sink_voltage_V']+gauge['add_to_raw_potential_V'],0,12)
        self.assertAlmostEqual(returned['source_voltage_V']+gauge['add_to_raw_potential_V'],result['return_drop_V'],12)
        self.assertEqual(self.electrical,before)

    def test_combined_ground_rise_can_fail_while_supply_leg_alone_is_feasible(self):
        electrical=copy.deepcopy(self.electrical);electrical['sinks'][0].update(current_A=5,min_voltage_V=3.25)
        request=return_request(electrical,self.definition)
        supply=self.solved(electrical);returned=self.solved(request,True)
        self.assertTrue(supply['feasibility']['feasible'])
        result=summarize_loop(electrical,supply,returned,self.definition)
        self.assertFalse(result['feasible']);self.assertEqual(result['status'],'INFEASIBLE')
        self.assertLess(result['delivered_load_voltage_V'],3.25)

    def test_return_ground_rise_can_correct_a_supply_only_maximum_violation(self):
        electrical=copy.deepcopy(self.electrical);electrical['sinks'][0].update(min_voltage_V=3.2,max_voltage_V=3.29)
        supply=self.solved(electrical);returned=self.solved(return_request(electrical,self.definition),True)
        self.assertFalse(supply['feasibility']['feasible'])
        self.assertGreater(supply['sink_voltage_V'],3.29)
        result=summarize_loop(electrical,supply,returned,self.definition)
        self.assertTrue(result['feasible']);self.assertEqual(result['status'],'COMPLETED')
        self.assertGreaterEqual(result['delivered_load_voltage_V'],3.2)
        self.assertLessEqual(result['delivered_load_voltage_V'],3.29)
        electrical['source_current_limit']=.5
        self.assertFalse(summarize_loop(electrical,supply,returned,self.definition)['feasible'])

    def test_unsupported_loop_topologies_do_not_guess_distribution(self):
        for changed in [dict(self.electrical,sinks=[*self.electrical['sinks'],{'terminal':'U2.1','current_A':1}]),
                dict(self.electrical,model_dimension='3d'),dict(self.electrical,load_resistance_ohm=1),
                dict(self.electrical,package_conduction=[{}]),dict(self.electrical,series=[{}])]:
            with self.subTest(changed=changed),self.assertRaises(ValueError):return_request(changed,self.definition)
        with self.assertRaises(ValueError):return_request(self.electrical,dict(self.definition,net=self.electrical['net']))
        with self.assertRaises(ValueError):return_request(self.electrical,dict(self.definition,sink_current=2))

    def test_current_mismatch_or_unbalanced_solver_result_cannot_pass_loop(self):
        supply=self.solved(self.electrical);returned=self.solved(return_request(self.electrical,self.definition),True)
        for bad in [dict(returned,sink_current_A=2),dict(returned,energy_relative_error=.1),
                    dict(returned,current_balance_error_A=1),dict(returned,voltage_drop_V=float('nan'))]:
            with self.assertRaises(ValueError):summarize_loop(self.electrical,supply,bad,self.definition)


class BatchLoopIntegrationTests(unittest.TestCase):
    setUp=fixtures.BatchTests.setUp
    run_cases=fixtures.BatchTests.run_cases
    electrical=fixtures.BatchTests.electrical
    def test_batch_replaces_supply_only_maximum_status_with_combined_load_check(self):
        item=case('Ground-rise load window',1)
        item['electrical']['sinks'][0].update(min_voltage_V=3.2,max_voltage_V=3.292)
        item['return_conduction']={'net':'GND','source_terminal':'U1.2','sink_terminal':'J1.2'}
        def runner(request):
            spec=copy.deepcopy(request.get('sinks',[{'current_A':request.get('sink_current')}])[0])
            spec.pop('terminal',None);spec.update(id='load',nodes=self.sink)
            return {'result':solve(self.mesh,self.source,sinks=[spec],source_voltage=request['source_voltage'])}
        result=self.run_cases([item],runner)['batch']['cases'][0]
        self.assertFalse(result['electrical']['result']['feasibility']['feasible'])
        self.assertTrue(result['loop']['feasible']);self.assertEqual(result['status'],'COMPLETED')

    def test_actual_supply_and_return_fem_are_combined_in_batch(self):
        item=case('Power loop',2);item['return_conduction']={'net':'GND','source_terminal':'U1.2','sink_terminal':'J1.2'}
        def runner(request):
            return {'result':solve(self.mesh,self.source,sinks=[{'id':'load','nodes':self.sink,
                'current_A':request.get('sink_current',request.get('sinks',[{}])[0].get('current_A'))}],
                source_voltage=request['source_voltage'])}
        result=self.run_cases([item],runner)['batch']['cases'][0]
        self.assertEqual(result['status'],'COMPLETED')
        loop=result['loop'];self.assertAlmostEqual(loop['supply_loss_W'],loop['return_loss_W'],12)
        self.assertEqual(result['return_conduction']['return_voltage_reference'],loop['return_voltage_reference'])
        self.assertIn('auxiliary reference',result['return_conduction']['return_conduction_notice'])


if __name__=='__main__':unittest.main()
