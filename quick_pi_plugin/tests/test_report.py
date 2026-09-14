"""Numerical-to-visual/report contracts for the analytical strip fixture."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from quick_pi_plugin.solver import solve
from quick_pi_plugin.report import cell_values,draw_view,write_report,via_markers
from quick_pi_plugin.tests.test_solver import strip


def bundle():
    mesh,source,sink=strip()
    mesh['triangle_layer']=[0]*len(mesh['triangles'])
    geometry={'net':'Analytical strip','layers':[{'id':0,'name':'F.Cu','polygons':[{'outer':[[0,0],[10,0],[10,1],[0,1]],'holes':[]}]}],
              'terminals':[{'id':'A','label':'A.1','polygons':{'0':[{'outer':[[0,0],[.1,0],[.1,1],[0,1]],'holes':[]}]}},
                           {'id':'B','label':'B.1','polygons':{'0':[{'outer':[[9.9,0],[10,0],[10,1],[9.9,1]],'holes':[]}]}}],
              'vias':[]}
    mesh['geometry']=geometry
    result=solve(mesh,source,sink,source_voltage=1,sink_current=2,options={'pulse_duration_s':1})
    return {'mesh':mesh,'geometry':geometry,'result':result,'request':{'source_terminal':'A','sink_terminal':'B','net':'Analytical strip'}}


class ReportTests(unittest.TestCase):
    def test_via_segments_use_layer_span_and_worst_overlap(self):
        geometry={'layers':[{'id':0,'z_mm':0},{'id':4,'z_mm':.5},{'id':2,'z_mm':1},{'id':31,'z_mm':1.5}]}
        mesh={'vias':[{'id':'v:0-2','top_layer':0,'bottom_layer':2,'x_mm':1,'y_mm':2,'drill_mm':.3,'plating_mm':.025},
                       {'id':'v:2-31','top_layer':2,'bottom_layer':31,'x_mm':1,'y_mm':2,'drill_mm':.3,'plating_mm':.025}]}
        result={'vias':[{'id':'v:0-2','current_density_A_mm2':100,'thermal':{'energy_ratio':2}},
                        {'id':'v:2-31','current_density_A_mm2':1000,'thermal':{'energy_ratio':20}}]}
        self.assertEqual(via_markers(mesh,result,geometry,4,'risk')[0]['value'],2)
        self.assertEqual(via_markers(mesh,result,geometry,0,'density')[0]['value'],100)
        self.assertEqual(len(via_markers(mesh,result,geometry,2,'density')),1)
        self.assertEqual(via_markers(mesh,result,geometry,2,'density')[0]['value'],1000)

    def test_hot_barrel_expands_color_scale_and_preserves_drill_hole(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        b=bundle();b['geometry']['layers'].append({'id':31,'name':'B.Cu','polygons':[]})
        b['mesh']['vias']=[{'id':'hot','top_layer':0,'bottom_layer':31,'x_mm':5,'y_mm':.5,'drill_mm':.3,'plating_mm':.025}]
        b['result']['vias']=[{'id':'hot','current_density_A_mm2':10000,'thermal':{'energy_ratio':1000}}]
        for metric,value in [('density',10000),('risk',1000)]:
            figure=Figure(figsize=(5,3));FigureCanvasAgg(figure)
            axes=draw_view(figure,b,'Results',0,metric);figure.canvas.draw()
            colored=next(p for p in axes.patches if p.get_gid()=='via-barrel:hot')
            image=next(c for c in axes.collections if c.get_array() is not None)
            self.assertGreaterEqual(image.get_clim()[1],value)
            self.assertTrue(np.allclose(colored.get_facecolor(),image.cmap(image.norm(value))))
            drill=axes.patches[-1];self.assertAlmostEqual(drill.radius,.15)
            self.assertEqual(tuple(drill.get_facecolor()),(1.,1.,1.,1.))

    def test_maps_use_solver_units_and_power_density(self):
        b=bundle();mesh,result=b['mesh'],b['result']
        self.assertTrue(np.allclose(cell_values(mesh,result,'density'),2/.035))
        self.assertTrue(np.allclose(cell_values(mesh,result,'flow'),2))
        self.assertTrue(np.allclose(cell_values(mesh,result,'loss'),result['total_power_W']/10))
        self.assertTrue(np.all(cell_values(mesh,result,'drop')>0))
        self.assertTrue(np.allclose(cell_values(mesh,result,'resistance'),cell_values(mesh,result,'drop')/2))
        self.assertTrue(np.all(cell_values(mesh,result,'risk')>0))

    def test_all_three_views_and_six_metrics_render(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        b=bundle()
        for view,metric in [('Net','drop'),('Mesh','drop')]+[('Results',m) for m in ('voltage','drop','resistance','density','flow','loss','risk')]:
            with self.subTest(view=view,metric=metric):
                figure=Figure(figsize=(5,3));FigureCanvasAgg(figure)
                axes=draw_view(figure,b,view,0,metric);figure.canvas.draw()
                self.assertTrue(axes.yaxis_inverted())
                self.assertTrue(axes.patches or axes.collections)

    def test_report_is_offline_and_retains_all_numeric_results(self):
        with tempfile.TemporaryDirectory() as directory:
            b=bundle();paths=write_report(Path(directory)/'report.html',b,0)
            html=Path(paths['html']).read_text()
            self.assertEqual(html.count('data:image/png;base64,'),7)
            self.assertNotIn('https://',html)
            self.assertIn('Copper resistance uses the solved voltage drop',html)
            self.assertIn('Mesh convergence not verified',html)
            stored=json.loads(Path(paths['json']).read_text())
            self.assertEqual(stored['result']['potential_V'],b['result']['potential_V'])
            self.assertEqual(stored['mesh']['triangles'],b['mesh']['triangles'])

    def test_explicit_components_are_distinguished_from_copper(self):
        with tempfile.TemporaryDirectory() as directory:
            b=bundle();b['request']['series']=[{'id':'R1'}]
            b['result']['components']=[{'id':'R1','resistance_ohm':.005,'inductance_h':1e-8,'power_W':.02}]
            b['result']['conductor_power_W']=b['result']['total_power_W']
            b['result']['component_power_W']=.02
            paths=write_report(Path(directory)/'series.html',b,0)
            html=Path(paths['html']).read_text()
            self.assertIn('Circuit resistance ΔV/I',html)
            self.assertIn('Component loss',html)
            self.assertIn('not an AC or transient solve',html)


if __name__=='__main__':unittest.main()
