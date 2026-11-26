import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from signal_integrity_advisor_plugin import live_screen, service
from wayricad_runtime import live_pcb, saved_board


class LiveScreenTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('example.kicad_pcb').resolve()
        self.snapshot = self.path.with_name('editor-copy.kicad_pcb')
        self.request = {'board_path': str(self.path), 'source_fingerprints': {str(self.path): 'saved'},
                        'net': 'DATA', 'start': 'J1.1', 'end': 'U1.1',
                        'reference': 'Auto', 'inputs': {'return_nets': ['GND'], 'frequency_mhz': 800}}
        self.reviewed = {'J1.1': 'source', 'U1.1': 'load'}

    def test_scope_contains_only_signal_and_selected_returns(self):
        self.assertEqual(live_screen.watched_nets(self.request), ('DATA', 'GND'))
        self.request['inputs'].clear()
        self.assertEqual(live_screen.watched_nets(self.request), ('DATA',))

    def run_sample(self, current_stamp):
        board = object()
        route = object()
        origin = object()
        captured = []

        @contextmanager
        def capture(path, context, *, watch_nets):
            self.assertEqual((path, context, watch_nets), (str(self.path), origin, ('DATA', 'GND')))
            yield self.snapshot, {'origin_sha256': 'saved', 'route_stamp': 'before'}

        with (patch.object(live_pcb, 'capture_live_pcb', capture),
              patch.object(live_pcb, 'route_stamp', return_value=current_stamp),
              patch.object(saved_board, 'load_board', return_value=board),
              patch.object(service, 'require_source'),
              patch.object(service, 'source_fingerprints', return_value={'copy': 'private'}),
              patch.object(live_screen, 'require_endpoints') as verify,
              patch.object(service, 'run_job', return_value={'report': {'source_path': 'copy', 'delay_ns': 2.0}}) as solve,
              patch.object(service, 'restore_path', return_value=route)):
            result = live_screen.run_live_screen(self.request, origin, ('DATA', 'GND'), self.reviewed,
                                                 lambda: False, captured.append)
        verify.assert_called_once_with(board, 'DATA', self.reviewed)
        worker_request = solve.call_args.args[0]
        self.assertEqual(worker_request['board_path'], str(self.snapshot))
        self.assertEqual(worker_request['start'], self.request['start'])
        self.assertEqual(worker_request['end'], self.request['end'])
        self.assertEqual(worker_request['inputs'], self.request['inputs'])
        self.assertEqual(captured, ['before'])
        return result, route, board

    def test_live_route_keeps_reviewed_setup_and_loses_saved_provenance(self):
        result, route, board = self.run_sample('before')
        self.assertEqual(result, ({'delay_ns': 2.0, 'live_editor_preview': True}, route, board))

    def test_edit_during_worker_discards_result_and_keeps_capture_baseline(self):
        result, _, _ = self.run_sample('after')
        self.assertIsNone(result)

    def test_changed_uuid_and_ambiguous_pads_rejected(self):
        def pad(uuid):
            return SimpleNamespace(GetNumber=lambda: '1', GetNetname=lambda: 'DATA',
                                   m_Uuid=SimpleNamespace(AsString=lambda: uuid))

        footprint = SimpleNamespace(GetReference=lambda: 'J1', Pads=lambda: [pad('source')])
        board = SimpleNamespace(GetFootprints=lambda: [footprint])
        live_screen.require_endpoints(board, 'DATA', {'J1.1': 'source'})
        with self.assertRaisesRegex(ValueError, 'changed identity'):
            live_screen.require_endpoints(board, 'DATA', {'J1.1': 'recreated'})
        footprint.Pads = lambda: [pad('source'), pad('duplicate')]
        with self.assertRaisesRegex(ValueError, 'changed identity'):
            live_screen.require_endpoints(board, 'DATA', {'J1.1': 'source'})
