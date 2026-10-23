"""Native fanout preview/apply/undo and local-review UI guard checks."""
import unittest
from test_fanout_live_ui import wait_preview
from unittest.mock import patch
import test_connector_escape as fixture
try:
    import wx
except ImportError:
    wx=None

@unittest.skipIf(wx is None or fixture.p is None,'KiCad wxPython required')
class ConnectorUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.App.Get() or wx.App(False)
    def setUp(self):
        with patch.object(fixture.p.ActionPlugin,'register'):
            from fanout_generator_plugin.fanout_generator_plugin import FanoutFrame
        self.fixture=fixture.ConnectorTests();self.fixture.setUp();self.fixture.connector()
        self.frame=FanoutFrame(None,self.fixture.board)
        self.frame.scope.SetValue('Reference wildcard');self.frame.ref.ChangeValue('J1')
        self.frame.pattern.SetValue('Connector edge');self.frame.add_vias.SetValue(False)
        self.frame._update_controls()
        self.frame.Show()
    def tearDown(self):
        self.frame.selection_timer.Stop();self.frame.Destroy();self.app.ProcessPendingEvents()
    def test_native_apply_and_undo(self):
        with patch.object(fixture.p,'Refresh'):
            self.frame.preview(None,silent=True);wait_preview(self.frame)
            self.assertEqual(len(self.frame.preview_plan),6)
            self.assertTrue(self.frame.commit_button.IsEnabled())
            self.assertFalse(self.frame.export_button.IsEnabled())
            self.frame.generate(None);self.assertEqual(len(list(self.fixture.board.GetTracks())),12)
            self.frame.undo(None);self.assertFalse(list(self.fixture.board.GetTracks()))
            self.frame.redo(None);self.assertEqual(len(list(self.fixture.board.GetTracks())),12)
    def test_local_rules_disable_live_apply(self):
        self.fixture.board.GetDesignSettings().m_MinClearance=fixture.p.FromMM(.1)
        self.frame.connector_clearance.ChangeValue('.15')
        self.frame.preview(None,silent=True);wait_preview(self.frame)
        self.assertEqual(len(self.frame.preview_plan),6)
        self.assertFalse(self.frame.commit_button.IsEnabled())
        self.assertTrue(self.frame.export_button.IsEnabled())
        with patch.object(wx,'MessageBox') as error:
            self.frame.generate(None)
        self.assertIn('Export review',error.call_args.args[0])
        self.assertFalse(list(self.fixture.board.GetTracks()))
if __name__=='__main__':unittest.main()
