"""Native imported comparison lifecycle, sorting, scale and guided flow."""
import json
import hashlib
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    import wx
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'Requires native wxPython')
class FabCompareUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from manufacturing_readiness_plugin.fab_compare_ui import FabCompareDialog
        cls.Dialog = FabCompareDialog
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fab-ui-')
        self.root = Path(self.temp.name)
        self.reference, self.observed = self.root/'reference.json', self.root/'cam.json'
        terminals = [dict(reference=reference,pin=str(pin),net='N'+str(pin))
                     for reference in ('J1','U1') for pin in range(1,10)]
        source = dict(schema='wayricad.fab-netlist/v1',units='mm',terminals=terminals,
                      provenance={'origin':'synthetic native UI test'})
        self.reference.write_text(json.dumps(source))
        source['terminals'] = [{**terminal,'net':'168'} for terminal in terminals]
        self.observed.write_text(json.dumps(source))

    def tearDown(self):
        self.temp.cleanup()

    def wait(self, predicate, timeout=30):
        deadline = time.monotonic()+timeout
        while not predicate() and time.monotonic() < deadline:
            wx.Yield()
            time.sleep(.01)
        self.assertTrue(predicate(),'Timed out waiting for comparison worker')

    def dialog(self, board=None):
        dialog = self.Dialog(None,reference_path=self.reference,board_path=board)
        dialog.observed.SetPath(str(self.observed))
        dialog.confirm.SetValue(True)
        wx.Yield()
        return dialog

    def finish(self, dialog):
        worker = dialog._thread
        dialog.Destroy()
        if worker is not None:
            worker.join(10)
            self.assertFalse(worker.is_alive())
        wx.Yield()

    def test_actual_short_full_pin_details_and_identity_survive_sort(self):
        dialog = self.dialog()
        try:
            dialog.compare()
            self.assertFalse(dialog.compare_button.IsEnabled())
            self.wait(lambda: dialog._thread is None)
            self.assertEqual(dialog.report['status'],'FAIL')
            self.assertEqual(dialog.table.GetItemCount(),1)
            key = dialog.table.GetItemData(0)
            self.assertIn('U1',dialog.details.GetValue())
            self.assertEqual(len(dialog._rows[key]['details']['endpoints']),18)
            dialog.sort(SimpleNamespace(GetColumn=lambda:2))
            self.assertEqual(dialog.table.GetItemData(0),key)
            self.assertIn('"design_groups"',dialog.details.GetValue())
            self.assertTrue(dialog.export_button.IsEnabled())
            self.assertIn('Reference binding: UNVERIFIED',dialog.summary.GetValue())
        finally:
            self.finish(dialog)

    def test_native_receipt_binding_is_guarded_and_missing_receipt_is_unverified(self):
        from manufacturing_readiness_plugin.fab_compare_ui import compare_files
        from manufacturing_readiness_plugin.fab_compare_report import validate_report
        board = self.root/'controller.kicad_pcb'
        board.write_bytes(b'saved board fixture')
        self.assertEqual(compare_files(str(self.reference),str(self.observed),True,str(board))['reference_binding']['status'],'UNVERIFIED')
        sidecar = self.reference.with_suffix(self.reference.suffix+'.receipt.json')
        receipt = dict(schema='wayricad.fab-reference/v1',basis='design-netlist',
            source_sha256=hashlib.sha256(board.read_bytes()).hexdigest(),
            output_sha256=hashlib.sha256(self.reference.read_bytes()).hexdigest())
        sidecar.write_text(json.dumps(receipt))
        report = compare_files(str(self.reference),str(self.observed),True,str(board))
        self.assertEqual(report['reference_binding']['status'],'BOUND_TO_SAVED_BOARD')
        self.assertTrue(any(source['role']=='native receipt' for source in report['report_metadata']['sources']))
        sidecar.write_bytes(sidecar.read_bytes()+b'\n')
        with self.assertRaises(ValueError):
            validate_report(report)
        board.write_bytes(b'another saved board')
        with self.assertRaisesRegex(ValueError,'different saved PCB'):
            compare_files(str(self.reference),str(self.observed),True,str(board))

    def test_receipt_snapshot_hash_must_equal_checked_receipt(self):
        from manufacturing_readiness_plugin.fab_compare_ui import compare_files
        sidecar = self.root/'checked.receipt.json'
        sidecar.write_text('{}')
        with patch('manufacturing_readiness_plugin.fab_reference.check_reference_receipt',return_value={
                'status':'REFERENCE_HASH_CHECKED','receipt_path':str(sidecar),'receipt_sha256':'0'*64}):
            with self.assertRaisesRegex(ValueError,'receipt changed'):
                compare_files(str(self.reference),str(self.observed),True)

    def test_cancel_edits_and_source_changes_discard_late_results_with_one_worker(self):
        from manufacturing_readiness_plugin.fab_compare_ui import compare_files
        for action in ('cancel','edit','source'):
            with self.subTest(action=action):
                dialog = self.dialog()
                entered, release = threading.Event(), threading.Event()
                threads = []
                def delayed(*snapshot, cancel=None):
                    threads.append(threading.get_ident())
                    result = compare_files(*snapshot)
                    entered.set()
                    if not release.wait(10):
                        raise RuntimeError('Test worker not released')
                    return result
                try:
                    with patch('manufacturing_readiness_plugin.fab_compare_ui.compare_files',side_effect=delayed) as comparator:
                        dialog.compare()
                        self.wait(entered.is_set)
                        worker = dialog._thread
                        heartbeat = threading.Event()
                        wx.CallAfter(heartbeat.set)
                        self.wait(heartbeat.is_set)
                        self.assertNotEqual(threads[0],threading.get_ident())
                        dialog.compare()
                        self.assertIs(dialog._thread,worker)
                        self.assertEqual(comparator.call_count,1)
                        if action == 'cancel':
                            dialog.cancel()
                        elif action == 'edit':
                            dialog.confirm.SetValue(False)
                            dialog.invalidate()
                        else:
                            self.observed.write_bytes(self.observed.read_bytes()+b'\n')
                        release.set()
                        self.wait(lambda:dialog._thread is None)
                        self.assertIsNone(dialog.report)
                        self.assertFalse(dialog.export_button.IsEnabled())
                        self.assertTrue(dialog.compare_button.IsEnabled())
                finally:
                    release.set()
                    self.finish(dialog)

    def test_destroy_never_dispatches_worker_to_deleted_controls(self):
        dialog = self.dialog()
        entered, release = threading.Event(), threading.Event()
        seen = []
        def delayed(*snapshot,cancel=None):
            entered.set()
            release.wait(10)
            seen.append(cancel())
            return None
        with patch('manufacturing_readiness_plugin.fab_compare_ui.compare_files',side_effect=delayed):
            dialog.compare()
            self.wait(entered.is_set)
            worker = dialog._thread
            dialog.Destroy()
            wx.Yield()
            try:
                with patch('manufacturing_readiness_plugin.fab_compare_ui.wx.CallAfter') as dispatch:
                    release.set()
                    worker.join(10)
                    self.assertFalse(worker.is_alive())
                    dispatch.assert_not_called()
                    self.assertEqual(seen,[True])
            finally:
                release.set()
                worker.join(10)

    def test_scale_caps_display_only_and_detail_preview_is_bounded(self):
        from manufacturing_readiness_plugin.fab_compare_ui import compare_files, detail_preview, MAX_VISIBLE_ROWS
        from manufacturing_readiness_plugin.fab_compare_report import build_report, render_report
        report = compare_files(str(self.reference),str(self.observed),True)
        report['issues'] = [dict(code='review',message='Finding '+str(index)) for index in range(5005)]
        report = build_report(report,sources=report['report_metadata']['sources'])
        dialog = self.dialog()
        try:
            with patch('manufacturing_readiness_plugin.fab_compare_ui.compare_files',return_value=report):
                dialog.compare()
                self.wait(lambda:dialog._thread is None)
            self.assertEqual(dialog.table.GetItemCount(),MAX_VISIBLE_ROWS)
            self.assertIn('Showing 5000 of 5006',dialog.notice.GetLabel())
            self.assertEqual(len(json.loads(render_report(dialog.report,'json'))['issues']),5005)
            preview = detail_preview({'mapping':'x'*10000},limit=500)
            self.assertLess(len(preview),650)
            self.assertIn('export JSON',preview)
            key = dialog.table.GetItemData(1)
            dialog.table.Select(1)
            dialog._show_row(key)
            dialog.sort(SimpleNamespace(GetColumn=lambda:5))
            selected = dialog.table.GetFirstSelected()
            self.assertEqual(dialog.table.GetItemData(selected),key)
        finally:
            self.finish(dialog)

    def test_guided_reference_export_fills_picker_and_uses_integrated_html_help(self):
        from manufacturing_readiness_plugin.fab_compare_report import source_snapshot
        board = self.root/'controller.kicad_pcb'
        board.write_text('(kicad_pcb)')
        output = self.root/'native-reference.d356'
        dialog = self.dialog(board)
        picker = Mock()
        picker.__enter__ = Mock(return_value=picker)
        picker.__exit__ = Mock(return_value=False)
        picker.ShowModal.return_value = wx.ID_OK
        picker.GetPath.return_value = str(output)
        def reference_export(board_path,destination,*,cancel=None):
            output.write_text('Synthetic helper response for UI lifecycle test')
            return dict(destination=str(output),receipt={'basis':'design-netlist',
                        'source_sha256':hashlib.sha256(board.read_bytes()).hexdigest()},
                        sources=[source_snapshot(board,'board context'),source_snapshot(output,'design reference')])
        try:
            with patch('manufacturing_readiness_plugin.fab_compare_ui.wx.FileDialog',return_value=picker), patch(
                    'manufacturing_readiness_plugin.fab_compare_ui._reference_files',side_effect=reference_export):
                dialog.export_reference()
                self.assertFalse(dialog.reference_button.IsEnabled())
                self.wait(lambda:dialog._thread is None)
            self.assertEqual(dialog.reference.GetPath(),str(output))
            self.assertIsNone(dialog.report)
            self.assertFalse(dialog.export_button.IsEnabled())
            self.assertIn('Design reference and receipt exported',dialog.notice.GetLabel())
            with patch('wayricad_runtime.help.open_help') as open_help:
                dialog.help()
                self.assertTrue(Path(open_help.call_args.args[1]).is_file())
                self.assertEqual(Path(open_help.call_args.args[1]).suffix,'.html')
        finally:
            self.finish(dialog)

    def test_guided_reference_adapter_rejects_wrong_source_receipt(self):
        from manufacturing_readiness_plugin.fab_compare_ui import _reference_files
        board, output = self.root/'controller.kicad_pcb', self.root/'exported.d356'
        board.write_bytes(b'original saved board')
        def fake_export(board_path,destination,**kwargs):
            Path(destination).write_bytes(b'synthetic adapter response')
            return dict(basis='design-netlist',source_sha256='0'*64,
                        output_sha256=hashlib.sha256(Path(destination).read_bytes()).hexdigest())
        with patch('manufacturing_readiness_plugin.fab_reference.export_reference',side_effect=fake_export):
            with self.assertRaisesRegex(ValueError,'receipt does not match'):
                _reference_files(str(board),str(output))
