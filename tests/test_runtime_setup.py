"""Portable runtime bootstrap regressions; no network or installed KiCad needed."""
from pathlib import Path
from unittest.mock import patch
import subprocess
import tempfile
import unittest
import json

from wayricad_runtime import runtime_setup as runtime


class RuntimeSetupTests(unittest.TestCase):
    def test_ipc_launch_only_installs_tool_specific_dependencies(self):
        from wayricad_runtime import bootstrap, launcher

        with patch.object(runtime, 'ensure_runtime', return_value=Path('fake-python')) as ensure, \
             patch.object(bootstrap.subprocess, 'call', return_value=0):
            bootstrap.relaunch(Path('plugin'), 'ipc_entrypoint.py')
            self.assertEqual(ensure.call_args.args[0], runtime.REQUIREMENTS_IPC)
            bootstrap.relaunch(Path('plugin'), 'ipc_entrypoint.py', profile='extract')
            self.assertEqual(ensure.call_args.args[0],
                             {**runtime.REQUIREMENTS_IPC, **runtime.REQUIREMENTS_EXTRACT})
            bootstrap.relaunch(Path('plugin'), 'desktop_entrypoint.py', profile='bom')
            self.assertEqual(ensure.call_args.args[0],
                             {**runtime.REQUIREMENTS_IPC, **runtime.REQUIREMENTS_BOM})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'wayricad-tool.json').write_text(json.dumps(dict(
                tool='extract_pins_plugin', module='plugin',
                **{'class': 'Plugin'}, name='Extract Pins')))
            with patch.object(bootstrap, 'relaunch', return_value=0) as launch:
                self.assertEqual(launcher.main(root), 0)
                self.assertEqual(launch.call_args.kwargs['profile'], 'extract')

    def test_magnetics_launch_selects_complete_scientific_runtime(self):
        from wayricad_runtime import launcher, bootstrap
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'wayricad-tool.json').write_text(json.dumps(dict(tool='planar_magnetics_plugin', module='plugin', **{'class':'Plugin'}, name='Magnetics')))
            with patch.object(bootstrap, 'relaunch', return_value=0) as launch:
                self.assertEqual(launcher.main(root), 0)
                self.assertEqual(launch.call_args.kwargs['profile'], 'magnetics')
        with patch.object(runtime, 'ensure_runtime', return_value=Path('fake-python')) as ensure, patch.object(bootstrap.subprocess, 'call', return_value=0):
            bootstrap.relaunch(Path('plugin'), 'ipc_entrypoint.py', profile='magnetics')
        self.assertEqual(ensure.call_args.args[0], {**runtime.REQUIREMENTS_IPC, **runtime.REQUIREMENTS_MAGNETICS})

    def test_relaunch_preserves_editor_socket_and_argument_boundaries(self):
        from wayricad_runtime import bootstrap

        root = Path('C:/Projects/Example Board/WayriCAD')
        env = {'KICAD_API_SOCKET': 'editor-pipe', 'KICAD_API_TOKEN': 'editor-token'}
        with patch.object(bootstrap.sys, 'argv', ['ipc_entrypoint.py', '--board', 'C:/Projects/Example Board/board.kicad_pcb']), \
             patch.object(runtime, 'ensure_runtime', return_value=Path('managed-python')), \
             patch.object(runtime, 'child_environment', return_value=env), \
             patch.object(bootstrap.subprocess, 'call', return_value=0) as call:
            self.assertEqual(bootstrap.relaunch(root, 'ipc_entrypoint.py'), 0)
        self.assertEqual(call.call_args.args[0], ['managed-python', '-I', str(root/'ipc_entrypoint.py'),
                                                 '--board', 'C:/Projects/Example Board/board.kicad_pcb'])
        self.assertIs(call.call_args.kwargs['env'], env)
        self.assertNotIn('shell', call.call_args.kwargs)
        self.assertIs(call.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertIs(call.call_args.kwargs['stdout'], subprocess.DEVNULL)
        self.assertIs(call.call_args.kwargs['stderr'], subprocess.DEVNULL)

    def test_environment_keeps_invoking_instance_but_not_foreign_python(self):
        with patch.dict(runtime.os.environ, {
            'KICAD_API_SOCKET': 'instance-a', 'KICAD_API_TOKEN': 'secret',
            'PYTHONHOME': 'wrong', 'PYTHONPATH': 'wrong', 'VIRTUAL_ENV': 'wrong',
            'CONDA_PREFIX': 'wrong'}, clear=True):
            env = runtime.child_environment()
        self.assertEqual(env['KICAD_API_SOCKET'], 'instance-a')
        self.assertEqual(env['KICAD_API_TOKEN'], 'secret')
        self.assertEqual(env['PYTHONNOUSERSITE'], '1')
        for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
            self.assertNotIn(key, env)

    def test_native_only_never_creates_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'not-created'
            with patch.object(runtime, 'native_python', return_value=Path('native')), \
                 patch.object(runtime, '_probe', return_value='identity'), \
                 patch.object(runtime, '_run') as run:
                self.assertEqual(runtime.ensure_runtime(cache_dir=cache), Path('native'))
            self.assertFalse(cache.exists())
            run.assert_not_called()

    def test_failed_install_is_actionable_and_never_targets_native(self):
        with tempfile.TemporaryDirectory() as directory:
            def probe(python, requirements=()):
                return None if requirements else 'identity'
            calls = []
            def run(command, timeout=30, log=None):
                calls.append(command)
                return subprocess.CompletedProcess(command, 1 if 'pip' in command else 0)
            with patch.object(runtime, 'native_python', return_value=Path('native')), \
                 patch.object(runtime, '_probe', side_effect=probe), \
                 patch.object(runtime, '_pip_source_options', return_value=[]), \
                 patch.object(runtime, '_run', side_effect=run):
                with self.assertRaisesRegex(RuntimeError, 'Setup log:'):
                    runtime.ensure_runtime({'numpy': 'numpy>=1.24,<3'}, cache_dir=directory)
            self.assertIn('--system-site-packages', calls[0])
            self.assertIn('--only-binary=:all:', calls[1])
            self.assertNotEqual(calls[1][0], 'native')
            self.assertTrue(list(Path(directory).glob('*.log')))

    def test_pip_access_configuration_does_not_redirect_installation(self):
        listing = "global.index-url='https://mirror.invalid/simple'\n:env:.no-index='1'\n:env:.find-links='file:///wheelhouse'\ninstall.target='/outside'\n:env:.user='1'\n"
        with patch.object(runtime, '_run', return_value=subprocess.CompletedProcess([], 0, listing)):
            options = runtime._pip_source_options('python')
        self.assertEqual(options, ['--index-url', 'https://mirror.invalid/simple',
                                   '--find-links', 'file:///wheelhouse', '--no-index'])
        self.assertNotIn('--target', options)
        self.assertNotIn('--user', options)

    def test_lock_is_released_after_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runtime.lock'
            with self.assertRaises(ValueError):
                with runtime._lock(path, .1):
                    raise ValueError('interrupted')
            with runtime._lock(path, .1):
                self.assertTrue(path.is_file())

    def test_probe_requires_native_bindings_and_isolated_imports(self):
        with patch.object(runtime, '_run', return_value=subprocess.CompletedProcess([], 0, 'ok')) as run:
            self.assertEqual(runtime._probe('python', ['kipy']), 'ok')
        command = run.call_args.args[0]
        self.assertEqual(command[1], '-I')
        self.assertIn('pcbnew', command[-1])
        self.assertIn('wx', command[-1])
        self.assertIn('0.8.', command[-1])

    def test_foreign_virtual_environment_is_removed_from_path(self):
        foreign = str(Path('foreign-runtime').absolute())
        safe = str(Path('system-bin').absolute())
        with patch.dict(runtime.os.environ, {'VIRTUAL_ENV': foreign,
                        'PATH': runtime.os.pathsep.join([foreign, str(Path(foreign) / 'Scripts'), safe])}):
            self.assertEqual(runtime.child_environment()['PATH'], safe)

    def test_explicit_native_override_preserves_venv_executable_path(self):
        with patch.dict(runtime.os.environ, {'WAYRICAD_KICAD_PYTHON': 'venv/bin/python'}), \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(runtime, '_probe', return_value='identity'):
            self.assertEqual(runtime.native_python(), Path('venv/bin/python').absolute())

    def test_cached_runtime_is_probed_under_lock_without_reinstall(self):
        with tempfile.TemporaryDirectory() as directory:
            native = Path('native')
            requirements = {'numpy': 'numpy>=1.24,<3'}
            key = runtime.hashlib.sha256(runtime.json.dumps(
                [str(native), 'identity', sorted(requirements.items())]).encode()).hexdigest()[:20]
            executable = Path(directory) / key / ('Scripts/python.exe' if runtime.os.name == 'nt' else 'bin/python')
            executable.parent.mkdir(parents=True)
            executable.touch()
            def probe(python, modules=()):
                return None if python == native and modules else 'identity'
            with patch.object(runtime, 'native_python', return_value=native), \
                 patch.object(runtime, '_probe', side_effect=probe), \
                 patch.object(runtime, '_run') as run:
                self.assertEqual(runtime.ensure_runtime(requirements, cache_dir=directory), executable)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
