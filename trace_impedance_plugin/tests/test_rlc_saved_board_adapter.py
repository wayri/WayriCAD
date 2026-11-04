"""Trace analysis binds converted native geometry to its saved source."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from trace_impedance_plugin import bulk_ui, cli


class SavedBoardAdapterTests(unittest.TestCase):
    def test_inventory_uses_adapter_guard_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('fixture', encoding='utf-8')
            evidence = {'source_path': str(path)}
            snapshot = SimpleNamespace(assert_current=Mock(), record=evidence)
            board = SimpleNamespace(_wayricad_saved_board=snapshot)
            pcbnew = SimpleNamespace()
            engine = SimpleNamespace(net_names=lambda: [], ground_nets=lambda: [],
                                     available_layers=lambda: [], zone_options=lambda _: [])
            args = cli.parser().parse_args(['inspect', str(path)])
            with patch.dict(sys.modules, {'pcbnew': pcbnew}), \
                 patch.object(cli, 'load_board', return_value=board) as load, \
                 patch('trace_impedance_plugin.measurement.TraceMeasurementEngine', return_value=engine):
                result = cli.analyze(args)
            load.assert_called_once_with(str(path.resolve()), pcbnew=pcbnew)
            snapshot.assert_current.assert_called_once_with()
            self.assertEqual(result['saved_board_provenance'], evidence)
            self.assertEqual(result['board'], str(path.resolve()))

    def test_bulk_guard_rejects_stale_conversion_before_return(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('fixture', encoding='utf-8')
            snapshot = SimpleNamespace(assert_current=Mock(side_effect=ValueError('CLI changed')))
            board = SimpleNamespace(_wayricad_saved_board=snapshot)
            with patch.dict(sys.modules, {'pcbnew': SimpleNamespace()}), \
                 patch.object(bulk_ui, 'load_board', return_value=board), \
                 patch('trace_impedance_plugin.measurement.TraceMeasurementEngine'), \
                 patch('trace_impedance_plugin.bulk.extract_board', return_value={}):
                with self.assertRaisesRegex(ValueError, 'CLI changed'):
                    bulk_ui.extract_saved(path)

    def test_native10_bulk_preserves_direct_load_and_document_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('(kicad_pcb (version 20260206))', encoding='utf-8')
            original = path.read_bytes()
            board = object()
            pcbnew = SimpleNamespace(LoadBoard=Mock(return_value=board))
            with patch.dict(sys.modules, {'pcbnew': pcbnew}), \
                 patch('trace_impedance_plugin.measurement.TraceMeasurementEngine'), \
                 patch('trace_impedance_plugin.bulk.extract_board', return_value={}):
                document, loaded = bulk_ui.extract_saved(path)
            pcbnew.LoadBoard.assert_called_once_with(str(path.resolve()))
            self.assertIs(loaded, board)
            self.assertNotIn('saved_board_provenance', document)
            self.assertEqual(path.read_bytes(), original)
