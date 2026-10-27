"""Native branch editing, SI-unit roundtrips and solver-result invalidation."""
import time
import unittest

try:
    import wx
    from quick_pi_plugin.shunt_caps_ui import ShuntCapacitorDialog
    from quick_pi_plugin.transient_setup import PITransientStudyDialog
    from quick_pi_plugin.plot_canvas import FigureCanvasWxAgg,NavigationToolbar2WxAgg
except ImportError:
    wx=None

from quick_pi_plugin.tests.test_shunt_inputs import terminals


@unittest.skipIf(wx is None,'Native wx runtime required')
class ShuntUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.GetApp() or wx.App(False)

    def test_bulk_parasitics_are_validated_before_selected_rows_change(self):
        bank=[dict(id='C1',capacitance_F=1e-6,esr_ohm=0.,esl_H=0.),
              dict(id='C2',capacitance_F=2e-6,esr_ohm=0.,esl_H=0.)]
        window=ShuntCapacitorDialog(None,'U1',bank);window.Show();self.app.Yield()
        failures=[];window.rows.SelectAll()
        def fill():
            dialog=next(d for d in wx.GetTopLevelWindows() if hasattr(d,'parasitic_controls'))
            try:
                fields=dialog.parasitic_controls
                fields['esr'].SetValue('12');fields['esl'].SetValue('invalid')
                button=fields['apply'];button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,button.GetId()))
                self.assertEqual(window.rows.GetCellValue(0,2),'0')
                fields['esl'].SetValue('1.2');button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,button.GetId()))
            except Exception as error:failures.append(error);dialog.EndModal(wx.ID_CANCEL)
        wx.CallLater(100,fill)
        try:
            window._fill();self.assertFalse(failures)
            result=window._values()
            for i,row in enumerate(result):
                self.assertAlmostEqual(row['capacitance_F'],bank[i]['capacitance_F'])
                self.assertAlmostEqual(row['esr_ohm'],.012)
                self.assertAlmostEqual(row['esl_H'],1.2e-9)
        finally:window.Destroy();self.app.Yield()

    def test_board_candidates_require_esr_esl_and_apply_detached_units(self):
        dialog=ShuntCapacitorDialog(None,'U1',[],terminals(),'VCC',['GND'])
        failures=[]
        def accept():
            try:
                dialog.SetSize((660,520));dialog.Layout();self.app.Yield();dialog._wrap()
                self.assertEqual(dialog.parts.GetItemCount(),1)
                dialog.parts.Select(0);dialog._include()
                self.assertEqual(dialog.rows.GetCellValue(0,0),'C1')
                with self.assertRaisesRegex(ValueError,'ESR'):dialog._values()
                dialog.rows.SetCellValue(0,2,'10');dialog.rows.SetCellValue(0,3,'.5');dialog.rise.SetValue('1')
                self.assertLessEqual(dialog.scroll.GetVirtualSize().width,dialog.scroll.GetClientSize().width+2)
                for item,_text in dialog._wrapped:
                    for line in item.GetLabel().splitlines():
                        self.assertLessEqual(item.GetTextExtent(line).width,dialog.scroll.GetClientSize().width-20)
                dialog._apply()
            except Exception as error:failures.append(error);dialog.EndModal(wx.ID_CANCEL)
        wx.CallLater(100,accept)
        try:
            self.assertEqual(dialog.ShowModal(),wx.ID_OK,failures)
            self.assertFalse(failures);self.assertEqual(dialog.result[0]['id'],'C1@owner1')
            self.assertAlmostEqual(dialog.result[0]['capacitance_F'],1e-7)
            self.assertAlmostEqual(dialog.result[0]['esl_H'],.5e-9);self.assertEqual(dialog.rise_time_s,1e-6)
        finally:dialog.Destroy();self.app.Yield()

    def test_bank_survives_mode_switch_and_runs_without_aggregate_double_count(self):
        from quick_pi_plugin.transient import solve_transient
        from wayricad_runtime.transient_study import execute_study
        bank=[dict(id='C1',capacitance_F=100e-6,esr_ohm=.02,esl_H=2e-9),
              dict(id='C2',capacitance_F=10e-6,esr_ohm=.01,esl_H=.5e-9)]
        initial=dict(source_voltage_V=3.3,source_resistance_ohm=.05,source_inductance_H=1e-6,
                     duration_s=10e-6,step_s=20e-9,loads=[dict(id='U1',initial_current_A=0,
                     step_current_A=.2,step_time_s=2e-6,path_resistance_ohm=.02,path_inductance_H=0,
                     shunt_capacitors=bank,rise_time_s=1e-6)])
        calls=[]
        def run(request,cancel):calls.append(request);return execute_study(request,lambda spec:solve_transient(spec,cancel=cancel))
        dialog=PITransientStudyDialog(None,'pi',initial,run,(FigureCanvasWxAgg,NavigationToolbar2WxAgg))
        try:
            dialog.Show();self.app.Yield()
            self.assertTrue(dialog.quick_rows.IsReadOnly(0,6))
            self.assertNotIn('capacitance_F',dialog._request()['study']['loads'][0])
            self.assertEqual(dialog._request()['study']['loads'][0]['rise_time_s'],1e-6)
            dialog.advanced.SetValue(True);dialog._toggle_advanced();self.assertEqual(dialog._request()['study']['loads'][0]['shunt_capacitors'],bank)
            dialog.rows.SetCellValue(0,0,'Renamed load')
            dialog.advanced.SetValue(False);dialog._toggle_advanced();self.assertEqual(dialog._request()['study']['loads'][0]['id'],'Renamed load')
            self.assertEqual(dialog._request()['study']['loads'][0]['shunt_capacitors'],bank)
            dialog._run();deadline=time.monotonic()+12
            while dialog._busy and time.monotonic()<deadline:self.app.Yield();time.sleep(.01)
            self.assertFalse(dialog._busy);self.assertIsNotNone(dialog.result,dialog.status.GetLabel())
            self.assertEqual(len(calls),1);self.assertEqual(len(dialog.result['transient']['loads'][0]['shunt_capacitors']),2)
            self.assertEqual(dialog.cap_table.GetItemCount(),2)
            dialog.cap_table.Select(0,False);dialog.cap_table.Select(1);dialog._plot_capacitor()
            self.assertEqual(len(dialog.cap_figure.axes),2)
            self.assertIn('C2',dialog.cap_figure.axes[0].get_title())
            dialog.quick_fields['step_s'].SetValue('0.01');self.app.Yield()
            self.assertIsNone(dialog.result);self.assertFalse(dialog.export.IsEnabled())
            self.assertEqual(dialog.cap_table.GetItemCount(),0)
        finally:dialog.Destroy();self.app.Yield()


if __name__=='__main__':unittest.main()
