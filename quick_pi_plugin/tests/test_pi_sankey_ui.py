"""Native power-flow actions retain stale-source checks before opening a report."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx = None

_app = None


@unittest.skipIf(wx is None, 'Native KiCad wx runtime required')
class PowerFlowUITests(unittest.TestCase):
    def test_action_available_after_solve_and_rejects_stale_source(self):
        from quick_pi_plugin.tests.test_workspace_ui import portrait_board, portrait_result
        global _app
        _app = wx.GetApp() or wx.App(False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'power.kicad_pcb'
            portrait_board(path)
            with patch.object(QuickPIFrame, '_inspect'):
                frame = QuickPIFrame(None, str(path))
            try:
                frame.bundle = portrait_result()
                frame.model_dimension.SetSelection(0)
                with patch.object(frame, '_snapshot_current', return_value=True), \
                        patch('quick_pi_plugin.sankey.open_sankey') as opened:
                    frame.on_power_flow()
                    opened.assert_called_once_with(frame.bundle)
                with patch.object(frame, '_snapshot_current', return_value=False), \
                        patch('quick_pi_plugin.sankey.open_sankey') as opened:
                    frame.on_power_flow()
                    opened.assert_not_called()
                    self.assertIn('changed', frame.status.GetLabel())
                self.assertEqual(frame.power_flow.GetLabel(), 'Power flow')
            finally:
                frame.Destroy()
                _app.Yield()
