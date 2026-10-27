"""Native modal setup cancellation, atomic apply and explicit endpoint review."""
import unittest
from unittest.mock import patch
try:
    import wx, pcbnew
except ImportError:
    wx=None
from signal_integrity_advisor_plugin.tests.test_setup_guide import VALUES

@unittest.skipIf(wx is None,'KiCad native wx runtime required')
class NativeSetupGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.GetApp() or wx.App(False)

    def test_modal_apply_keeps_peers_separate_and_reviewed_units(self):
        from signal_integrity_advisor_plugin.setup_guide import setup_dialog
        frame=wx.Frame(None)
        def apply():
            dialog=next(w for w in wx.GetTopLevelWindows() if hasattr(w,'setup_controls'))
            c=dialog.setup_controls
            self.assertIn('U1.2',c['peers'].GetLabel())
            c['values']['z0_ohm'].SetValue('55');c['eye'].SetValue(True)
            button=c['run'];button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,button.GetId()))
        wx.CallLater(80,apply)
        try:
            rows=[dict(label=p,net='DATA',footprint_uuid=owner) for p,owner in [('U1.1','a'),('U1.2','a'),('J1.1','b')]]
            result=setup_dialog(frame,{'DATA':['U1.1','U1.2','J1.1']},rows,
                                dict(net='DATA',start='U1.1',end='J1.1'),VALUES,False,['GND'])
            self.assertTrue(result['run']);self.assertTrue(result['eye_enabled'])
            self.assertEqual(result['values']['z0_ohm'],'55');self.assertEqual(result['start'],'U1.1')
            self.assertNotIn('terminals',result)
        finally:frame.Destroy();self.app.Yield()

    def test_narrow_dialog_reflows_peer_names_and_validation_error(self):
        from signal_integrity_advisor_plugin.setup_guide import setup_dialog
        frame=wx.Frame(None);checks=[];failure=[]
        long_pad='U1.'+'VeryLongPinName_'*16
        def inspect():
            d=next(w for w in wx.GetTopLevelWindows() if hasattr(w,'setup_controls'))
            try:
                d.SetSize((560,650));d.Layout();self.app.Yield()
                c=d.setup_controls
                c['values']['rise_ns'].ChangeValue('invalid')
                b=c['apply'];b.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,b.GetId()))
                d.Layout();self.app.Yield()
                self.assertIn('Enter a number',c['error'].GetLabel())
                self.assertIn('VeryLongPinName',c['peers'].GetLabel())
                self.assertLessEqual(c['scroll'].GetVirtualSize().width,c['scroll'].GetClientSize().width)
                for control in (c['peers'],c['error']):
                    for line in control.GetLabel().splitlines():
                        self.assertLessEqual(control.GetTextExtent(line).width,c['scroll'].GetClientSize().width-20)
                checks.append(True)
            except Exception as error:failure.append(error)
            finally:d.EndModal(wx.ID_CANCEL)
        wx.CallLater(100,inspect)
        rows=[dict(label=p,net='DATA',footprint_uuid=owner) for p,owner in [('U1.1','a'),(long_pad,'a'),('J1.1','b')]]
        try:
            self.assertIsNone(setup_dialog(frame,{'DATA':[r['label'] for r in rows]},rows,
                                          dict(net='DATA',start='U1.1',end='J1.1'),VALUES,False,['GND']))
            if failure:raise failure[0]
            self.assertEqual(checks,[True])
        finally:frame.Destroy();self.app.Yield()

    def test_circuit_timing_button_keeps_model_inputs_explicit(self):
        from signal_integrity_advisor_plugin.ibis_ui import circuit_options_dialog
        frame=wx.Frame(None)
        def fill():
            d=next(w for w in wx.GetTopLevelWindows() if isinstance(w,wx.Dialog) and w.GetTitle()=='KiCad circuit export settings')
            b=next(c for c in d.GetChildren() if isinstance(c,wx.Button) and c.GetLabel()=='Suggest timing from selected routes')
            b.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,b.GetId()))
            d.EndModal(wx.ID_OK)
        wx.CallLater(80,fill)
        try:
            result=circuit_options_dialog(frame,[dict(delay_ns=2.,inputs=dict(rise_ns=.5,frequency_mhz=100.))])
            self.assertAlmostEqual(result['timestep_ns'],.025)
            self.assertEqual(result['duration_ns'],100.)
            self.assertFalse(result['allow_approximations'])
            self.assertIsNone(result['via_inductance_nh'])
        finally:frame.Destroy();self.app.Yield()

    def test_cancel_preserves_panel_and_no_board_write(self):
        from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
        from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import RoutePreview
        frame=wx.Frame(None);board=pcbnew.BOARD();panel=QuickSIPanel(frame,board,RoutePreview)
        try:
            with patch('signal_integrity_advisor_plugin.setup_guide.setup_dialog',return_value=None),patch.object(panel,'changed') as changed:
                panel.setup_path();changed.assert_not_called()
            self.assertEqual(len(list(board.GetTracks())),0)
        finally:frame.Destroy();self.app.Yield()

if __name__=='__main__':unittest.main()
