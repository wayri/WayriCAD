"""Native window workflow with independent validation and reversible Apply."""
import unittest
from unittest.mock import patch
import test_native
try:
    import wx
except ImportError:
    wx=None


@unittest.skipIf(wx is None or test_native.api is None,'Native KiCad wxPython required')
class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Standalone native tests have no editor action-plugin registry.
        with patch.object(test_native.api.ActionPlugin,'register'):
            from trace_refiner_plugin.ui import RefinerFrame
        cls.app=wx.App.Get() or wx.App(False)
    def setUp(self):
        self.fixture=test_native.NativeTests();self.fixture.setUp()
        from trace_refiner_plugin.ui import RefinerFrame
        self.open=True;self.frame=RefinerFrame(None,self.fixture.board,lambda:self.open)
        self.warning=patch.object(wx,'MessageBox');self.messages=self.warning.start()
        self.frame.Show();wx.Yield()
    def tearDown(self):
        self.warning.stop();self.frame.Destroy();wx.Yield();self.fixture.tearDown()
    def test_resize_and_drag_review_panes(self):
        self.frame.SetSize((1024,720));self.frame.Show();wx.Yield()
        for splitter in (self.frame.settings_splitter,self.frame.results_splitter):
            before=splitter.GetWindow1().GetSize()
            splitter.SetSashPosition(splitter.GetSashPosition()-35);wx.Yield()
            self.assertNotEqual(before,splitter.GetWindow1().GetSize())
        self.assertGreater(self.frame.details.GetClientSize().height,100)
        self.frame.details.SetFocus();self.assertIs(wx.Window.FindFocus(),self.frame.details)

    def test_preview_validation_apply_undo(self):
        from trace_refiner_plugin.refiner import snapshot
        before=snapshot(self.fixture.board,test_native.api)
        self.frame.scope.SetSelection(2);self.frame.on_preview();wx.Yield()
        self.assertTrue(self.frame.review.changes);self.assertFalse(self.frame.apply_button.IsEnabled())
        self.frame.on_validate();wx.Yield();self.assertTrue(self.frame.apply_button.IsEnabled(),self.frame.status.GetLabel())
        with patch.object(test_native.api,'Refresh'):
            self.frame.on_apply();self.assertEqual(len(self.frame.transactions),1)
            self.frame.undo();self.assertEqual(snapshot(self.fixture.board,test_native.api),before)
        self.messages.assert_not_called()
    def test_contact_centering_tab_preview_validation_apply_undo(self):
        from trace_refiner_plugin.refiner import snapshot
        api=test_native.api
        self.fixture.tracks[0].SetStart(self.fixture.v(1.1,2))
        before=snapshot(self.fixture.board,api)
        self.frame.operation.SetSelection(1);wx.Yield()
        self.assertTrue(self.frame.center_shift.IsEnabled())
        self.assertFalse(self.frame.deviation.IsEnabled())
        self.frame.scope.SetSelection(2);self.frame.on_preview();wx.Yield()
        self.assertEqual(self.frame.review.settings['mode'],'center contacts')
        self.assertEqual(len(self.frame.review.changes),1)
        self.assertEqual(tuple(self.frame.review.changes[0].after[0]),(api.FromMM(1),api.FromMM(2)))
        self.assertIn('contact repairs',self.frame.status.GetLabel())
        self.assertFalse(self.frame.apply_button.IsEnabled())
        self.frame.on_validate();wx.Yield()
        self.assertTrue(self.frame.apply_button.IsEnabled(),self.frame.status.GetLabel())
        with patch.object(api,'Refresh'):
            self.frame.on_apply();self.assertEqual(len(self.frame.transactions),1)
            self.frame.undo();self.assertEqual(snapshot(self.fixture.board,api),before)
        self.frame.operation.SetSelection(0);wx.Yield()
        self.assertIsNone(self.frame.review)
        self.assertFalse(self.frame.center_shift.IsEnabled())
        self.messages.assert_not_called()

    def test_comparison_view_switch_keeps_validated_proposal_and_source(self):
        from trace_refiner_plugin.refiner import snapshot
        api=test_native.api
        self.frame.scope.SetSelection(2);self.frame.on_preview();self.frame.on_validate();wx.Yield()
        self.assertTrue(self.frame.review.validated,self.frame.status.GetLabel())
        review=self.frame.review;before=snapshot(self.fixture.board,api)
        for mode in self.frame.canvas.DISPLAY_MODES:
            self.frame.view_mode.SetStringSelection(mode)
            event=wx.CommandEvent(wx.wxEVT_CHOICE,self.frame.view_mode.GetId())
            event.SetEventObject(self.frame.view_mode);self.frame.view_mode.GetEventHandler().ProcessEvent(event)
            self.assertEqual(self.frame.canvas.display_mode,mode)
            self.assertIs(self.frame.review,review);self.assertTrue(review.validated)
            self.assertTrue(self.frame.apply_button.IsEnabled())
        self.assertEqual(snapshot(self.fixture.board,api),before)
        self.messages.assert_not_called()
    def test_review_metrics_focus_subset_requires_native_revalidation(self):
        from trace_refiner_plugin.refiner import snapshot
        api=test_native.api
        points=[(x,y+1.5) for x,y in self.fixture.points]
        second_net=api.NETINFO_ITEM(self.fixture.board,'SIGNAL_OTHER',2);self.fixture.board.Add(second_net)
        for a,b in zip(points,points[1:]):self.fixture.track(a,b).SetNet(second_net)
        for index,position in enumerate((points[0],points[-1]),3):
            fp=api.FOOTPRINT(self.fixture.board);fp.SetReference('J'+str(index));fp.SetPosition(self.fixture.v(*position));self.fixture.board.Add(fp)
            pad=api.PAD(fp);pad.SetPosition(self.fixture.v(*position));pad.SetSize(self.fixture.v(.6,.6));pad.SetShape(api.PAD_SHAPE_RECT);pad.SetAttribute(api.PAD_ATTRIB_SMD);pad.SetLayerSet(pad.SMDMask());pad.SetNumber('1');pad.SetNet(second_net);fp.Add(pad)
        self.frame.Show();self.frame.scope.SetSelection(2);self.frame.on_preview();wx.Yield()
        self.assertEqual(len(self.frame.review.changes),2)
        self.assertGreater(float(self.frame.details.GetItemText(0,2)),float(self.frame.details.GetItemText(0,3)))
        self.assertGreater(float(self.frame.details.GetItemText(0,4)),0)
        self.assertIn('5 → 1',self.frame.details.GetItemText(0,5))
        self.frame.on_validate();wx.Yield();self.assertTrue(self.frame.review.validated,self.frame.status.GetLabel())
        before=snapshot(self.fixture.board,api)
        event=wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED);event.SetIndex(0)
        self.frame.details.SetItemState(0,wx.LIST_STATE_SELECTED,wx.LIST_STATE_SELECTED);self.frame._review_selected(event);wx.Yield()
        self.assertEqual(self.frame.canvas.active_change,0);self.assertIsNotNone(self.frame.canvas.focus_bounds)
        self.assertEqual(snapshot(self.fixture.board,api),before,'Table focus changed native source or selection')
        self.frame.review.skipped.append(('PRESERVED_NOTICE','A protected chain remains untouched.'))
        self.frame.exclude_selected();wx.Yield()
        self.assertEqual(len(self.frame.review.changes),1);self.assertFalse(self.frame.review.validated)
        self.assertFalse(self.frame.review.evidence);self.assertFalse(self.frame.apply_button.IsEnabled())
        self.assertTrue(self.frame.validate_button.IsEnabled());self.assertIn('Validate this subset again',self.frame.status.GetLabel())
        notices=[self.frame.details.GetItemText(row,6) for row in range(self.frame.details.GetItemCount())]
        self.assertIn('A protected chain remains untouched.',notices);self.assertIn('Excluded by review; original copper retained.',notices)
        self.assertEqual(snapshot(self.fixture.board,api),before,'Exclusion modified native copper')
        self.frame.on_validate();wx.Yield();self.assertTrue(self.frame.review.validated,self.frame.status.GetLabel())
        self.assertTrue(self.frame.apply_button.IsEnabled())
        self.messages.assert_not_called()

    def test_multiselect_excludes_proposals_not_preserved_rows(self):
        self.frame.scope.SetSelection(2);self.frame.on_preview();wx.Yield()
        self.frame.review.skipped.append(('FULL/LONG/PROTECTED/NET','Protected notice'))
        self.frame._populate_review()
        for row in range(self.frame.details.GetItemCount()):self.frame.details.SetItemState(row,wx.LIST_STATE_SELECTED,wx.LIST_STATE_SELECTED)
        self.frame.exclude_selected();wx.Yield()
        self.assertFalse(self.frame.review.changes);self.assertFalse(self.frame.validate_button.IsEnabled());self.assertFalse(self.frame.apply_button.IsEnabled())
        self.assertIn(('FULL/LONG/PROTECTED/NET','Protected notice'),self.frame.review.skipped)
        self.assertEqual(len(self.frame._excluded_notices),1)
        self.messages.assert_not_called()

    def test_search_preserves_checked_nets_and_board_guard(self):
        self.frame.netlist.Check(0);self.frame.search.SetValue('no match');wx.Yield()
        self.assertIn('SIGNAL',self.frame.checked)
        self.open=False;self.frame.on_preview();self.assertIn('closed or replaced',self.frame.status.GetLabel())

    def test_native_action_dispatch_and_replacement_guard(self):
        from trace_refiner_plugin.action import TraceRefinerAction
        action=TraceRefinerAction();current=[self.fixture.board]
        with patch.object(test_native.api,'GetBoard',side_effect=lambda:current[0]),patch.object(wx,'GetActiveWindow',return_value=None):
            action.Run();wx.Yield()
            try:
                self.assertTrue(action._frame.guard())
                current[0]=test_native.api.BOARD()
                self.assertFalse(action._frame.guard())
            finally:action._frame.Destroy();wx.Yield()
        self.messages.assert_not_called()


if __name__=='__main__':unittest.main()
