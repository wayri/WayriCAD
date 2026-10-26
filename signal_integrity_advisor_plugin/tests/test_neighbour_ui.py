"""Actual native neighbour worker, painting, selection and stale-result checks."""
from functools import partial
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
try:
    import wx,pcbnew
except ImportError:
    wx=pcbnew=None


def make_board(path):
    board=pcbnew.BOARD();board.SetFileName(str(path))
    for code,name,y in ((1,'DATA',10.),(2,'CLOCK',10.5),(3,'RESET',13.)):
        net=pcbnew.NETINFO_ITEM(board,name,code);board.Add(net)
        track=pcbnew.PCB_TRACK(board);track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(5),pcbnew.FromMM(y)));track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(35),pcbnew.FromMM(y)))
        track.SetWidth(pcbnew.FromMM(.2));track.SetLayer(pcbnew.F_Cu);track.SetNet(net);board.Add(track)
    pcbnew.SaveBoard(str(path),board)
    return pcbnew.LoadBoard(str(path))


_app=None
@unittest.skipIf(wx is None or pcbnew is None,'Native KiCad wx required')
class NativeNeighbourUITests(unittest.TestCase):
    def test_real_worker_paint_filter_pick_units_and_source_guard(self):
        from signal_integrity_advisor_plugin.neighbour_ui import NeighbourPanel
        from signal_integrity_advisor_plugin import service
        global _app
        _app=wx.GetApp() or wx.App(False)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'board.kicad_pcb';board=make_board(path);before=path.read_bytes()
            frame=wx.Frame(None,size=(1024,720));panel=NeighbourPanel(frame,board,True)
            layout=wx.BoxSizer(wx.VERTICAL);layout.Add(panel,1,wx.EXPAND);frame.SetSizer(layout)
            try:
                frame.Show();_app.Yield();panel.net.SetValue('DATA');panel.layer.SetSelection(1)
                # Use the already prepared native interpreter; still execute
                # the real isolated worker, never a mocked geometry result.
                with patch.object(service,'run_job',partial(service.run_job,python=sys.executable)):
                    panel.run();deadline=time.monotonic()+30
                    while not panel.run_button.IsEnabled() and time.monotonic()<deadline:_app.Yield();time.sleep(.03)
                self.assertIsNotNone(panel.report,panel.status.GetLabel());self.assertEqual(len(panel.report['pairs']),1)
                self.assertAlmostEqual(panel.report['pairs'][0]['gap_mm'],.3);self.assertEqual(panel.table.GetItemText(0,4),'30')
                self.assertEqual(panel.table.GetItemText(0,5),'UNKNOWN');self.assertTrue(panel.export_button.IsEnabled())
                panel.canvas.Refresh();panel.canvas.Update();_app.Yield();self.assertTrue(panel.canvas.strokes,str(panel.canvas.GetSize()))
                a,b,row=panel.canvas.strokes[0];self.assertIsNotNone(panel.canvas.hit(((a[0]+b[0])/2,(a[1]+b[1])/2)))
                panel.select_pair(row['id']);self.assertIn('parallel overlap 30 mm',panel.detail.GetValue());self.assertIn('edge gap 0.3 mm',panel.detail.GetValue())
                self.assertIn('closest location',panel.detail.GetValue());self.assertGreater(panel.canvas.GetClientSize().height,120)
                panel.search.SetValue('CLOCK');panel.filter();self.assertEqual(len(panel.visible),1)
                panel.search.SetValue('MISSING');panel.filter();self.assertFalse(panel.visible)
                panel.search.SetValue('');panel.filter();self.assertEqual(len(panel.visible),1)
                self.assertEqual(path.read_bytes(),before)
                path.write_bytes(before+b'\n');panel.run();self.assertIsNone(panel.report);self.assertIn('changed',panel.status.GetLabel())
            finally:frame.Destroy();_app.Yield()

    def test_input_change_discards_old_callback_and_live_mode_is_explicit(self):
        from signal_integrity_advisor_plugin.neighbour_ui import NeighbourPanel
        global _app
        _app=wx.GetApp() or wx.App(False)
        with tempfile.TemporaryDirectory() as directory:
            board=make_board(Path(directory)/'board.kicad_pcb');frame=wx.Frame(None)
            panel=NeighbourPanel(frame,board,False)
            try:
                self.assertFalse(panel.run_button.IsEnabled());self.assertIn('unsaved live geometry',panel.status.GetLabel())
                serial=panel.serial;panel.invalidate();panel.finished(serial,None,'obsolete failure')
                self.assertNotIn('obsolete',panel.status.GetLabel());self.assertFalse(panel.export_button.IsEnabled())
            finally:frame.Destroy();_app.Yield()


if __name__=='__main__':unittest.main()
