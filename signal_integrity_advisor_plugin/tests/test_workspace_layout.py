"""Native resize and independent form-scroll regression."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    import wx,pcbnew
    from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
    from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import RoutePreview
except ImportError:
    wx=None
_app=None

@unittest.skipIf(wx is None,'native KiCad wx runtime required')
class ResizableWorkspaceTests(unittest.TestCase):
    def test_resize_and_scroll(self):
        global _app
        _app=wx.GetApp() or wx.App(False)
        frame=wx.Frame(None,size=(1000,740))
        panel=QuickSIPanel(frame,pcbnew.BOARD(),RoutePreview)
        layout=wx.BoxSizer(wx.VERTICAL);layout.Add(panel,1,wx.EXPAND);frame.SetSizer(layout)
        try:
            frame.Maximize(False);frame.SetSize((1000,740));frame.Show();frame.Layout();_app.Yield()
            for splitter in (panel.workspace_splitter,panel.results_splitter):
                before=splitter.GetSashPosition();splitter.SetSashPosition(before+25)
                self.assertNotEqual(splitter.GetSashPosition(),before)
                self.assertGreater(splitter.GetWindow1().GetSize().width,0)
                self.assertGreater(splitter.GetWindow2().GetSize().height,0)
            form=panel.inputs
            for child in form.GetChildren():
                if isinstance(child,wx.CollapsiblePane):child.Collapse(False)
            form.Layout();form.FitInside()
            self.assertGreaterEqual(form.GetVirtualSize().height,form.GetClientSize().height)
            if form.GetVirtualSize().height>form.GetClientSize().height:
                form.Scroll(0,9999);self.assertGreater(form.GetViewStart()[1],0)
        finally:
            frame.Destroy();_app.Yield()
