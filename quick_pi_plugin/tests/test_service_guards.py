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
