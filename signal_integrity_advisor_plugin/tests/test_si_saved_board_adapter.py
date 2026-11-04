"""Saved-board consumers preserve conversion evidence and reject stale results."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from signal_integrity_advisor_plugin import neighbours, service


class SavedBoardAdapterTests(unittest.TestCase):
    def test_neighbour_worker_loads_adapter_and_preserves_original_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('(kicad_pcb (version 20260206))', encoding='utf-8')
            original = path.read_bytes()
            evidence = {'schema': 'wayricad.saved-board-analysis/v1', 'source_path': str(path)}
            snapshot = SimpleNamespace(assert_current=Mock(), record=evidence)
            board = SimpleNamespace(_wayricad_saved_board=snapshot)
            pcbnew = SimpleNamespace(LoadBoard=Mock())
            request = {'board_path': str(path), 'mode': 'neighbours',
                       'source_fingerprints': service.source_fingerprints(path)}
            with patch.dict(sys.modules, {'pcbnew': pcbnew}), \
                 patch.object(service, 'load_board', return_value=board) as load, \
                 patch.object(neighbours, 'map_board', return_value={}) as mapper:
                result = service.execute(request)['neighbours']
                load.assert_called_once_with(str(path.resolve()), pcbnew=pcbnew)
                mapper.call_args.kwargs['guard']()
            self.assertGreaterEqual(snapshot.assert_current.call_count, 2)
            self.assertEqual(result['saved_board_provenance'], evidence)
            self.assertEqual(result['source_path'], str(path.resolve()))
            self.assertEqual(path.read_bytes(), original)
            pcbnew.LoadBoard.assert_not_called()

    def test_worker_does_not_return_stale_converted_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('fixture', encoding='utf-8')
            snapshot = SimpleNamespace(assert_current=Mock(side_effect=ValueError('CLI changed')))
            board = SimpleNamespace(_wayricad_saved_board=snapshot)
            request = {'board_path': str(path), 'mode': 'neighbours',
                       'source_fingerprints': service.source_fingerprints(path)}
            with patch.dict(sys.modules, {'pcbnew': SimpleNamespace()}), \
                 patch.object(service, 'load_board', return_value=board), \
                 patch.object(neighbours, 'map_board', return_value={}):
                with self.assertRaisesRegex(ValueError, 'CLI changed'):
                    service.execute(request)

    def test_native10_worker_keeps_direct_load_and_result_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('(kicad_pcb (version 20260206))', encoding='utf-8')
            board = object()
            pcbnew = SimpleNamespace(LoadBoard=Mock(return_value=board))
            request = {'board_path': str(path), 'mode': 'neighbours',
                       'source_fingerprints': service.source_fingerprints(path)}
            with patch.dict(sys.modules, {'pcbnew': pcbnew}), \
                 patch.object(neighbours, 'map_board', return_value={}):
                result = service.execute(request)['neighbours']
            pcbnew.LoadBoard.assert_called_once_with(str(path.resolve()))
            self.assertNotIn('saved_board_provenance', result)
