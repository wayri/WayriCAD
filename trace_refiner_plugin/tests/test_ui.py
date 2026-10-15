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
    def setUpClass(cls):cls.app=wx.App.Get() or wx.App(False)
    def setUp(self):
        self.fixture=test_native.NativeTests();self.fixture.setUp()
        from trace_refiner_plugin.ui import RefinerFrame
        self.open=True;self.frame=RefinerFrame(None,self.fixture.board,lambda:self.open)
        self.warning=patch.object(wx,'MessageBox');self.messages=self.warning.start()
    def tearDown(self):
        self.warning.stop();self.frame.Destroy();wx.Yield();self.fixture.tearDown()
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
    def test_search_preserves_checked_nets_and_board_guard(self):
        self.frame.netlist.Check(0);self.frame.search.SetValue('no match');wx.Yield()
        self.assertIn('SIGNAL',self.frame.checked)
        self.open=False;self.frame.on_preview();self.assertIn('closed or replaced',self.frame.status.GetLabel())


if __name__=='__main__':unittest.main()
