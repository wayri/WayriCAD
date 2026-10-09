"""Supported display gradients and explicit partial/physical field identity."""
import copy
import unittest

import numpy as np
from matplotlib import colormaps
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from quick_therm_plugin.thermal_plot import default_thermal_mode, draw_thermal_view, field_available


def field(xs=(1.,9.),ys=(1.,9.)):
    return {'x_centers_mm':list(xs),'y_centers_mm':list(ys),
            'values_c':[[20.+2*x+3*y for x in xs] for y in ys]}


def view():
    return {'bbox_mm':[0,0,10,10],'components':[{'id':'fixture','reference':'U1','side':'top','solved':False}],
            'outline':[{'outer_mm':[[0,0],[10,0],[10,10],[0,10]],'holes_mm':[]}]}


def pixel(canvas,axes,x,y):
    xp,yp=axes.transData.transform((x,y))
    rgba=np.asarray(canvas.buffer_rgba())
    return rgba[rgba.shape[0]-1-round(yp),round(xp),:3].astype(float)


class ThermalGradientTests(unittest.TestCase):
    def test_default_prefers_physical_field_and_matching_side(self):
        samples=field();board={**view(),'fields_by_side':{'top':samples,'bottom':samples}}
        network={'board_field':samples,'layers':[dict(samples,name='F.Cu'),dict(samples,name='B.Cu')]}
        self.assertEqual(default_thermal_mode(board,network),'Layer model: F.Cu')
        self.assertEqual(default_thermal_mode(board,network,'bottom'),'Layer model: B.Cu')
        network.pop('layers')
        self.assertEqual(default_thermal_mode(board,network),'Top board model')
        self.assertEqual(default_thermal_mode(board),'Top-side contour')
        board['fields_by_side']['bottom']={'status':'unavailable'}
        self.assertEqual(default_thermal_mode(board,side='bottom'),'Bottom-side map')

    def test_isolated_point_samples_are_not_a_continuous_field(self):
        samples=field();samples['values_c'][0][0]=None
        self.assertFalse(field_available(samples))
        self.assertEqual(default_thermal_mode(view(),{'board_field':samples}),'Top-side map')

    def test_partial_hull_stays_visible_and_no_extrapolation_after_zoom(self):
        samples=field((2.,4.),(2.,4.));hull=[[2,2],[4,2],[4,4],[2,4]]
        samples['support_hull_mm']=hull
        board={**view(),'fields_by_side':{'top':samples}};original=copy.deepcopy(board)
        figure=Figure(figsize=(7,5),dpi=100);canvas=FigureCanvasAgg(figure)
        axes=draw_thermal_view(figure,board,'Top-side contour');canvas.draw()
        boundary=next(p for p in axes.patches if p.get_gid()=='quicktherm-junction-support-hull')
        np.testing.assert_array_equal(boundary.get_xy()[:-1],hull)
        self.assertEqual(boundary.get_linestyle(),'--')
        self.assertIn('partial same-side junction interpolation',axes.get_title())
        self.assertTrue(any('Blank regions are unknown' in t.get_text() and 'Whole-board study' in t.get_text()
                            for t in axes.texts))
        np.testing.assert_array_equal(pixel(canvas,axes,8,8),[255,255,255])
        axes.set_xlim(1,5);axes.set_ylim(5,1);canvas.draw()
        np.testing.assert_array_equal(pixel(canvas,axes,4.6,4.6),[255,255,255])
        self.assertEqual(board,original)

    def test_known_linear_field_colors_are_continuous_when_zoomed(self):
        samples=field();original=copy.deepcopy(samples)
        figure=Figure(figsize=(7,5),dpi=100);canvas=FigureCanvasAgg(figure)
        axes=draw_thermal_view(figure,view(),'Top board model',network={'board_field':samples})
        canvas.draw()
        colors=colormaps['inferno'](np.array([0.,.4,1.]))[:,:3]
        expected=(np.array([.375,.375,.25])@colors)*255
        np.testing.assert_allclose(pixel(canvas,axes,6,3),expected,atol=3)
        axes.set_xlim(4,8);axes.set_ylim(5,1);canvas.draw()
        np.testing.assert_allclose(pixel(canvas,axes,6,3),expected,atol=3)
        colors_at_zoom=np.array([pixel(canvas,axes,x,3) for x in np.linspace(4.1,7.9,100)])
        self.assertGreater(len(np.unique(colors_at_zoom,axis=0)),50)
        self.assertLess(np.abs(np.diff(colors_at_zoom,axis=0)).max(),5)
        self.assertEqual(samples,original)

    def test_physical_cell_edges_and_both_render_layers_preserve_drill_void(self):
        samples=field((2.5,7.5),(2.5,7.5))
        samples.update(value_location='finite_volume_cell',x_edges_mm=[0,5,10],y_edges_mm=[0,5,10])
        board=view();board['drills']=[{'contour_mm':[[4.8,4.8],[5.2,4.8],[5.2,5.2],[4.8,5.2]]}]
        figure=Figure(figsize=(7,5),dpi=100);canvas=FigureCanvasAgg(figure)
        axes=draw_thermal_view(figure,board,'Top board model',network={'board_field':samples},
                               temperature_limits_c=(20.,70.));canvas.draw()
        self.assertEqual(tuple(figure.axes[1].get_ylim()),(20.,70.))
        self.assertFalse(np.array_equal(pixel(canvas,axes,.5,.5),[255,255,255]))
        np.testing.assert_array_equal(pixel(canvas,axes,5,5),[255,255,255])
        axes.set_xlim(4,6);axes.set_ylim(6,4);canvas.draw()
        np.testing.assert_array_equal(pixel(canvas,axes,5,5),[255,255,255])


if __name__=='__main__':unittest.main()
