"""Two-point DC potential probes: analytical field, custody and UI contracts."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from contextlib import redirect_stdout
import unittest

from quick_pi_plugin.differential_probe import sample_point,differential_probe,report_html,saved_probe


def field():
    return {'mesh':{'points_mm':[[0,0,0],[2,0,0],[0,2,0]],'triangles':[[0,1,2]],'triangle_layer':[0]},
            'result':{'potential_V':[5.,3.,1.]}}


class DifferentialTests(unittest.TestCase):
    def test_malformed_saved_objects_and_nonfinite_json_fail_cleanly(self):
        with self.assertRaisesRegex(ValueError,'objects'):sample_point({'mesh':None,'result':{}},0,0,0)
        from quick_pi_plugin.cli import main
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'result.json';path.write_text('{"mesh":{},"result":{},"bad":NaN}')
            with redirect_stdout(io.StringIO()) as output:
                status=main(['--probe-result',str(path),'--probe-a','0','0','0','--probe-b','0','1','1'])
            self.assertEqual(status,2)
            self.assertIn('Non-finite',json.loads(output.getvalue())['error'])

    def test_affine_fem_field_sign_zero_and_reversal(self):
        b=field();a=dict(layer=0,x_mm=.25,y_mm=.25);z=dict(layer=0,x_mm=1,y_mm=.5)
        self.assertAlmostEqual(sample_point(b,**a)['potential_V'],4.25)
        self.assertAlmostEqual(differential_probe(b,a,z)['voltage_a_minus_b_V'],1.25)
        self.assertAlmostEqual(differential_probe(b,z,a)['voltage_a_minus_b_V'],-1.25)
        self.assertEqual(differential_probe(b,a,a)['voltage_a_minus_b_V'],0)

    def test_unknown_void_layer_and_potential_are_not_nearest_guesses(self):
        b=field()
        for point in (dict(layer=0,x_mm=2,y_mm=2),dict(layer=3,x_mm=.1,y_mm=.1)):
            self.assertIsNone(sample_point(b,**point)['potential_V'])
        b['result']['potential_V'][0]=None
        self.assertIsNone(sample_point(b,0,.1,.1)['potential_V'])
        with self.assertRaises(ValueError):sample_point(b,'all',.1,.1)
        for value in (float('inf'),float('nan')):
            with self.assertRaises(ValueError):sample_point(b,0,value,0)

    def test_common_gauge_and_stale_source(self):
        a=dict(layer=0,x_mm=.1,y_mm=.1)
        with self.assertRaisesRegex(ValueError,'Independent'):differential_probe({'cases':[field()]},a,a)
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'board.kicad_pcb';source.write_bytes(b'old')
            b=field();b.update(board_path=str(source),source_sha256=hashlib.sha256(b'old').hexdigest())
            self.assertEqual(differential_probe(b,a,a)['status'],'SAMPLED')
            source.write_bytes(b'new')
            with self.assertRaisesRegex(ValueError,'changed'):differential_probe(b,a,a)

    def test_saved_points_recompute_and_report_is_inert(self):
        b=field();b['differential_probes']={'a':dict(layer=0,x_mm=.25,y_mm=.25),'b':dict(layer=0,x_mm=1,y_mm=.5)}
        self.assertAlmostEqual(saved_probe(b)['voltage_a_minus_b_V'],1.25)
        html=report_html(b,0)
        self.assertIn('Saved probe V(A) - V(B): 1.25 V',html)
        self.assertIn('diff-readout',html);self.assertIn('canvas.addEventListener',html)
        b['result']['potential_V']=[2*v for v in b['result']['potential_V']]
        self.assertAlmostEqual(saved_probe(b)['voltage_a_minus_b_V'],2.5)

    def test_saved_cli_no_solve_and_source_retained(self):
        from quick_pi_plugin.cli import main
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'result.json';path.write_text(json.dumps(field()))
            raw=path.read_bytes();output=Path(temporary)/'probe.json'
            arguments=['--probe-result',str(path),'--probe-a','0','.25','.25','--probe-b','0','1','.5','--output',str(output)]
            self.assertEqual(main(arguments),0)
            self.assertEqual(json.loads(output.read_text())['voltage_a_minus_b_V'],1.25)
            self.assertEqual(raw,path.read_bytes())
            with redirect_stdout(io.StringIO()):self.assertEqual(main(arguments[:-1]+[str(path)]),2)
            self.assertEqual(raw,path.read_bytes())

    def test_plot_markers_and_saved_report(self):
        from quick_pi_plugin.tests.test_report import bundle
        from quick_pi_plugin.report import draw_view,write_report
        from matplotlib.figure import Figure
        b=bundle();b['differential_probes']={'a':dict(layer=0,x_mm=1,y_mm=.5),'b':dict(layer=0,x_mm=9,y_mm=.5)}
        axes=draw_view(Figure(),b,'Results',0,'drop')
        self.assertTrue({'A','B'}<=set(text.get_text() for text in axes.texts))
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'report.html';write_report(path,b)
            self.assertIn('Saved probe V(A) - V(B)',path.read_text(encoding='utf-8'))
            self.assertEqual(json.loads(path.with_suffix('.json').read_text())['differential_probes'],b['differential_probes'])

    def test_location_cache_retains_only_geometry_and_resamples_updated_nodes(self):
        b=field();a=dict(layer=0,x_mm=.25,y_mm=.25);z=dict(layer=0,x_mm=1,y_mm=.5);cache={}
        self.assertEqual(differential_probe(b,a,z,location_cache=cache)['voltage_a_minus_b_V'],1.25)
        import numpy as np
        from unittest.mock import patch
        with patch.object(np,'asarray',side_effect=AssertionError('cached positions must not rebuild full arrays')):
            b['result']['potential_V']=[10.,6.,2.]
            self.assertEqual(differential_probe(b,a,z,location_cache=cache)['voltage_a_minus_b_V'],2.5)
        other=field();other['mesh']['points_mm'][1][0]=4
        self.assertNotEqual(differential_probe(other,a,z,location_cache=cache)['voltage_a_minus_b_V'],2.5)

    def test_invalid_mesh_overflow_and_dense_report_bound(self):
        b=field();b['mesh']['triangles'][0][0]=100
        with self.assertRaises(ValueError):sample_point(b,0,.1,.1)
        b=field();b['result']['potential_V']=[1.7e308,-1.7e308,0.]
        with self.assertRaisesRegex(ValueError,'finite'):differential_probe(b,dict(layer=0,x_mm=0,y_mm=0),dict(layer=0,x_mm=2,y_mm=0))
        b=field();b['mesh']['triangles']*=20001;b['mesh']['triangle_layer']*=20001
        html=report_html(b,0)
        self.assertIn('omitted above 20,000',html);self.assertNotIn('diff-data',html)

    def test_offline_browser_locator_matches_analytical_points(self):
        import re,shutil,subprocess
        node=shutil.which('node')
        if not node:self.skipTest('Node is required to execute the offline report locator.')
        html=report_html(field(),0)
        payload=re.search(r'<script type="application/json" class="diff-data">(.*?)</script>',html,re.S)[1]
        locator=html[html.index('const cross='):html.index('function draw()')]
        script='const data='+payload+';const byLayer=new Map([["0",[0]]]);'+locator+';console.log(JSON.stringify([sample({layer:0,x_mm:.25,y_mm:.25}),sample({layer:0,x_mm:1,y_mm:.5}),sample({layer:0,x_mm:2,y_mm:2})]));'
        result=subprocess.run([node,'-e',script],capture_output=True,text=True,timeout=10,check=True)
        self.assertEqual(json.loads(result.stdout),[4.25,3,None])


if __name__=='__main__':unittest.main()
