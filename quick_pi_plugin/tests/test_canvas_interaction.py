"""Native canvas redraw scheduling, pan precision and probe event delivery."""
import unittest
from unittest.mock import patch

try:
    import wx
    from matplotlib.figure import Figure
    from quick_pi_plugin.plot_canvas import FigureCanvasWxAgg
except ImportError:
    wx=None

_app=None


class Pointer:
    def __init__(self,x,y,dragging=False):self.x=x;self.y=y;self.dragging=dragging
    def GetX(self):return self.x
    def GetY(self):return self.y
    def Dragging(self):return self.dragging
    def ControlDown(self):return False
    def Skip(self):pass


@unittest.skipIf(wx is None,'KiCad native wx runtime required')
class CanvasInteractionTests(unittest.TestCase):
    def setUp(self):
        global _app
        _app=wx.GetApp() or wx.App(False)
        self.frame=wx.Frame(None,size=(640,480))
        self.figure=Figure(figsize=(6.4,4.8),dpi=100)
        self.canvas=FigureCanvasWxAgg(self.frame,wx.ID_ANY,self.figure)
        self.canvas.SetSize((640,480))
        self.axes=self.figure.add_subplot()
        self.axes.plot([0,100],[0,100]);self.axes.set_xlim(0,100);self.axes.set_ylim(100,0)
        self.canvas.draw()

    def tearDown(self):
        self.frame.Destroy();_app.Yield()

    def _fallback(self):
        if not hasattr(self.canvas,'_pan_offset'):self.skipTest('Agg fallback-specific gesture')

    def test_idle_burst_has_one_timer_and_explicit_draw_cancels_it(self):
        with patch('quick_pi_plugin.plot_canvas.wx.CallLater') as timer:
            for _ in range(100):self.canvas.draw_idle()
            timer.assert_called_once()
            self.assertGreaterEqual(timer.call_args.args[0],1)
            self.assertLessEqual(timer.call_args.args[0],34)
            self.canvas.draw()
            timer.return_value.Stop.assert_called_once()
            self.assertIsNone(self.canvas._render_timer)

    def test_pan_uses_bitmap_until_release_and_final_limits_are_exact(self):
        self._fallback()
        self.canvas._down(Pointer(300,200))
        original=self.canvas._bitmap
        with patch.object(self.canvas,'draw',wraps=self.canvas.draw) as draw:
            for delta in range(1,31):self.canvas._motion(Pointer(300+delta,200+delta,True))
            draw.assert_not_called()
            self.assertIs(self.canvas._bitmap,original)
            self.assertEqual(self.canvas._pan_offset,(30,30))
            expected_x=-30*100/self.axes.bbox.width
            expected_y=100+30*(-100)/self.axes.bbox.height
            self.assertAlmostEqual(self.axes.get_xlim()[0],expected_x)
            self.assertAlmostEqual(self.axes.get_ylim()[0],expected_y)
            with patch('quick_pi_plugin.plot_canvas.wx.CallLater') as timer:
                self.canvas._up(Pointer(330,230))
                timer.assert_called_once()
                callback=timer.call_args.args[1]
                callback()
            draw.assert_called_once()
            self.assertEqual(self.canvas._pan_offset,(0,0))
            self.assertAlmostEqual(self.axes.get_xlim()[0],expected_x)
            self.assertAlmostEqual(self.axes.get_ylim()[0],expected_y)

    def test_fallback_dispatches_hover_press_and_release_to_probes(self):
        self._fallback()
        events=[]
        for name in ('motion_notify_event','button_press_event','button_release_event'):
            self.canvas.mpl_connect(name,lambda event:events.append(event))
        self.canvas._motion(Pointer(300,200))
        self.canvas._down(Pointer(300,200))
        self.canvas._up(Pointer(300,200))
        self.assertEqual([event.name for event in events],
                         ['motion_notify_event','button_press_event','button_release_event'])
        self.assertTrue(all(event.inaxes is self.axes for event in events))
        self.assertIsNotNone(events[0].xdata)

    def test_leave_clears_hover_and_control_right_click_reaches_probe_clear(self):
        self._fallback()
        events=[]
        self.canvas.mpl_connect('motion_notify_event',lambda event:events.append(event))
        self.canvas.mpl_connect('button_press_event',lambda event:events.append(event))
        self.canvas._leave(Pointer(300,200))
        self.assertIsNone(events[0].inaxes)
        event=Pointer(300,200);event.ControlDown=lambda:True
        self.canvas._down(event,3)
        self.assertEqual(events[1].button,3)
        self.assertEqual(events[1].key,'control')
        self.assertIsNone(self.canvas._drag)
        self.canvas._up(event,3)

    def test_3d_capture_loss_cancels_rotation_and_pending_probe_without_click(self):
        self._fallback()
        from wayricad_runtime.plot_probe import attach_probes
        self.figure.clear();self.axes=self.figure.add_subplot(projection='3d')
        self.axes.scatter([0],[0],[0]);self.canvas.draw()
        controller=attach_probes(self.canvas,self.axes,[[0,0,1,'sample',0]],'V')
        self.canvas._down(Pointer(300,200))
        self.assertTrue(self.canvas.HasCapture())
        self.assertEqual(self.axes.button_pressed,1)
        self.assertIsNotNone(controller['press'])
        # Simulate the native loss event after another window takes capture.
        self.canvas.ReleaseMouse()
        event=wx.MouseCaptureLostEvent(self.canvas.GetId())
        self.canvas._capture_lost(event)
        self.assertIsNone(self.axes.button_pressed)
        self.assertIsNone(self.canvas._button)
        self.assertIsNone(controller['press'])
        self.assertEqual(controller['probes'],[])
        self.assertIsNone(self.canvas._pressed_button)
        controller['disconnect']()

    def test_3d_release_outside_canvas_ends_captured_gesture(self):
        self._fallback()
        self.figure.clear();self.axes=self.figure.add_subplot(projection='3d')
        self.axes.scatter([0],[0],[0]);self.canvas.draw()
        self.canvas._down(Pointer(300,200))
        self.assertTrue(self.canvas.HasCapture())
        self.canvas._up(Pointer(-10,-10))
        self.assertFalse(self.canvas.HasCapture())
        self.assertIsNone(self.axes.button_pressed)
        self.assertIsNone(self.canvas._pressed_button)

    def test_blit_publishes_agg_pixels_without_full_render(self):
        self._fallback()
        before=bytes(self.canvas._bitmap.ConvertToImage().GetData())
        artist=self.axes.text(50,50,'PROBE',color='red',fontsize=24)
        self.axes.draw_artist(artist)
        with patch.object(self.canvas,'draw',side_effect=AssertionError('No full render needed')):
            self.canvas.blit(self.axes.bbox)
        after=bytes(self.canvas._bitmap.ConvertToImage().GetData())
        self.assertNotEqual(before,after)

    def test_pending_timer_is_stopped_when_window_is_destroyed(self):
        with patch('quick_pi_plugin.plot_canvas.wx.CallLater') as timer:
            self.canvas.draw_idle()
            self.frame.Destroy();_app.Yield()
            timer.return_value.Stop.assert_called_once()
            self.assertTrue(self.canvas._closed)
        self.frame=wx.Frame(None)


if __name__=='__main__':unittest.main()
