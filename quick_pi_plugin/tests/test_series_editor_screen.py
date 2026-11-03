"""Native series actions remain reachable on a small/high-DPI work area."""
import unittest
from unittest.mock import patch
try:
    import wx
except ImportError:
    wx=None
_APP=None
_LOG=None
_PREVIOUS_LOG=None

@unittest.skipIf(wx is None,'Native wx runtime required')
class SeriesScreenTests(unittest.TestCase):
    def test_small_work_area_keeps_footer_visible_and_content_scrollable(self):
        global _APP,_LOG,_PREVIOUS_LOG
        _APP=wx.GetApp() or wx.App(False)
        if _LOG is None:
            _LOG=wx.LogStderr();_PREVIOUS_LOG=wx.Log.SetActiveTarget(_LOG)
        from quick_pi_plugin.series_editor import SeriesPathDialog
        from quick_pi_plugin.tests.test_series_editor import INVENTORY
        parent=wx.Frame(None)
        work=wx.Rect(0,0,1200,700)
        try:
            with patch('wx.Display') as display:
                display.GetFromWindow.return_value=0
                display.return_value.GetClientArea.return_value=work
                editor=SeriesPathDialog(parent,INVENTORY,'Example.kicad_pcb')
            try:
                editor.dialog.Layout();editor.body.FitInside()
                rect=editor.dialog.GetRect()
                self.assertTrue(work.Contains(rect))
                for label in ('Load path…','Save path…','Run this path','Cancel'):
                    button=wx.FindWindowByLabel(label,editor.dialog)
                    self.assertIsNotNone(button)
                    self.assertIs(button.GetParent(),editor.dialog)
                    self.assertLessEqual(button.GetRect().bottom,editor.dialog.GetClientSize().height)
                    self.assertLessEqual(button.GetRect().right,editor.dialog.GetClientSize().width)
                self.assertGreater(editor.body.GetVirtualSize().height,editor.body.GetClientSize().height)
                editor.body.Scroll(0,1000)
                self.assertGreater(editor.body.GetViewStart()[1],0)
            finally:editor.dialog.Destroy()
        finally:parent.Destroy();_APP.Yield()

if __name__=='__main__':unittest.main()
