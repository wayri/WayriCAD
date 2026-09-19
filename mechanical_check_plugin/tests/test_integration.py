"""Saved-file launch, dependency discovery and command regression coverage."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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
            with patch.object(entry.importlib.util, 'find_spec', return_value=None), \
                 patch.object(runtime, 'discover', return_value={'kicad_python': native}), \
                 patch.dict(os.environ, {'PYTHONHOME': 'incompatible', 'PYTHONPATH': 'incompatible'}), \
                 patch.object(entry.subprocess, 'run', return_value=SimpleNamespace(returncode=7)) as run:
                self.assertEqual(entry.main(['--gui', 'board with spaces.kicad_pcb']), 7)
                args, kwargs = run.call_args
                self.assertEqual(args[0], [native, str(ROOT / 'launch.py'), '--gui', 'board with spaces.kicad_pcb'])
                self.assertNotIn('PYTHONHOME', kwargs['env'])
                self.assertNotIn('PYTHONPATH', kwargs['env'])

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
