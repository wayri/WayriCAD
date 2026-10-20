"""Native resize and independent form-scroll regression."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    import wx,pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
    from quick_pi_plugin.tests.test_workspace_ui import portrait_board
except ImportError:
    wx=None
_app=None

@unittest.skipIf(wx is None,'native KiCad wx runtime required')
class ResizableWorkspaceTests(unittest.TestCase):
    def test_resize_and_scroll(self):
        global _app
        _app=wx.GetApp() or wx.App(False)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"board.kicad_pcb";portrait_board(path)
            with patch.object(QuickPIFrame,"_inspect"):
                frame=QuickPIFrame(None,str(path))
        try:
            frame.Maximize(False);frame.SetSize((1000,740));frame.Show();frame.Layout();_app.Yield()
            for splitter in (frame.workspace_splitter,frame.splitter):
                before=splitter.GetSashPosition();splitter.SetSashPosition(before+25)
                self.assertNotEqual(splitter.GetSashPosition(),before)
                self.assertGreater(splitter.GetWindow1().GetSize().width,0)
                self.assertGreater(splitter.GetWindow2().GetSize().height,0)
            form=frame.inputs
            for child in form.GetChildren():
                if isinstance(child,wx.CollapsiblePane):child.Collapse(False)
            form.Layout();form.FitInside()
            self.assertGreaterEqual(form.GetVirtualSize().height,form.GetClientSize().height)
            if form.GetVirtualSize().height>form.GetClientSize().height:
                form.Scroll(0,9999);self.assertGreater(form.GetViewStart()[1],0)
        finally:
            frame.Destroy();_app.Yield()
