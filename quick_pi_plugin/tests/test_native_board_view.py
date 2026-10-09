"""Native viewport fit and coordinate contracts, independent of wx layout."""
import copy
import unittest

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import TriMesh
from matplotlib.figure import Figure

from quick_pi_plugin.report import draw_view, probe_result, result_scale
from quick_pi_plugin.tests.test_report import bundle


class NativeBoardViewTests(unittest.TestCase):
    def make_view(self, size=(8, 4), **kwargs):
        figure=Figure(figsize=size,dpi=100);canvas=FigureCanvasAgg(figure)
        data=bundle();axes=draw_view(figure,data,board_view=True,**kwargs)
        canvas.draw()
        return data,figure,canvas,axes

    def assert_physical_aspect(self, axes):
        origin,x,y=axes.transData.transform([[0,0],[1,0],[0,1]])
        self.assertAlmostEqual(np.linalg.norm(x-origin),np.linalg.norm(y-origin),places=8)
        self.assertLess(y[1],origin[1])  # KiCad Y increases down the screen.

    def test_native_view_fills_canvas_and_has_no_chart_chrome(self):
        _,figure,_,axes=self.make_view()
        self.assertEqual(len(figure.axes),1)  # Color legend belongs in inspector.
        self.assertFalse(axes.axison)
        self.assertEqual(axes.get_xlabel(),'');self.assertEqual(axes.get_ylabel(),'')
        self.assertEqual(axes.get_title(loc='left'),'')
        self.assertGreater(axes.bbox.width/figure.bbox.width,.97)
        self.assertGreater(axes.bbox.height/figure.bbox.height,.97)
        self.assert_physical_aspect(axes)
        copper=axes.transData.transform([[0,0],[10,1]])
        self.assertGreater(abs(copper[1,0]-copper[0,0])/axes.bbox.width,.93)
        self.assertLess(axes.get_xlim()[0],0);self.assertGreater(axes.get_xlim()[1],10)
        self.assertLess(axes.get_ylim()[1],0);self.assertGreater(axes.get_ylim()[0],1)
        self.assertTrue(axes._wayricad_scale_bar[1].get_text().endswith(' mm'))

    def test_resize_and_fit_preserve_all_geometry_and_equal_mm_scale(self):
        _,figure,canvas,axes=self.make_view()
        for size in [(3,8),(12,2),(6,6)]:
            figure.set_size_inches(*size);canvas.draw()
            self.assert_physical_aspect(axes)
            self.assertLess(axes.get_xlim()[0],0);self.assertGreater(axes.get_xlim()[1],10)
            self.assertLess(axes.get_ylim()[1],0);self.assertGreater(axes.get_ylim()[0],1)
            self.assertAlmostEqual(sum(axes.get_xlim())/2,5.)
            self.assertAlmostEqual(sum(axes.get_ylim())/2,.5)
            np.testing.assert_allclose((axes.get_xlim(),axes.get_ylim()),axes._wayricad_home,atol=1e-12)
        axes.set_xlim(3,7);axes.set_ylim(1,-1);canvas.draw()
        axes._wayricad_fit();canvas.draw()
        np.testing.assert_allclose((axes.get_xlim(),axes.get_ylim()),axes._wayricad_home,atol=1e-12)

    def test_resizing_keeps_panned_center_and_zoom_relative_to_fit(self):
        _,figure,canvas,axes=self.make_view()
        xlim,ylim=axes._wayricad_home
        axes.set_xlim(*[6+(x-5)*.5 for x in xlim])
        axes.set_ylim(*[1+(y-.5)*.5 for y in ylim]);canvas.draw()
        figure.set_size_inches(3,8);canvas.draw()
        self.assertAlmostEqual(sum(axes.get_xlim())/2,6.)
        self.assertAlmostEqual(sum(axes.get_ylim())/2,1.)
        for current,home in zip((axes.get_xlim(),axes.get_ylim()),axes._wayricad_home):
            self.assertAlmostEqual((current[1]-current[0])/(home[1]-home[0]),.5)
        self.assert_physical_aspect(axes)

    def test_native_colors_and_probes_keep_exact_solver_coordinates(self):
        data=bundle();before=copy.deepcopy(data)
        figure=Figure(figsize=(8,4));canvas=FigureCanvasAgg(figure)
        axes=draw_view(figure,data,metric='density',color_limits=(0,100),board_view=True)
        canvas.draw();image=next(item for item in axes.collections if isinstance(item,TriMesh))
        self.assertEqual(image.get_clim(),(0,100))
        self.assertEqual(axes._wayricad_color_scale['limits'],(0,100))
        self.assertEqual(axes._wayricad_color_scale['unit'],'A/mm²')
        self.assertIs(axes._wayricad_color_mappable,image)
        for point in [(5,.5),(1,.25),(9,.75)]:
            coordinate=axes.transData.inverted().transform(axes.transData.transform(point))
            np.testing.assert_allclose(coordinate,point,atol=1e-12)
            self.assertEqual(probe_result(data,0,*coordinate)['id'],probe_result(data,0,*point)['id'])
        self.assertEqual(data,before)
        figure.clear();axes=draw_view(figure,data,board_view=True,show_overlay=False)
        self.assertIsNone(axes._wayricad_color_scale)

    def test_empty_native_view_and_export_default_keep_distinct_presentations(self):
        figure=Figure();canvas=FigureCanvasAgg(figure)
        axes=draw_view(figure,{},board_view=True);canvas.draw()
        self.assertFalse(axes.axison);self.assertEqual(len(figure.axes),1)
        self.assertTrue(axes.yaxis_inverted())
        axes=draw_view(figure,bundle());canvas.draw()
        self.assertTrue(axes.axison);self.assertEqual(len(figure.axes),2)
        self.assertEqual(axes.get_xlabel(),'X (mm)');self.assertEqual(axes.get_ylabel(),'Y (mm)')
        self.assertIn('F.Cu',axes.get_title(loc='left'))
        self.assertEqual(axes._wayricad_color_scale['limits'],result_scale(bundle(),'drop',0))

    def test_board_context_fits_before_net_selection(self):
        data={'board_scene':{'primitives':[{'kind':'polygon','role':'track','layer':0,
                                           'points':[[20,30],[30,30],[30,50],[20,50]],'holes':[]}]}}
        figure=Figure(figsize=(8,4));canvas=FigureCanvasAgg(figure)
        axes=draw_view(figure,data,board_view=True);canvas.draw()
        self.assert_physical_aspect(axes)
        self.assertLess(axes.get_xlim()[0],20);self.assertGreater(axes.get_xlim()[1],30)
        self.assertLess(axes.get_ylim()[1],30);self.assertGreater(axes.get_ylim()[0],50)

    def test_native_overlay_keeps_unavailable_triangle_gaps(self):
        data=bundle();data['result']['cell_J_A_mm2'][0]=None
        figure=Figure();canvas=FigureCanvasAgg(figure)
        axes=draw_view(figure,data,metric='density',board_view=True);canvas.draw()
        image=next(item for item in axes.collections if isinstance(item,TriMesh))
        expected=np.asarray(data['mesh']['points_mm'])[np.asarray(data['mesh']['triangles'][1:]),:2]
        xy=np.column_stack((image._triangulation.x,image._triangulation.y))
        np.testing.assert_array_equal(xy[image._triangulation.triangles],expected)
        center=np.asarray(data['mesh']['points_mm'])[data['mesh']['triangles'][0],:2].mean(axis=0)
        self.assertIsNone(probe_result(data,0,*center,'density')['value'])

    def test_saved_context_stays_above_full_plane_without_obscuring_field(self):
        scene={'layers':{0:'F.Cu',31:'B.Cu',37:'F.SilkS',36:'B.SilkS',49:'F.Fab',48:'B.Fab',50:'F.CrtYd',51:'B.CrtYd'},
               'primitives':[{'kind':'polygon','role':'outline','layer':44,'uuid':'edge',
                              'points':[[0,0],[10,0],[10,1],[0,1]]}]}
        for copper,side,graphics in [(0,'front',(37,49,50)),(31,'back',(36,48,51))]:
            scene['primitives'].append({'kind':'text','role':'reference','layer':copper,
                                        'uuid':side+'-ref','text':side+'-R1','center':[5,.5]})
            scene['primitives'].append({'kind':'polygon','role':'drill','layer':copper,
                                        'uuid':side+'-hole','points':[[4,.3],[4.2,.3],[4.2,.5],[4,.5]]})
            for index,graphic in enumerate(graphics):
                scene['primitives'].append({'kind':'polygon','role':'footprint','layer':graphic,
                                            'uuid':side+str(index),'points':[[2,.2],[3,.2],[3,.8],[2,.8]]})
        for copper,side in [(0,'front'),(31,'back')]:
            with self.subTest(side=side):
                data=bundle();data['board_scene']=scene
                data['geometry']['layers'][0].update(id=copper,name='F.Cu' if copper==0 else 'B.Cu')
                data['mesh']['triangle_layer']=[copper]*len(data['mesh']['triangles'])
                figure=Figure();canvas=FigureCanvasAgg(figure)
                axes=draw_view(figure,data,layer=copper,board_view=True);canvas.draw()
                field=next(item for item in axes.collections if isinstance(item,TriMesh))
                contours=[item for item in axes.patches if str(item.get_gid()).startswith('board-context:')]
                self.assertEqual(len(contours),5)  # Board, drill, silk, fab, courtyard.
                self.assertTrue(all(item.get_zorder()>field.get_zorder() for item in contours))
                self.assertTrue(all(item.get_facecolor()[3]==0 for item in contours))
                labels=[item for item in axes.texts if str(item.get_gid()).startswith('board-context:')]
                self.assertEqual([item.get_text() for item in labels],[side+'-R1'])
                self.assertEqual(probe_result(data,copper,5,.5)['kind'],'sheet')
                axes=draw_view(figure,data,layer=copper,board_view=True,show_context=False)
                self.assertFalse(any(str(item.get_gid()).startswith('board-context:') for item in axes.patches))
                axes=draw_view(figure,data,layer=copper)
                self.assertFalse(any(str(item.get_gid()).startswith('board-context:') for item in axes.patches))

    def test_kicad_10_layer_names_and_back_copper_id_show_matching_contours(self):
        scene={'layers':{0:'F.Cu',2:'B.Cu',7:'F.Silkscreen',9:'B.Silkscreen',
                         11:'F.Fab',13:'B.Fab',15:'F.Courtyard',17:'B.Courtyard'},'primitives':[]}
        for side,graphics in [('front',(7,11,15)),('back',(9,13,17))]:
            for index,layer in enumerate(graphics):
                scene['primitives'].append({'kind':'polygon','role':'footprint','layer':layer,
                                            'uuid':side+str(index),'points':[[2,.2],[3,.2],[3,.8],[2,.8]]})
        for copper,side in [(0,'front'),(2,'back')]:
            with self.subTest(side=side):
                data=bundle();data['board_scene']=scene
                data['geometry']['layers'][0].update(id=copper,name='F.Cu' if copper==0 else 'B.Cu')
                data['mesh']['triangle_layer']=[copper]*len(data['mesh']['triangles'])
                figure=Figure();canvas=FigureCanvasAgg(figure)
                axes=draw_view(figure,data,layer=copper,board_view=True);canvas.draw()
                identities=[item.get_gid() for item in axes.patches if str(item.get_gid()).startswith('board-context:')]
                self.assertEqual(identities,['board-context:footprint:'+side+str(i) for i in range(3)])


if __name__=='__main__':unittest.main()
