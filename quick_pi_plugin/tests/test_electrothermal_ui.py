"""Native dialog execution, invalidation and cancellation contracts."""
import json
import os
from pathlib import Path
import threading
import time
import unittest

try:
    import wx
    from quick_pi_plugin.plot_canvas import FigureCanvasWxAgg, NavigationToolbar2WxAgg
    from quick_pi_plugin.electrothermal_ui import ElectrothermalStudyDialog, initial_studies
except ImportError:
    wx = None

from quick_pi_plugin.service import execute
from quick_pi_plugin.tests.test_electrothermal import request as steady
from quick_pi_plugin.tests.test_electrothermal_transient import request as transient

_native_app = None


@unittest.skipIf(wx is None, 'native wx runtime required')
class ElectrothermalDialogTests(unittest.TestCase):
    def setUp(self):
        global _native_app
        _native_app = wx.GetApp() or wx.App(False)
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            if not dialog._closed:
                dialog._close()
        wx.CallLater(50, _native_app.ExitMainLoop)
        _native_app.MainLoop()

    def dialog(self, runner=execute):
        # Production runner accepts a cancellation callback; execute is synchronous.
        wrapper = (lambda request, cancel: execute(request)) if runner is execute else runner
        dialog = ElectrothermalStudyDialog(None, {'steady': steady(), 'transient': transient()},
            wrapper, (FigureCanvasWxAgg, NavigationToolbar2WxAgg))
        self.dialogs.append(dialog)
        return dialog

    def wait_for(self, condition, timeout=30):
        deadline = time.monotonic() + timeout
        while not condition():
            wx.YieldIfNeeded()
            if time.monotonic() > deadline:
                self.fail('Native dialog worker did not finish within its test bound.')
            time.sleep(.005)
        wx.YieldIfNeeded()

    def test_both_models_run_render_and_input_change_invalidates(self):
        dialog = self.dialog()
        dialog.Show(); dialog.Layout()
        self.wait_for(lambda: dialog.canvas.GetClientSize().width > 100)
        for index, mode in enumerate(('steady', 'transient')):
            with self.subTest(mode=mode):
                dialog.mode.SetSelection(index)
                dialog._reset()
                dialog._run()
                self.assertFalse(dialog.run.IsEnabled())
                self.assertTrue(dialog.stop.IsEnabled())
                self.wait_for(lambda: not dialog._busy)
                self.assertIsNotNone(dialog.result, dialog.status.GetLabel())
                self.assertEqual(dialog.result['mode'], mode)
                self.assertTrue(dialog.export.IsEnabled())
                self.assertIn('accepted', dialog.status.GetLabel())
                self.assertGreater(len(dialog.figure.axes), 1)
                self.assertIn('status', dialog.details.GetValue())
                capture = os.environ.get('ELECTROTHERMAL_UI_CAPTURE')
                if capture:
                    # Export this dialog's figure directly; avoid desktop pixels.
                    dialog.canvas.draw()
                    dialog.figure.savefig(Path(capture) / (mode + '-dialog.png'), dpi=130)
                dialog.input_path = 'old-study.json'; dialog.input_sha = 'old'
                dialog._changed()
                self.assertIsNone(dialog.result)
                self.assertFalse(dialog.export.IsEnabled())
                self.assertIsNone(dialog.input_path)
                self.assertEqual(dialog.details.GetValue(), '')

    def test_strict_json_and_missing_physical_inputs_have_solve_actions(self):
        dialog = self.dialog()
        dialog.setup.ChangeValue('{"source_voltage_V": 1, "source_voltage_V": 2}')
        dialog._run()
        self.assertFalse(dialog._busy)
        self.assertIn('Repeated electrothermal JSON field', dialog.status.GetLabel())
        seed = initial_studies({'source_voltage': 3.3, 'sink_current': 1, 'source_terminal': 'A',
                                'sink_terminal': 'B'}, [{'id': 'A'}, {'id': 'B'}])
        self.assertIsNone(seed['steady']['thermal_settings']['board_h_w_m2k'])
        self.assertIsNone(seed['transient']['thermal_nodes'][0]['resistance_K_W'])
        dialog.mode.SetSelection(1)
        dialog.setup.ChangeValue(json.dumps(seed['transient']))
        dialog._run(); self.wait_for(lambda: not dialog._busy)
        self.assertIsNone(dialog.result)
        self.assertFalse(dialog.export.IsEnabled())
        self.assertTrue(dialog.run.IsEnabled())
        self.assertTrue(dialog.status.GetLabel())

    def test_close_cancels_and_waits_for_worker_then_discards_result(self):
        started = threading.Event(); release = threading.Event(); cancelled = threading.Event()
        def runner(request, cancel):
            started.set()
            while not release.wait(.005):
                if cancel(): cancelled.set()
            raise InterruptedError('cancelled')
        dialog = self.dialog(runner)
        dialog._run(); self.assertTrue(started.wait(1))
        dialog._close()
        self.wait_for(cancelled.is_set)
        self.assertFalse(dialog._closed)
        self.assertTrue(dialog._closing)
        release.set(); self.wait_for(lambda: dialog._closed)
        self.assertIsNone(dialog.result)

    def test_joule_guided_inputs_share_advanced_model_without_physical_defaults(self):
        from quick_pi_plugin.electrothermal_ui import feedback_studies, FEEDBACK_FIELDS
        initial=feedback_studies({'net':'RAIL','source_terminal':'J1.1','sink_terminal':'J2.1',
                                 'source_voltage':3.3,'sink_current':1.})
        dialog=ElectrothermalStudyDialog(None,initial,lambda *args:None,
            (FigureCanvasWxAgg,NavigationToolbar2WxAgg),steady_only=True)
        self.dialogs.append(dialog)
        self.assertEqual(dialog.book.GetPageText(0),'Materials + cooling')
        self.assertEqual(dialog.feedback_controls[('thermal_settings','ambient_c')].GetValue(),'')
        values=[25,.3,385,.025,10,.8,1.724e-8,.00393,-40,150,105]
        for (label,path),value in zip(FEEDBACK_FIELDS,values):
            dialog.feedback_controls[path].ChangeValue(str(value))
        dialog._guided_changed()
        request=dialog._request()
        self.assertTrue(request['require_explicit_thermal'])
        self.assertEqual(request['study']['thermal_settings']['ambient_c'],25)
        self.assertEqual(request['study']['electrical']['options']['resistivity_ohm_m'],1.724e-8)
        # An advanced edit is reflected in the guided page, with no hidden override.
        model=json.loads(dialog.setup.GetValue());model['thermal_settings']['ambient_c']=31
        dialog.setup.ChangeValue(json.dumps(model));dialog._changed()
        self.assertEqual(float(dialog.feedback_controls[('thermal_settings','ambient_c')].GetValue()),31)
        dialog.feedback_controls[('thermal_settings','ambient_c')].ChangeValue('nan');dialog._guided_changed()
        with self.assertRaisesRegex(ValueError,'ambient_c'):dialog._request()


if __name__ == '__main__':
    unittest.main()
