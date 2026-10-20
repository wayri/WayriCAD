"""Independent-case report contracts: failures remain visible and escaped."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from quick_pi_plugin.report import write_batch_report,write_sweep_report


class BatchReportTests(unittest.TestCase):
    def test_failed_case_is_not_dropped_or_promoted(self):
        attack='<img src=x onerror=alert(1)>'
        bundle={'batch':{'schema':'wayricad.pi-batch/v1','status':'INCOMPLETE','cases':[{'name':attack,'status':'FAILED','error':attack}]}}
        with tempfile.TemporaryDirectory() as temporary:
            paths=write_batch_report(Path(temporary)/'batch.html',bundle)
            html=Path(paths['html']).read_text(encoding='utf-8')
            self.assertIn('FAILED',html);self.assertIn('&lt;img',html)
            self.assertNotIn(attack,html)
            self.assertIn('No completed result report',html)
            self.assertEqual(json.loads(Path(paths['json']).read_text(encoding='utf-8')),bundle)

    def test_child_render_failure_has_linked_error_and_exact_evidence(self):
        child={'result':{'voltage_drop_V':.05,'total_power_W':.1}}
        bundle={'batch':{'status':'COMPLETED','cases':[{'name':'Supply','status':'COMPLETED','electrical':child}]}}
        with tempfile.TemporaryDirectory() as temporary,patch('quick_pi_plugin.report.write_report',side_effect=ValueError('missing inputs')):
            paths=write_batch_report(Path(temporary)/'batch.html',bundle)
            html=Path(paths['html']).read_text(encoding='utf-8')
            self.assertIn('missing inputs',html)
            linked=Path(temporary)/paths['case_reports'][0]
            self.assertIn('REPORT ERROR',linked.read_text(encoding='utf-8'))
            self.assertEqual(json.loads(linked.with_suffix('.json').read_text(encoding='utf-8')),child)

    def test_plot_failure_leaves_existing_html_and_json_unchanged(self):
        from quick_pi_plugin.report import write_report
        from quick_pi_plugin.tests.test_report import bundle
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'report.html';evidence=output.with_suffix('.json')
            output.write_text('old report');evidence.write_text('old evidence')
            with patch('quick_pi_plugin.report.draw_view',side_effect=RuntimeError('plot failure')):
                with self.assertRaisesRegex(RuntimeError,'plot failure'):write_report(output,bundle())
            self.assertEqual(output.read_text(),'old report')
            self.assertEqual(evidence.read_text(),'old evidence')

    def test_single_operating_point_sweep_exports_without_zero_division(self):
        bundle={'sweep':{'rows':[{'current_A':1.,'path_drop_V':.1,'sink_voltage_V':3.2,'negative_sink_voltage':False}]}}
        with tempfile.TemporaryDirectory() as temporary:
            paths=write_sweep_report(Path(temporary)/'single.html',bundle)
            self.assertIn('Fixed-temperature DC current sweep',Path(paths['html']).read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
