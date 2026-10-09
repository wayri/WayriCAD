"""Continuous display uses solved support and preserves numerical evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import PolyCollection, TriMesh
from matplotlib.figure import Figure

from quick_pi_plugin.report import (cell_values, draw_view, gradient_surface,
                                    probe_result, result_scale, write_report)
from quick_pi_plugin.tests.test_report import bundle


class FieldRenderingTests(unittest.TestCase):
    def test_linear_strip_retains_nodal_voltage_drop_and_endpoints(self):
        b=bundle();mesh=b['mesh'];result=b['result']
        indices=np.arange(len(mesh['triangles']))
        for metric,scale in [('voltage',1.),('drop',1000.),('resistance',500.)]:
            xy,faces,values=gradient_surface(mesh,result,metric,indices)
            potential=1.-result['voltage_drop_V']*xy[:,0]/10.
            expected=potential if metric=='voltage' else (1.-potential)*scale
            np.testing.assert_allclose(values,expected,atol=2e-10)
            self.assertEqual(len(faces),len(indices))
        self.assertAlmostEqual(result_scale(b,'drop')[0],0.,10)
        self.assertAlmostEqual(result_scale(b,'drop')[1],1000.*result['voltage_drop_V'],10)

    def test_area_weighted_cell_display_stays_within_original_values(self):
        mesh={'points_mm':[[0,0,0],[1,0,0],[0,1,0],[1,2,0]],
              'triangles':[[0,1,2],[1,3,2]],'triangle_layer':[0,0],
              'triangle_thickness_mm':[.035,.035]}
        result={'cell_J_A_mm2':[[1,0],[9,0]]}
        _,_,values=gradient_surface(mesh,result,'density',[0,1])
        # Areas are .5 and 1.; their shared corners use (1*.5+9*1)/1.5.
        np.testing.assert_allclose(values,[1.,19./3,19./3,19./3,9.,19./3])
        self.assertGreaterEqual(values.min(),1.)
        self.assertLessEqual(values.max(),9.)
        for key,replacement in [('triangle_thickness_mm',[.035,.070]),('triangle_layer',[0,31])]:
            split=copy.deepcopy(mesh);split[key]=replacement
            _,_,values=gradient_surface(split,result,'density',[0,1])
            np.testing.assert_allclose(values,[1,1,1,9,9,9])

    def test_coincident_disconnected_nodes_do_not_share_colors(self):
        mesh={'points_mm':[[0,0,0],[1,0,0],[0,1,0]]*2,
              'triangles':[[0,1,2],[3,4,5]],'triangle_layer':[0,0],
              'triangle_thickness_mm':[.035,.035]}
        _,_,values=gradient_surface(mesh,{'cell_J_A_mm2':[[1,0],[9,0]]},'density',[0,1])
        np.testing.assert_allclose(values,[1,1,1,9,9,9])

    def test_holes_and_unavailable_triangles_are_never_filled(self):
        # Ring topology around a square hole, without a triangulator inferring
        # any triangles between the inner vertices.
        mesh={'points_mm':[[0,0,0],[3,0,0],[3,3,0],[0,3,0],
                           [1,1,0],[2,1,0],[2,2,0],[1,2,0]],
              'triangles':[[0,1,5],[0,5,4],[1,2,6],[1,6,5],
                           [2,3,7],[2,7,6],[3,0,4],[3,4,7]],
              'triangle_layer':[0]*8,'triangle_thickness_mm':[.035]*8}
        result={'cell_J_A_mm2':[[1,0]]*8}
        result['cell_J_A_mm2'][0]=None
        xy,faces,values=gradient_surface(mesh,result,'density',range(8))
        np.testing.assert_array_equal(xy[faces],np.asarray(mesh['points_mm'])[np.asarray(mesh['triangles'][1:]),:2])
        self.assertTrue(np.isfinite(values).all())
        from matplotlib.path import Path as MplPath
        self.assertFalse(any(MplPath(xy[face]).contains_point((1.5,1.5)) for face in faces))
        result={'potential_V':[None,1,1,1,1,1,1,1],'source_voltage_V':1.,'sink_current_A':1.}
        xy,faces,_=gradient_surface(mesh,result,'drop',range(8))
        self.assertEqual(len(faces),5)  # Three triangles touch the unknown node.
        np.testing.assert_array_equal(xy[faces],np.asarray(mesh['points_mm'])[np.asarray(mesh['triangles'])[[2,3,4,5,7]],:2])

    def test_smooth_zoom_raw_option_and_extrema_do_not_change_probes(self):
        b=bundle();before=copy.deepcopy(b)
        b['result']['cell_J_A_mm2'][5]=[10000.,0.]
        original=copy.deepcopy(b)
        figure=Figure();canvas=FigureCanvasAgg(figure)
        axes=draw_view(figure,b,metric='density')
        image=next(item for item in axes.collections if isinstance(item,TriMesh))
        self.assertEqual(image.get_clim(),result_scale(b,'density',0))
        self.assertEqual(image.get_clim()[1],10000.)
        axes.set_xlim(3,4);axes.set_ylim(.75,.25);canvas.draw()
        self.assertEqual(axes.get_xlim(),(3.,4.))
        axes=draw_view(figure,b,metric='density',field_style='cells')
        raw=next(item for item in axes.collections if isinstance(item,PolyCollection))
        np.testing.assert_allclose(raw.get_array(),cell_values(b['mesh'],b['result'],'density'))
        self.assertEqual(probe_result(b,0,5,.5,'drop')['value'],probe_result(before,0,5,.5,'drop')['value'])
        self.assertEqual(b,original)

    def test_export_retains_style_and_describes_cell_interpolation(self):
        b=bundle();b['view_settings']={'field_style':'smooth','scale_mode':1}
        with tempfile.TemporaryDirectory() as directory:
            paths=write_report(Path(directory)/'gradient.html',b)
            html=Path(paths['html']).read_text(encoding='utf-8')
            self.assertIn('Linear nodal field',html)
            self.assertIn('Cell values interpolated for display',html)
            self.assertEqual(json.loads(Path(paths['json']).read_text())['view_settings'],b['view_settings'])
        b['view_settings']['field_style']='cells'
        axes=draw_view(Figure(),b,metric='drop')
        self.assertFalse(any(isinstance(item,TriMesh) for item in axes.collections))


if __name__=='__main__':unittest.main()
