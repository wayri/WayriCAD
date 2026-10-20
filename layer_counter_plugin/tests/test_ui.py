"""Native windows use the real copper generator and guarded board context."""
import unittest
from unittest.mock import patch
try:
    import pcbnew as api
    import wx
except ImportError:
    api=None
from layer_counter_plugin import core


@unittest.skipIf(api is None,'Native KiCad/wx required')
class UITests(unittest.TestCase):
    def setUp(self):
        from layer_counter_plugin.ui import LayerCounterFrame
        self.app=wx.GetApp() or wx.App(False)
        self.board=api.BOARD();self.board.SetCopperLayerCount(4)
        self.frame=LayerCounterFrame(None,self.board)
        self.frame.Show();wx.Yield()
        self.messages=[];self.frame.error=self.messages.append

    def tearDown(self):
        self.frame.Destroy();wx.Yield()

    def test_help_event_opens_resizable_offline_guide(self):
        with patch.object(wx.Dialog,'ShowModal',return_value=wx.ID_OK) as modal:
            event=wx.HelpEvent(wx.EVT_HELP.typeId,self.frame.GetId())
            self.assertTrue(self.frame.GetEventHandler().ProcessEvent(event))
            modal.assert_called_once()

    def test_settings_can_resize_and_scroll_at_laptop_size(self):
        self.frame.SetSize((1024,720));wx.Yield()
        split=self.frame.settings_splitter;before=split.GetWindow1().GetSize()
        split.SetSashPosition(400);wx.Yield()
        self.assertNotEqual(before,split.GetWindow1().GetSize())
        self.assertGreater(self.frame.canvas.GetClientSize().width,280)
        split.GetWindow1().FitInside();split.GetWindow1().Scroll(0,200);wx.Yield()
        self.frame.pairs.SetFocus();self.assertIs(wx.Window.FindFocus(),self.frame.pairs)

    def test_preview_insert_undo_redo_and_settings_invalidation(self):
        before=core.fingerprint(self.board,api)
        self.frame.make_preview();wx.Yield()
        self.assertEqual(before,core.fingerprint(self.board,api))
        self.assertEqual(len(self.frame.canvas.glyphs),4)
        with patch.object(api,'Refresh'):
            self.frame.add();self.assertEqual(len(list(self.board.Groups())),1)
            self.frame.history(False);self.assertEqual(before,core.fingerprint(self.board,api))
            self.frame.history(True);self.assertEqual(len(list(self.board.Groups())),1)
        self.frame.make_preview();self.frame.fields['pitch'].SetValue('6');wx.Yield()
        self.assertIsNone(self.frame.preview);self.assertFalse(self.frame.add_button.IsEnabled())
        self.assertFalse(self.messages)

    def test_originating_board_guard_and_stale_insert(self):
        before=core.fingerprint(self.board,api)
        self.frame.board_guard=lambda:False
        self.frame.make_preview();self.assertIsNone(self.frame.preview)
        self.assertTrue(self.messages);self.assertEqual(before,core.fingerprint(self.board,api))
        self.messages.clear();self.frame.board_guard=lambda:True
        self.frame.make_preview();extra=api.PCB_TEXT(self.board);extra.SetText('changed');self.board.Add(extra)
        changed=core.fingerprint(self.board,api);self.frame.add()
        self.assertTrue(self.messages);self.assertEqual(changed,core.fingerprint(self.board,api))
        self.assertFalse(list(self.board.Groups()))

    def test_action_dispatch_uses_native_board_identity_and_replacement_guard(self):
        from layer_counter_plugin.action import LayerCounterAction
        action=LayerCounterAction()
        current=[self.board]
        with patch.object(api,'GetBoard',side_effect=lambda:current[0]),patch.object(wx,'GetActiveWindow',return_value=None):
            action.Run();wx.Yield()
            try:
                self.assertTrue(action._frame.board_guard())
                self.assertEqual(core._board_identity(self.board),core._board_identity(self.board.this))
                current[0]=api.BOARD()
                self.assertFalse(action._frame.board_guard())
            finally:action._frame.Destroy();wx.Yield()

    def test_core_mirroring_and_single_layer_view(self):
        self.frame.style.SetSelection(self.frame.styles.index('core-mirrored'))
        self.frame.make_preview();wx.Yield()
        self.assertFalse(self.messages)
        self.assertEqual([r['mirror'] for r in self.frame.preview.labels],[False,True,False,True])
        self.frame.view_layer.SetSelection(4)
        event=wx.CommandEvent(wx.EVT_CHOICE.typeId,self.frame.view_layer.GetId())
        self.frame.view_layer.GetEventHandler().ProcessEvent(event);wx.Yield()
        self.assertEqual(self.frame.canvas.layer,api.B_Cu)
        self.frame.canvas.Refresh();self.frame.canvas.Update();wx.Yield()
        self.assertTrue(self.frame.canvas.glyphs)


if __name__=='__main__':unittest.main()
