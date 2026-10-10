"""Numerical-to-visual/report contracts for the analytical strip fixture."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from quick_pi_plugin.solver import solve
from quick_pi_plugin.report import (cell_values,draw_view,write_report,via_markers,
                                   probe_result,inspection_record,result_scale,validate_scale)
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
    def test_package_ledger_and_board_package_voltages_are_exported(self):
        from quick_pi_plugin.package_contacts import attach
        from quick_pi_plugin.tests.test_package_contacts import path
        b=bundle();mesh=b['mesh'];geo=b['geometry']
        for row,ref in zip(geo['terminals'],('J1','U1')):
            row.update(reference=ref,pad_number='1',net=geo['net'])
        source=[i for i,p in enumerate(mesh['points_mm']) if p[0]==0]
        sink=[i for i,p in enumerate(mesh['points_mm']) if p[0]==10]
        mesh.update(terminal_nodes={'A':source,'B':sink},terminal_nodes_by_layer={'A':{'0':source},'B':{'0':sink}})
        contact=path('lead','J1','source')
        contact['segments'][0].update(width_mm=.1,thickness_mm=.5,rho_ohm_m=5e-7)
        net,src,loads=attach(mesh,geo,[contact],'A',
                             [dict(id='B',terminal='B',nodes=sink,current_A=2)])
        b.update(mesh=net,result=solve(net,src,sinks=loads))
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'contacts.html'
            write_report(output,b)
            html=output.read_text(encoding='utf-8')
            self.assertIn('Explicit package contacts',html)
            self.assertIn('package 1 V; board',html)
            self.assertIn('Package contact loss',html)
            payload=json.loads(output.with_suffix('.json').read_text())
            self.assertAlmostEqual(payload['result']['package_contacts'][0]['segments'][0]['power_W'],.04,10)

    def test_probe_hits_actual_triangle_and_retains_unknowns(self):
        b=bundle()
        row=probe_result(b,0,5,.5,'drop')
        self.assertEqual(row['kind'],'sheet')
        self.assertEqual(row['unit'],'mV')
        self.assertAlmostEqual(row['value'],cell_values(b['mesh'],b['result'],'drop')[row['id']])
        self.assertEqual(row['source_ids'],[])
        self.assertIsNone(probe_result(b,31,5,.5))
        self.assertIsNone(probe_result(b,0,11,.5))
        b['result']['cell_J_A_mm2'][row['id']]=None
        unknown=inspection_record(b,'sheet',row['id'],'density')
        self.assertIsNone(unknown['value'])
        self.assertIsNone(unknown['current_density_A_mm2'])

    def test_barrel_probe_resolves_saved_identity_and_excludes_drill_and_wrong_layer(self):
        b=bundle()
        b['geometry']['layers'].append({'id':31,'name':'B.Cu','z_mm':1.6,'polygons':[]})
        b['geometry']['vias']=[{'id':'saved-object'}]
        b['mesh']['vias']=[{'id':'saved-object:0-31','top_layer':0,'bottom_layer':31,
                          'x_mm':5,'y_mm':.5,'drill_mm':.3,'plating_mm':.025}]
        b['result']['vias']=[{'id':'saved-object:0-31','current_density_A_mm2':10000,
                              'current_A':1,'power_W':.02,'thermal':{'energy_ratio':5}}]
        row=probe_result(b,0,5.16,.5,'drop')
        self.assertEqual(row['kind'],'via')
        self.assertEqual(row['source_ids'],['saved-object'])
        self.assertEqual((row['value'],row['unit']),(10000,'A/mm²'))
        self.assertIsNone(probe_result(b,0,5,.5))
        self.assertIsNone(probe_result(b,5,5.16,.5))
        b['geometry']['vias']=[]
        self.assertEqual(inspection_record(b,'via','saved-object:0-31')['source_ids'],[])

    def test_shared_scale_includes_all_layers_and_barrel_peaks(self):
        b=bundle()
        b['geometry']['layers'].append({'id':31,'name':'B.Cu','polygons':[]})
        b['mesh']['vias']=[{'id':'hot','top_layer':31,'bottom_layer':31,'x_mm':5,'y_mm':.5,'drill_mm':.3,'plating_mm':.025}]
        b['result']['vias']=[{'id':'hot','current_density_A_mm2':10000,'thermal':{'energy_ratio':50}}]
        self.assertGreaterEqual(result_scale(b,'density')[1],10000)
        self.assertLess(result_scale(b,'density',0)[1],10000)
        self.assertEqual(result_scale(b,'risk')[0],0)
        self.assertIsNone(result_scale({},'density'))
        for limits in [(1,1),(2,1),(float('nan'),3),(0,float('inf'))]:
            with self.assertRaises(ValueError):validate_scale(*limits)

    def test_manual_color_scale_and_selected_location_are_rendered(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        b=bundle();figure=Figure(figsize=(5,3));FigureCanvasAgg(figure)
        row=probe_result(b,0,5,.5,'density')
        axes=draw_view(figure,b,'Results',0,'density',(0,100),row);figure.canvas.draw()
        image=next(item for item in axes.collections if item.get_array() is not None)
        self.assertEqual(image.get_clim(),(0,100))
        marker=next(item for item in axes.lines if item.get_marker()=='+')
        self.assertAlmostEqual(marker.get_xdata()[0],row['location_mm'][0])

    def test_board_context_overlay_toggle_and_exact_trace_outline(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        b=bundle();scene={'layers':{0:'F.Cu'},'warnings':[],'bounds':[0,0,12,3],
                         'primitives':[{'kind':'polygon','role':'track','layer':0,'uuid':'actual-track','net':'Analytical strip',
                                        'points':[[11,2],[12,2],[12,3],[11,3]],'holes':[]}]}
        b['board_scene']=scene
        figure=Figure(figsize=(5,3));FigureCanvasAgg(figure)
        row=probe_result(b,0,5,.5);row['source_ids']=['actual-track']
        ax=draw_view(figure,b,'Results',0,'density',inspection=row,show_overlay=False)
        self.assertFalse(any(item.get_array() is not None for item in ax.collections))
        self.assertTrue(any(patch.get_zorder()==9 for patch in ax.patches))
        self.assertGreaterEqual(ax.get_xlim()[1],12)
        ax=draw_view(figure,b,'Results',0,'density',show_context=False,show_copper=False,show_overlay=False)
        self.assertFalse(ax.patches)

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
            html=Path(paths['html']).read_text(encoding='utf-8')
            self.assertEqual(html.count('data:image/png;base64,'),7)
            self.assertNotIn('https://',html)
            self.assertIn('Three primary result plots',html)
            self.assertLess(html.index('<figcaption>Voltage drop'),html.index('<figcaption>Current density'))
            self.assertLess(html.index('<figcaption>Current density'),html.index('<figcaption>Copper loss density'))
            self.assertIn('Copper resistance uses the solved voltage drop',html)
            self.assertIn('Mesh convergence not verified',html)
            stored=json.loads(Path(paths['json']).read_text(encoding='utf-8'))
            self.assertEqual(stored['result']['potential_V'],b['result']['potential_V'])
            self.assertEqual(stored['mesh']['triangles'],b['mesh']['triangles'])

    def test_explicit_components_are_distinguished_from_copper(self):
        with tempfile.TemporaryDirectory() as directory:
            b=bundle();b['request']['series']=[{'id':'R1'}]
            b['result']['components']=[{'id':'R1','resistance_ohm':.005,'inductance_h':1e-8,'power_W':.02}]
            b['result']['conductor_power_W']=b['result']['total_power_W']
            b['result']['component_power_W']=.02
            paths=write_report(Path(directory)/'series.html',b,0)
            html=Path(paths['html']).read_text(encoding='utf-8')
            self.assertIn('Circuit resistance ΔV/I',html)
            self.assertIn('Component loss',html)
            self.assertIn('not an AC or transient solve',html)

    def test_forward_drop_report_labels_apparent_ratio_and_voltage_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            b=bundle();b['request']['series']=[{'id':'D1','fixed_drop_v':1.}]
            b['result']['contains_forward_drop']=True
            b['result']['negative_sink_voltage']=True
            b['result']['components']=[{'id':'D1','model':'fixed_drop','current_A':2.,
                'voltage_before_V':.8,'voltage_drop_V':1.,'voltage_after_V':-.2,'power_W':2.}]
            path=write_report(Path(directory)/'diode.html',b,0)['html']
            html=Path(path).read_text(encoding='utf-8')
            self.assertIn('Circuit apparent ΔV/I',html)
            self.assertIn('not resistance',html)
            self.assertIn('Operating-point warning',html)
            self.assertIn('D1</td><td>fixed_drop',html)

    def test_multisink_report_and_maps_keep_all_demands_and_overload_diagnostic(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        b=bundle();mesh,source,sink=strip()
        middle=[index for index,point in enumerate(mesh['points_mm']) if point[0]==5]
        b['geometry']['terminals'].append({'id':'C','label':'C.1','polygons':{'0':[{'outer':[[4.9,0],[5.1,0],[5.1,1],[4.9,1]],'holes':[]}]}})
        b['request'].pop('sink_terminal');b['request']['sinks']=[{'terminal':'B'},{'terminal':'C'}]
        b['result']=solve(b['mesh'],source,sinks=[{'id':'B','label':'B.1','nodes':sink,'current_A':1,'min_voltage_V':.99},
                                               {'id':'C','label':'C.1','nodes':middle,'current_A':.5,'min_voltage_V':.9,'max_voltage_V':1.1}],
                          source_current_limit=1)
        figure=Figure(figsize=(6,4));FigureCanvasAgg(figure)
        axes=draw_view(figure,b,'Results',0,'resistance');figure.canvas.draw()
        self.assertIn('requested-load diagnostic',axes.get_title(loc='left'))
        self.assertIn('total demand',figure.axes[1].get_ylabel())
        labels=[text.get_text() for text in axes.texts]
        for label in ('Source: A.1','Sink: B.1','Sink: C.1'):self.assertIn(label,labels)
        with tempfile.TemporaryDirectory() as directory:
            paths=write_report(Path(directory)/'multisink.html',b,0)
            html=Path(paths['html']).read_text(encoding='utf-8')
            for text in ('INFEASIBLE','B.1','C.1','Headroom: -0.5 A','Worst drop / total demand','requested-load diagnostic',
                         'not a physical two-terminal resistance','Min V','Max V'):
                self.assertIn(text,html)
            self.assertNotIn('Copper resistance ΔV/I',html)
            stored=json.loads(Path(paths['json']).read_text(encoding='utf-8'))
            self.assertEqual(stored['result']['sinks'],b['result']['sinks'])
            self.assertFalse(stored['result']['feasibility']['operating_point_valid'])


if __name__=='__main__':unittest.main()
