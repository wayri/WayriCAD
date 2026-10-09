"""Native field control defaults and zoom-preserving event delivery."""
import unittest
from unittest.mock import patch

try:
    import wx
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx=None


@unittest.skipIf(wx is None,'native wx runtime required')
class FieldStyleControlTests(unittest.TestCase):
    def test_native_control_defaults_to_gradient_and_preserves_zoom_on_change(self):
        app=wx.GetApp() or wx.App(False)
        # Build the real inspector without starting board or worker lifecycles.
        frame=QuickPIFrame.__new__(QuickPIFrame)
        wx.Frame.__init__(frame,None,title='Synthetic field control test')
        frame.splitter=wx.SplitterWindow(frame)
        try:
            with patch.object(QuickPIFrame,'_draw') as draw:
                frame._build_inspector()
                self.assertEqual(frame.field_style.GetStringSelection(),'Smooth gradient')
                self.assertIn('Probes and peaks retain solver cell values',frame.field_style.GetToolTipText())
                frame.field_style.SetSelection(1)
                event=wx.CommandEvent(wx.EVT_CHOICE.typeId,frame.field_style.GetId())
                event.SetEventObject(frame.field_style)
                frame.field_style.GetEventHandler().ProcessEvent(event)
                draw.assert_called_once_with(preserve=True)
                self.assertEqual(frame.field_style.GetStringSelection(),'Solver cells')
        finally:
            frame.Destroy();app.Yield()


if __name__=='__main__':unittest.main()
