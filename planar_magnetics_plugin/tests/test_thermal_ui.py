"""Native dialog lifecycle checks; no board or installed plugin is modified."""
import unittest
import threading
import time
from unittest.mock import patch

try:
    import wx
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'Requires native wxPython')
class ThermalDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import before creating wx.App: package startup registers actions only
        # when an app already exists, which requires an actual KiCad host.
        from planar_magnetics_plugin.thermal_ui import ThermalDialog
        cls.app = wx.GetApp() or wx.App(False)

    def wait_for(self, predicate):
        deadline = time.monotonic()+30
        while not predicate() and time.monotonic() < deadline:
            wx.Yield()
            time.sleep(.01)
        self.assertTrue(predicate(), 'Timed out waiting for thermal worker')

    def make_dialog(self):
        from planar_magnetics_plugin.analysis import CoilSpec, MagneticsEngine
        from planar_magnetics_plugin.thermal_ui import ThermalDialog
        return ThermalDialog(None, MagneticsEngine.analyze(CoilSpec(turns=1)))

    def test_solve_input_change_and_failure_clear_results(self):
        dialog = self.make_dialog()
        try:
            dialog.solve(None)
            self.assertFalse(dialog.run_button.IsEnabled())
            self.wait_for(lambda: dialog._worker is None)
            self.assertEqual(dialog.study['status'], 'converged')
            self.assertTrue(dialog.export_button.IsEnabled())
            self.assertEqual(len(dialog.figure.axes), 2)
            dialog.fields['ambient'].SetValue('21')
            wx.Yield()
            self.assertIsNone(dialog.study)
            self.assertFalse(dialog.export_button.IsEnabled())
            self.assertEqual(len(dialog.figure.axes), 0)
            with patch('planar_magnetics_plugin.thermal_ui.wx.MessageBox') as message:
                dialog.fields['width'].SetValue('-1')
                dialog.solve(None)
                message.assert_called_once()
                self.assertIsNone(dialog.study)
                self.assertFalse(dialog.export_button.IsEnabled())
        finally:
            dialog.Destroy()
            wx.Yield()

    def test_single_worker_snapshot_cancel_and_changed_inputs_discard_late_output(self):
        from planar_magnetics_plugin.thermal_coupling import solve_thermal_study
        from dataclasses import replace
        for action in ('cancel', 'edit', 'silent-mutation'):
            with self.subTest(action=action):
                dialog = self.make_dialog()
                entered, release = threading.Event(), threading.Event()
                captured = []
                def delayed(*snapshot, cancel=None):
                    captured.append((snapshot, threading.get_ident()))
                    entered.set()
                    if not release.wait(10):
                        raise RuntimeError('Test worker was not released')
                    # Deliberately emulate an uninterruptible backend returning late.
                    return solve_thermal_study(*snapshot)
                try:
                    with patch('planar_magnetics_plugin.thermal_ui.solve_thermal_study',
                               side_effect=delayed) as solver, patch(
                               'planar_magnetics_plugin.thermal_ui.wx.MessageBox') as message:
                        dialog.solve(None)
                        self.wait_for(entered.is_set)
                        worker = dialog._worker
                        heartbeat = threading.Event()
                        wx.CallAfter(heartbeat.set)
                        self.wait_for(heartbeat.is_set)
                        self.assertIsNot(captured[0][0][0], dialog.result)
                        self.assertNotEqual(captured[0][1], threading.get_ident())
                        dialog.solve(None)
                        self.assertIs(dialog._worker, worker)
                        self.assertEqual(solver.call_count, 1)
                        if action == 'cancel':
                            dialog.cancel(None)
                        elif action == 'edit':
                            dialog.fields['ambient'].SetValue('21')
                            wx.Yield()
                        else:
                            dialog.result.spec = replace(dialog.result.spec, current_a=.7)
                        self.assertFalse(dialog.run_button.IsEnabled())
                        release.set()
                        self.wait_for(lambda: dialog._worker is None)
                        self.assertIsNone(dialog.study)
                        self.assertFalse(dialog.export_button.IsEnabled())
                        self.assertTrue(dialog.run_button.IsEnabled())
                        self.assertEqual(message.call_count, int(action == 'silent-mutation'))
                finally:
                    release.set()
                    worker = dialog._worker
                    dialog.Destroy()
                    if worker is not None:
                        worker.join(10)
                    wx.Yield()

    def test_worker_failure_restores_controls_without_results(self):
        dialog = self.make_dialog()
        try:
            with patch('planar_magnetics_plugin.thermal_ui.solve_thermal_study',
                       side_effect=RuntimeError('Backend failed')), patch(
                       'planar_magnetics_plugin.thermal_ui.wx.MessageBox') as message:
                dialog.solve(None)
                self.wait_for(lambda: dialog._worker is None)
                message.assert_called_once()
                self.assertIn('Backend failed', message.call_args.args[0])
                self.assertIsNone(dialog.study)
                self.assertTrue(dialog.run_button.IsEnabled())
                self.assertFalse(dialog.cancel_button.IsEnabled())
                self.assertFalse(dialog.export_button.IsEnabled())
                self.assertFalse(dialog.layer.IsEnabled())
        finally:
            dialog.Destroy()
            wx.Yield()

    def test_destroy_cancels_and_never_schedules_completion_on_dead_dialog(self):
        dialog = self.make_dialog()
        entered, release = threading.Event(), threading.Event()
        cancellation_seen = []
        def delayed(*snapshot, cancel=None):
            entered.set()
            release.wait(10)
            cancellation_seen.append(cancel())
            return None
        with patch('planar_magnetics_plugin.thermal_ui.solve_thermal_study', side_effect=delayed):
            dialog.solve(None)
            self.wait_for(entered.is_set)
            worker = dialog._worker
            dialog.Destroy()
            wx.Yield()
            try:
                with patch('planar_magnetics_plugin.thermal_ui.wx.CallAfter') as dispatch:
                    release.set()
                    worker.join(10)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(cancellation_seen, [True])
                    dispatch.assert_not_called()
            finally:
                release.set()
                worker.join(10)

    def test_already_queued_completion_is_safe_after_destroy(self):
        dialog = self.make_dialog()
        with patch('planar_magnetics_plugin.thermal_ui.solve_thermal_study', return_value=None), patch(
                'planar_magnetics_plugin.thermal_ui.wx.CallAfter') as dispatch:
            dialog.solve(None)
            worker = dialog._worker
            worker.join(10)
            self.assertFalse(worker.is_alive())
            completions = [call for call in dispatch.call_args_list if len(call.args) == 3]
            self.assertEqual(len(completions), 1)
            callback, *args = completions[0].args
            dialog.Destroy()
            wx.Yield()
            callback(*args)  # Must not touch deleted wx controls.
