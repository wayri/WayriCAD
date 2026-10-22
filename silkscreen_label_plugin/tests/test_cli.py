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
    def test_references_only_overrides_settings_before_native_launch(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as raw:
            settings=Path(raw)/'settings.json'
            settings.write_text(json.dumps(dict(references=False,values=True,board_text=True)))
            captured=[]
            def native(command,**kwargs):
                request=json.loads(Path(command[-2]).read_text(encoding='utf-8'))
                captured.append(request['settings'])
                Path(command[-1]).write_text(json.dumps({'status':'PREVIEW'}),encoding='utf-8')
                return SimpleNamespace(returncode=0,stderr='')
            with patch('wayricad_runtime.runtime_setup.native_python',return_value=Path('native-python')),patch.object(cli.subprocess,'run',side_effect=native),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['preview','board.kicad_pcb','--settings',str(settings),'--references-only']),0)
            self.assertEqual(captured,[dict(references=True,values=False,board_text=False)])

    def test_problems_only_sets_planner_scope_before_native_launch(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as raw:
            captured=[]
            def native(command,**kwargs):
                captured.append(json.loads(Path(command[-2]).read_text(encoding='utf-8'))['settings'])
                Path(command[-1]).write_text(json.dumps({'status':'PREVIEW'}),encoding='utf-8')
                return SimpleNamespace(returncode=0,stderr='')
            with patch('wayricad_runtime.runtime_setup.native_python',return_value=Path('native-python')),patch.object(cli.subprocess,'run',side_effect=native),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['preview','board.kicad_pcb','--problems-only']),0)
            self.assertEqual(captured,[{'problem_only':True}])

    def test_generated_audit_cli_is_read_only_native_worker_request(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as raw:
            source=Path(raw)/'board.kicad_pcb';source.write_text('board bytes')
            captured=[]
            def native(command,**kwargs):
                request=json.loads(Path(command[-2]).read_text(encoding='utf-8'))
                captured.append(request)
                Path(command[-1]).write_text(json.dumps({'status':'AUDIT','findings':[]}),encoding='utf-8')
                return SimpleNamespace(returncode=0,stderr='')
            out=io.StringIO()
            with patch('wayricad_runtime.runtime_setup.native_python',return_value=Path('native-python')),patch.object(cli.subprocess,'run',side_effect=native),contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(['audit-generated',str(source)]),0)
            self.assertEqual(captured[0]['operation'],'audit-generated')
            self.assertEqual(captured[0]['board'],str(source.resolve()))
            self.assertEqual(captured[0]['settings'],{})
            self.assertEqual(source.read_text(),'board bytes')
            self.assertEqual(json.loads(out.getvalue())['status'],'AUDIT')

    def test_report_option_writes_only_explicit_new_html_path(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as raw:
            source=Path(raw)/'board.kicad_pcb';source.write_text('board bytes')
            report=Path(raw)/'review.html';captured=[]
            def native(command,**kwargs):
                request=json.loads(Path(command[-2]).read_text(encoding='utf-8'));captured.append(request)
                payload={'status':'PREVIEW','source_sha256':'hash','stats':{},'rejected':[],'skipped':[],
                    'review_geometry':{'board_mm':[0,0,1,1],'features':[],'outcomes':[{'id':'i','side':'top','label':'<script>','status':'UNRESOLVED'}]}}
                Path(command[-1]).write_text(json.dumps(payload),encoding='utf-8')
                return SimpleNamespace(returncode=0,stderr='')
            out=io.StringIO()
            with patch('wayricad_runtime.runtime_setup.native_python',return_value=Path('native-python')),patch.object(cli.subprocess,'run',side_effect=native),contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(['preview',str(source),'--report',str(report)]),0)
            self.assertTrue(captured[0]['include_report_geometry'])
            self.assertTrue(report.is_file())
            self.assertEqual(source.read_text(),'board bytes')
            html=report.read_text(encoding='utf-8')
            self.assertIn('&lt;script&gt;',html)
            self.assertEqual(html.count('<script>'),1)
            self.assertNotIn('review_geometry',out.getvalue())

    def test_run_native_generated_audit_returns_findings_without_mutation(self):
        from types import SimpleNamespace
        import sys
        from silkscreen_label_plugin import lifecycle, placement
        with tempfile.TemporaryDirectory() as raw:
            source=Path(raw)/'board.kicad_pcb';source.write_text('board bytes')
            native=SimpleNamespace(LoadBoard=lambda _path:object())
            report=SimpleNamespace(source_fingerprint='fingerprint',as_dict=lambda:{'findings':[{'status':'legacy_unverified'}],'cleanup_group_ids':[]})
            with patch.dict(sys.modules,{'pcbnew':native}),patch.object(placement,'fingerprint',return_value='same'),patch.object(lifecycle,'audit',return_value=report):
                result=cli.run_native({'operation':'audit-generated','board':str(source)})
            self.assertEqual(result['status'],'AUDIT')
            self.assertFalse(result['writes_board'])
            self.assertFalse(result['can_apply'])
            self.assertEqual(result['findings'],[{'status':'legacy_unverified'}])
            self.assertEqual(source.read_text(),'board bytes')

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
