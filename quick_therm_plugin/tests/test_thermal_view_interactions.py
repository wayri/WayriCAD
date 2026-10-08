"""View interactions preserve geometry and sample actual stored field frames."""
import unittest
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from mpl_toolkits.mplot3d import proj3d
from quick_therm_plugin.thermal_review import board_point_from_3d, transient_frame_network


class ViewInteractionsTests(unittest.TestCase):
    def test_screen_ray_recovers_board_position_across_camera_angles(self):
        figure=Figure();FigureCanvasAgg(figure);axes=figure.add_subplot(111,projection='3d')
        axes.set_xlim(0,20);axes.set_ylim(0,30);axes.set_zlim(-1,4)
        for elev,azim in [(25,-60),(60,20),(10,150)]:
            with self.subTest(elev=elev,azim=azim):
                axes.view_init(elev=elev,azim=azim);figure.canvas.draw()
                px,py,_=proj3d.proj_transform(7.,12.,1.6,axes.get_proj())
                sx,sy=axes.transData.transform((px,py))
                point=board_point_from_3d(axes,sx,sy,1.6)
                self.assertAlmostEqual(point[0],7.,places=8)
                self.assertAlmostEqual(point[1],12.,places=8)

    def test_frame_rebuild_uses_sparse_cell_order_and_does_not_mutate(self):
        network={'layers':[{'name':'F.Cu','values_c':[[90,None]]},{'name':'B.Cu','values_c':[[80,None]]}],
                 'transient':{'frames':[{'time_s':2,'temperatures_c':[31,42]}],
                              'spatial_index':{'cells':[[0,0]],'active_cells_per_layer':1,
                                               'x_centers_mm':[1,2],'y_centers_mm':[3]}}}
        frame=transient_frame_network(network,0)
        self.assertEqual(frame['layers'][0]['values_c'],[[31,None]])
        self.assertEqual(frame['layers'][1]['values_c'],[[42,None]])
        self.assertEqual(network['layers'][0]['values_c'],[[90,None]])
        self.assertEqual(frame['display_time_s'],2)

    def test_weighted_contact_scheduled_junction_and_missing_resistance(self):
        from quick_therm_plugin.thermal_review import frame_view, frame_limit_status
        network={'layers':[{'name':'F.Cu','values_c':[[80,90]]}],
                 'components':[{'reference':'U1','junction_c':99},{'reference':'U2','junction_c':88}],
                 'transient':{'frames':[{'time_s':5,'temperatures_c':[30,50]}],
                    'components':[{'reference':'U1','nodes':[[0,.25],[1,.75]],'power_w':2,'junction_resistance_k_per_w':4},
                                  {'reference':'U2','nodes':[[0,1]],'power_w':1,'junction_resistance_k_per_w':None}],
                    'power_schedules':{'U1':[[0,0],[10,1]]},
                    'spatial_index':{'cells':[[0,0],[1,0]],'active_cells_per_layer':2,'x_centers_mm':[1,2],'y_centers_mm':[3]}}}
        frame=transient_frame_network(network,0)
        self.assertNotIn('transient',frame)
        self.assertEqual(frame['components'][0]['board_site_c'],45)
        self.assertEqual(frame['components'][0]['junction_c'],49)
        self.assertEqual(frame['components'][0]['power_w'],1)
        self.assertIsNone(frame['components'][1]['junction_c'])
        view={'components':[{'reference':'U1','junction_c':99},{'reference':'U2','junction_c':88}]}
        display=frame_view(view,frame)
        self.assertEqual(display['components'][0]['junction_c'],49)
        self.assertIsNone(display['components'][1]['junction_c'])
        self.assertEqual(view['components'][0]['junction_c'],99)
        bounds={'minimum_c':20,'maximum_c':48,'status':'PASS'}
        self.assertEqual(frame_limit_status(bounds,49),'FAIL')
        self.assertEqual(frame_limit_status(bounds,47),'PASS')
        self.assertEqual(frame_limit_status(bounds,None),'UNKNOWN')
