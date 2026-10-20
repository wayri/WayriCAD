"""Rotated slot voids and barrel sidewalls in physical probes and report maps."""
import math
import unittest
import numpy as np
from quick_pi_plugin.barrel import drill_wall_distance,drill_contour
from quick_pi_plugin.report import probe_result,via_markers,draw_view


def slot(angle=0,center=(0.,0.)):
    return {'id':'slot','x_mm':center[0],'y_mm':center[1],'drill_mm':.8,
            'drill_size_mm':[2.4,.8],'drill_shape':'obround','drill_angle_deg':angle,
            'plating_mm':.025,'top_layer':0,'bottom_layer':31}


def rotate(point,angle,center=(0.,0.)):
    theta=math.radians(angle)
    return (center[0]+point[0]*math.cos(theta)+point[1]*math.sin(theta),
            center[1]-point[0]*math.sin(theta)+point[1]*math.cos(theta))


class SlotReportTests(unittest.TestCase):
    def test_rotated_capsule_probe_never_invents_copper_inside_void(self):
        for angle in (0,45,90):
            with self.subTest(angle=angle):
                barrel=slot(angle)
                bundle={'mesh':{'vias':[barrel],'points_mm':[],'triangles':[]},
                    'geometry':{'layers':[{'id':0,'z_mm':0},{'id':31,'z_mm':1.6}]},
                    'result':{'vias':[{'id':'slot','current_density_A_mm2':10.,
                        'current_A':1.,'power_W':.01,'thermal':{'energy_ratio':2}}]}}
                for point in ((0,0),(.4125,0),(1.1,0),(.8,.35)):
                    position=rotate(point,angle)
                    self.assertLess(drill_wall_distance(position,barrel),0)
                    self.assertIsNone(probe_result(bundle,0,*position))
                for point in ((.8,.4125),(-.8,-.4125),(1.2125,0),(-1.2125,0)):
                    position=rotate(point,angle)
                    self.assertAlmostEqual(drill_wall_distance(position,barrel),.0125,12)
                    row=probe_result(bundle,0,*position)
                    self.assertEqual((row['kind'],row['id'],row['value']),('via','slot',10.))
                self.assertIsNone(probe_result(bundle,0,*rotate((1.3,0),angle)))
                self.assertIsNone(probe_result(bundle,5,*rotate((.8,.4125),angle)))
                marker=via_markers(bundle['mesh'],bundle['result'],bundle['geometry'],0,'density')[0]
                self.assertEqual(marker['drill_size_mm'],[2.4,.8])
                self.assertEqual(marker['drill_angle_deg'],angle)

    def test_vertical_drill_and_contours_keep_native_orientation_and_void(self):
        barrel=slot(45);barrel['drill_size_mm']=[.8,2.4]
        self.assertAlmostEqual(drill_wall_distance(rotate((.4125,.8),45),barrel),.0125,12)
        for angle in (0,45,90):
            barrel=slot(angle)
            inner=drill_contour(barrel,circumscribed=True)
            outer=drill_contour(barrel,.025)
            # Whole void contour stays at/outside the true drill; outer
            # vertices belong to the true plated wall.
            for position in inner:self.assertGreaterEqual(drill_wall_distance(position,barrel),-1e-12)
            for position in outer:self.assertAlmostEqual(drill_wall_distance(position,barrel),.025,12)

    def test_slot_marker_and_context_drill_render_capsules_instead_of_circles(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.patches import Polygon
        from quick_pi_plugin.tests.test_report import bundle as strip_bundle
        for angle in (0,45,90):
            bundle=strip_bundle();barrel=slot(angle,(5.,.5))
            bundle['mesh']['vias']=[barrel]
            bundle['geometry']['layers'].append({'id':31,'name':'B.Cu','z_mm':1.6,'polygons':[]})
            bundle['geometry']['vias']=[dict(barrel,layers=[0,31],diameter_mm=1.6,polygons={})]
            bundle['result']['vias']=[{'id':'slot','current_density_A_mm2':1000.,'thermal':{'energy_ratio':2.}}]
            figure=Figure(figsize=(5,3));FigureCanvasAgg(figure)
            axes=draw_view(figure,bundle,'Results',0,'density');figure.canvas.draw()
            colored=next(p for p in axes.patches if p.get_gid()=='via-barrel:slot')
            hole=next(p for p in axes.patches if p.get_gid()=='via-drill:slot')
            self.assertIsInstance(colored,Polygon);self.assertIsInstance(hole,Polygon)
            for artist in (colored,hole):
                self.assertGreater(np.ptp(artist.get_xy(),axis=0).max(),1.8)
            self.assertEqual(tuple(hole.get_facecolor()),(1.,1.,1.,1.))


if __name__=='__main__':unittest.main()
