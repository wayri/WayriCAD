
"""Resolve PCB selections by saved item identity and preserve originating editor."""

from hashlib import sha256
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from trace_impedance_plugin.origin_selection import OriginSelection, TerminalIndex, saved_pick
from wayricad_runtime.context import LaunchContext


def item(uuid, net, number=''):
    return SimpleNamespace(
        m_Uuid=SimpleNamespace(AsString=lambda: uuid),
        GetNetname=lambda: net,
        GetNumber=lambda: number,
    )


def board(*, duplicate=False):
    start = item('a', '/Power', '1')
    extra = [item('duplicate', '/Power', '1')] if duplicate else []
    footprints = [
        SimpleNamespace(GetReference=lambda: 'J1', Pads=lambda: [start, *extra]),
        SimpleNamespace(GetReference=lambda: 'U1', Pads=lambda: [item('b', '/Power', '5'),
                                                               item('c', '/Power', '6')]),
    ]
    return SimpleNamespace(
        GetFootprints=lambda: footprints,
        GetTracks=lambda: [item('t', '/Power'), item('v', '/Power'), item('n', '')],
        Zones=lambda: [item('z', 'GND')],
    )


class PcbSelectionTest(TestCase):
    def test_route_uses_only_explicitly_selected_pad_labels(self):
        self.assertEqual(saved_pick(board(), ['T', 'v'], route=True), ('/Power', []))
        self.assertEqual(saved_pick(board(), ['b', 't'], route=True), ('/Power', ['U1.5']))
        self.assertEqual(saved_pick(board(), ['b', 'a', 't'], route=True), ('/Power', ['J1.1', 'U1.5']))

    def test_bulk_deduplicates_same_net_and_accepts_multiple_nets(self):
        self.assertEqual(saved_pick(board(), ['a', 't', 'z']), ['/Power', 'GND'])
        with self.assertRaisesRegex(ValueError, 'one net'):
            saved_pick(board(), ['a', 't', 'z'], route=True)

    def test_missing_unassigned_and_ambiguous_items_require_explicit_fix(self):
        for ids, message in [(['t', 'missing'], 'missing'), (['n'], 'no assigned net'),
                             ([], 'first'), (['a', 'b', 'c'], 'two endpoint pads')]:
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, message):
                saved_pick(board(), ids, route=True)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            saved_pick(board(duplicate=True), ['a'], route=True)
        self.assertEqual(saved_pick(board(duplicate=True), ['a']), ['/Power'])

    def test_refresh_keeps_only_unique_physical_terminals(self):
        old = TerminalIndex(board())
        ids = old.ids('/Power', ('J1.1', 'U1.5'))
        renamed = SimpleNamespace(GetFootprints=lambda: [
            SimpleNamespace(GetReference=lambda:'J7', Pads=lambda:[item('a','/Renamed','3')]),
            SimpleNamespace(GetReference=lambda:'U2', Pads=lambda:[item('b','/Renamed','5')])])
        self.assertEqual(TerminalIndex(renamed).restore('/Power',ids,['/Renamed']),
                         ('/Renamed',['J7.3','U2.5']))
        new_ids = SimpleNamespace(GetFootprints=lambda: [
            SimpleNamespace(GetReference=lambda:'J1', Pads=lambda:[item('replaced','/Power','1')])])
        self.assertEqual(TerminalIndex(new_ids).restore('/Power',ids,['/Power']),('/Power',['','']))
        duplicate = TerminalIndex(board(duplicate=True))
        self.assertEqual(duplicate.restore('/Power',ids,['/Power']),('/Power',['','U1.5']))

    def test_origin_reads_and_writes_use_same_launch_identity_and_digest(self):
        # Use this source as immutable bytes to avoid creating PCB files.
        path = __file__
        context = LaunchContext('ipc://test-pcb', 'synthetic-session')
        with patch('trace_impedance_plugin.origin_selection.LaunchContext.capture', return_value=context):
            origin = OriginSelection(path)
        with patch('trace_impedance_plugin.origin_selection.SavedSelectionReader') as reader:
            reader.return_value.read.return_value = ['a']
            self.assertEqual(origin.read(), ['a'])
            digest = sha256(origin.path.read_bytes()).hexdigest()
            reader.assert_called_once_with(origin.path, expected_sha256=digest, launch_context=context)
            reader.return_value.expected_sha256 = digest
            with patch('trace_impedance_plugin.origin_selection.select_origin', return_value={'count': 1}) as select:
                self.assertEqual(origin.select_net('/Power'), {'count': 1})
                select.assert_called_once_with(origin.path, net='/Power', expected_sha256=digest,
                                               focus=True, return_details=True, launch_context=context)
        with patch('trace_impedance_plugin.origin_selection.source_stamp', return_value=None):
            with self.assertRaisesRegex(ValueError, 'changed'):
                origin.read()
