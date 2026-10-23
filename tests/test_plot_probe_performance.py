"""Exact cell picking and redraw-cost regressions for native plot probes."""
import math
import unittest
from unittest.mock import patch

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backend_bases import MouseEvent
from matplotlib.figure import Figure
from matplotlib.path import Path

from wayricad_runtime.plot_probe import _CellIndex, attach_probes


class CellIndexTests(unittest.TestCase):
    def test_matches_linear_containment_and_first_overlap(self):
        polygons = [[[0, 0], [2, 0], [0, 2]],
                    [[.2, .2], [.6, .2], [.2, .6]],
                    [[3, 0], [4, 0], [4, 1], [3, 1]]]
        index = _CellIndex(polygons)
        paths = [Path(poly) for poly in polygons]
        for ix in range(-2, 44):
            for iy in range(-2, 24):
                point = (ix/10, iy/10)
                expected = next((i for i, p in enumerate(paths) if p.contains_point(point)), None)
                self.assertEqual(index.pick(*point, len(paths)), expected, point)
        self.assertEqual(index.pick(.3, .3, 3), 0)
        self.assertIsNone(index.pick(math.nan, 0, 3))
        self.assertIsNone(index.pick(3.5, .5, 2))

    def test_many_cells_construct_paths_only_for_local_candidates(self):
        polygons = [[[x, y], [x+.8, y], [x, y+.8]]
                    for x in range(100) for y in range(100)]
        index = _CellIndex(polygons)
        self.assertEqual(index.paths, {})
        with patch.object(Path, 'contains_point', autospec=True, return_value=True) as contains:
            for _ in range(10):
                self.assertEqual(index.pick(50.1, 50.1, 10000), 5050)
            self.assertEqual(contains.call_count, 10)
        self.assertEqual(len(index.paths), 1)
        self.assertIsNone(index.pick(50.9, 50.9, 10000))

    def test_large_cell_and_degenerate_dimensions(self):
        polys = [[[0, 0], [100, 0], [100, 100], [0, 100]]]
        polys += [[[i, i], [i+.1, i], [i, i+.1]] for i in range(100)]
        index = _CellIndex(polys)
        self.assertEqual(index.pick(70, 80, len(polys)), 0)
        self.assertTrue(index.large)
        self.assertIsNone(_CellIndex([]).pick(0, 0, 0))
        self.assertIsNone(_CellIndex([[]]).pick(0, 0, 1))


class ProbeRedrawTests(unittest.TestCase):
    def setUp(self):
        self.figure = Figure()
        self.canvas = FigureCanvasAgg(self.figure)
        self.axes = self.figure.add_subplot()
        self.axes.set(xlim=(0, 3), ylim=(0, 3))
        self.control = attach_probes(self.canvas, self.axes, [[.2, .2, 2, 'cell']],
                                     polygons=[[[0, 0], [1, 0], [0, 1]]])
        self.canvas.draw()

    def tearDown(self):
        self.control['disconnect']()

    def event(self, name, x, y, button=None):
        sx, sy = self.axes.transData.transform((x, y))
        event = MouseEvent(name, self.canvas, sx, sy, button=button)
        self.canvas.callbacks.process(name, event)

    def test_hover_blits_only_changes_and_never_redraws_board(self):
        with patch.object(self.canvas, 'draw_idle') as draw, patch.object(self.canvas, 'blit') as blit:
            self.event('motion_notify_event', 1.5, 1.5)
            self.assertEqual(blit.call_count, 0)
            self.event('motion_notify_event', .2, .2)
            self.assertEqual(blit.call_count, 1)
            self.event('motion_notify_event', .21, .21)
            self.assertEqual(blit.call_count, 1)
            self.event('motion_notify_event', 1.5, 1.5)
            self.assertEqual(blit.call_count, 2)
            self.event('motion_notify_event', 1.6, 1.6)
            self.assertEqual(blit.call_count, 2)
            draw.assert_not_called()

    def test_click_drag_clear_and_disconnect(self):
        self.event('motion_notify_event', .2, .2)
        tip=self.axes.texts[0]
        self.assertTrue(tip.get_visible())
        self.event('button_press_event', .2, .2, 1)
        self.assertFalse(tip.get_visible())
        with patch.object(self.canvas, 'blit') as blit:
            self.event('motion_notify_event', .25, .25, 1)
            blit.assert_not_called()
        self.event('button_release_event', .4, .4, 1)
        self.assertEqual(self.control['probes'], [])
        self.event('button_press_event', .2, .2, 1)
        self.event('button_release_event', .2, .2, 1)
        self.assertEqual(len(self.control['probes']), 1)
        self.control['clear']()
        self.assertEqual(self.control['probes'], [])
        self.control['disconnect']()
        self.assertEqual(self.control['ids'], [])
        # The disconnect callback can be safely called more than once.
        self.control['disconnect']()

    def test_stale_axes_requires_full_redraw(self):
        self.axes.set_xlim(0, 4)
        with patch.object(self.canvas, 'draw_idle') as draw:
            self.event('motion_notify_event', .2, .2)
            draw.assert_called_once()

class SampleProbeTests(unittest.TestCase):
    def test_projected_3d_samples_follow_rotated_and_zoomed_view(self):
        from mpl_toolkits.mplot3d import proj3d
        figure = Figure()
        canvas = FigureCanvasAgg(figure)
        axes = figure.add_subplot(projection='3d')
        axes.set(xlim=(0, 3), ylim=(0, 3), zlim=(0, 3))
        selected = []
        row = [1.1, 1.2, 4, 'part', 2.1]
        control = attach_probes(canvas, axes, [row, [math.nan, 0, 1, 'bad']], on_select=selected.append)
        for elevation, azimuth, limit in ((30, -60, 3), (55, 110, 5)):
            axes.view_init(elev=elevation, azim=azimuth)
            axes.set_xlim(0, limit)
            canvas.draw()
            x, y, _ = proj3d.proj_transform(row[0], row[1], row[4], axes.get_proj())
            sx, sy = axes.transData.transform((x, y))
            for name in ('button_press_event', 'button_release_event'):
                canvas.callbacks.process(name, MouseEvent(name, canvas, sx, sy, button=1))
        self.assertEqual(selected, [row, row])
        self.assertEqual(len(control['probes']), 2)
        control['disconnect']()

    def test_non_blit_backend_redraws_only_changed_tooltip(self):
        figure = Figure()
        canvas = FigureCanvasAgg(figure)
        axes = figure.add_subplot()
        axes.set(xlim=(0, 3), ylim=(0, 3))
        with patch.object(canvas, 'supports_blit', False):
            control = attach_probes(canvas, axes, [[1, 1, 2, 'part']])
            canvas.draw()
            with patch.object(canvas, 'draw_idle') as draw:
                sx, sy = axes.transData.transform((1, 1))
                for _ in range(5):
                    canvas.callbacks.process('motion_notify_event', MouseEvent('motion_notify_event', canvas, sx, sy))
                draw.assert_called_once()
            control['disconnect']()


if __name__ == '__main__':
    unittest.main()
