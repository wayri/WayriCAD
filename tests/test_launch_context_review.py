"""Regression checks for independent KiCad windows and runtime handoffs."""
from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from wayricad_runtime import bootstrap, context, runtime_setup


class LaunchContextReviewTests(unittest.TestCase):
    def test_connection_uses_only_invoking_socket_and_token(self):
        factory = Mock()
        with patch.dict(sys.modules, {'kipy': SimpleNamespace(KiCad=factory)}), \
             patch.dict(os.environ, {'KICAD_API_SOCKET': 'socket-A', 'KICAD_API_TOKEN': 'token-A'}):
            context.connect(timeout_ms=900)
        factory.assert_called_once_with(socket_path='socket-A', kicad_token='token-A', timeout_ms=900)

    def test_missing_socket_does_not_autodiscover_another_editor(self):
        factory = Mock()
        with patch.dict(sys.modules, {'kipy': SimpleNamespace(KiCad=factory)}), \
             patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'originating'):
                context.connect()
        factory.assert_not_called()

    def test_board_uses_document_filename_and_project_not_cwd(self):
        with tempfile.TemporaryDirectory() as folder:
            board_path = Path(folder) / 'active.kicad_pcb'
            board_path.touch()
            board = SimpleNamespace(document=SimpleNamespace(board_filename='active.kicad_pcb'),
                                    name='other.kicad_pcb',
                                    get_project=lambda: SimpleNamespace(path=str(Path(folder) / 'project.kicad_pro')))
            self.assertEqual(context.saved_board(SimpleNamespace(get_board=lambda: board)), board_path.resolve())

    def test_relaunch_preserves_instance_and_lexical_venv_path(self):
        executable = Path('distinct-venv/bin/python').absolute()
        with patch.object(runtime_setup, 'ensure_runtime', return_value=executable), \
             patch.object(bootstrap.subprocess, 'call', return_value=0) as launch, \
             patch.dict(os.environ, {'KICAD_API_SOCKET': 'socket-B', 'KICAD_API_TOKEN': 'token-B'}):
            self.assertEqual(bootstrap.relaunch('/plugin', 'entry.py'), 0)
        self.assertEqual(launch.call_args.args[0][0], str(executable))
        self.assertEqual(launch.call_args.kwargs['env']['KICAD_API_SOCKET'], 'socket-B')
        self.assertEqual(launch.call_args.kwargs['env']['KICAD_API_TOKEN'], 'token-B')

    def test_current_runtime_does_not_relaunch_recursively(self):
        with patch.object(runtime_setup, 'ensure_runtime', return_value=Path(sys.executable)), \
             patch.object(bootstrap.sys, 'flags', SimpleNamespace(isolated=1)), \
             patch.object(bootstrap.subprocess, 'call') as launch:
            self.assertIsNone(bootstrap.relaunch('/plugin', 'entry.py'))
        launch.assert_not_called()

    def test_current_runtime_without_isolation_relaunches_with_isolation(self):
        with patch.object(runtime_setup, 'ensure_runtime', return_value=Path(sys.executable)), \
             patch.object(bootstrap.sys, 'flags', SimpleNamespace(isolated=0)), \
             patch.object(bootstrap.subprocess, 'call', return_value=0) as launch:
            self.assertEqual(bootstrap.relaunch('/plugin', 'entry.py'), 0)
        self.assertEqual(launch.call_args.args[0][1], '-I')

    def test_copper_uses_native_only_shared_runtime(self):
        from copper_balancer_plugin import native_runner
        with patch.object(runtime_setup, 'ensure_runtime', return_value=Path('native')) as ensure:
            self.assertEqual(native_runner.find_native_python(), Path('native'))
        ensure.assert_called_once_with()
        with patch.dict(os.environ, {'PYTHONPATH': 'wrong', 'KICAD_API_SOCKET': 'socket-C'}):
            env = native_runner.child_environment()
        self.assertNotIn('PYTHONPATH', env)
        self.assertEqual(env['WAYRICAD_COPPER_NO_REGISTER'], '1')
        self.assertEqual(env['KICAD_API_SOCKET'], 'socket-C')

    def test_invalid_launch_json_has_actionable_error(self):
        from wayricad_runtime import launcher
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'wayricad-tool.json').write_text('[]', encoding='utf-8')
            with patch.object(bootstrap, 'failure', return_value=1) as failure, \
                 patch.object(launcher, 'print'):
                self.assertEqual(launcher.main(folder), 1)
        self.assertIn('JSON object', str(failure.call_args.args[0]))

    def test_launch_traceback_redacts_instance_token(self):
        from wayricad_runtime import launcher
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'wayricad-tool.json').write_text('{"tool":"secret-token"}', encoding='utf-8')
            with patch.dict(os.environ, {'KICAD_API_TOKEN': 'secret-token'}), \
                 patch.object(bootstrap, 'failure', return_value=1), \
                 patch.object(launcher.traceback, 'format_exc', return_value='failure secret-token'), \
                 patch.object(launcher, 'print') as output:
                launcher.main(folder)
        self.assertEqual(output.call_args.args[0], 'failure [redacted]')


if __name__ == '__main__':
    unittest.main()
