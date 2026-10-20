"""Independent-case report contracts: failures remain visible and escaped."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from quick_pi_plugin.report import write_batch_report,write_sweep_report


class BatchReportTests(unittest.TestCase):
    def test_index_uses_compact_inputs_and_links_complete_mesh_evidence(self):
        marker='BULKY_MESH_SENTINEL'
        child={'request':{'net':'Supply','source_terminals':['J1.1','J1.2']},
               'mesh':{'large_array':[marker]*1000},
               'result':{'voltage_drop_V':.05,'total_power_W':.1}}
        batch={'batch':{'status':'COMPLETED','cases':[{'name':'Supply','status':'COMPLETED','electrical':child}]}}
        with tempfile.TemporaryDirectory() as temporary,patch('quick_pi_plugin.report.write_report',side_effect=ValueError('fixture without geometry')):
            paths=write_batch_report(Path(temporary)/'batch.html',batch)
            html=Path(paths['html']).read_text(encoding='utf-8')
            self.assertNotIn(marker,html)
            self.assertIn('source_terminals',html)
            self.assertEqual(json.loads(Path(paths['json']).read_text(encoding='utf-8')),batch)

    def test_shared_return_report_has_physical_ground_maps_and_perload_voltages(self):
        from quick_pi_plugin.tests.test_report import bundle as strip_bundle
        from quick_pi_plugin.solver import solve
        child=strip_bundle();mesh=child['mesh']
        source=[i for i,p in enumerate(mesh['points_mm']) if p[0]==0]
        sink=[i for i,p in enumerate(mesh['points_mm']) if p[0]==10]
        child['result']=solve(mesh,source,sink,source_voltage=0,sink_current=2)
        load={'case':'Supply','sink':'chip','current_A':2.,'ground_rise_V':.01,
              'supply_drop_V':.02,'delivered_load_voltage_V':3.27,'voltage_limits_met':True}
        group={'name':'Common ground','status':'COMPLETED','return_conduction':child,'loads':[load],
               'return_loss_W':.02,'total_loss_W':.06,'power_balance_error_W':0.}
        batch={'batch':{'status':'COMPLETED','cases':[{'name':'Supply','status':'COMPLETED',
            'shared_return':{'group':'Common ground','loads':[load]}}],
            'shared_returns':[group]}}
        with tempfile.TemporaryDirectory() as temporary:
            paths=write_batch_report(Path(temporary)/'batch.html',batch)
            html=Path(paths['html']).read_text(encoding='utf-8')
            self.assertIn('3.27',html);self.assertIn('Shared return loss (counted once)',html)
            linked=Path(temporary)/paths['case_reports'][0]
            physical=json.loads(linked.with_suffix('.json').read_text(encoding='utf-8'))
            reference=physical['evidence_reference']
            parent=json.loads((linked.parent/reference['json']).read_text(encoding='utf-8'))
            raw=parent
            for key in reference['json_pointer'].split('/')[1:]:
                raw=raw[int(key)] if isinstance(raw,list) else raw[key]
            self.assertEqual(raw,child)
            self.assertGreater(raw['result']['potential_V'][sink[0]]*reference['sign_transforms']['/result/potential_V'],0)
            self.assertLess(raw['result']['cell_J_A_mm2'][0][0]*reference['sign_transforms']['/result/cell_J_A_mm2'],0)
            self.assertIn('Ground rise above source ground',linked.read_text(encoding='utf-8'))

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
            descriptor=json.loads(linked.with_suffix('.json').read_text(encoding='utf-8'))
            reference=descriptor['evidence_reference']
            raw=json.loads((linked.parent/reference['json']).read_text(encoding='utf-8'))
            for key in reference['json_pointer'].split('/')[1:]:
                raw=raw[int(key)] if isinstance(raw,list) else raw[key]
            self.assertEqual(raw,child)

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
