"""The shared loading window must not outlive plugin startup."""
import json
from pathlib import Path
import tempfile
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from wayricad_runtime import bootstrap, launcher, loading, runtime_setup


class LoadingLauncherTests(unittest.TestCase):
    def test_finish_hides_window_without_waiting_for_deferred_destruction(self):
        class DeferredWindow:
            shown = True
            destroy_queued = False

            def Hide(self):
                self.shown = False

            def Destroy(self):
                self.destroy_queued = True

        splash = loading.LoadingWindow.__new__(loading.LoadingWindow)
        window = DeferredWindow()
        splash.window = window
        splash.finish()
        self.assertFalse(window.shown)
        self.assertTrue(window.destroy_queued)
        self.assertIsNone(splash.window)
        splash.finish()  # Repeated error/finally cleanup is harmless.

    def test_splash_stays_responsive_during_runtime_setup(self):
        prepared = threading.Event()
        loading = Mock(window=object())

        def prepare(_requirements):
            assert prepared.wait(2)
            return Path('managed-python')

        def tick():
            prepared.set()

        loading.tick.side_effect = tick
        with patch.object(runtime_setup, 'ensure_runtime', side_effect=prepare), \
             patch.object(bootstrap.subprocess, 'Popen') as spawn:
            spawn.return_value.poll.return_value = 0
            spawn.return_value.wait.return_value = 0
            self.assertEqual(bootstrap.relaunch('plugin', 'entry.py', loading=loading), 0)
        loading.tick.assert_called()

    def test_wx_does_not_parse_plugin_arguments(self):
        original = ['ipc_entrypoint.py', '-I', '--board', 'C:/Projects/Example/board.kicad_pcb']
        observed = []

        def create(_redirect):
            observed.append(list(sys.argv))
            return object()

        wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: None))
        wx.App = Mock(side_effect=create, Get=lambda: None)
        with patch.object(sys, 'argv', original):
            self.assertIsNotNone(loading.ensure_wx_app(wx))
            self.assertIs(sys.argv, original)
        self.assertEqual(observed, [['ipc_entrypoint.py']])

    def test_bootstrap_closes_loading_when_child_signals_ready(self):
        loading = Mock(window=object())
        process = Mock()
        process.poll.side_effect = [None, None]
        process.wait.return_value = 0

        def start(_command, **kwargs):
            Path(kwargs['env']['WAYRICAD_SPLASH_READY']).touch()
            return process

        with patch.object(runtime_setup, 'ensure_runtime', return_value=Path('managed-python')), \
             patch.object(bootstrap.subprocess, 'Popen', side_effect=start):
            self.assertEqual(bootstrap.relaunch('plugin', 'ipc_entrypoint.py', loading=loading), 0)
        loading.finish.assert_called_once()
        process.wait.assert_called_once()

    def test_bootstrap_closes_loading_when_child_exits_without_ready(self):
        splash = Mock(window=object())
        process = Mock()
        process.poll.return_value = 1
        process.wait.return_value = 1
        with patch.object(runtime_setup, 'ensure_runtime', return_value=Path('managed-python')), \
             patch.object(bootstrap.subprocess, 'Popen', return_value=process):
            self.assertEqual(bootstrap.relaunch('plugin', 'entry.py', loading=splash), 1)
        splash.finish.assert_called_once()

    def test_launcher_clears_loading_before_reporting_setup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'wayricad-tool.json').write_text(json.dumps({
                'tool': 'via_stitching_plugin', 'module': 'unused',
                'class': 'Unused', 'name': 'Via Stitching'}), encoding='utf-8')
            splash = Mock(window=object())

            def report_failure(_error, _title):
                splash.finish.assert_called_once()
                return 1

            with patch.object(loading, 'LoadingWindow', return_value=splash), \
                 patch.dict('os.environ', {'WAYRICAD_SPLASH_READY': ''}), \
                 patch.object(bootstrap, 'relaunch', side_effect=RuntimeError('setup failed')), \
                 patch.object(bootstrap, 'failure', side_effect=report_failure), \
                 patch.object(sys, 'stderr'):
                self.assertEqual(launcher.main(root), 1)

    def test_launcher_signals_ready_before_plugin_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / 'ready'
            (root / 'wayricad-tool.json').write_text(json.dumps({
                'tool': 'bom_studio_plugin', 'module': 'unused',
                'class': 'Unused', 'name': 'BOM Studio'}), encoding='utf-8')
            fake_wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: object()))
            observed = []

            def open_bom():
                observed.append(ready.is_file())
                return 0

            fake_bom = SimpleNamespace(main=open_bom)
            with patch.object(bootstrap, 'relaunch', return_value=None), \
                 patch.dict('os.environ', {'WAYRICAD_SPLASH_READY': str(ready)}), \
                 patch.dict(sys.modules, {'wx': fake_wx, 'bomstudio': SimpleNamespace(),
                                          'bomstudio.launch': fake_bom}):
                self.assertEqual(launcher.main(root), 0)
            self.assertEqual(observed, [True])


if __name__ == '__main__':
    unittest.main()
