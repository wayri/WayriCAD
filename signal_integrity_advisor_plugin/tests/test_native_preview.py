"""Actual native canvas regression: vias must provide a layer to KiCad 10."""
import unittest
try:
    import pcbnew,wx
    from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import RoutePreview
except ImportError:
    pcbnew=wx=RoutePreview=None
from types import SimpleNamespace

@unittest.skipUnless(pcbnew is not None,'Native KiCad/wx required')
class NativeRouteDrawing(unittest.TestCase):
    def test_via_and_endpoints_draw_without_paint_fallback(self):
        app=wx.GetApp() or wx.App(False);frame=wx.Frame(None,size=(700,500));canvas=RoutePreview(frame)
        board=pcbnew.BOARD();via=pcbnew.PCB_VIA(board);via.SetPosition(pcbnew.VECTOR2I(2000000,3000000));via.SetWidth(pcbnew.F_Cu,600000);via.SetDrill(300000);via.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu);board.Add(via)
        track=pcbnew.PCB_TRACK(board);track.SetStart(pcbnew.VECTOR2I(0,0));track.SetEnd(via.GetPosition());track.SetWidth(200000);board.Add(track)
        path=SimpleNamespace(board_items=[track,via],net_name='SIGNAL',start_pad='U1.1',end_pad='J1.1')
        try:
            canvas.show_result(SimpleNamespace(primary=path,mate=None));canvas.route_endpoints=[(0,0),(2,3)]
            bitmap=wx.Bitmap(700,500);dc=wx.MemoryDC(bitmap);gc=wx.GraphicsContext.Create(dc)
            # Direct call fails the test even when on_paint catches exceptions.
            canvas.draw_scene(gc,canvas.project)
            frame.Show();wx.Yield();canvas.Refresh();canvas.Update();wx.Yield()
            self.assertIsNone(canvas.draw_error)
            self.assertEqual(len(canvas.tracks),2)
            del gc;dc.SelectObject(wx.NullBitmap)
        finally:frame.Destroy();wx.Yield()

if __name__=='__main__':unittest.main()
