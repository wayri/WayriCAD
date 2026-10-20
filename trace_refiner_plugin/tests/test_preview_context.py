"""Native geometry capture and cached drawing; not an IPC/editor latency test."""
import unittest
from unittest.mock import Mock, patch

try:
    import pcbnew
    import wx
except ImportError:
    pcbnew=wx=None


@unittest.skipIf(wx is None or pcbnew is None,'KiCad native wxPython required')
class ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A standalone Python process has no KiCad action-plugin host.
        with patch.object(pcbnew.ActionPlugin,'register'):
            from trace_refiner_plugin.ui import Preview
        cls.app=wx.App.Get() or wx.App(False)

    def setUp(self):
        from trace_refiner_plugin.ui import Preview
        self.board=pcbnew.BOARD()
        for a,b in (((0,0),(30,0)),((30,0),(30,30)),((30,30),(0,30)),((0,30),(0,0))):
            shape=pcbnew.PCB_SHAPE(self.board);shape.SetLayer(pcbnew.Edge_Cuts)
            shape.SetShape(pcbnew.SHAPE_T_SEGMENT);shape.SetStart(self.point(*a));shape.SetEnd(self.point(*b));self.board.Add(shape)
        self.line=pcbnew.PCB_TRACK(self.board);self.line.SetStart(self.point(2,3));self.line.SetEnd(self.point(8,3));self.line.SetWidth(pcbnew.FromMM(.2));self.board.Add(self.line)
        self.via=pcbnew.PCB_VIA(self.board);self.via.SetPosition(self.point(15,15));self.via.SetWidth(pcbnew.FromMM(.8));self.via.SetDrill(pcbnew.FromMM(.3));self.via.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu);self.via.SetViaType(pcbnew.VIATYPE_THROUGH);self.board.Add(self.via)
        self.arc=pcbnew.PCB_ARC(self.board);self.arc.SetStart(self.point(3,20));self.arc.SetMid(self.point(8,15));self.arc.SetEnd(self.point(13,20));self.arc.SetWidth(pcbnew.FromMM(.25));self.board.Add(self.arc)
        self.frame=wx.Frame(None,size=(600,500));self.canvas=Preview(self.frame,self.board,lambda:True)
        self.frame.Show();wx.Yield()

    def tearDown(self):self.frame.Destroy();wx.Yield()

    @staticmethod
    def point(x,y):return pcbnew.VECTOR2I(pcbnew.FromMM(x),pcbnew.FromMM(y))

    def test_native_capture_preserves_width_bounds_via_and_arc_curve(self):
        records={row[0]:row for row in self.canvas.context}
        self.assertEqual(records['line'][1],self.line.GetWidth())
        self.assertEqual(records['via'][1],self.via.GetWidth(self.via.TopLayer()))
        self.assertEqual(records['line'][2],((2000000,3000000),(8000000,3000000)))
        self.assertEqual(records['line'][3],(1900000,2900000,8100000,3100000))
        arc=records['arc']
        self.assertGreater(len(arc[2]),20)
        self.assertEqual(arc[2][0],(3000000,20000000))
        self.assertEqual(arc[2][-1],(13000000,20000000))
        self.assertAlmostEqual(min(p[1] for p in arc[2]),15000000,delta=1000)
        self.assertEqual(self.canvas.context_bounds,(-50000,-50000,30050000,30050000))

    def test_repaints_pan_zoom_and_fit_make_no_board_geometry_calls(self):
        with patch.object(self.board,'GetTracks',side_effect=AssertionError('paint read native tracks')),patch.object(self.board,'GetBoardEdgesBoundingBox',side_effect=AssertionError('paint read native bounds')):
            for scale in (1,2,4):
                self.canvas.zoom=scale;self.canvas.pan=[20*scale,10*scale]
                self.canvas.Refresh();self.canvas.Update();wx.Yield()
            self.canvas.fit();self.canvas.Update();wx.Yield()
            self.canvas.draw_context(Mock(),lambda x,y:(round(x/100000),round(y/100000)),.00001,(-1,-1,31000000,31000000))

    def test_focus_uses_cached_proposal_geometry_without_native_reads(self):
        from types import SimpleNamespace as NS
        before=[(2000000,3000000),(5000000,3010000),(8000000,3000000)]
        after=[before[0],before[-1]]
        self.canvas.set_plan(NS(changes=[NS(before=before,after=after,width=200000)]))
        source_selected=[item.IsSelected() for item in (self.line,self.arc,self.via)]
        with patch.object(self.board,'GetTracks',side_effect=AssertionError('Focus read native geometry')),patch.object(self.board,'GetBoardEdgesBoundingBox',side_effect=AssertionError('Focus read native bounds')):
            self.assertTrue(self.canvas.focus_change(0));self.canvas.Update();wx.Yield()
            self.assertEqual(self.canvas.active_change,0);self.assertIsNotNone(self.canvas.focus_bounds)
            self.assertFalse(self.canvas.focus_change(20))
        self.assertEqual([item.IsSelected() for item in (self.line,self.arc,self.via)],source_selected)
        self.canvas.fit();self.assertIsNone(self.canvas.focus_bounds)

    def test_culling_and_batched_strokes_exclude_offscreen_geometry(self):
        dc=Mock()
        self.canvas.draw_context(dc,lambda x,y:(round(x/100000),round(y/100000)),.00001,(0,0,9000000,5000000))
        dc.DrawLineList.assert_called_once()
        self.assertEqual(dc.DrawLineList.call_args.args[0],[(20,30,80,30)])
        dc.DrawCircle.assert_not_called()

    def test_explicit_refresh_updates_context_without_mutating_board(self):
        initial=self.canvas.context_generation
        self.line.SetEnd(self.point(9,3))
        self.assertEqual(next(row for row in self.canvas.context if row[0]=='line')[2][-1],(8000000,3000000))
        self.canvas.capture_context()
        self.assertEqual(self.canvas.context_generation,initial+1)
        self.assertEqual(next(row for row in self.canvas.context if row[0]=='line')[2][-1],(9000000,3000000))
        self.assertEqual(len(list(self.board.GetTracks())),3)


@unittest.skipIf(wx is None or pcbnew is None,'KiCad native wxPython required')
class ContextLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(pcbnew.ActionPlugin,'register'):
            from trace_refiner_plugin.ui import RefinerFrame
        cls.app=wx.App.Get() or wx.App(False)

    def test_preview_apply_undo_redo_refresh_context_after_real_validation(self):
        import test_native
        from trace_refiner_plugin.ui import RefinerFrame
        fixture=test_native.NativeTests();fixture.setUp()
        self.addCleanup(fixture.tearDown)
        source_bytes=fixture.path.read_bytes()
        frame=RefinerFrame(None,fixture.board)
        def close():
            frame.Destroy();wx.Yield()
        self.addCleanup(close)
        with patch.object(wx,'MessageBox') as messages,patch.object(pcbnew,'Refresh'):
            initial=frame.canvas.context_generation
            original=sorted(frame.canvas.context)
            frame.invalidate()
            self.assertEqual(frame.canvas.context_generation,initial)
            frame.scope.SetSelection(2);frame.on_preview();wx.Yield()
            self.assertEqual(frame.canvas.context_generation,initial+1)
            self.assertTrue(frame.review.changes)
            frame.on_validate();wx.Yield()
            self.assertTrue(frame.apply_button.IsEnabled(),frame.status.GetLabel())
            frame.on_apply()
            self.assertEqual(frame.canvas.context_generation,initial+2)
            self.assertLess(len(frame.canvas.context),len(original))
            frame.undo()
            self.assertEqual(frame.canvas.context_generation,initial+3)
            self.assertEqual(sorted(frame.canvas.context),original)
            frame.redo()
            self.assertEqual(frame.canvas.context_generation,initial+4)
            self.assertLess(len(frame.canvas.context),len(original))
            messages.assert_not_called()
        self.assertEqual(fixture.path.read_bytes(),source_bytes)
        wx.Yield()


if __name__=='__main__':unittest.main()
