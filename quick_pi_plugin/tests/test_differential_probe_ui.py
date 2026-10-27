"""Native two-point picking, colour markers and stale/clear behavior."""
from types import SimpleNamespace
import unittest

try:
    import wx
    from quick_pi_plugin.tests import test_live_ui as fixture
except ImportError:
    wx=None


@unittest.skipIf(wx is None,'Native KiCad wx runtime required')
class DifferentialUITests(unittest.TestCase):
    def test_native_pair_selection_clear_and_stale_guard(self):
        case=fixture.LiveUITests('test_plain_wheel_zoom_empty_space_and_disabled_scroll_do_not_change_load')
        case.setUp()
        try:
            frame=case.frame
            frame.layer.SetSelection(next(i for i,row in enumerate(frame._layers) if str(row['id'])=='0'))
            frame.differential_target.SetSelection(1);frame._draw();wx.GetApp().Yield()
            for x in (2.,8.):
                figure,canvas,_=frame.views[2];canvas.draw()
                px,py=figure.axes[0].transData.transform((x,.5));py=canvas.GetClientSize().height-py
                event=SimpleNamespace(GetX=lambda:int(px),GetY=lambda:int(py),Skip=lambda:None)
                frame._probe_down(event,2);frame._probe_up(event,2);wx.GetApp().Yield()
            self.assertEqual(set(frame.bundle['differential_probes']),{'a','b'})
            self.assertIn('V(A) - V(B)',frame.differential_readout.GetLabel())
            self.assertTrue({'A','B'} <= {t.get_text() for t in frame.views[2][0].axes[0].texts})
            import os
            capture=os.environ.get('WAYRICAD_PI_DIFFERENTIAL_CAPTURE')
            if capture:
                frame.current.ChangeValue('2')
                frame.SetSize((1500,900));frame.splitter.SetSashPosition(max(600,frame.splitter.GetClientSize().width-400));frame.Layout();wx.GetApp().Yield();frame.views[2][1].draw()
                frame.Refresh();frame.Update();wx.GetApp().Yield()
                width,height=frame.main_panel.GetClientSize();bitmap=wx.Bitmap(width,height)
                memory=wx.MemoryDC(bitmap);memory.Blit(0,0,width,height,wx.ClientDC(frame.main_panel),0,0);memory.SelectObject(wx.NullBitmap)
                image=bitmap.ConvertToImage()
                from PIL import Image
                Image.frombytes('RGB',(width,height),bytes(image.GetData())).save(capture)
            frame._clear_differential();self.assertNotIn('differential_probes',frame.bundle)
            self.assertIn('choose A and B',frame.differential_readout.GetLabel())
            frame._saved_source_current=False;frame._update_differential()
            self.assertIn('board changed',frame.differential_readout.GetLabel())
        finally:case.tearDown()


if __name__=='__main__':unittest.main()
