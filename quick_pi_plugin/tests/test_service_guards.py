"""Read-only input and worker boundary regression checks."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from quick_pi_plugin import cli,service


class ServiceGuards(unittest.TestCase):
    def test_cli_output_cannot_replace_source_board(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'board.kicad_pcb';source.write_bytes(b'original PCB')
            with patch.object(service,'run_job') as job,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main([str(source),'--output',str(source)]),2)
                job.assert_not_called()
            self.assertEqual(source.read_bytes(),b'original PCB')

    def test_benchmark_cli_status_and_invalid_output(self):
        with patch.object(service,'run_job',return_value={'pass':True}) as job, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--verify']),0)
            job.assert_called_once_with({'action':'verify'},timeout=300.)
            job.return_value={'pass':False}
            self.assertEqual(cli.main(['--verify']),1)
            job.reset_mock()
            self.assertEqual(cli.main(['--verify','--output','board.kicad_pcb']),2)
            job.assert_not_called()

    def test_convergence_cli_propagates_options_and_failure(self):
        args=['board.kicad_pcb','--net','VCC','--source','C1.1','--sink','U1.2','--converge-levels','4']
        with patch.object(service,'run_job',return_value={'convergence':{'status':'NOT_STABLE'}}) as job, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(args),3)
            request=job.call_args.args[0]
            self.assertEqual(request['action'],'converge')
            self.assertEqual(request['convergence_levels'],4)
            self.assertEqual(request['convergence_tolerance_percent'],1.)
            job.return_value={'convergence':{'status':'STABLE_WITHIN_TOLERANCE'}}
            self.assertEqual(cli.main(args),0)
            job.reset_mock()
            self.assertEqual(cli.main(args+['--convergence-tolerance-percent','nan']),2)
            job.assert_not_called()

    def test_nonfinite_timeout_or_precancelled_job_never_spawns(self):
        with patch.object(service.subprocess,'Popen') as spawn:
            for timeout in (0,-1,float('nan'),float('inf')):
                with self.subTest(timeout=timeout),self.assertRaises(ValueError):service.run_job({},timeout=timeout)
            with self.assertRaises(InterruptedError):service.run_job({},cancelled=lambda:True)
            spawn.assert_not_called()

    def test_direct_series_request_cannot_duplicate_component_pads(self):
        def pad(uid,number,net):
            p=Mock();p.GetNetCode.return_value=1;p.m_Uuid.AsString.return_value=uid
            p.GetNumber.return_value=number;p.GetNetname.return_value=net;return p
        def footprint(ref,pads):
            f=Mock();f.GetReference.return_value=ref;f.m_Uuid.AsString.return_value=ref;f.Pads.return_value=pads;return f
        board=Mock();board.GetFootprints.return_value=[footprint('C1',[pad('start','1','A')]),
            footprint('C2',[pad('end','1','A')]),footprint('R1',[pad('in','1','A'),pad('out','2','B')])]
        request={'source_terminal':'start','sink_terminal':'end','net':'A',
                 'series':[{'from_pad':'in','to_pad':'out','resistance_ohm':.01},
                           {'from_pad':'out','to_pad':'in','resistance_ohm':.01}]}
        with patch.dict('sys.modules',{'quick_pi_plugin.mesh':None}), self.assertRaisesRegex(ValueError,'Repeated series endpoint'):
            service.series_execute(board,Path('unused.kicad_pcb'),request)


if __name__=='__main__':unittest.main()
