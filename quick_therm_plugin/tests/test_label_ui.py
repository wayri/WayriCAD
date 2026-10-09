"""Actual native motion/leave events and selected labels in QuickTherm."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import wx
    import pcbnew
    from quick_therm_plugin.ui import QuickThermFrame
except ImportError:
    wx=None


@unittest.skipIf(wx is None,'native KiCad wx runtime required')
class ThermalLabelUITests(unittest.TestCase):
    def test_native_hover_leave_and_paired_workspace(self):
        from matplotlib.backend_bases import MouseEvent
        from quick_therm_plugin.tests.test_component_labels import dense_view,component_labels
        from quick_therm_plugin.plot_canvas import FigureCanvasWxAgg
        from matplotlib.figure import Figure
        app=wx.GetApp() or wx.App(False)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'thermal-label-demo.kicad_pcb';pcbnew.SaveBoard(str(path),pcbnew.BOARD())
            original=hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.object(QuickThermFrame,'_inspect'):
                frame=QuickThermFrame(None,str(path))
                try:
                    view=dense_view(256)
                    frame.thermal_bundle={'board_thermal_view':view,'source_sha256':original}
                    frame._thermal_rows=[(item,{}) for item in view['components']]
                    frame._thermal_selected='0';frame.therm_mode.SetStringSelection('Top-side map')
                    frame._draw_thermal();frame.Show();app.Yield();canvas=frame.therm_canvas;canvas.draw()
                    ax=frame.therm_figure.axes[0];self.assertEqual(len(component_labels(ax)),1)
                    target=view['components'][1];px,py=ax.transData.transform(target['position_mm'])
                    event=MouseEvent('motion_notify_event',canvas,px,py)
                    canvas.callbacks.process('motion_notify_event',event);app.Yield();canvas.draw()
                    self.assertEqual(len(component_labels(ax)),2)
                    self.assertIn('U2',ax._thermal_hover_label.get_text())
                    limits=(ax.get_xlim(),ax.get_ylim())
                    leave=wx.MouseEvent(wx.wxEVT_LEAVE_WINDOW);canvas.GetEventHandler().ProcessEvent(leave);app.Yield()
                    self.assertEqual(len(component_labels(ax)),1);self.assertEqual((ax.get_xlim(),ax.get_ylim()),limits)
                    # Exercise the paired dialog's actual registered hover and leave callbacks.
                    def paired(dialog):
                        dialog.Show();app.Yield()
                        def children(window):
                            for child in window.GetChildren():
                                yield child;yield from children(child)
                        canvases=[child for child in children(dialog) if isinstance(child,FigureCanvasWxAgg)]
                        self.assertEqual(len(canvases),2)
                        top=canvases[0];top.draw();axes=top.figure.axes[0]
                        x,y=axes.transData.transform(target['position_mm'])
                        top.callbacks.process('motion_notify_event',MouseEvent('motion_notify_event',top,x,y));app.Yield()
                        self.assertEqual(len(component_labels(axes)),2)
                        top.GetEventHandler().ProcessEvent(wx.MouseEvent(wx.wxEVT_LEAVE_WINDOW));app.Yield()
                        self.assertEqual(len(component_labels(axes)),1);dialog.Hide();return wx.ID_CLOSE
                    with patch.object(wx.Dialog,'ShowModal',paired):frame.on_expand_thermal()
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),original)
                    capture=os.environ.get('WAYRICAD_THERM_LABEL_CAPTURE')
                    if capture:
                        frame.therm_figure.savefig(capture,dpi=140)
                finally:
                    frame.Destroy();app.Yield()


if __name__=='__main__':unittest.main()
