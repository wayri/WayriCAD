"""Native resize and independent form-scroll regression."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    import wx,pcbnew
    from quick_therm_plugin.ui import QuickThermFrame
except ImportError:
    wx=None
_app=None

@unittest.skipIf(wx is None,'native KiCad wx runtime required')
class ResizableWorkspaceTests(unittest.TestCase):
    def test_resize_and_scroll(self):
        global _app
        _app=wx.GetApp() or wx.App(False)
        path=Path(__file__).resolve().parents[1]/"examples/thermal-demo.kicad_pcb"
        with patch.object(QuickThermFrame,"_inspect"):
            frame=QuickThermFrame(None,str(path))
        try:
            frame.Maximize(False);frame.SetSize((1000,740));frame.Show();frame.Layout();_app.Yield()
            frame._toggle_thermal_pane(frame.therm_setup_splitter,frame._therm_input_page,frame.therm_result_splitter,True,340)
            for splitter in (frame.therm_setup_splitter,frame.therm_result_splitter):
                if splitter is frame.therm_result_splitter:
                    frame._toggle_thermal_pane(splitter,frame.therm_visual_host,frame.therm_inspector,True,-340,True)
                before=splitter.GetSashPosition();splitter.SetSashPosition(before+25)
                self.assertNotEqual(splitter.GetSashPosition(),before)
                self.assertGreater(splitter.GetWindow1().GetSize().width,0)
                self.assertGreater(splitter.GetWindow2().GetSize().height,0)
            frame._toggle_thermal_pane(frame.therm_setup_splitter,frame._therm_input_page,frame.therm_result_splitter,True,340)
            form=frame._therm_input_page
            for child in form.GetChildren():
                if isinstance(child,wx.CollapsiblePane):child.Collapse(False)
            form.Layout();form.FitInside()
            self.assertGreaterEqual(form.GetVirtualSize().height,form.GetClientSize().height)
            if form.GetVirtualSize().height>form.GetClientSize().height:
                form.Scroll(0,9999);self.assertGreater(form.GetViewStart()[1],0)
        finally:
            frame.Close();_app.Yield()
