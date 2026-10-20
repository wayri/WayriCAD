"""Saved-board CLI preflight and source custody checks."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from silkscreen_label_plugin import cli

class SilkscreenCLITests(unittest.TestCase):
    def test_settings_are_machine_readable_without_opening_board(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.assertEqual(cli.main(['settings']),0)
        self.assertFalse(json.loads(out.getvalue())['writes_board'])
        self.assertTrue(json.loads(out.getvalue())['settings']['auto_size'])

    def test_preview_never_overwrites_existing_result_or_board(self):
        with tempfile.TemporaryDirectory() as raw:
            source=Path(raw)/'board.kicad_pcb';source.write_text('source')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['preview',str(source),'--output',str(source)]),1)
            self.assertEqual(source.read_text(),'source')

    def test_duplicate_settings_and_timeout_are_rejected_before_native_launch(self):
        with tempfile.TemporaryDirectory() as raw:
            settings=Path(raw)/'settings.json';settings.write_text('{"height":1,"height":2}')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['preview','board.kicad_pcb','--settings',str(settings)]),1)
                self.assertEqual(cli.main(['preview','board.kicad_pcb','--timeout','nan']),1)


class WorkerCustodyTests(unittest.TestCase):
    def test_direct_worker_never_overwrites_source_or_request_even_on_error(self):
        from silkscreen_label_plugin import cli_worker
        import sys
        with tempfile.TemporaryDirectory() as raw:
            board=Path(raw)/'board.kicad_pcb';board.write_text('original board')
            request=Path(raw)/'request.json';request.write_text(json.dumps({'board':str(board)}))
            for target in (board,request,board.with_suffix('.kicad_pro')):
                before={path:path.read_bytes() if path.exists() else None for path in (board,request,target)}
                with patch.object(sys,'argv',['worker',str(request),str(target)]),contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli_worker.main(),1)
                self.assertEqual(before,{path:path.read_bytes() if path.exists() else None for path in before})

    def test_creation_of_previously_absent_rules_invalidates_preview(self):
        from types import SimpleNamespace
        import sys
        from silkscreen_label_plugin import placement
        with tempfile.TemporaryDirectory() as raw:
            board=Path(raw)/'board.kicad_pcb';board.write_text('original board')
            def changed(*args,**kwargs):
                board.with_suffix('.kicad_dru').write_text('new rules')
                return SimpleNamespace(changes=[],settings={},stats={},rejected=[],skipped=[])
            fake=SimpleNamespace(LoadBoard=lambda path:object())
            with patch.dict(sys.modules,{'pcbnew':fake}),patch.object(placement,'fingerprint',return_value='same'),patch.object(placement,'plan',side_effect=changed):
                with self.assertRaisesRegex(ValueError,'rules changed'):cli.run_native({'board':str(board)})
            self.assertEqual(board.read_text(),'original board')
