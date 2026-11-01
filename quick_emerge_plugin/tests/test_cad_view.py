"""Geometry framing must not stretch copper or redefine a simulated region."""
import copy
import unittest
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from quick_emerge_plugin.cad_view import fit_2d, geometry_bounds, framing_bounds
from quick_emerge_plugin import plots, region_view


def rectangle(x0,y0,x1,y1):
    return {'outer_mm':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],'holes_mm':[]}


class CadViewTests(unittest.TestCase):
    def region(self):
        return dict(substrate={'outline':[rectangle(0,0,100,70)],'thickness_mm':1.53},
            area={'name':'Antenna region'}, copper=[
                dict(layer='B.Cu',net='GND',polygons=[rectangle(0,0,100,70)]),
                dict(layer='F.Cu',net='SIGNAL',polygons=[rectangle(50,24,90,46)])],
            ports=[dict(signal_net='SIGNAL',reference_net='GND',a_mm=[50,34],b_mm=[50,36],number=1)])

    def test_focus_uses_declared_signal_and_feed_not_the_larger_ground_plane(self):
        region=self.region(); original=copy.deepcopy(region)
        self.assertEqual(geometry_bounds(region),(50,90,24,46,-1.53,0))
        self.assertEqual(geometry_bounds(region,focus=False),(0,100,0,70,-1.53,0))
        self.assertEqual(region,original)
        region['ports']=[]
        self.assertEqual(geometry_bounds(region),(0,100,0,70,-1.53,0))

    def test_fit_contains_copper_and_equal_mm_scale_at_wide_and_tall_sizes(self):
        bounds=(50,90,24,46,-1.53,0)
        for width,height in ((1264,639),(700,900),(2500,700)):
            xlim,ylim=fit_2d(bounds,width,height)
            self.assertLess(xlim[0],50); self.assertGreater(xlim[1],90)
            self.assertLess(ylim[0],24); self.assertGreater(ylim[1],46)
            self.assertAlmostEqual(width/(xlim[1]-xlim[0]),height/(ylim[1]-ylim[0]))

    def test_template_focus_uses_radiator_instead_of_substrate(self):
        from quick_emerge_plugin.model import validate_config
        config=validate_config({'substrate_x_mm':100,'substrate_y_mm':100,
                                'patch_width_mm':28,'patch_length_mm':22})
        focused=geometry_bounds(config); whole=geometry_bounds(config,focus=False)
        self.assertEqual(focused[:2],(-14,14)); self.assertEqual(whole[:4],(-50,50,-50,50))

    def test_cad_option_removes_geometry_graph_without_changing_report_style(self):
        region=self.region(); original=copy.deepcopy(region)
        figure=Figure(); FigureCanvasAgg(figure)
        for renderer in (region_view.enclosure,region_view.geometry):
            renderer(figure,region,{'cad_view':True}); figure.canvas.draw()
            self.assertFalse(figure.axes[0].axison); self.assertEqual(figure.axes[0].get_title(),'')
            self.assertFalse(figure.texts)
            renderer(figure,region)
            self.assertTrue(figure.axes[0]._axis3don if getattr(figure.axes[0],'name','')=='3d' else figure.axes[0].axison)
            self.assertTrue(figure.axes[0].get_title())
        plots.plan_geometry(figure,{}, {'cad_view':True})
        self.assertFalse(figure.axes[0].axison); self.assertEqual(figure.axes[0].get_title(),'')
        self.assertEqual(region,original)

    def test_spatial_focus_is_bounded_by_original_samples(self):
        region=self.region()
        result=dict(region=region,field=dict(x_mm=[55,80],y_mm=[30,40],z_mm=2))
        self.assertEqual(framing_bounds('Field probes',result)[:4],(55,80,30,40))
        result['field'].update(x_mm=[110,120],y_mm=[80,90])
        self.assertEqual(framing_bounds('Field probes',result)[:4],(110,120,80,90))

    def test_cad_field_overlay_uses_actual_signal_contours_and_preserves_unknowns(self):
        import numpy as np
        result=dict(config={'mode':'pcb_region'},region=self.region(),
                    field=dict(x_mm=[50,90],y_mm=[24,46],z_mm=2,frequency_hz=1e9,
                               norm_e_v_m=[[None,2],[3,4]]))
        before=copy.deepcopy(result); figure=Figure(); FigureCanvasAgg(figure)
        plots.near_field(figure,result,{'cad_view':True})
        outlines=[line for line in figure.axes[0].lines if line.get_gid()=='cad-signal-outline']
        self.assertEqual(len(outlines),1)
        self.assertEqual(list(outlines[0].get_xdata()),[50,90,90,50,50])
        self.assertEqual(int(np.ma.getmaskarray(figure.axes[0].collections[0].get_array()).sum()),1)
        self.assertEqual(result,before)
        plots.near_field(figure,result)
        self.assertFalse(any(line.get_gid()=='cad-signal-outline' for line in figure.axes[0].lines))


if __name__=='__main__': unittest.main()
