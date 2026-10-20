"""Discoverable batch CLI, path preservation and explicit failure exit codes."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from quick_pi_plugin.cli import main
from quick_pi_plugin.tests.test_batch import study


class BatchCLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.board=self.root/'board.kicad_pcb';self.board.write_text('board')
        self.input=self.root/'cases.json';self.input.write_text(json.dumps(study()),encoding='utf-8')

    def invoke(self,extra=(),status='COMPLETED',case_status='COMPLETED'):
        output=io.StringIO();result={'batch':{'status':status,'cases':[{'name':'A','status':case_status}]}}
        with patch('quick_pi_plugin.service.run_job',return_value=result) as worker,contextlib.redirect_stdout(output):
            code=main([str(self.board),'--batch',str(self.input),*extra])
        return code,worker,output.getvalue()

    def test_explicit_batch_and_report_targets_reach_worker(self):
        target=self.root/'raw-cases.json';html=self.root/'out.html'
        code,worker,text=self.invoke(['--output',str(target),'--html',str(html)])
        self.assertEqual(code,0)
        request=worker.call_args.args[0]
        self.assertEqual(request['action'],'batch');self.assertEqual(request['study'],study())
        self.assertEqual(request['html_output'],str(html.resolve()))
        self.assertEqual(request['study_input_path'],str(self.input.resolve()))
        self.assertEqual(len(request['study_file_sha256']),64)
        self.assertEqual(json.loads(target.read_text())['batch']['status'],'COMPLETED')
        self.assertEqual(self.board.read_text(),'board')

    def test_no_false_success_when_case_failed_or_load_infeasible(self):
        self.assertEqual(self.invoke(status='INCOMPLETE',case_status='FAILED')[0],3)
        self.assertEqual(self.invoke(status='INCOMPLETE',case_status='INFEASIBLE')[0],4)

    def test_mixed_modes_and_source_overwrites_do_not_run(self):
        for extra in (['--net','other'],['--output',str(self.root/'result.json'),'--html',str(self.root/'result.html')],['--output',str(self.input)],['--output',str(self.board)],['--html',str(self.input.with_suffix('.html'))]):
            with self.subTest(extra=extra):
                code,worker,text=self.invoke(extra)
                self.assertEqual(code,2);worker.assert_not_called();self.assertIn('error',text)
        self.assertEqual(json.loads(self.input.read_text()),study())

    def test_bad_or_duplicate_json_cannot_launch_worker(self):
        self.input.write_text('{"schema":"first","schema":"duplicate","cases":[]}',encoding='utf-8')
        code,worker,text=self.invoke();self.assertEqual(code,2);worker.assert_not_called()
        self.assertIn('Repeated',text)


if __name__=='__main__':unittest.main()
