"""Native automatic/manual sizing controls remain explicit and readable."""
from pathlib import Path
import gc
import tempfile
import unittest
from unittest.mock import patch
try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx=None
_app=None


@unittest.skipIf(wx is None,'Native KiCad wx runtime required')
class AutomaticMeshUITests(unittest.TestCase):
    def test_default_automatic_manual_override_and_3d_switch(self):
        from quick_pi_plugin.tests.test_workspace_ui import portrait_board
        global _app
        _app=wx.GetApp() or wx.App(False)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'board.kicad_pcb';portrait_board(path)
            with patch.object(QuickPIFrame,'_inspect'):
                frame=QuickPIFrame(None,str(path))
            try:
                frame._buttons()
                self.assertTrue(frame.auto_mesh.GetValue());self.assertFalse(frame.edge.IsEnabled())
                self.assertEqual(frame._request('mesh',False)['mesh_sizing'],'auto')
                frame.auto_mesh.SetValue(False);frame._buttons();frame.edge.SetValue('.17')
                self.assertTrue(frame.edge.IsEnabled())
                self.assertEqual(frame._request('mesh',False)['edge_mm'],.17)
                self.assertNotIn('mesh_sizing',frame._request('mesh',False))
                frame.auto_mesh.SetValue(True);frame.model_dimension.SetSelection(1)
                frame._model_changed()
                self.assertFalse(frame.auto_mesh.GetValue());self.assertFalse(frame.auto_mesh.IsEnabled())
                self.assertTrue(frame.edge.IsEnabled());self.assertEqual(frame.edge.GetValue(),'.17')
            finally:
                # Exercise the real close path: it stops the polling timer before
                # deferred window/canvas deletion. Collect wrappers while wx's
                # art providers are still alive rather than destroying the App.
                frame._end();_app.Yield()
                del frame
                gc.collect();_app.Yield()
