"""Exact saved-item emphasis and camera behavior in the shared native preview."""
import unittest
from unittest.mock import patch

try:
    import wx
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'native wxPython is required')
class PreviewHighlightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.App.Get() or wx.App(False)

    def setUp(self):
        from wayricad_runtime.preview import GeometryPreview
        self.frame = wx.Frame(None, size=(700, 500))
        self.view = GeometryPreview(self.frame)
        self.view.SetSize((650, 450))
        self.view.focus_points = [(0., 0.), (20., 10.)]
        self.view.context_lines = [(0., 0., 5., 0., .2), (0., 3., 5., 3., .2)]
        self.view.context_pads = [dict(center=(1., 1.), size=(2., 2.), angle=0.,
            shape='rectangle', rings=[], drill=(0., 0.), number='1', radius=0)]
        self.view.context_vias = [(4., 1., 1., .4)]
        self.view.context_rings = [([(0., -2.), (6., -2.), (6., 4.), (0., 4.)], 'zone'),
                                   ([(-2., -4.), (30., -4.), (30., 14.), (-2., 14.)], 'edge')]
        self.view._context_identity = {
            'context_lines': [('VCC', 'track-a'), ('VCC_AUX', 'track-b')],
            'context_pads': [('VCC', 'pad-a')], 'context_vias': [('VCC', 'via-a')],
            'context_rings': [('VCC', 'zone-a'), ('', '')]}

    def tearDown(self):
        self.frame.Destroy(); self.app.Yield()

    def test_exact_net_highlights_native_items_without_replacing_candidates(self):
        self.view.set_geometry(lines=[(12., 8., 14., 8.)])
        before = list(self.view.lines)
        count = self.view.set_highlight(nets=['VCC'])
        self.assertEqual(count, 4)
        self.assertEqual(self.view._highlight_indices['context_lines'], {0})
        self.assertFalse(self.view._highlighted('context_lines', 1))
        self.assertEqual(self.view.lines, before)
        self.assertTrue(self.view._bitmap_for_view().IsOk())

    def test_uuid_selection_and_clear_restore_neutral_pixels(self):
        original = self.view._bitmap_for_view().ConvertToImage().GetData()
        self.view.set_highlight(identifiers=['PAD-A'])
        selected = self.view._bitmap_for_view().ConvertToImage().GetData()
        self.assertNotEqual(selected, original)
        self.assertEqual(self.view._highlight_indices['context_pads'], {0})
        self.view.set_highlight()
        self.assertEqual(self.view._bitmap_for_view().ConvertToImage().GetData(), original)

    def test_highlight_does_not_jump_camera_and_focus_fit_are_explicit(self):
        self.view.zoom = 2.; self.view.pan = [13., 27.]
        self.view.set_highlight(nets=['VCC'])
        self.assertEqual((self.view.zoom, self.view.pan), (2., [13., 27.]))
        self.assertTrue(self.view.focus_highlight())
        self.assertEqual((self.view.zoom, self.view.pan), (1., [0., 0.]))
        self.assertEqual(max(x for x, _ in self.view._view_bounds), 6.)
        self.assertTrue(self.view.fit_board())
        self.assertEqual(max(x for x, _ in self.view._view_bounds), 30.)
        self.view.set_highlight(nets=['MISSING'])
        self.assertFalse(self.view.focus_highlight())

    def test_shared_snapshot_has_independent_emphasis(self):
        from wayricad_runtime.preview import GeometryPreview
        other = GeometryPreview(self.frame)
        other.set_board_context(self.view)
        other.set_highlight(nets=['VCC_AUX'])
        self.assertFalse(self.view._highlight_nets)
        self.assertEqual(other._highlight_indices['context_lines'], {1})
        self.assertIs(other.context_lines, self.view.context_lines)

    def test_hover_retains_highlight_bitmap(self):
        self.view.set_highlight(nets=['VCC'])
        bitmap = self.view._bitmap_for_view()
        for i in range(20):
            self.view.cursor = (i, 20)
            self.assertIs(self.view._bitmap_for_view(), bitmap)

    def test_switching_nets_reuses_muted_board_but_camera_and_edits_do_not(self):
        with patch.object(self.view, '_render_scene', wraps=self.view._render_scene) as render:
            for net in ['VCC', 'VCC_AUX', 'VCC']:
                self.view.set_highlight(nets=[net])
                self.view._bitmap_for_view()
            self.assertEqual(render.call_count, 1)
            self.view.pan[0] += 20
            self.view._bitmap_for_view()
            self.assertEqual(render.call_count, 2)
            self.view.context_lines[0] = (0., 0., 4., 0., .2)
            self.view.invalidate_scene()
            self.view._bitmap_for_view()
            self.assertEqual(render.call_count, 3)

    def test_indexed_pick_matches_original_exact_screen_distance(self):
        import math
        from wayricad_runtime.picking import segment_distance
        self.view.net_targets = [dict(net='VCC',start=(0.,0.),end=(5.,0.),radius=.1),
                                 dict(net='VCC_AUX',start=(0.,3.),end=(5.,3.),radius=.1),
                                 dict(net='VIA',start=(4.,1.),end=(4.,1.),radius=.5)]
        for zoom in (.1, 1., 10.):
            self.view.zoom = zoom; self.view._bitmap_for_view()
            for world in [(0,0), (3,1), (4,1), (5,3), (20,20)]:
                screen = self.view.project(world)
                closest = None; distance = math.inf
                for target in self.view.net_targets:
                    a,b = self.view.project(target['start']),self.view.project(target['end'])
                    radius = math.dist(a,self.view.project((target['start'][0]+target['radius'],target['start'][1])))
                    gap = max(0,segment_distance(screen,a,b)-radius)
                    if gap<=7 and gap<distance: closest=target;distance=gap
                self.assertIs(self.view.pick_net(screen), closest)


if __name__ == '__main__':
    unittest.main()
