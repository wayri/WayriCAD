import unittest
from unittest.mock import patch
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from quick_emerge_plugin import plots


class PlotTests(unittest.TestCase):
    def setUp(self):
        self.figure = Figure()
        FigureCanvasAgg(self.figure)
        self.result = {'config': {}, 'field': {'x_mm': [0, 1, 2], 'y_mm': [0, 1, 2],
            'z_mm': 2, 'frequency_hz': 1e9,
            'norm_e_v_m': [[0, None, 3], [1, 2, 4], [2, 3, 5]]}}

    def test_log_mask_and_manual_limits(self):
        plots.near_field(self.figure, self.result, {'scale': 'log', 'minimum': .5, 'maximum': 10})
        image = self.figure.axes[0].collections[0]
        self.assertEqual(image.get_clim(), (.5, 10))
        self.assertEqual(np.ma.getmaskarray(image.get_array()).sum(), 2)
        self.figure.canvas.draw()
        plots.near_field3d(self.figure, self.result, {'scale': 'log', 'minimum': .5, 'maximum': 10})
        self.assertEqual(self.figure.axes[1].collections[1].get_clim(), (.5, 10))
        self.figure.canvas.draw()

    def test_no_plottable_data(self):
        self.result['field']['norm_e_v_m'] = [[0, None, 0]] * 3
        for renderer in (plots.near_field, plots.near_field3d):
            renderer(self.figure, self.result, {'scale': 'log'})
            self.assertTrue(any('No plottable' in t.get_text() for t in self.figure.axes[0].texts))
            self.figure.canvas.draw()

    def test_geometry_visibility_and_mesh(self):
        plots.geometry(self.figure, {}, {'show_context': False, 'copper': False, 'ports': False})
        ax = self.figure.axes[0]
        self.assertEqual(len(ax.collections), 0)
        self.assertEqual(len(ax.lines), 0)
        plots.near_field3d(self.figure, self.result, {'show_context': False, 'copper': False,
                           'ports': False, 'field': False, 'mesh': True})
        self.assertEqual(len(self.figure.axes), 1)
        self.assertTrue(any('sample grid' in t.get_text() for t in self.figure.axes[0].texts))
        self.figure.canvas.draw()

    def test_dense_grid_retains_original_cells_and_unknown_holes(self):
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        values = np.ones((81, 81)).tolist()
        self.result['field'].update(x_mm=list(range(81)), y_mm=list(range(81)), norm_e_v_m=values)
        captured = []
        original = Poly3DCollection.__init__
        def capture(obj, verts, *args, **kwargs):
            captured.append(len(verts))
            original(obj, verts, *args, **kwargs)
        with patch.object(Poly3DCollection, '__init__', capture):
            plots.near_field3d(self.figure, self.result, {'show_context': False, 'copper': False})
        all_faces = captured[-1]
        self.assertEqual(all_faces,80*80)
        values[1][1] = None
        captured.clear()
        with patch.object(Poly3DCollection, '__init__', capture):
            plots.near_field3d(self.figure, self.result, {'show_context': False, 'copper': False})
        self.assertEqual(captured[-1],all_faces-4)

    def test_network_keeps_all_actual_samples_and_reports_spacing(self):
        import copy
        f=np.linspace(2.4e9,2.6e9,81)
        result={'schema':1,'config':{'z0_ohm':50},'port_count':1,'frequencies_hz':f.tolist(),
                's_parameters':{'S11':[[.2+.001*i,.01] for i in range(81)]}}
        before=copy.deepcopy(result)
        for quantity in ('Magnitude','Phase','Group delay','Impedance','Diagnostics'):
            plots.response(self.figure,result,{'network_quantity':quantity})
            axes=self.figure.axes[0]
            self.assertIn('81 stored frequency samples',axes.get_title(loc='left'))
            self.assertIn('2.5 MHz',axes.get_title(loc='left'))
            for line in axes.lines:
                if line.get_label()=='_child2':continue
                if line.get_label().startswith(('S','Port','Largest','Reciprocity')):
                    self.assertEqual(len(line.get_xdata()),81)
        self.assertEqual(result,before)

    def test_plane_quantity_units_actual_grid_and_thermal_context(self):
        self.result['field'].update(display_quantity='H magnitude',display_unit='A/m',
            display_values=[[1,2,3],[4,5,6],[7,8,9]])
        plots.near_field(self.figure,self.result)
        self.assertEqual(self.figure.axes[1].get_ylabel(),'H magnitude [A/m]')
        self.assertIn('3×3 original samples',self.figure.axes[0].get_title())
        self.result['thermal']={'x_mm':[0,1],'y_mm':[0,2],'z_mm':0,
            'temperature_k':[[300,301],[302,303]],'time_s':2}
        plots.near_field(self.figure,self.result)
        self.assertEqual(self.figure.axes[1].get_ylabel(),'Temperature [K]')
        self.assertIn('2 s',self.figure.axes[0].get_title())
        self.assertNotIn('GHz',self.figure.axes[0].get_title())
        self.figure.canvas.draw()

    def test_dense_radiation_does_not_use_matplotlib_default_decimation(self):
        theta=np.linspace(0,np.pi,91);phi=np.linspace(-np.pi,np.pi,181)
        result={'radiation':{'theta_rad':theta.tolist(),'phi_rad':phi.tolist(),
            'norm_e':np.ones((91,181)).tolist(),'frequency_hz':2.5e9}}
        from mpl_toolkits.mplot3d.axes3d import Axes3D
        captured={}
        def capture(ax,x,y,z,**kwargs):captured.update(shape=x.shape,**kwargs)
        with patch.object(Axes3D,'plot_surface',capture):plots.radiation(self.figure,result)
        self.assertEqual(captured['shape'],(91,181))
        self.assertEqual((captured['rcount'],captured['ccount']),(91,181))
        self.assertIn('91×181 stored angular samples',self.figure.axes[0].get_title())

    def test_radiation_axis_order_and_color_by_amplitude(self):
        result = {'radiation': {'theta_rad': [0, np.pi/2], 'phi_rad': [0, np.pi/2, np.pi],
                  'norm_e': [[1, 1, 1], [1, .5, .25]], 'frequency_hz': 1e9}}
        from mpl_toolkits.mplot3d.axes3d import Axes3D
        original = Axes3D.plot_surface
        captured = {}
        def capture(ax, x, y, z, **kwargs):
            captured.update(x=x, y=y, z=z, colors=kwargs['facecolors'])
            return original(ax, x, y, z, **kwargs)
        with patch.object(Axes3D, 'plot_surface', capture):
            plots.radiation(self.figure, result)
        self.assertEqual(captured['x'].shape, (2, 3))
        self.assertAlmostEqual(captured['y'][1, 1], .5)
        self.assertAlmostEqual(captured['x'][1, 2], -.25)
        self.assertAlmostEqual(captured['z'][0, 2], 1)
        self.assertFalse(np.allclose(captured['colors'][1, 0], captured['colors'][1, 1]))
        self.assertIn('normalized', self.figure.axes[1].get_ylabel())
        self.figure.canvas.draw()


if __name__ == '__main__': unittest.main()
