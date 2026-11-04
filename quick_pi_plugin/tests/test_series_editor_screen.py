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
    def test_inferred_route_dialog_accepts_values_and_retains_parallel_pin_groups(self):
        global _APP,_LOG,_PREVIOUS_LOG
        _APP=wx.GetApp() or wx.App(False)
        if _LOG is None:
            _LOG=wx.LogStderr();_PREVIOUS_LOG=wx.Log.SetActiveTarget(_LOG)
        from quick_pi_plugin.series_inference import choose_inferred_path
        from quick_pi_plugin.tests.series_inference_fixture import inventory
        from quick_pi_plugin.series_editor import parse_saved_path
        parent=wx.Frame(None);created=[];errors=[]
        constructor=wx.Dialog
        def create(*args,**kwargs):
            dialog=constructor(*args,**kwargs);created.append(dialog)
            return dialog
        def enter_values():
            dialog=created[0]
            try:
                def children(window):
                    for child in window.GetChildren():
                        yield child
                        yield from children(child)
                controls=list(children(dialog))
                fields=[c for c in controls if isinstance(c,wx.TextCtrl)]
                self.assertEqual(len(fields),4)
                self.assertTrue(all(c.GetValue()=='' for c in fields))
                for field,value in zip(fields,('100m','200m','100m','200m')):field.SetValue(value)
                button=wx.FindWindowByLabel('Use reviewed path',dialog)
                self.assertIsInstance(button.GetParent(),wx.Panel)
                area=next(c for c in controls if isinstance(c,wx.ScrolledWindow))
                self.assertGreater(area.GetVirtualSize().height,area.GetClientSize().height)
                area.Scroll(0,1000)
                self.assertGreater(area.GetViewStart()[1],0)
                position=area.ScreenToClient(button.ClientToScreen((0,0)))
                self.assertGreaterEqual(position.y,0)
                self.assertLessEqual(position.y+button.GetSize().height,area.GetClientSize().height)
                button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,button.GetId()))
            except BaseException as exc:
                errors.append(exc);dialog.EndModal(wx.ID_CANCEL)
        timer=wx.CallLater(100,enter_values)
        try:
            with patch('wx.Dialog',side_effect=create),patch('wx.Display') as display:
                display.GetFromWindow.return_value=0
                display.return_value.GetClientArea.return_value=wx.Rect(0,0,1200,700)
                data=choose_inferred_path(parent,inventory(),'J1.1','J2.1')
            if errors:raise errors[0]
            parsed=parse_saved_path(data,inventory())
            self.assertEqual(len(parsed['series']),2)
            self.assertTrue(all(len(s['parallel'])==1 for s in parsed['series']))
            self.assertEqual(parsed['series'][0]['parallel'][0]['from_pads'],['Q2-1','Q2-2'])
        finally:
            timer.Stop();parent.Destroy();_APP.Yield()

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
