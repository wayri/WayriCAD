"""Simple native flow and originating-board replacement guard."""
import unittest
from unittest.mock import patch
import test_placement as fixture
api=fixture.api
try:
    import wx
except ImportError:
    wx=None
@unittest.skipIf(wx is None or api is None,'Native KiCad wxPython required')
class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.App.Get() or wx.App(False)
    def setUp(self):
        with patch.object(api.ActionPlugin,'register'):
            from silkscreen_label_plugin.ui import SilkscreenFrame
        self.fixture=fixture.PlacementTests();self.fixture.setUp()
        self.open=True
        self.frame=SilkscreenFrame(None,self.fixture.board,board_guard=lambda:self.open)
    def tearDown(self):self.frame.Destroy();wx.Yield()
    def test_review_expands_into_resizable_split_and_options_resize(self):
        from silkscreen_label_plugin.options_ui import OptionsDialog
        self.frame.SetSize((1024,720));self.frame.Show();wx.Yield()
        self.frame.details.Expand();self.frame.toggle_details(None);wx.Yield()
        self.assertTrue(self.frame.review_splitter.IsSplit())
        split=self.frame.review_splitter;before=self.frame.list.GetSize()
        split.SetSashPosition(split.GetSashPosition()-40);wx.Yield()
        self.assertGreater(self.frame.list.GetSize().height,before.height)
        self.frame.details.Collapse();self.frame.toggle_details(None);wx.Yield()
        self.assertFalse(split.IsSplit())
        dialog=OptionsDialog(self.frame,self.frame.settings)
        try:
            dialog.SetSize((560,470));dialog.Show();wx.Yield()
            self.assertTrue(dialog.GetWindowStyle()&wx.RESIZE_BORDER)
            self.assertGreater(dialog.controls['testpoint_pattern'].GetSize().height,15)
        finally:dialog.Destroy();wx.Yield()

    def test_preview_apply_undo_redo(self):
        from silkscreen_label_plugin.placement import fingerprint
        before=fingerprint(self.fixture.board,api)
        self.frame.on_preview();wx.Yield();self.assertTrue(self.frame.apply_button.IsEnabled())
        with patch.object(api,'Refresh'):
            self.frame.on_apply();self.assertEqual(len(self.frame.transactions),1)
            self.frame.undo();self.assertEqual(fingerprint(self.fixture.board,api),before)
            self.frame.redo();self.assertEqual(len(self.frame.transactions),1)

    def test_references_only_overrides_custom_categories(self):
        self.frame.settings.update(references=False,values=True,board_text=True)
        settings=self.frame.current_settings()
        self.assertTrue(settings['references'])
        self.assertFalse(settings['values']);self.assertFalse(settings['board_text'])
        self.frame.text_scope.SetSelection(1)
        self.assertTrue(self.frame.current_settings()['board_text'])
        self.frame.SetSize((850,600));self.frame.Show();wx.Yield()
        self.assertLessEqual(self.frame.text_scope.GetRect().GetRight(),self.frame.text_scope.GetParent().GetClientSize().width)

    def test_partial_apply_retains_unresolved_review_and_red_originals(self):
        fp=api.FOOTPRINT(self.fixture.board);fp.SetReference('R99')
        fp.SetPosition(self.fixture.v(100,100));self.fixture.board.Add(fp)
        fp.Reference().SetLayer(api.F_SilkS);fp.Reference().SetVisible(True)
        fp.Reference().SetPosition(self.fixture.v(100,100))
        self.frame.on_preview()
        self.assertEqual(len(self.frame.preview.rejected),1)
        self.assertEqual(self.frame.preview.stats['placed'],1)
        reviewed=self.frame.preview
        with patch.object(api,'Refresh'):self.frame.on_apply()
        self.assertIsNone(self.frame.preview)
        self.assertIs(self.frame.canvas.preview,reviewed)
        self.assertIn('1 unresolved',self.frame.status.GetLabel())
        self.assertIn(str(fp.Reference().m_Uuid.AsString()),reviewed.unresolved_ids)
        self.assertFalse(self.frame.apply_button.IsEnabled())
    def test_replaced_board_blocks_apply_and_preview(self):
        self.frame.on_preview();self.open=False
        with patch.object(wx,'MessageBox') as warning:self.frame.on_apply()
        self.assertIn('closed or replaced',warning.call_args.args[0])
        self.assertFalse(self.frame.transactions)
        self.frame.on_preview();self.assertIn('closed or replaced',self.frame.status.GetLabel())
    def test_reopening_preserves_existing_net_label_mode(self):
        from silkscreen_label_plugin.placement import plan,apply
        from silkscreen_label_plugin.ui import SilkscreenFrame
        case=self.fixture;case.fp.SetReference('TP1')
        net=api.NETINFO_ITEM(case.board,'SENSE');case.board.Add(net);case.pad.SetNet(net)
        apply(case.board,api,plan(case.board,api,dict(testpoint_net_names=True)))
        other=SilkscreenFrame(None,case.board)
        try:
            self.assertTrue(other.settings['testpoint_net_names'])
            self.assertEqual(other.settings['testpoint_pattern'],'TP1')
            review=plan(case.board,api,other.current_settings())
            self.assertTrue(all(c.annotation is None or not c.annotation.remove for c in review.changes))
            self.assertFalse(case.fp.Reference().IsVisible())
        finally:other.Destroy();wx.Yield()

    def test_angle_controls_accept_custom_values_and_scroll(self):
        from silkscreen_label_plugin.options_ui import OptionsDialog
        dialog=OptionsDialog(self.frame,self.frame.settings)
        try:
            dialog.Show();dialog.Layout();wx.Yield()
            dialog.other_angles.SetValue('17, 22.5')
            result=dialog.result()
            self.assertIn(45,result['allowed_rotations'])
            self.assertIn(17,result['allowed_rotations'])
            self.assertIn(22.5,result['allowed_rotations'])
            page=dialog.other_angles.GetParent()
            self.assertIsInstance(page,wx.ScrolledWindow)
            page.FitInside()
            self.assertGreaterEqual(page.GetVirtualSize().height,page.GetSizer().GetMinSize().height)
            dialog.other_angles.SetValue('nan')
            with self.assertRaisesRegex(ValueError,'finite'):dialog.result()
        finally:dialog.Destroy()

    def test_typography_options_roundtrip_and_validation(self):
        from silkscreen_label_plugin.options_ui import OptionsDialog, PRESETS, RuleDialog
        dialog=OptionsDialog(self.frame,self.frame.settings)
        try:
            dialog.controls['auto_size'].SetValue(True)
            dialog.controls['testpoint_net_names'].SetValue(True)
            dialog.controls['testpoint_pattern'].SetValue('TP*')
            dialog.controls['height'].SetValue('1.2');dialog.controls['min_height'].SetValue('0.8')
            dialog.horizontal.SetValue(False);dialog.vertical.SetValue(True);dialog.diagonal.SetValue(False);dialog.other_angles.SetValue('');dialog.direction.SetSelection(1)
            dialog.rules.append(dict(PRESETS[0]));result=dialog.result()
            self.assertTrue(result['testpoint_net_names']);self.assertEqual(result['testpoint_pattern'],'TP*')
            self.assertEqual(result['allowed_rotations'],(90,));self.assertEqual(result['reading_direction'],'Top/left')
            self.assertEqual(result['min_height'],.8);self.assertTrue(result['formatting_rules'][0]['knockout'])
            self.assertFalse(self.frame.settings['formatting_rules'])
            dialog.vertical.SetValue(False)
            with self.assertRaisesRegex(ValueError,'orientation'):dialog.result()
        finally:dialog.Destroy()
        editor=RuleDialog(self.frame,PRESETS[1])
        try:
            rule=editor.result();self.assertTrue(rule['bold']);self.assertNotIn('italic',rule)
            editor.controls['italic'].SetSelection(2);self.assertFalse(editor.result()['italic'])
        finally:editor.Destroy()
if __name__=='__main__':unittest.main()
