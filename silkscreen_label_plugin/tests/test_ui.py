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
    def tearDown(self):self.frame.Destroy();self.app.ProcessPendingEvents()
    def test_preview_apply_undo_redo(self):
        from silkscreen_label_plugin.placement import fingerprint
        before=fingerprint(self.fixture.board,api)
        self.frame.on_preview();wx.Yield();self.assertTrue(self.frame.apply_button.IsEnabled())
        with patch.object(api,'Refresh'):
            self.frame.on_apply();self.assertEqual(len(self.frame.transactions),1)
            self.frame.undo();self.assertEqual(fingerprint(self.fixture.board,api),before)
            self.frame.redo();self.assertEqual(len(self.frame.transactions),1)
    def test_replaced_board_blocks_apply_and_preview(self):
        self.frame.on_preview();self.open=False
        with patch.object(wx,'MessageBox') as warning:self.frame.on_apply()
        self.assertIn('closed or replaced',warning.call_args.args[0])
        self.assertFalse(self.frame.transactions)
        self.frame.on_preview();self.assertIn('closed or replaced',self.frame.status.GetLabel())
    def test_typography_options_roundtrip_and_validation(self):
        from silkscreen_label_plugin.options_ui import OptionsDialog, PRESETS, RuleDialog
        dialog=OptionsDialog(self.frame,self.frame.settings)
        try:
            dialog.controls['auto_size'].SetValue(True)
            dialog.controls['height'].SetValue('1.2');dialog.controls['min_height'].SetValue('0.8')
            dialog.horizontal.SetValue(False);dialog.vertical.SetValue(True);dialog.direction.SetSelection(1)
            dialog.rules.append(dict(PRESETS[0]));result=dialog.result()
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
