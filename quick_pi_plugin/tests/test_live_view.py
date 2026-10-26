"""Live-current artist reuse, scientific colour values and probe refresh."""
import unittest
import copy
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from quick_pi_plugin.tests.test_report import bundle
from quick_pi_plugin.live_current import LiveCurrentModel
from quick_pi_plugin.report import draw_view,update_current_view,METRICS


class LiveViewTests(unittest.TestCase):
    def test_updates_match_fresh_plots_without_rebuilding_or_moving_camera(self):
        base=bundle();base['request'].update(action='solve',sink_current=2,source_voltage=1)
        model=LiveCurrentModel(base)
        for style in ('cells','smooth'):
            for metric in METRICS:
                with self.subTest(style=style,metric=metric):
                    figure=Figure();FigureCanvasAgg(figure)
                    ax=draw_view(figure,base,'Results',0,metric,field_style=style,board_view=True)
                    ax.set_xlim(2,7);ax.set_ylim(1.1,-.1)
                    identities=[id(item) for item in ax.collections]
                    for current in (6.,.5,2.):
                        output=model.update(current)
                        unchanged=update_current_view(ax,output)
                        fresh=Figure();FigureCanvasAgg(fresh)
                        expected=draw_view(fresh,output,'Results',0,metric,field_style=style,board_view=True)
                        np.testing.assert_allclose(ax._wayricad_color_mappable.get_array(),expected._wayricad_color_mappable.get_array(),rtol=1e-9,atol=1e-10)
                        np.testing.assert_allclose(ax._wayricad_color_mappable.get_clim(),expected._wayricad_color_mappable.get_clim(),rtol=1e-9,atol=1e-10)
                        self.assertEqual(identities,[id(item) for item in ax.collections])
                        self.assertEqual(ax.get_xlim(),(2,7));self.assertEqual(ax.get_ylim(),(1.1,-.1))
                        # Pulse-limit and melting maps retain their capped
                        # 0..1 scale, so current changes can require recolouring.
                        if metric not in ('risk','melt'):self.assertTrue(unchanged)

    def test_manual_scale_recolors_and_keeps_limits(self):
        base=bundle();base['request'].update(action='solve',sink_current=2,source_voltage=1)
        figure=Figure();FigureCanvasAgg(figure)
        ax=draw_view(figure,base,'Results',0,'drop',color_limits=(0,10),board_view=True)
        self.assertFalse(update_current_view(ax,LiveCurrentModel(base).update(4),(0,10)))
        self.assertEqual(ax._wayricad_color_mappable.get_clim(),(0,10))

    def test_probe_rows_and_pinned_labels_refresh_together(self):
        from matplotlib.backend_bases import MouseEvent
        from wayricad_runtime.plot_probe import attach_probes
        figure=Figure();canvas=FigureCanvasAgg(figure);ax=figure.add_subplot();ax.set_xlim(0,1);ax.set_ylim(0,1)
        rows=[[.5,.5,1.,'Cell']];controller=attach_probes(canvas,ax,rows,'A');canvas.draw()
        x,y=ax.transData.transform((.5,.5))
        canvas.callbacks.process('button_press_event',MouseEvent('button_press_event',canvas,x,y,button=1))
        canvas.callbacks.process('button_release_event',MouseEvent('button_release_event',canvas,x,y,button=1))
        self.assertEqual(len(controller['probes']),1)
        rows[0][2]=3.;controller['refresh_values']()
        self.assertIn('3 A',controller['probes'][0].get_text())
        controller['disconnect']()

    def test_via_colors_update_in_batched_dense_board_geometry(self):
        for count in (1,250):
            with self.subTest(vias=count):
                base=bundle()
                base['mesh']['vias']=[{'id':'v','top_layer':0,'bottom_layer':0,'x_mm':5,'y_mm':.5,'drill_mm':.3,'plating_mm':.025}]
                base['result']['vias']=[{'id':'v','current_density_A_mm2':100,'thermal':{'energy_ratio':2}}]
                base['geometry']['vias']=[{'id':str(i),'x_mm':5,'y_mm':.5,'diameter_mm':.6,'drill_mm':.3,'layers':[0]} for i in range(count)]
                figure=Figure();FigureCanvasAgg(figure)
                ax=draw_view(figure,base,'Results',0,'density',color_limits=(0,500),board_view=True)
                output=copy.deepcopy(base);output['result']['sink_current_A']=6
                output['result']['cell_J_A_mm2']=(np.asarray(output['result']['cell_J_A_mm2'])*3).tolist()
                output['result']['vias'][0]['current_density_A_mm2']=300
                update_current_view(ax,output,(0,500))
                fresh=Figure();FigureCanvasAgg(fresh)
                expected=draw_view(fresh,output,'Results',0,'density',color_limits=(0,500),board_view=True)
                if count==250:
                    got=next(x for x in ax.collections if x.get_gid()=='pi-geometry-5')
                    want=next(x for x in expected.collections if x.get_gid()=='pi-geometry-5')
                    np.testing.assert_allclose(got.get_facecolors(),want.get_facecolors())
                    np.testing.assert_allclose(got.get_edgecolors(),want.get_edgecolors())
                else:
                    got=next(x for x in ax.patches if str(x.get_gid()).startswith('via-barrel:'))
                    want=next(x for x in expected.patches if str(x.get_gid()).startswith('via-barrel:'))
                    np.testing.assert_allclose(got.get_facecolor(),want.get_facecolor())


if __name__=='__main__':unittest.main()
