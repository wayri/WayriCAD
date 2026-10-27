"""Actual native shunt editor apply/cancel, units and invalid-row handling."""
import copy
import unittest
try:
    import wx
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'Native wx runtime required')
class ShuntCapacitorUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.GetApp() or wx.App(False)

    def test_modal_apply_rejects_unknown_c_then_returns_entered_rlc(self):
        from signal_integrity_advisor_plugin.shunt_caps_ui import shunt_capacitor_dialog
        frame=wx.Frame(None);errors=[]
        def apply():
            dialog=next(window for window in wx.GetTopLevelWindows() if hasattr(window,'shunt_controls'))
            try:
                dialog.SetSize((560,460));self.app.Yield()
                controls=dialog.shunt_controls;grid=controls['grid']
                grid.SetCellValue(0,1,'C_FILTER')
                button=controls['apply']
                button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,button.GetId()))
                self.assertIn('finite number',controls['error'].GetLabel())
                self.assertTrue(dialog.IsModal())
                for column,value in [(3,'0.1'),(4,'50'),(5,'1')]:grid.SetCellValue(0,column,value)
                button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,button.GetId()))
            except Exception as error:
                errors.append(error);dialog.EndModal(wx.ID_CANCEL)
        wx.CallLater(100,apply)
        try:
            result=shunt_capacitor_dialog(frame,['DATA'])
            if errors:raise errors[0]
            self.assertEqual(len(result['DATA']),1)
            row=result['DATA'][0]
            self.assertEqual((row['id'],row['at']),('C_FILTER','receiver'))
            self.assertAlmostEqual(row['capacitance_F'],1e-10,delta=1e-24)
            self.assertEqual((row['esr_ohm'],row['esl_H']),(.05,1e-9))
        finally:frame.Destroy();self.app.Yield()

    def test_cancel_preserves_existing_capacitors(self):
        from signal_integrity_advisor_plugin.shunt_caps_ui import shunt_capacitor_dialog
        frame=wx.Frame(None)
        initial={'DATA':[dict(id='C1',at='source',capacitance_F=1e-9,esr_ohm=0.,esl_H=0.)]}
        original=copy.deepcopy(initial)
        def cancel():
            dialog=next(window for window in wx.GetTopLevelWindows() if hasattr(window,'shunt_controls'))
            dialog.shunt_controls['grid'].SetCellValue(0,3,'99')
            dialog.EndModal(wx.ID_CANCEL)
        wx.CallLater(80,cancel)
        try:
            self.assertIsNone(shunt_capacitor_dialog(frame,['DATA'],initial))
            self.assertEqual(initial,original)
        finally:frame.Destroy();self.app.Yield()


if __name__=='__main__':unittest.main()
