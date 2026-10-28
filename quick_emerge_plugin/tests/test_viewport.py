import copy
import sys
import unittest
from types import SimpleNamespace

try:
    if sys.platform != 'win32':
        raise ImportError('native viewport tests require Windows')
    import wx
    import numpy as np
    from mpl_toolkits.mplot3d import proj3d
    from matplotlib.backend_bases import MouseEvent
    from quick_emerge_plugin import plots
    from quick_emerge_plugin.viewport import PlotViewport, closest_projected
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'Windows wx display unavailable')
class ViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.app = wx.App.Get() or wx.App(False)
        except Exception as exc:
            raise unittest.SkipTest(f'wx display unavailable: {exc}')

    def setUp(self):
        self.frame = wx.Frame(None, size=(800, 600))
        self.events = []
        self.view = PlotViewport(self.frame, '3D fields', lambda *args: self.events.append(args))
        self.frame.Show()
        self.result = {'config': {}, 'field': {'x_mm': [0, 1, 2], 'y_mm': [0, 1, 2],
                       'z_mm': 2, 'frequency_hz': 1e9,
                       'norm_e_v_m': [[1, 2, 3], [2, 3, 4], [3, 4, 5]]}}
        self.original = copy.deepcopy(self.result)
        self.view.render(plots.near_field3d, self.result, reset=True,
                         options={'minimum': 1, 'maximum': 6})
        self.view.canvas.draw()

    def tearDown(self):
        self.frame.Destroy()
        wx.Yield()

    def test_camera_zoom_redraw_fit_and_markers(self):
        row = {'kind': 'field', 'x_mm': 1, 'y_mm': 1, 'z_mm': 2}
        self.view.set_selection(row, pins=[row])
        home = self.view.home
        self.view.set_camera(preset='Top', projection='persp')
        self.view.zoom(.5)
        bounds = self.view._bounds()
        self.view.render(options={'copper': False, 'minimum': 1, 'maximum': 6})
        self.assertEqual(self.view._bounds(), bounds)
        self.assertEqual((self.view.axes().elev, self.view.axes().azim), (90, -90))
        self.assertEqual(self.view.camera.projection, 'persp')
        self.assertEqual(self.view.selection, row)
        self.assertEqual(self.view.markers, [row])
        self.assertEqual(sum(a.get_gid() == 'inspection-marker' for a in self.view.axes().collections), 2)
        self.view.fit()
        self.assertEqual(self.view._bounds(), home)
        self.assertEqual(self.result, self.original)
        self.view.render(plots.near_field, self.result, reset=True, options={'minimum': 1, 'maximum': 6})
        self.assertEqual(self.view.axes().collections[0].get_clim(), (1, 6))
        self.view.render(plots.near_field3d, self.result, reset=True)
        self.assertEqual(self.view.figure.axes[1].collections[1].get_clim(), (1, 6))

    def test_projected_pick_and_drag(self):
        ax = self.view.axes()
        points = [(0, 0, 2), (2, 2, 2)]
        x, y, _ = proj3d.proj_transform(*points[0], ax.get_proj())
        px, py = ax.transData.transform((x, y))
        self.assertEqual(closest_projected(points, ax, px, py), 0)
        self.assertIsNone(closest_projected(points, ax, -10000, -10000))
        self.view.set_samples([{'x_mm': x, 'y_mm': y, 'z_mm': z} for x, y, z in points])
        self.view.set_mode('Probe')
        self.view._press(SimpleNamespace(x=px, y=py, button=1))
        self.view._release(SimpleNamespace(x=px+20, y=py, button=1, inaxes=ax))
        self.assertEqual(self.events, [])
        self.view._press(SimpleNamespace(x=px, y=py, button=1))
        self.view._release(SimpleNamespace(x=px, y=py, button=1, inaxes=ax))
        self.assertEqual(len(self.events), 1)
        self.assertTrue(self.events[0][-1])

    def dispatch(self, name, x, y, button=1):
        event = MouseEvent(name, self.view.canvas, x, y, button=button)
        self.view.canvas.callbacks.process(name, event)
        return event

    def drag(self, mode, dx, dy):
        self.view.set_mode(mode)
        self.view.canvas.draw()
        box = self.view.axes().bbox
        x, y = (box.x0 + box.x1)/2, (box.y0 + box.y1)/2
        self.dispatch('button_press_event', x, y)
        self.dispatch('motion_notify_event', x + dx, y + dy)
        self.dispatch('button_release_event', x + dx, y + dy)

    def test_real_mouse_navigation_and_probe(self):
        initial = self.view._bounds()
        angles = (self.view.axes().elev, self.view.axes().azim)
        self.drag('Orbit', 35, 20)
        self.assertNotEqual((self.view.axes().elev, self.view.axes().azim), angles)
        self.assertEqual(self.view._bounds(), initial)
        self.assertEqual(self.events, [])
        self.drag('Pan', 30, 20)
        panned = self.view._bounds()
        self.assertNotEqual(panned, initial)
        for before, after in zip(initial, panned):
            self.assertAlmostEqual(before[1]-before[0], after[1]-after[0])
        self.assertEqual(self.events, [])
        self.drag('Zoom', 0, 40)
        zoomed = self.view._bounds()
        self.assertNotAlmostEqual(zoomed[0][1]-zoomed[0][0], panned[0][1]-panned[0][0])
        self.assertEqual(self.events, [])
        self.view.set_mode('Probe')
        point = (1, 1, 2)
        self.view.set_samples([{'x_mm': point[0], 'y_mm': point[1], 'z_mm': point[2]}])
        self.view.canvas.draw()
        ax = self.view.axes()
        projected = proj3d.proj_transform(*point, ax.get_proj())
        x, y = ax.transData.transform(projected[:2])
        camera = (ax.elev, ax.azim, ax.roll)
        self.dispatch('button_press_event', x, y)
        self.dispatch('button_release_event', x, y)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][2]['x_mm'], 1)
        self.assertEqual((ax.elev, ax.azim, ax.roll), camera)
        self.events.clear()
        self.drag('Probe', 20, 20)
        self.assertEqual(self.events, [])

    def test_2d_probe_and_roll_fit(self):
        self.view.axes().view_init(elev=30, azim=40, roll=17)
        self.view.render()
        self.assertAlmostEqual(self.view.axes().roll, 17)
        home = self.view.home
        self.view.zoom(.85)
        self.view.zoom(1/.85)
        for expected, actual in zip(home, self.view._bounds()):
            np.testing.assert_allclose(expected, actual)
        self.view.zoom(.85)
        self.view.fit()
        self.assertEqual(self.view._bounds(), home)
        self.view.name = 'Field probes'
        self.view.render(plots.near_field, self.result, reset=True)
        self.view.set_mode('Probe')
        self.view.canvas.draw()
        x, y = self.view.axes().transData.transform((1, 1))
        self.dispatch('button_press_event', x, y)
        self.dispatch('button_release_event', x, y)
        self.assertEqual(len(self.events), 1)
        self.assertAlmostEqual(self.events[0][1].xdata, 1, places=1)
        self.assertAlmostEqual(self.events[0][1].ydata, 1, places=1)


if __name__ == '__main__': unittest.main()
