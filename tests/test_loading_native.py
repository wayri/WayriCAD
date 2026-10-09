"""Loading frames must disappear before the launcher's blocking child wait."""
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wayricad_runtime import bootstrap, loading, runtime_setup

try:
    import wx
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'native wx runtime required')
class NativeLoadingTests(unittest.TestCase):
    def setUp(self):
        self.app = loading.ensure_wx_app(wx)
        self.previous_exit_policy = self.app.GetExitOnFrameDelete()
        self.app.SetExitOnFrameDelete(False)

    def tearDown(self):
        self.app.Yield()
        self.app.SetExitOnFrameDelete(self.previous_exit_policy)

    def test_ready_handoff_hides_splash_before_blocking_child_wait(self):
        splash = loading.LoadingWindow('Disposable handoff check')
        window = splash.window
        self.assertTrue(window.IsShown())
        child_frame = wx.Frame(None, title='Disposable plugin window')
        process = Mock()
        process.poll.return_value = None

        def spawn(_command, **options):
            child_frame.Show()
            Path(options['env']['WAYRICAD_SPLASH_READY']).touch()
            return process

        def wait():
            # No Yield/MainLoop after finish: wx destruction is still queued.
            self.assertFalse(bool(window) and window.IsShown())
            self.assertTrue(child_frame.IsShown())
            splash.finish()
            return 0

        process.wait.side_effect = wait
        try:
            with patch.object(runtime_setup, 'ensure_runtime', return_value=Path('managed-python')), \
                 patch.object(bootstrap.subprocess, 'Popen', side_effect=spawn):
                self.assertEqual(bootstrap.relaunch('plugin', 'entry.py', loading=splash), 0)
        finally:
            splash.finish(); child_frame.Destroy()

    def test_failed_window_construction_leaves_no_visible_loading_frame(self):
        baseline = set(wx.GetTopLevelWindows())
        with patch.object(wx, 'StaticText', side_effect=RuntimeError('UI construction failed')):
            splash = loading.LoadingWindow('Disposable failure check')
        self.assertIsNone(splash.window)
        self.assertFalse(any(window.IsShown() for window in wx.GetTopLevelWindows() if window not in baseline))


if __name__ == '__main__':
    unittest.main()
