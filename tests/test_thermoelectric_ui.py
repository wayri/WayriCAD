import os
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('WAYRICAD_THERMO3D_NATIVE'),'Explicit native wx controller run required.')
class NativeStudyControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx=wx;cls.app=wx.GetApp() or wx.App(False)

    def setUp(self):
        from wayricad_runtime.thermoelectric_ui import open_study
        request=dict(schema_version=1,grid=dict(edges_mm=dict(x=[0,1,2,3],y=[0,1],z=[0,1])),
            materials={'metal':dict(thermal_conductivity_w_mk=10,resistivity_ohm_m=.001)},
            material_ids=['metal']*3,fixed_voltage_v={'0':.1,'2':0},fixed_temperature_c={'0':20,'2':20})
        with patch('wayricad_runtime.local_webview.try_new_webview',return_value=(None,'Browser intentionally disabled for controller tests.')):
            self.frame=open_study(request=request)

    def tearDown(self):
        if self.frame:self.frame.close(None)
        if hasattr(self.frame,'worker'):self.frame.worker.join(timeout=10)
        self.wx.YieldIfNeeded()

    def wait(self):
        deadline=time.monotonic()+30
        while self.frame.busy and time.monotonic()<deadline:
            self.wx.YieldIfNeeded();time.sleep(.01)
        self.assertFalse(self.frame.busy)

    def test_actual_solve_updates_metrics_and_export_gates(self):
        self.frame.run(None);self.wait()
        self.assertIsNotNone(self.frame.report,self.frame.status.GetLabel())
        self.assertGreater(self.frame.metrics.GetItemCount(),3)
        self.assertTrue(self.frame.buttons['html'].IsEnabled())
        self.frame.editor.SetValue('{}');self.wx.YieldIfNeeded()
        self.assertIsNone(self.frame.report)
        self.assertFalse(self.frame.buttons['html'].IsEnabled())

    def test_failed_rerun_clears_old_results(self):
        self.frame.run(None);self.wait()
        self.frame.editor.SetValue('{}');self.frame.run(None);self.wait()
        self.assertIsNone(self.frame.report)
        self.assertEqual(self.frame.metrics.GetItemCount(),0)

    def test_destroyed_window_does_not_accept_late_completion(self):
        serial=self.frame.serial
        self.frame.close(None)
        self.frame.finished(serial,None,'late result')
        self.assertTrue(self.frame.closed);self.assertTrue(self.frame.cancel.is_set())

    def test_minimum_window_toolbar_and_split_fit(self):
        self.frame.SetSize((760,520));self.frame.Layout();self.wx.YieldIfNeeded()
        for button in self.frame.buttons.values():
            rect=button.GetScreenRect();parent=button.GetParent().GetScreenRect()
            self.assertGreaterEqual(rect.x,parent.x)
            self.assertLessEqual(rect.right,parent.right+2)

    def test_regenerate_requires_confirmation_for_edited_inputs(self):
        self.frame.editor.SetValue('{"reviewed_custom_input": true}')
        with patch.object(self.wx,'MessageBox',return_value=self.wx.NO) as confirm:
            self.frame.generate(None)
        confirm.assert_called_once()
        self.assertIn('reviewed_custom_input',self.frame.editor.GetValue())
