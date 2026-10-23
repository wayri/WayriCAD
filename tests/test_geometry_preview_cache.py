"""Native wx regression checks for the shared board preview pixel cache."""
import math
import unittest
from unittest.mock import patch

try:
    import wx
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'native wxPython is required')
class GeometryPreviewCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.App.Get() or wx.App(False)

    def setUp(self):
        from wayricad_runtime.preview import GeometryPreview
        self.frame = wx.Frame(None, size=(640, 480))
        self.panel = GeometryPreview(self.frame)
        self.panel.SetSize((600, 400))
        self.panel.set_geometry(lines=[(0., 0., 2., 0.)])

    def tearDown(self):
        self.frame.Destroy()
        self.app.Yield()

    def test_hover_and_probe_overlays_reuse_static_pixels(self):
        with patch.object(self.panel, '_render_scene', wraps=self.panel._render_scene) as render:
            bitmap = self.panel._bitmap_for_view()
            for i in range(30):
                self.panel.cursor = (100 + i, 80)
                self.panel.probes = [(1., 0.)]
                self.assertIs(self.panel._bitmap_for_view(), bitmap)
            self.assertEqual(render.call_count, 1)

    def test_camera_size_selection_and_grid_invalidate(self):
        with patch.object(self.panel, '_render_scene', wraps=self.panel._render_scene) as render:
            self.panel._bitmap_for_view()
            for change in (
                lambda: setattr(self.panel, 'zoom', 2.),
                lambda: self.panel.pan.__setitem__(0, 3.),
                lambda: self.panel.SetSize((500, 350)),
                lambda: setattr(self.panel, 'pick', 0),
                lambda: setattr(self.panel, 'show_grid', True),
                lambda: setattr(self.panel, 'focus_points', [(4., 5.)]),
            ):
                change()
                self.panel._bitmap_for_view()
            self.assertEqual(render.call_count, 7)

    def test_drag_translates_pixels_and_release_renders_exactly_once(self):
        with patch.object(self.panel, '_render_scene', wraps=self.panel._render_scene) as render:
            self.panel._bitmap_for_view()
            self.panel.drag = wx.Point(100, 100)
            for step in range(20):
                self.panel.pan[:] = [step * 2., step * 3.]
                self.assertEqual(self.panel._drag_bitmap_offset(), (step * 2, step * 3))
            self.assertEqual(render.call_count, 1)
            self.panel.drag = None
            self.assertIsNone(self.panel._drag_bitmap_offset())
            self.panel._bitmap_for_view()
            self.assertEqual(render.call_count, 2)
            self.panel.drag = wx.Point(100, 100)
            self.panel.zoom *= 2
            self.assertIsNone(self.panel._drag_bitmap_offset())

    def test_geometry_replacement_and_explicit_in_place_edit(self):
        original = self.panel._bitmap_for_view()
        self.panel.set_geometry(lines=[(0., 0., 4., 0.)])
        self.assertIsNot(self.panel._bitmap_for_view(), original)
        with patch.object(self.panel, '_render_scene', wraps=self.panel._render_scene) as render:
            self.panel.lines[0] = (0., 0., 5., 0.)
            self.panel.invalidate_scene()
            self.panel._bitmap_for_view()
            self.assertEqual(render.call_count, 1)

    def test_shared_context_has_independent_camera_and_geometry(self):
        from wayricad_runtime.preview import GeometryPreview
        other = GeometryPreview(self.frame, compact=True)
        self.panel.context_lines = [(0., 0., 5., 0., .2)]
        other.set_board_context(self.panel)
        self.assertIs(other.context_lines, self.panel.context_lines)
        other.focus_points = [(20., 30.)]
        other.pan[0] = 25.
        self.assertEqual(self.panel.pan, [0., 0.])
        self.assertEqual(self.panel.focus_points, [])
        self.assertEqual(other.lines, [])

    def test_culled_context_keeps_native_pad_rings_intact(self):
        ring = [(0., 0.), (1., 0.), (1., 1.), (0., 1.)]
        self.panel.context_pads = [dict(center=(.5, .5), size=(1., 1.), angle=0.,
            shape='rectangle', rings=[ring], drill=(0., 0.), number='1')]
        self.panel._bitmap_for_view()
        self.assertEqual(self.panel.context_pads[0]['rings'], [ring])
        point = (.25, .7)
        world = self.panel.unproject(self.panel.project(point))
        self.assertLess(math.dist(point, world), .03)

    def test_custom_pad_extending_beyond_anchor_is_not_culled(self):
        # Custom copper may extend far from its nominal pad anchor/size.
        self.panel.context_pads = [dict(center=(100., 100.), size=(1., 1.), angle=0.,
            shape='rectangle', bounds=(0., 0., 1., 1.),
            rings=[[(0., 0.), (1., 0.), (1., 1.), (0., 1.)]],
            drill=(0., 0.), number='1')]
        bitmap = self.panel._bitmap_for_view()
        x, y = self.panel.project((.5, .5))
        image = bitmap.ConvertToImage()
        self.assertEqual((image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y)),
                         (215, 179, 108))

    def test_empty_view_does_not_keep_stale_coordinate_transform(self):
        self.panel._bitmap_for_view()
        self.panel.clear()
        self.panel._bitmap_for_view()
        self.assertIsNone(self.panel.unproject((100, 100)))

    def test_compact_view_omits_footer_and_cursor_caption(self):
        self.panel.compact = True
        self.panel.cursor = (40, 40)
        with patch.object(wx.MemoryDC, 'DrawText') as text:
            self.panel._bitmap_for_view()
            dc = wx.MemoryDC(wx.Bitmap(600, 400))
            self.panel._draw_inspection(dc)
            dc.SelectObject(wx.NullBitmap)
        self.assertEqual(text.call_count, 0)


if __name__ == '__main__':
    unittest.main()
