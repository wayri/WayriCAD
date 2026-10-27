"""Native engineering-unit setup and explicit PDN/AC quick-start controls."""
import time
import unittest

try:
    import wx
    from quick_pi_plugin.transient_setup import PITransientStudyDialog
    from quick_pi_plugin.decoupling.impedance_ui import PdnImpedanceDialog
    from quick_pi_plugin.ac_ui import ACStudyDialog
    from quick_pi_plugin.plot_canvas import FigureCanvasWxAgg,NavigationToolbar2WxAgg
except ImportError:
    wx=None


@unittest.skipIf(wx is None,'Native wx/Matplotlib runtime required')
class SetupGuideUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.GetApp() or wx.App(False)

    def test_pi_engineering_setup_switches_advanced_and_runs_explicit_network(self):
        from quick_pi_plugin.tests.test_setup_guides import transient
        from quick_pi_plugin.transient import solve_transient
        from wayricad_runtime.transient_study import execute_study
        calls=[]
        def runner(request,cancel):calls.append(request);return execute_study(request,solve_transient)
        dialog=PITransientStudyDialog(None,'pi',transient(),runner,(FigureCanvasWxAgg,NavigationToolbar2WxAgg))
        try:
            dialog.Show();self.app.Yield()
            self.assertEqual(float(dialog.quick_fields['source_resistance_ohm'].GetValue()),10.)
            dialog.quick_rows.SetCellValue(0,6,'')
            with self.assertRaisesRegex(ValueError,'Effective C'):dialog._request()
            dialog.advanced.SetValue(True);dialog._toggle_advanced()
            self.assertTrue(dialog.advanced.GetValue())
            self.assertEqual(dialog.rows.GetCellValue(0,6),'')
            dialog.rows.SetCellValue(0,6,'100e-6')
            dialog.advanced.SetValue(False);dialog._toggle_advanced()
            self.assertEqual(float(dialog.quick_rows.GetCellValue(0,6)),100.)
            dialog._recommend();self.assertIn('half-step',dialog.status.GetLabel())
            dialog._run();deadline=time.monotonic()+10
            while dialog._busy and time.monotonic()<deadline:self.app.Yield();time.sleep(.01)
            self.assertFalse(dialog._busy);self.assertIsNotNone(dialog.result)
            self.assertEqual(len(calls),1);self.assertEqual(len(dialog.figure.axes),2)
            self.assertEqual(dialog.book.GetSelection(),1)
            dialog.quick_fields['source_inductance_H'].SetValue('10');self.app.Yield()
            self.assertIsNone(dialog.result);self.assertFalse(dialog.export.IsEnabled())
        finally:dialog.Destroy();self.app.Yield()

    def test_pdn_target_curve_invalidates_after_input_change(self):
        dialog=PdnImpedanceDialog(None)
        try:
            dialog.Show();self.app.Yield();dialog._run()
            self.assertIsNotNone(dialog.result);self.assertEqual(len(dialog.figure.axes),2)
            self.assertAlmostEqual(dialog.result['target_ohm'],.05)
            self.assertIn('lumped',dialog.summary.GetValue())
            self.assertTrue(dialog.export.IsEnabled())
            dialog.fields['allowed_ripple_V'].SetValue('10');self.app.Yield()
            self.assertIsNone(dialog.result);self.assertFalse(dialog.export.IsEnabled())
        finally:dialog.Destroy();self.app.Yield()

    def test_ac_quick_loop_replaces_tables_and_keeps_return_balance(self):
        from quick_pi_plugin.ac_setup import PRESETS
        dialog=ACStudyDialog(None,lambda request,cancel:None,(FigureCanvasWxAgg,NavigationToolbar2WxAgg))
        try:
            dialog.Show();self.app.Yield();dialog.quick_preset.SetSelection(2)
            dialog.quick_fields['ripple_rms_a'].SetValue('1.5');dialog._apply_quick()
            study=dialog._study()
            self.assertEqual(len(study['conductors']),3)
            self.assertAlmostEqual(sum(row['current_scale'] for row in study['conductors']),0)
            self.assertEqual(study['harmonics'][0]['current_rms_a'],1.5)
            self.assertIn('no board extraction',dialog.status.GetLabel())
        finally:dialog.Destroy();self.app.Yield()


if __name__=='__main__':unittest.main()
