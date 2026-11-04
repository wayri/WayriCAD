"""Thermal saved-board boundaries guard and retain converted snapshot evidence."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quick_therm_plugin import component_model_worker, component_models, service, thermal_transient


class SavedBoardAdapterTests(unittest.TestCase):
    def test_cancelled_worker_uses_parent_owned_converter_scratch(self):
        process = SimpleNamespace(poll=Mock(return_value=None), terminate=Mock(), wait=Mock())
        cancellations = iter([False, True])
        with patch('wayricad_runtime.runtime_setup.ensure_runtime', return_value='python'), \
             patch('wayricad_runtime.runtime_setup.child_environment', return_value={}), \
             patch.object(service.subprocess, 'Popen', return_value=process) as popen, \
             patch('wayricad_runtime.analysis_process.stop_worker', side_effect=lambda child: child.terminate()) as stop:
            with self.assertRaises(InterruptedError):
                service.run_job({}, cancelled=lambda: next(cancellations))
        process.terminate.assert_called_once_with()
        stop.assert_called_once_with(process)
        scratch = Path(popen.call_args.kwargs['env']['WAYRICAD_ANALYSIS_SCRATCH'])
        self.assertEqual(scratch, Path(popen.call_args.args[0][-2]).parent)
        self.assertFalse(scratch.exists())

    def test_model_worker_inherits_converter_and_parent_scratch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = SimpleNamespace(poll=lambda: 0, returncode=0)
            with patch.dict('os.environ', {'WAYRICAD_ANALYSIS_CLI': 'origin-cli'}), \
                 patch.object(component_models.subprocess, 'Popen', return_value=process) as popen:
                component_models._run(['python', 'prepare'], root, None, 0)
            environment = popen.call_args.kwargs['env']
            self.assertEqual(environment['WAYRICAD_ANALYSIS_CLI'], 'origin-cli')
            self.assertEqual(environment['WAYRICAD_ANALYSIS_SCRATCH'], str(root))

    def test_desktop_binds_converter_to_authenticated_editor(self):
        from quick_therm_plugin import desktop_entrypoint
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('fixture', encoding='utf-8')
            client = object(); process = SimpleNamespace(wait=Mock(return_value=0))
            with patch.object(sys, 'argv', ['desktop_entrypoint.py']), \
                 patch.dict('os.environ', {'WAYRICAD_SPLASH_READY': '1'}), \
                 patch('wayricad_runtime.bootstrap.relaunch', return_value=None), \
                 patch('wayricad_runtime.native_analysis.child_environment', return_value={'base': 'env'}), \
                 patch('wayricad_runtime.context.connect', return_value=client), \
                 patch('wayricad_runtime.context.saved_board', return_value=path), \
                 patch('wayricad_runtime.saved_board.origin_environment', return_value={'origin': 'bound'}) as origin, \
                 patch.object(desktop_entrypoint.subprocess, 'Popen', return_value=process) as popen:
                self.assertEqual(desktop_entrypoint.main(), 0)
            origin.assert_called_once_with(client, {'base': 'env'})
            environment=popen.call_args.kwargs['env']
            self.assertEqual(environment['origin'], 'bound')
            self.assertFalse(Path(environment['WAYRICAD_ANALYSIS_SCRATCH']).exists())

    def test_inventory_adapter_guard_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('fixture', encoding='utf-8')
            evidence = {'source_path': str(path)}
            snapshot = SimpleNamespace(assert_current=Mock(), record=evidence)
            board = SimpleNamespace(GetFootprints=lambda: [], _wayricad_saved_board=snapshot)
            pcbnew = SimpleNamespace()
            with patch.dict(sys.modules, {'pcbnew': pcbnew}), \
                 patch('wayricad_runtime.saved_board.load_board', return_value=board) as load:
                result = service.execute({'action': 'inspect', 'board_path': str(path)})
            load.assert_called_once_with(str(path.resolve()), pcbnew=pcbnew)
            snapshot.assert_current.assert_called_once_with()
            self.assertEqual(result['saved_board_provenance'], evidence)
            self.assertEqual(path.read_text(encoding='utf-8'), 'fixture')

    def test_inventory_rejects_stale_converter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('fixture', encoding='utf-8')
            snapshot = SimpleNamespace(assert_current=Mock(side_effect=ValueError('CLI changed')), record={})
            board = SimpleNamespace(GetFootprints=lambda: [], _wayricad_saved_board=snapshot)
            with patch.dict(sys.modules, {'pcbnew': SimpleNamespace()}), \
                 patch('wayricad_runtime.saved_board.load_board', return_value=board):
                with self.assertRaisesRegex(ValueError, 'CLI changed'):
                    service.execute({'action': 'inspect', 'board_path': str(path)})

    def test_transient_retains_all_snapshots_and_guards_after_solve(self):
        with tempfile.TemporaryDirectory() as directory:
            records = []; boards = []; loaded = []
            for index in range(4):
                path = Path(directory) / f'board{index}.kicad_pcb'
                path.write_text('fixture', encoding='utf-8')
                evidence = {'source_path': str(path)}
                snapshot = SimpleNamespace(assert_current=Mock(), record=evidence)
                loaded.append(SimpleNamespace(GetFootprints=lambda: [], _wayricad_saved_board=snapshot))
                records.append(evidence)
                boards.append({'name': f'B{index}', 'board_path': str(path), 'components': []})
            def solve(_):
                self.assertTrue(all(not item._wayricad_saved_board.assert_current.called for item in loaded))
                return {}
            with patch.dict(sys.modules, {'pcbnew': SimpleNamespace()}), \
                 patch('wayricad_runtime.saved_board.load_board', side_effect=loaded) as load, \
                 patch.object(thermal_transient, 'solve_coupled_transient', side_effect=solve):
                result = thermal_transient.run_saved_board_transient({'boards': boards})
            self.assertEqual(load.call_count, 4)
            self.assertEqual(result['saved_board_provenance'], {f'B{i}': row for i, row in enumerate(records)})
            for item in loaded:
                item._wayricad_saved_board.assert_current.assert_called_once_with()

    def test_component_private_snapshot_guard_precedes_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'board.kicad_pcb'
            path.write_text('fixture', encoding='utf-8')
            evidence = {'source_path': str(path)}
            snapshot = SimpleNamespace(assert_current=Mock(), record=evidence)
            board = SimpleNamespace(GetFootprints=lambda: [], _wayricad_saved_board=snapshot,
                                    GetDesignSettings=lambda: SimpleNamespace(GetBoardThickness=lambda: 1.6))
            def save(destination, _board):
                snapshot.assert_current.assert_called_once_with()
                self.assertEqual(Path(destination), root / 'snapshot.kicad_pcb')
                return True
            pcbnew = SimpleNamespace(ToMM=lambda value: value, SaveBoard=Mock(side_effect=save))
            with patch.dict(sys.modules, {'pcbnew': pcbnew}), \
                 patch('wayricad_runtime.saved_board.load_board', return_value=board), \
                 patch.object(component_model_worker, 'model_variables', return_value={}):
                component_model_worker.prepare({'board_path': str(path), 'root': str(root),
                    'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            self.assertEqual(snapshot.assert_current.call_count, 2)
            self.assertEqual(json.loads((root / 'prepared.json').read_text())['saved_board_provenance'], evidence)
            self.assertEqual(path.read_text(encoding='utf-8'), 'fixture')
