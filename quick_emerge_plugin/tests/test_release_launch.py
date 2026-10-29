"""Release launcher contracts without installing dependencies or opening windows."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quick_emerge_plugin import desktop_entrypoint as desktop
from quick_emerge_plugin import __main__ as entry
from wayricad_runtime import bootstrap, runtime_setup


class ReleaseLaunchTests(unittest.TestCase):
    def test_flat_workers_do_not_execute_editor_initializer(self):
        import shutil
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'installed'; root.mkdir()
            for path in source.glob('*.py'): shutil.copy2(path, root/path.name)
            (root/'__init__.py').write_text("raise RuntimeError('EDITOR_INITIALIZER_EXECUTED')")
            result = subprocess.run([sys.executable,'-I',str(root/'__main__.py'),'--help'],stdin=subprocess.DEVNULL,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            code = "import runpy; runpy.run_path("+repr(str(root/'network_worker.py'))+", run_name='worker_import')"
            result = subprocess.run([sys.executable,'-I','-c',code],stdin=subprocess.DEVNULL,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_import_and_help_do_not_require_gui(self):
        root = Path(__file__).resolve().parents[2]
        code = ("import sys; sys.modules['wx']=None; "
                "import quick_emerge_plugin.desktop_entrypoint; "
                "import quick_emerge_plugin.__main__")
        result = subprocess.run([sys.executable, '-I', '-c',
                                 "import sys; sys.path.insert(0, " + repr(str(root)) + "); " + code],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for script in ('__main__.py', 'desktop_entrypoint.py'):
            result = subprocess.run([sys.executable, '-I', str(root/'quick_emerge_plugin'/script), '--help'],
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_runtime_without_gui(self):
        with patch.dict(sys.modules, {'wx': None}), patch(
                'quick_emerge_plugin.backend.runtime_info', return_value={'version': 'test'}) as probe:
            self.assertEqual(entry.main(['--check-runtime']), 0)
        probe.assert_called_once_with()

    def test_profile_has_desktop_dependencies_without_solver_or_vtk(self):
        requirements = runtime_setup.REQUIREMENTS_QUICK_EMERGE
        self.assertEqual(set(requirements), {'numpy', 'matplotlib', 'packaging', 'kipy', 'vtk', 'reportlab', 'matplotlib.backends.backend_wxagg'})
        self.assertFalse(any('emerge' in spec for spec in requirements.values()))
        with patch.object(runtime_setup, 'ensure_runtime', return_value=Path('managed-python')) as ensure, \
             patch.object(bootstrap.subprocess, 'call', return_value=0), \
             patch.object(sys, 'argv', ['desktop_entrypoint.py', '--board', 'example.kicad_pcb']):
            self.assertEqual(bootstrap.relaunch(Path('.'), 'desktop_entrypoint.py', profile='quick-emerge'), 0)
        self.assertEqual(ensure.call_args.args[0], requirements)

    def test_relaunch_short_circuits_and_reports_errors(self):
        with patch.object(bootstrap, 'relaunch', return_value=7) as launch, \
             patch('wayricad_runtime.loading.LoadingWindow') as loading:
            self.assertEqual(desktop.main([]), 7)
            self.assertEqual(launch.call_args.kwargs['profile'], 'quick-emerge')
            loading.return_value.finish.assert_called_once()
        with patch.object(bootstrap, 'relaunch', side_effect=RuntimeError('Setup failed; retry')), \
             patch.object(bootstrap, 'failure', return_value=1) as failure, \
             patch('wayricad_runtime.loading.LoadingWindow'):
            self.assertEqual(desktop.main([]), 1)
            self.assertIn('retry', str(failure.call_args.args[0]))

    def test_origin_board_and_visible_frame_ready_handshake(self):
        with tempfile.TemporaryDirectory() as folder:
            board = Path(folder)/'origin.kicad_pcb'
            board.write_text('(kicad_pcb)', encoding='utf-8')
            ready = Path(folder)/'ready'
            frame = Mock()
            callbacks = []
            wx = SimpleNamespace(App=Mock(), CallAfter=lambda callback: callbacks.append(callback))
            wx.App.Get.return_value = None
            def loop():
                self.assertFalse(ready.exists())
                frame.Show.assert_called_once()
                for callback in callbacks:
                    callback()
                self.assertTrue(ready.exists())
            wx.App.return_value.MainLoop.side_effect = loop
            with patch.dict(os.environ, {'WAYRICAD_SPLASH_READY': str(ready)}), \
                 patch.dict(sys.modules, {'wx': wx, 'quick_emerge_plugin.ui':
                                         SimpleNamespace(QuickEMergeFrame=Mock(return_value=frame))}), \
                 patch('quick_emerge_plugin.model.source_identity'), \
                 patch('wayricad_runtime.context.saved_board', return_value=board) as origin, \
                 patch.object(bootstrap, 'relaunch', return_value=None):
                self.assertEqual(desktop.main([]), 0)
                origin.assert_called_once()

    def test_invalid_board_uses_visible_failure(self):
        with patch.dict(os.environ, {'WAYRICAD_SPLASH_READY': 'inherited'}), \
             patch.object(bootstrap, 'relaunch', return_value=None), \
             patch.object(bootstrap, 'failure', return_value=1) as failure:
            self.assertEqual(desktop.main(['--board', 'missing.kicad_pcb']), 1)
        self.assertIn('saved KiCad PCB', str(failure.call_args.args[0]))


if __name__ == '__main__':
    unittest.main()
