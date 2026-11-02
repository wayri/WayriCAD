"""Native format selection and recoverable HTML/JSON/PDF publication."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from wayricad_runtime.report_dialog import choose_report_path
from wayricad_runtime.report_ui import publish_report


class ReportFormats(unittest.TestCase):
    def test_pdf_keeps_readable_html_and_exact_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'study.pdf'
            bundle={'net':'VCC', 'result':{'missing':None, 'values':[1,2,3]}}
            result=publish_report(path,'<html><h1>Current study</h1><p>2 A</p></html>',bundle)
            text=''.join(page.extract_text() for page in PdfReader(result['pdf']).pages)
            self.assertIn('Current study',text)
            self.assertIn('2 A',text)
            self.assertIn('<h1>Current study</h1>',Path(result['html']).read_text())
            self.assertEqual(json.loads(Path(result['json']).read_text()),bundle)

    def test_failed_pdf_render_keeps_all_previous_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'study.pdf'
            paths=[path,path.with_suffix('.html'),path.with_suffix('.json')]
            for candidate in paths:candidate.write_bytes(b'original')
            with patch('wayricad_runtime.pdf_report.pdf_bytes',side_effect=RuntimeError('render failed')):
                with self.assertRaisesRegex(RuntimeError,'render failed'):
                    publish_report(path,'<h1>Study</h1>',{'result':1})
            self.assertTrue(all(candidate.read_bytes()==b'original' for candidate in paths))

    def test_failed_pdf_publication_rolls_back_html_and_evidence(self):
        import wayricad_runtime.report_ui as module
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'study.pdf'
            paths=[path,path.with_suffix('.html'),path.with_suffix('.json')]
            for candidate in paths:candidate.write_bytes(b'original')
            replace=module.os.replace
            failed=False
            def fail_once(source,target):
                nonlocal failed
                if Path(target)==path and not failed:
                    failed=True
                    raise OSError('publish failed')
                return replace(source,target)
            with patch.object(module.os,'replace',side_effect=fail_once):
                with self.assertRaisesRegex(OSError,'publish failed'):
                    publish_report(path,'<h1>Study</h1>',{'result':1})
            self.assertTrue(all(candidate.read_bytes()==b'original' for candidate in paths))

    def test_pdf_cannot_replace_recorded_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source.pdf';path.write_bytes(b'source')
            with self.assertRaises(ValueError):
                publish_report(path,'<h1>Study</h1>',{'source_path':str(path)})
            self.assertEqual(path.read_bytes(),b'source')

    def test_native_format_choice_cancel_and_added_extension_overwrite(self):
        class Dialog:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def ShowModal(self):return state.modal
            def GetPath(self):return state.path
            def GetFilterIndex(self):return state.filter
        state=SimpleNamespace(modal=1,path='study.html',filter=1)
        wx=SimpleNamespace(FileDialog=lambda *a,**kw:Dialog(),ID_OK=1,FD_SAVE=2,FD_OVERWRITE_PROMPT=4,
                           YES_NO=8,NO_DEFAULT=16,ICON_QUESTION=32,YES=64,OK=128,ICON_ERROR=256,
                           MessageBox=lambda *a:0)
        with patch.dict('sys.modules',wx=wx):
            self.assertEqual(choose_report_path(None,'.','study'),Path('study.pdf'))
            state.modal=0
            self.assertIsNone(choose_report_path(None,'.','study'))
            state.modal=1
            with tempfile.TemporaryDirectory() as directory:
                state.path=str(Path(directory)/'existing')
                Path(state.path+'.pdf').write_bytes(b'keep')
                self.assertIsNone(choose_report_path(None,directory,'existing'))
                self.assertEqual(Path(state.path+'.pdf').read_bytes(),b'keep')

    def test_pi_and_thermal_real_reports_export_pdf(self):
        from quick_pi_plugin.tests.test_report import bundle
        from quick_pi_plugin.report import write_report
        from quick_therm_plugin.quick_therm import simulate_steady_state
        from quick_therm_plugin.report import write_report as thermal_report
        thermal={'quick_therm':simulate_steady_state([
            {'reference':'U1','values':{'power_w':1.,'theta_ja_air_k_per_w':40.}}
        ],environment='air',ambient_c=20.),'thermal_network':None,'board_thermal_view':{}}
        with tempfile.TemporaryDirectory() as directory:
            for name,writer,data in [('pi',write_report,bundle()),('thermal',thermal_report,thermal)]:
                with self.subTest(tool=name):
                    result=writer(Path(directory)/(name+'.pdf'),data)
                    reader=PdfReader(result['pdf'])
                    self.assertGreater(len(reader.pages),0)
                    self.assertIn('Quick',reader.pages[0].extract_text())
                    self.assertTrue(Path(result['html']).exists())

    def test_volume_pdf_contains_static_field_figures(self):
        from quick_pi_plugin.volume_view import write_volume_report
        from quick_pi_plugin.tests.test_volume_view import sample_bundle
        with tempfile.TemporaryDirectory() as directory:
            result=write_volume_report(Path(directory)/'volume.pdf',sample_bundle())
            reader=PdfReader(result['pdf'])
            self.assertGreater(sum(len(page.images) for page in reader.pages),0)
            self.assertIn('saved display samples',''.join(page.extract_text() for page in reader.pages))

    def test_batch_pdf_keeps_case_plots_under_named_scope(self):
        from quick_pi_plugin.report import write_batch_report
        from quick_pi_plugin.tests.test_report import bundle
        child=bundle();child['request']['net']='/Supply/LOAD'
        data={'batch':{'status':'COMPLETED','cases':[
            {'name':'Load path','status':'COMPLETED','electrical':child}]}}
        with tempfile.TemporaryDirectory() as directory:
            result=write_batch_report(Path(directory)/'batch.pdf',data)
            reader=PdfReader(result['pdf'])
            text=''.join(page.extract_text() for page in reader.pages)
            self.assertIn('/Supply/LOAD',text)
            self.assertIn('Voltage drop',text)
            self.assertGreater(sum(len(page.images) for page in reader.pages),0)

    def test_ac_and_electrothermal_pdf_exports(self):
        from quick_pi_plugin.ac_report import write_report as ac_report
        from quick_pi_plugin.tests.test_ac_workflow import result_bundle
        from quick_pi_plugin.electrothermal_report import write_report as coupled_report
        from quick_pi_plugin.service import execute
        from quick_pi_plugin.tests.test_electrothermal import request
        with tempfile.TemporaryDirectory() as directory:
            coupled=execute({'action':'electrothermal','mode':'steady','study':request()})
            for name,writer,data in [('ac',ac_report,result_bundle()),('coupled',coupled_report,coupled)]:
                with self.subTest(tool=name):
                    result=writer(Path(directory)/(name+'.pdf'),data)
                    self.assertTrue(Path(result['pdf']).read_bytes().startswith(b'%PDF-'))
                    self.assertEqual(json.loads(Path(result['json']).read_text(encoding='utf-8')),
                                     json.loads(json.dumps(data,allow_nan=False)))
