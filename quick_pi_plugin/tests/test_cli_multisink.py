"""CLI load configuration and engineering-status propagation."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from quick_pi_plugin.cli import main


class MultisinkCLITests(unittest.TestCase):
    def invoke(self,arguments,result=None):
        result=result or {'result':{'feasibility':{'status':'FEASIBLE','feasible':True},'sinks':[{'id':'B','current_A':1}]}}
        output=io.StringIO()
        with patch('quick_pi_plugin.service.run_job',return_value=result) as worker,contextlib.redirect_stdout(output):
            status=main(['example.kicad_pcb',*arguments])
        return status,worker,output.getvalue()

    def test_multisink_demands_and_voltage_windows_reach_worker(self):
        status,worker,output=self.invoke(['--net','VCC','--source','J1.1','--voltage','3.3',
            '--load','U1.1','.8','--load','U2.1','.6','--source-current-limit','2',
            '--load-voltage-limits','U1.1','3.1','3.4','--load-voltage-limits','U2.1','3','-'])
        self.assertEqual(status,0);request=worker.call_args.args[0]
        self.assertEqual(request['sinks'],[{'terminal':'U1.1','current_A':.8,'min_voltage_V':3.1,'max_voltage_V':3.4},
                                          {'terminal':'U2.1','current_A':.6,'min_voltage_V':3.}])
        self.assertNotIn('sink_terminal',request);self.assertNotIn('sink_current',request)
        self.assertEqual(request['source_current_limit'],2)
        self.assertIn('feasibility',json.loads(output)['result']);self.assertIn('sinks',json.loads(output)['result'])

    def test_infeasibility_exit_takes_precedence_over_convergence_status(self):
        status,_,output=self.invoke(['--net','VCC','--source','A','--load','B','1'],
            {'result':{'feasibility':{'status':'INFEASIBLE','feasible':False,'source_current_limit_exceeded':True}},
             'convergence':{'status':'INCOMPLETE'}})
        self.assertEqual(status,4);self.assertIn('INFEASIBLE',output)

    def test_legacy_defaults_and_zero_source_budget(self):
        status,worker,_=self.invoke(['--net','VCC','--source','A','--sink','B','--source-current-limit','0'])
        self.assertEqual(status,0);request=worker.call_args.args[0]
        self.assertEqual(request['sink_current'],1);self.assertEqual(request['source_current_limit'],0)
        self.assertNotIn('sinks',request)

    def test_legacy_series_command_retains_source_budget(self):
        from quick_pi_plugin.tests.test_console import INVENTORY
        output=io.StringIO();result={'result':{'feasibility':{'feasible':True}}}
        with patch('quick_pi_plugin.service.run_job',side_effect=[INVENTORY,result]) as worker,contextlib.redirect_stdout(output):
            status=main(['example.kicad_pcb','--command','run pi C1.1 R1:5m U8.2','--current','2','--source-current-limit','3',
                         '--sink-min-voltage','.5','--sink-max-voltage','1.1'])
        self.assertEqual(status,0);request=worker.call_args.args[0]
        self.assertEqual(request['source_current_limit'],3);self.assertEqual(request['sink_current'],2)
        self.assertEqual(request['sink_min_voltage'],.5);self.assertEqual(request['sink_max_voltage'],1.1)
        self.assertEqual(request['series'][0]['resistance_ohm'],.005)

    def test_invalid_demands_limits_and_mixed_interfaces_do_not_launch_worker(self):
        base=['--net','VCC','--source','A','--load','B','1']
        cases=[['--sink','C'],['--current','1'],['--command','run pi A B'],['--load','B','2'],
               ['--load','C','0'],['--load','C','nan'],['--source-current-limit','-1'],['--source-current-limit','inf'],
               ['--load-voltage-limits','B','2','1'],['--load-voltage-limits','C','1','2'],
               ['--load-voltage-limits','B','nan','2'],['--load-voltage-limits','B','-1','2'],['--sink-min-voltage','1']]
        for extra in cases:
            with self.subTest(extra=extra):
                status,worker,output=self.invoke(base+extra)
                self.assertEqual(status,2);worker.assert_not_called();self.assertIn('error',json.loads(output))


if __name__=='__main__':unittest.main()
