"""Saved-file launch, dependency discovery and command regression coverage."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from wayricad_mechanical import runtime


def load_entrypoint(name):
    spec = importlib.util.spec_from_file_location('mechanical_test_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LaunchTests(unittest.TestCase):
    def test_document_context_requires_existing_saved_file(self):
        entry = load_entrypoint('desktop_entrypoint')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'board.kicad_pcb'
            document = SimpleNamespace(board_filename=path.name, project=SimpleNamespace(path=temp))
            board = SimpleNamespace(document=document)
            client = SimpleNamespace(get_board=lambda: board)
            self.assertIsNone(entry.saved_board_path(client))
            path.write_text('(kicad_pcb)', encoding='utf-8')
            self.assertEqual(entry.saved_board_path(client), str(path.resolve()))
            self.assertEqual(path.read_text(), '(kicad_pcb)')
            document.board_filename = ''
            self.assertIsNone(entry.saved_board_path(client))

    def test_gui_relaunches_native_python_without_polluted_environment(self):
        entry = load_entrypoint('cli')
        with tempfile.TemporaryDirectory() as temp:
            native = str(Path(temp) / 'native-python.exe')
            with patch('wayricad_runtime.runtime_setup.ensure_runtime', return_value=native) as prepare, \
                 patch.dict(os.environ, {'PYTHONHOME': 'incompatible', 'PYTHONPATH': 'incompatible'}), \
                 patch.object(entry.subprocess, 'run', return_value=SimpleNamespace(returncode=7)) as run:
                self.assertEqual(entry.main(['--gui', 'board with spaces.kicad_pcb']), 7)
                args, kwargs = run.call_args
                self.assertEqual(args[0], [native, '-I', str(ROOT / 'launch.py'), '--gui', 'board with spaces.kicad_pcb'])
                self.assertNotIn('PYTHONHOME', kwargs['env'])
                self.assertNotIn('PYTHONPATH', kwargs['env'])
                self.assertEqual(prepare.call_args.args[0], {
                    'OpenGL.GL': 'PyOpenGL>=3.1,<4', 'OpenGL.GLU': 'PyOpenGL>=3.1,<4'})

    def test_gui_setup_failure_is_actionable_before_ui_import(self):
        entry = load_entrypoint('cli')
        output = io.StringIO()
        with patch('wayricad_runtime.runtime_setup.ensure_runtime', side_effect=RuntimeError('Setup log: runtime.log')), \
             patch.object(entry.subprocess, 'run') as run, contextlib.redirect_stderr(output):
            self.assertEqual(entry.main(['--review', 'report.json']), 1)
            run.assert_not_called()
        self.assertIn('Setup log: runtime.log', output.getvalue())

    def test_ipc_profile_prepares_actual_viewer_modules(self):
        from wayricad_runtime import bootstrap
        with patch('wayricad_runtime.runtime_setup.ensure_runtime', return_value=sys.executable) as prepare, \
             patch.object(bootstrap.sys, 'flags', SimpleNamespace(isolated=True)):
            self.assertIsNone(bootstrap.relaunch(ROOT, 'desktop_entrypoint.py', profile='mechanical'))
        self.assertEqual(prepare.call_args.args[0]['OpenGL.GL'], 'PyOpenGL>=3.1,<4')
        self.assertEqual(prepare.call_args.args[0]['OpenGL.GLU'], 'PyOpenGL>=3.1,<4')
        self.assertIn('kipy', prepare.call_args.args[0])

    def test_missing_gl_modules_install_pyopengl_only_in_private_runtime(self):
        from wayricad_runtime import runtime_setup as setup
        installed = False
        commands = []
        def probe(python, requirements=()):
            return 'identity' if not requirements or installed else None
        def run(command, timeout=30, log=None):
            nonlocal installed
            commands.append(command)
            if 'pip' in command:
                installed = True
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory() as cache, \
             patch.object(setup, 'native_python', return_value=Path('native')), \
             patch.object(setup, '_probe', side_effect=probe), \
             patch.object(setup, '_pip_source_options', return_value=[]), \
             patch.object(setup, '_run', side_effect=run):
            python = setup.ensure_runtime(setup.REQUIREMENTS_MECHANICAL, cache_dir=cache)
            self.assertTrue(python.is_relative_to(Path(cache)))
        self.assertIn('--system-site-packages', commands[0])
        self.assertIn('PyOpenGL>=3.1,<4', commands[1])
        self.assertIn('--only-binary=:all:', commands[1])
        self.assertNotEqual(commands[1][0], 'native')

    def test_native_action_uses_managed_runtime_without_importing_ui_in_editor(self):
        board = SimpleNamespace(GetFileName=lambda: 'C:/Projects/Example/board.kicad_pcb')
        host = SimpleNamespace(ActionPlugin=object, GetBoard=lambda: board)
        with patch.dict(sys.modules, {'pcbnew': host}):
            entry = load_entrypoint('plugin')
        with patch('wayricad_runtime.runtime_setup.ensure_runtime', return_value='prepared-python') as prepare, \
             patch('wayricad_runtime.loading.LoadingWindow') as loading, \
             patch.object(entry.subprocess, 'Popen') as launch:
            entry.MechanicalCheckPlugin().Run()
        self.assertIn('OpenGL.GL', prepare.call_args.args[0])
        self.assertEqual(launch.call_args.args[0], [
            'prepared-python', '-I', str(ROOT / 'launch.py'), '--gui', board.GetFileName()])
        loading.return_value.finish.assert_called()

    def test_native_action_keeps_originating_board_during_setup(self):
        original='C:/Projects/Origin/board.kicad_pcb'
        active={'path':original}
        host=SimpleNamespace(ActionPlugin=object,GetBoard=lambda:SimpleNamespace(GetFileName=lambda:active['path']))
        with patch.dict(sys.modules,{'pcbnew':host}):
            entry=load_entrypoint('plugin')
        def prepare(requirements):
            active['path']='C:/Projects/Other/board.kicad_pcb'
            return 'prepared-python'
        with patch('wayricad_runtime.runtime_setup.ensure_runtime',side_effect=prepare), \
             patch('wayricad_runtime.loading.LoadingWindow'), \
             patch.object(entry.subprocess,'Popen') as launch:
            entry.MechanicalCheckPlugin().Run()
        self.assertEqual(launch.call_args.args[0][-1],original)

    def test_native_action_pumps_loading_events_during_cold_setup(self):
        host = SimpleNamespace(ActionPlugin=object, GetBoard=lambda: None)
        with patch.dict(sys.modules, {'pcbnew': host}):
            entry = load_entrypoint('plugin')
        import threading
        completed = threading.Event()
        loading = SimpleNamespace(tick=Mock(side_effect=completed.set), finish=Mock())
        def prepare(requirements):
            self.assertTrue(completed.wait(2), 'Editor events were not pumped during setup')
            return 'prepared-python'
        with patch('wayricad_runtime.loading.LoadingWindow', return_value=loading), \
             patch('wayricad_runtime.runtime_setup.ensure_runtime', side_effect=prepare), \
             patch.object(entry.subprocess, 'Popen'):
            entry.MechanicalCheckPlugin().Run()
        loading.tick.assert_called()
        loading.finish.assert_called()

    def test_prepared_isolated_gui_enters_ui_without_relaunch(self):
        entry = load_entrypoint('cli')
        ui_cli = SimpleNamespace(main=Mock(return_value=0))
        with patch('wayricad_runtime.runtime_setup.ensure_runtime', return_value=sys.executable), \
             patch.object(entry.sys, 'flags', SimpleNamespace(isolated=True)), \
             patch.dict(sys.modules, {'wayricad_mechanical.cli': ui_cli}), \
             patch.object(entry.subprocess, 'run') as run:
            self.assertEqual(entry.main(['--gui']), 0)
        run.assert_not_called()
        ui_cli.main.assert_called_once_with(['--gui'])

    def test_rules_export_works_without_native_imports(self):
        entry = load_entrypoint('cli')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'rules.json'
            self.assertEqual(entry.main(['--init-rules', str(path)]), 0)
            self.assertEqual(json.loads(path.read_text())['schema_version'], 1)

    def test_missing_native_runtime_is_visible_and_fails(self):
        entry = load_entrypoint('desktop_entrypoint')
        with patch('wayricad_runtime.bootstrap.relaunch', side_effect=RuntimeError('Install KiCad 10 with native Python bindings.')), \
             patch.object(entry, 'notify_error', return_value=1) as notify:
            self.assertEqual(entry.main(), 1)
            self.assertIn('Install KiCad 10', notify.call_args.args[0])

    @unittest.skipUnless(os.name == 'nt', 'Windows KiCad installation discovery')
    def test_discovery_does_not_select_unsupported_9_or_11(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for version in ('9.0', '10.0', '11.0'):
                binary = root / 'KiCad' / version / 'bin'
                binary.mkdir(parents=True)
                (binary / 'kicad-cli.exe').touch()
                (binary / 'python.exe').touch()
            with patch.dict(os.environ, {'PROGRAMFILES': temp, 'LOCALAPPDATA': temp}, clear=True), \
                 patch.object(runtime.shutil, 'which', return_value=None):
                found = runtime.discover()
                self.assertEqual(Path(found['kicad_python']).resolve(), (root / 'KiCad/10.0/bin/python.exe').resolve())
                self.assertEqual(Path(found['kicad_cli']).resolve(), (root / 'KiCad/10.0/bin/kicad-cli.exe').resolve())


if __name__ == '__main__':
    unittest.main()
