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


if __name__ == '__main__':
    unittest.main()
