"""Portable suite reports, safe exports, and actionable bad-input handling."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from signal_integrity_advisor_plugin.cli import execute, main, parser
from signal_integrity_advisor_plugin.protocol_view import html_report, route_svg


def route():
    return dict(schema='wayricad.quick-si/v1',status='SCREENED',
                path=dict(status='ok',net_name='DATA<script>',start_pad='U1.1',end_pad='U2.1',
                          via_count=0,layer_changes=0,segments=[dict(kind='track',start_mm=[0,0],end_mm=[2,1],reference_layer='B.Cu',reference_net='GND')]),
                delay_ns=1,delay_to_rise_ratio=.2,z0_ohm=50,board_sha256='fixture',
                z0_source='User assumption',delay_source='User assumption')


class ProtocolCLITests(unittest.TestCase):
    def test_catalog_without_native_runtime(self):
        report=execute(parser().parse_args(['profiles']))
        self.assertGreaterEqual(len(report['profiles']),30)
        self.assertIn('spi',{p['id'] for p in report['profiles']})

    def test_suite_exports_and_escapes_without_modifying_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'route.json';source.write_text(json.dumps(route()),encoding='utf-8')
            before=source.read_bytes();output=Path(folder)/'suite.json';page=Path(folder)/'suite.html'
            report=execute(parser().parse_args(['suite','--profile','uart','--reports',str(source),'--max-delay-ns','1','--max-delay-to-rise-ratio','.2','--output',str(output),'--html',str(page)]))
            self.assertEqual('WITHIN_BUDGET',report['status'])
            self.assertEqual(before,source.read_bytes())
            self.assertEqual(report,json.loads(output.read_text()))
            rendered=page.read_text(encoding='utf-8')
            self.assertIn('DATA&lt;script&gt;',rendered);self.assertNotIn('<script>',rendered)
            self.assertIn('<svg',rendered)

    def test_input_overwrite_and_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'route.json';source.write_text(json.dumps(route()))
            args=['suite','--profile','uart','--reports',str(source)]
            with self.assertRaisesRegex(ValueError,'overwrite'):execute(parser().parse_args(args+['--output',str(source)]))
            source.write_text('{"bad":NaN}')
            errors=io.StringIO()
            with contextlib.redirect_stderr(errors):self.assertEqual(1,main(args))
            self.assertIn('Non-finite',errors.getvalue())

    def test_incomplete_exit_and_invalid_eye_report(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'route.json';value=route();value['eye']={'status':'ILLUSTRATIVE'}
            source.write_text(json.dumps(value))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(3,main(['suite','--profile','uart','--reports',str(source)]))
            rendered=html_report({'profile':{},'paths':[value]})
            self.assertIn('Eye plot unavailable',rendered)
            value['eye']=['invalid'];rendered=html_report({'profile':{},'paths':[value]})
            self.assertIn('Eye plot unavailable',rendered)

    def test_invalid_geometry_not_injected(self):
        result=route_svg({'segments':[{'start_mm':['<script>',0],'end_mm':[1,1]},None,{'start_mm':[float('inf'),0],'end_mm':[1,1]}]})
        self.assertNotIn('<script>',result);self.assertNotIn('<line',result)


if __name__=='__main__':unittest.main()
