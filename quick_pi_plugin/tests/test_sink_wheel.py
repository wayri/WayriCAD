"""Native Ctrl+wheel sink picking, independent currents and ordinary zoom."""
import hashlib
import os
import unittest

from quick_pi_plugin.tests import test_live_ui as live_tests


@unittest.skipIf(live_tests.wx is None, 'Native KiCad wx runtime required')
class SinkWheelTests(unittest.TestCase):
    setUp = live_tests.LiveUITests.setUp
    tearDown = live_tests.LiveUITests.tearDown
    until = live_tests.LiveUITests.until
    event = live_tests.LiveUITests.event

    def multi(self):
        from quick_pi_plugin.tests.test_sink_current import fixture
        base = fixture()
        geometry = base['geometry']
        geometry['source_sha256'] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        polygon = lambda x0, y0, x1, y1: {'outer': [[x0,y0],[x1,y0],[x1,y1],[x0,y1]], 'holes': []}
        geometry['layers'] = [
            {'id': 0, 'name': 'F.Cu', 'polygons': [polygon(0,0,10,1)]},
            {'id': 1, 'name': 'In1.Cu', 'polygons': [polygon(0,0,20,2)]}]
        for row in geometry['terminals']:
            row['polygons'] = ({'0': [polygon(9.9,0,10,1)]} if row['id']=='a' else
                               {'1': [polygon(19.9,0,20,2)]} if row['id']=='b' else
                               {'0': [polygon(0,0,.1,1)], '1': [polygon(0,0,.1,2)]})
        frame = self.frame
        frame.net.Set(['rail']);frame.net.SetValue('rail')
        frame._accept_result(base, base['request'], 'solve')
        self.until(lambda: frame._live_model is not None)
        index = next(i for i,row in enumerate(frame._layers) if row['id']=='all')
        frame.layer.SetSelection(index);frame._draw()
        frame.views[2][1].draw();live_tests._app.Yield()
        return frame

    def test_ctrl_wheel_changes_only_hit_sink_and_proportional_tuning_rebases(self):
        frame = self.multi()
        self.assertTrue(frame._live_wheel(self.event(xdata=10., ydata=.5)))
        self.until(lambda: not frame._live_running and abs(frame.bundle['result']['sinks'][0]['current_A']-1.01)<1e-8)
        self.assertEqual(frame.bundle['result']['sinks'][1]['current_A'], 2.)
        self.assertIn('recomputed', frame.status.GetLabel())
        self.assertEqual(frame._live_active_sink, 0)
        self.assertTrue(frame._live_preview.IsShown())
        row=frame._live_preview.rows[0]
        self.assertEqual(row['before'],1.)
        self.assertAlmostEqual(row['after'],1.01)
        if os.environ.get('WAYRICAD_PI_CURSOR_CAPTURE'):
            window=frame._live_preview;window.Update();live_tests._app.Yield()
            size=window.GetClientSize();bitmap=live_tests.wx.Bitmap(size.width,size.height)
            target=live_tests.wx.MemoryDC(bitmap)
            target.Blit(0,0,size.width,size.height,live_tests.wx.ClientDC(window),0,0)
            target.SelectObject(live_tests.wx.NullBitmap)
            bitmap.SaveFile(os.environ['WAYRICAD_PI_CURSOR_CAPTURE'],live_tests.wx.BITMAP_TYPE_PNG)
        before=[r['current_A'] for r in frame.bundle['result']['sinks']]
        frame.live_current.SetValue(6.02);frame._queue_live_current(6.02)
        self.until(lambda: abs(frame.bundle['result']['sink_current_A']-6.02)<1e-8 and not frame._live_running)
        for row,old in zip(frame.bundle['result']['sinks'],before):
            self.assertAlmostEqual(row['current_A'],old*2,8)

    def test_normal_scroll_on_sink_zooms_and_second_sink_is_independent(self):
        frame=self.multi()
        frame.live_preview_mode.SetSelection(1)
        self.assertFalse(frame._live_wheel(self.event(xdata=20.,ydata=1.,key=None)))
        self.assertTrue(frame._live_wheel(self.event(xdata=20.,ydata=1.)))
        self.until(lambda: not frame._live_running and abs(frame.bundle['result']['sinks'][1]['current_A']-2.01)<1e-8)
        self.assertEqual(frame.bundle['result']['sinks'][0]['current_A'],1.)
        self.assertEqual(len(frame._live_preview.rows),10)
