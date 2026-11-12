import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from manufacturing_readiness_plugin import fab_reference


class ReferenceExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.board = self.root / 'demo.kicad_pcb'
        self.board.write_text('(kicad_pcb (version 20240108))', encoding='utf-8')
        self.destination = self.root / 'reference.d356'

    def command(self, cli, arguments, folder, timeout_s, cancel):
        if arguments == ['--version']:
            return 'fixture-1'
        Path(folder, 'reference.d356').write_bytes(b'P  CODE 00\n999\n')
        return 'fixture native exporter'

    def test_reference_and_receipt_are_read_only_design_evidence(self):
        original = self.board.read_bytes()
        with patch.object(fab_reference, '_command', side_effect=self.command):
            receipt = fab_reference.export_reference(self.board, self.destination, cli=sys.executable)
        self.assertEqual(self.board.read_bytes(), original)
        self.assertEqual(receipt['basis'], 'design-netlist')
        self.assertEqual(receipt['output_sha256'], hashlib.sha256(self.destination.read_bytes()).hexdigest())
        self.assertEqual(json.loads(self.destination.with_suffix('.d356.receipt.json').read_text()), receipt)
        self.assertIn('not Gerber', receipt['notice'])

    def test_existing_outputs_are_never_silently_replaced(self):
        self.destination.write_text('keep', encoding='utf-8')
        with patch.object(fab_reference, '_command') as command:
            with self.assertRaisesRegex(ValueError, 'new output'):
                fab_reference.export_reference(self.board, self.destination, cli=sys.executable)
        command.assert_not_called()
        self.assertEqual(self.destination.read_text(), 'keep')

    def test_source_drift_prevents_publication(self):
        def mutate(*args):
            result = self.command(*args)
            if args[1] != ['--version']:
                self.board.write_text('changed', encoding='utf-8')
            return result
        with patch.object(fab_reference, '_command', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'changed during export'):
                fab_reference.export_reference(self.board, self.destination, cli=sys.executable)
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.destination.with_suffix('.d356.receipt.json').exists())

    def test_pre_cancelled_run_never_starts_native_command(self):
        cancel = threading.Event(); cancel.set()
        with patch.object(fab_reference, '_command') as command:
            with self.assertRaises(InterruptedError):
                fab_reference.export_reference(self.board, self.destination, cli=sys.executable, cancel=cancel)
        command.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_native_timeout_terminates_owned_process(self):
        with self.assertRaises(TimeoutError):
            fab_reference._command(sys.executable, ['-c', 'import time;time.sleep(10)'], self.root, .05, None)

    def test_boolean_or_infinite_timeout_is_rejected(self):
        for timeout in (True, float('inf'), -1):
            with self.assertRaises(ValueError):
                fab_reference.export_reference(self.board, self.destination, cli=sys.executable, timeout_s=timeout)

    def test_native_receipt_binds_only_matching_saved_board(self):
        with patch.object(fab_reference, '_command', side_effect=self.command):
            fab_reference.export_reference(self.board, self.destination, cli=sys.executable)
        binding = fab_reference.check_reference_receipt(self.destination, self.board)
        self.assertEqual(binding['status'], 'BOUND_TO_SAVED_BOARD')
        self.board.write_text('different saved design', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'different saved PCB'):
            fab_reference.check_reference_receipt(self.destination, self.board)

    def test_tampered_reference_is_rejected_by_receipt(self):
        with patch.object(fab_reference, '_command', side_effect=self.command):
            fab_reference.export_reference(self.board, self.destination, cli=sys.executable)
        self.destination.write_text('different netlist', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'differ from'):
            fab_reference.check_reference_receipt(self.destination)

    def test_absent_receipt_never_implies_board_correspondence(self):
        self.destination.write_text('imported external reference', encoding='utf-8')
        self.assertEqual(fab_reference.check_reference_receipt(self.destination, self.board)['status'], 'UNVERIFIED')

    def test_malformed_reference_receipt_is_rejected(self):
        self.destination.write_text('input', encoding='utf-8')
        sidecar = self.destination.with_suffix('.d356.receipt.json')
        for payload in ('{"schema":1,"schema":2}', '{"schema":NaN}'):
            sidecar.write_text(payload, encoding='utf-8')
            with self.assertRaises(ValueError):
                fab_reference.check_reference_receipt(self.destination)


if __name__ == '__main__':
    unittest.main()
