"""Native synthetic inspector smoke plus stale-result/navigation contracts."""
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import wx
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx=None

_native_app=None


@unittest.skipIf(wx is None,'native wx runtime required')
class InspectorTests(unittest.TestCase):
    def test_saved_source_change_and_missing_file_are_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.kicad_pcb';path.write_bytes(b'original')
            frame=SimpleNamespace(board_path=str(path),bundle={'geometry':{'source_sha256':hashlib.sha256(b'original').hexdigest()}})
            self.assertTrue(QuickPIFrame._snapshot_current(frame))
            path.write_bytes(b'changed')
            self.assertFalse(QuickPIFrame._snapshot_current(frame))
            path.unlink()
            self.assertFalse(QuickPIFrame._snapshot_current(frame))

    def test_stale_export_stops_before_opening_save_dialog(self):
        messages=[]
        frame=SimpleNamespace(bundle={'result':{'available':True}},_snapshot_current=lambda:False,
                              model_dimension=SimpleNamespace(GetSelection=lambda:0),
                              status=SimpleNamespace(SetLabel=messages.append))
        QuickPIFrame.on_export(frame)
        self.assertIn('Reload and rerun',messages[0])

    def test_ranked_hotspot_keeps_mesh_identity_and_requests_map_focus(self):
        from quick_pi_plugin.tests.test_report import bundle
        b=bundle();calls=[]
        row=b['result']['analytics']['hotspots_by_current_density'][0]
        frame=SimpleNamespace(bundle=b,_finding_rows=[row],finding_order=SimpleNamespace(GetSelection=lambda:0),
                              _choose_inspection=lambda value,focus:calls.append((value,focus)))
        QuickPIFrame._finding_selected(frame,SimpleNamespace(GetIndex=lambda:0))
        self.assertEqual(calls[0][0]['id'],row['id'])
        self.assertEqual(calls[0][0]['source_ids'],[])
        self.assertTrue(calls[0][1])

    def test_native_inspector_renders_and_links_ranked_row(self):
        try:import pcbnew
        except ImportError:self.skipTest('KiCad native pcbnew runtime required')
        from quick_pi_plugin.tests.test_report import bundle
        global _native_app
        _native_app=wx.GetApp() or wx.App(False)
        app=_native_app
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic-pi.kicad_pcb'
            board=pcbnew.BOARD()
            net=pcbnew.NETINFO_ITEM(board,'Analytical strip',1);board.Add(net)
            track=pcbnew.PCB_TRACK(board);track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(.5),pcbnew.FromMM(.5)))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(9.5),pcbnew.FromMM(.5)))
            track.SetWidth(pcbnew.FromMM(1));track.SetLayer(pcbnew.F_Cu);track.SetNetCode(1);board.Add(track)
            via=pcbnew.PCB_VIA(board);via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(8),pcbnew.FromMM(.5)))
            via.SetWidth(pcbnew.FromMM(.6));via.SetDrill(pcbnew.FromMM(.3))
            via.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu);via.SetNetCode(1);board.Add(via)
            pcbnew.SaveBoard(str(path),board)
            with patch.object(QuickPIFrame,'_inspect'):
                frame=QuickPIFrame(None,str(path))
                try:
                    b=bundle();b['geometry']['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                    frame.net.Set(['Analytical strip']);frame.net.SetValue('Analytical strip')
                    frame._terminals=[{'id':'A','label':'A.1'},{'id':'B','label':'B.1'}]
                    frame.source.Set(['A.1','B.1']);frame.source.SetSelection(0)
                    frame.sink.Set(['A.1','B.1']);frame.sink.SetSelection(1)
                    frame._accept_result(b,b['request'],'solve')
                    frame.Show();app.Yield()
                    self.assertTrue(frame.splitter.IsSplit())
                    self.assertGreater(frame.findings.GetItemCount(),0)
                    frame._finding_selected(SimpleNamespace(GetIndex=lambda:0));app.Yield()
                    self.assertEqual(frame._inspection['id'],frame._finding_rows[0]['id'])
                    self.assertEqual(frame._inspection['source_ids'],[track.m_Uuid.AsString()])
                    self.assertTrue(frame.inspector_select.IsEnabled())
                    from wayricad_runtime.board_render import hit_test
                    self.assertEqual(hit_test(frame._board_scene,8,.5,[0],net='Analytical strip')[-1]['role'],'track')
                    self.assertTrue(any(row['role']=='via' for row in frame._board_scene['primitives']))
                    figure,canvas,_=frame.views[2];canvas.draw()
                    x,y=frame._inspection['location_mm'][:2]
                    px,py=figure.axes[0].transData.transform((x,y));py=canvas.GetClientSize().height-py
                    event=SimpleNamespace(GetX=lambda:int(px),GetY=lambda:int(py),Skip=lambda:None)
                    frame._probe_down(event,2);frame._probe_up(event,2)
                    self.assertEqual(frame._inspection['unit'],'mV')
                    frame.scale_mode.SetSelection(1);frame._scale_changed();app.Yield()
                    figure,canvas,_=frame.views[2];canvas.draw()
                    self.assertEqual(b['view_settings']['scale_mode'],1)
                    self.assertIn('2.5D DC',frame.model_basis.GetValue())
                    capture=os.environ.get('WAYRICAD_PI_UI_CAPTURE')
                    if capture:
                        area=wx.Display(wx.Display.GetFromWindow(frame)).GetClientArea()
                        frame.SetSize((min(1180,area.width),min(800,area.height)))
                        frame.SetPosition((area.x,area.y));frame.Raise();frame.Refresh();frame.Update()
                        capture_errors=[]
                        def save_capture():
                            try:
                                frame.Refresh();frame.Update();canvas.draw()
                                width,height=frame.main_panel.GetClientSize()
                                bitmap=wx.Bitmap(width,height);dc=wx.MemoryDC(bitmap)
                                self.assertTrue(dc.Blit(0,0,width,height,wx.ClientDC(frame.main_panel),0,0))
                                dc.SelectObject(wx.NullBitmap)
                                target=Path(capture);target.parent.mkdir(parents=True,exist_ok=True)
                                self.assertTrue(bitmap.SaveFile(str(target),wx.BITMAP_TYPE_PNG))
                            except Exception as exc:capture_errors.append(exc)
                            finally:app.ExitMainLoop()
                        wx.CallLater(800,save_capture);app.MainLoop()
                        if capture_errors:raise capture_errors[0]
                    path.write_bytes(path.read_bytes()+b'\n')
                    frame._draw()
                    self.assertFalse(frame.export.IsEnabled())
                    self.assertEqual(frame.findings.GetItemCount(),0)
                    self.assertTrue(any('Saved PCB changed' in text.get_text() for text in figure.axes[0].texts))
                finally:
                    frame._end()
                    wx.CallLater(100,app.ExitMainLoop);app.MainLoop()


if __name__=='__main__':unittest.main()
