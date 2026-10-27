"""Power demands must reach the worker without becoming constant currents."""
import unittest
from quick_pi_plugin.tests.test_cli_multisink import MultisinkCLITests


class PowerCLITests(MultisinkCLITests):
    def test_singular_power_and_mixed_load_flags(self):
        status,worker,_=self.invoke(['--net','VCC','--source','J1.1','--sink','U1.1','--load-power','2.5','--voltage','5'])
        self.assertEqual(status,0);request=worker.call_args.args[0]
        self.assertEqual(request['load_power_W'],2.5);self.assertNotIn('sink_current',request)
        status,worker,_=self.invoke(['--net','VCC','--source','J1.1','--power-load','U1.1','2.5',
                                   '--load','U2.1','.25','--load-voltage-limits','U1.1','4.5','-'])
        self.assertEqual(status,0);request=worker.call_args.args[0]
        self.assertEqual(request['sinks'],[{'terminal':'U2.1','current_A':.25},
                                         {'terminal':'U1.1','power_W':2.5,'min_voltage_V':4.5}])

    def test_power_conflicts_do_not_start_a_worker(self):
        for extra in (['--current','1'],['--load-ohms','5'],['--load-power','nan']):
            status,worker,_=self.invoke(['--net','VCC','--source','A','--sink','B','--load-power','1',*extra])
            self.assertEqual(status,2);worker.assert_not_called()

    def test_batch_rejects_unmodeled_coupled_power_returns(self):
        from quick_pi_plugin.batch import validate_study
        case={'name':'Power','electrical':{'net':'VCC','source_voltage':5,'source_terminal':'s',
                                          'sinks':[{'terminal':'a','power_W':2}]}}
        study={'schema':'wayricad.pi-batch/v1','cases':[case]}
        validate_study(study)
        case['return_conduction']={}
        with self.assertRaisesRegex(ValueError,'Constant-power'):validate_study(study)

    def test_reviewed_series_file_includes_parallel_parts(self):
        import contextlib,io,json,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from quick_pi_plugin.cli import main
        from quick_pi_plugin.tests.test_parallel_parts import inventory
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'path.json'
            path.write_text(json.dumps({'schema':1,'source':'J1.1','sink':'U1.1','branches':[
                {'reference':'R1','model':'100m','parallel':[{'footprint_uuid':'r2','model':'200m'}]}]}),encoding='utf-8')
            with patch('quick_pi_plugin.service.run_job',side_effect=[inventory(),{'result':{}}]) as worker,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['Example.kicad_pcb','--series-file',str(path),'--current','2']),0)
            request=worker.call_args.args[0]
            self.assertEqual(request['series'][0]['parallel'][0]['resistance_ohm'],.2)
            self.assertEqual(request['sink_current'],2)


if __name__=='__main__':unittest.main()
