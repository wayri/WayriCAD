import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from quick_pi_plugin.cli import main


class ACPortsCLITests(unittest.TestCase):
    def test_planar_entrypoint_retains_modelled_status_and_does_not_claim_convergence(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=Path(folder)/'plane.json',Path(folder)/'result.json'
            source.write_text(json.dumps({'schema':'wayricad.pi-plane-ports/v1'}))
            with patch('quick_pi_plugin.plane_ports.run_study',return_value={'status':'MODELLED'}) as solve:
                code=main(['--plane-ports',str(source),'--output',str(target)])
            self.assertEqual(code,3);solve.assert_called_once()
            self.assertEqual(json.loads(target.read_text())['status'],'MODELLED')

    def test_headless_two_port_entrypoint_and_source_bound_export(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/'study.json', Path(folder)/'result.json'
            source.write_text(json.dumps({'schema':'wayricad.pi-ac-ports/v1'}))
            with patch('quick_pi_plugin.ac_ports.run_study',return_value={'status':'PROVISIONAL'}) as solve:
                code=main(['--ac-ports',str(source),'--output',str(target)])
            self.assertEqual(code,3)
            self.assertEqual(json.loads(target.read_text())['study_input_path'],str(source.resolve()))
            self.assertTrue(solve.call_args.kwargs['cancel'] is not None)
            self.assertIn('schema',json.loads(source.read_text()))

    def test_source_alias_and_unrelated_board_flags_are_rejected_before_solve(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'study.json'
            source.write_text(json.dumps({'schema':'wayricad.pi-ac-ports/v1'}))
            for options in (['--output',str(source)],['--net','VCC'],['--timeout','nan']):
                with patch('quick_pi_plugin.ac_ports.run_study') as solve, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['--ac-ports',str(source),*options]),2)
                    solve.assert_not_called()
