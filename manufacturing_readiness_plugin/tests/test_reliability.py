"""DFM/DFA failure recovery and native GUI thread-boundary regressions."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from manufacturing_readiness_plugin.assembly_checks import apply_assembly_findings, corrective_action
from manufacturing_readiness_plugin.common_checklist import with_common_checks
from manufacturing_readiness_plugin import analysis, checklists
from manufacturing_readiness_plugin import dfm_checks, vendor_catalog


TEST_TEMP_ROOT = Path(os.environ.get('WAYRICAD_MANUFACTURING_TEST_TEMP', tempfile.gettempdir())).resolve()


class SavedLayerPreflightTests(unittest.TestCase):
    def test_saved_layer_mismatch_is_rejected_before_cli_discovery(self):
        profile = vendor_catalog.load_catalog()['profiles'][0]
        context = dict(board_type='rigid', copper_oz=1,
                       copper_basis='vendor_order_option', layers=4)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            path = Path(directory) / 'board.kicad_pcb'
            path.write_text('(kicad_pcb (layers (0 "F.Cu" signal) '
                            '(31 "B.Cu" signal) (44 "Edge.Cuts" user)))', encoding='utf-8')
            before = path.read_bytes()
            with patch.object(dfm_checks, 'find_cli') as find, \
                    patch.object(dfm_checks.subprocess, 'Popen') as launch:
                with self.assertRaisesRegex(ValueError, 'Saved PCB has 2 copper layers.*specifies 4'):
                    dfm_checks.audit_snapshot(path, profile, context)
                find.assert_not_called(); launch.assert_not_called()
            self.assertEqual(before, path.read_bytes())

    def test_missing_or_ambiguous_saved_layer_table_is_rejected(self):
        profile = vendor_catalog.load_catalog()['profiles'][0]
        context = dict(board_type='rigid', copper_oz=1,
                       copper_basis='vendor_order_option', layers=2)
        table = '(layers (0 "F.Cu" signal) (31 "B.Cu" signal))'
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            path = Path(directory) / 'board.kicad_pcb'
            for text in ('(kicad_pcb)', '(kicad_pcb ' + table + ' ' + table + ')'):
                with self.subTest(text=text):
                    path.write_text(text, encoding='utf-8')
                    with patch.object(dfm_checks.subprocess, 'Popen') as launch:
                        with self.assertRaisesRegex(ValueError, 'unambiguous layer table'):
                            dfm_checks.audit_snapshot(path, profile, context, cli='unused-cli')
                        launch.assert_not_called()


class ControllerBoundaryTests(unittest.TestCase):
    """Exercise real controller methods without initializing native windows."""
    @classmethod
    def setUpClass(cls):
        cls.wx = SimpleNamespace(Panel=object, Frame=object)
        path = Path(__file__).resolve().parents[1] / 'dfm_ui.py'
        spec = importlib.util.spec_from_file_location(
            'manufacturing_readiness_plugin._reliability_headless_ui', path)
        cls.ui = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'wx': cls.wx}):
            spec.loader.exec_module(cls.ui)

    def setUp(self):
        self.frame = self.ui.DFMFrame.__new__(self.ui.DFMFrame)
        self.frame.catalog = vendor_catalog.load_catalog()
        self.frame.profiles = [with_common_checks(p) for p in self.frame.catalog['profiles']]
        self.frame.document = checklists.new_checklist(self.frame.profiles[0])
        self.frame.busy = False
        self.frame.board = Mock(); self.frame.board.GetCopperLayerCount.return_value = 2
        self.frame.profile = Mock(); self.frame.notice = Mock(); self.frame.confirm = Mock()
        self.frame.input_checklists = set(); self.frame.context_fields = {}
        for name in ('clear_view', 'update_run_caption', 'refresh_rows', 'choose_profile'):
            setattr(self.frame, name, Mock())
        self.wx.FD_OPEN = 1; self.wx.FD_FILE_MUST_EXIST = 2; self.wx.ID_OK = 3

    def load_path(self, path):
        dialog = MagicMock()
        dialog.__enter__.return_value = dialog
        dialog.ShowModal.return_value = self.wx.ID_OK
        dialog.GetPath.return_value = str(path)
        self.wx.FileDialog = Mock(return_value=dialog)
        self.frame.load(None)

    def custom_profile(self):
        profile = deepcopy(self.frame.catalog['profiles'][0])
        profile['id'] = 'reliability-custom-process'
        profile['name'] = 'Custom reviewed process'
        return profile

    def test_loaded_custom_profile_syncs_catalog_and_rejects_collision_transactionally(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            path = Path(directory) / 'custom.json'
            profile = self.custom_profile()
            checklists.save_profile(path, profile)
            self.load_path(path)
            loaded = self.frame.document
            self.assertEqual(profile['id'], loaded['profile']['id'])
            matches = [p for p in self.frame.catalog['profiles'] if p['id'] == profile['id']]
            self.assertEqual(1, len(matches))
            self.assertEqual(loaded['profile'], matches[0])
            before_catalog, before_profiles = deepcopy(self.frame.catalog), deepcopy(self.frame.profiles)
            before_inputs = set(self.frame.input_checklists)
            conflicting = deepcopy(profile)
            conflicting['rules'][0]['minimum'] += .1
            with self.assertRaisesRegex(ValueError, 'already exists'):
                vendor_catalog.import_custom_profile(self.frame.catalog, json.dumps(conflicting))
            checklists.save_profile(path, conflicting)
            self.frame.profile.reset_mock(); self.frame.clear_view.reset_mock()
            self.load_path(path)
            self.assertIs(loaded, self.frame.document)
            self.assertEqual(before_catalog, self.frame.catalog)
            self.assertEqual(before_profiles, self.frame.profiles)
            self.assertEqual(before_inputs, self.frame.input_checklists)
            self.frame.profile.Append.assert_not_called()
            self.frame.profile.SetSelection.assert_not_called()
            self.frame.clear_view.assert_not_called()
            self.assertIn('conflicts', self.frame.notice.SetLabel.call_args.args[0])

    def test_library_collision_cannot_select_or_replace_loaded_rules(self):
        loaded = with_common_checks(self.custom_profile())
        self.frame.profiles.append(loaded)
        self.frame.document = checklists.new_checklist(loaded)
        incoming = deepcopy(loaded)
        incoming['rules'][0]['minimum'] += .1
        catalog = vendor_catalog.import_custom_profile(self.frame.catalog, json.dumps(incoming))
        original = self.frame.catalog
        library = SimpleNamespace(choose_process=Mock(return_value=(incoming['id'], catalog)))
        with patch.dict('sys.modules', {'manufacturing_readiness_plugin.vendor_catalog_ui': library}):
            self.frame.vendors(None)
        self.assertIs(original, self.frame.catalog)
        self.assertEqual(loaded, self.frame.document['profile'])
        self.frame.choose_profile.assert_not_called()
        self.assertIn('Conflicting profile ID', self.frame.notice.SetLabel.call_args.args[0])

    def test_parent_destruction_cancels_and_late_completion_cannot_touch_controls(self):
        self.frame.closing = False; self.frame.cancel = threading.Event()
        self.frame.timer = Mock(); self.frame.process = Mock()
        self.frame.process.poll.return_value = None
        event = Mock(); event.GetEventObject.return_value = self.frame
        self.frame.destroying(event)
        self.assertTrue(self.frame.closing)
        self.assertTrue(self.frame.cancel.is_set())
        self.frame.timer.Stop.assert_called_once()
        self.frame.process.terminate.assert_called_once()
        event.Skip.assert_called_once()
        self.frame.run_button = Mock(side_effect=AssertionError('Destroyed control accessed'))
        self.frame.finished(None, None, None, None, None)
        self.frame.run_button.Enable.assert_not_called()
        self.frame.profile.Enable.assert_not_called()

    def test_child_control_destruction_does_not_cancel_frame(self):
        self.frame.closing = False; self.frame.cancel = threading.Event()
        self.frame.timer = Mock(); self.frame.process = Mock()
        event = Mock(); event.GetEventObject.return_value = object()
        self.frame.destroying(event)
        self.assertFalse(self.frame.closing)
        self.assertFalse(self.frame.cancel.is_set())
        self.frame.timer.Stop.assert_not_called()
        self.frame.process.terminate.assert_not_called()
        event.Skip.assert_called_once()


class AssemblyEvidenceTests(unittest.TestCase):
    def test_absence_never_passes_complete_dfa_requirement(self):
        rows = [dict(rule_id='engineering-component-clearance', status='UNKNOWN', message='Manual')]
        self.assertEqual(apply_assembly_findings(rows, [])[0]['status'], 'UNKNOWN')

    def test_native_courtyard_failures_retain_unique_objects(self):
        rows = [dict(rule_id='engineering-component-clearance', status='UNKNOWN', message='Manual')]
        finding = dict(type='courtyards_overlap', items=[dict(uuid='u1'), dict(uuid='u2'), dict(uuid='u1')])
        result = apply_assembly_findings(rows, [finding])[0]
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['object_ids'], ['u1', 'u2'])
        self.assertIn('Partial negative evidence', result['message'])
        self.assertIn('courtyard', corrective_action(finding))

    def test_legacy_profile_malformed_input_is_actionable(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            path = Path(folder) / 'profile.json'
            for value in ([], dict(schema='wayricad.vendor-profile/v1')):
                path.write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaises(ValueError): analysis.load_profile(path)

    def test_invalid_profile_cannot_overwrite_saved_profile(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            path = Path(folder) / 'profile.json'; path.write_text('keep', encoding='utf-8')
            with self.assertRaises(ValueError): analysis.save_profile(path, analysis.FabricatorProfile(minimum_track_mm=-1))
            self.assertEqual(path.read_text(), 'keep')


NATIVE = bool(os.environ.get('WAYRICAD_MANUFACTURING_NATIVE'))


@unittest.skipUnless(NATIVE, 'Requires an explicit native KiCad provider test run.')
class NativeAssemblyProviderTests(unittest.TestCase):
    def test_ignored_courtyard_provider_is_enabled_in_private_snapshot(self):
        import pcbnew as p
        temporary_root = TEST_TEMP_ROOT
        if os.name == 'nt':
            self.assertEqual('d:', temporary_root.drive.casefold(),
                             'Run this disposable native fixture with TEMP/TMP on D:.')
        with tempfile.TemporaryDirectory(prefix='wayricad-assembly-provider-', dir=temporary_root) as directory:
            path = Path(directory) / 'overlapping-courtyards.kicad_pcb'
            board = p.BOARD(); board.SetCopperLayerCount(2)
            point = lambda x, y: p.VECTOR2I(p.FromMM(x), p.FromMM(y))
            identifiers = set()
            for reference, x in (('U1', 10), ('U2', 12)):
                footprint = p.FOOTPRINT(board)
                footprint.SetReference(reference); footprint.SetValue('Synthetic courtyard fixture')
                footprint.SetPosition(point(x, 10)); board.Add(footprint)
                courtyard = p.PCB_SHAPE(footprint)
                courtyard.SetShape(p.SHAPE_T_RECT)
                courtyard.SetStart(point(x - 2, 8)); courtyard.SetEnd(point(x + 2, 12))
                courtyard.SetLayer(p.F_CrtYd); courtyard.SetWidth(p.FromMM(.05))
                footprint.Add(courtyard); footprint.BuildCourtyardCaches()
                identifiers.add(str(footprint.m_Uuid.AsString()))
            self.assertEqual(2, len(identifiers))
            p.SaveBoard(str(path), board)
            project = path.with_suffix('.kicad_pro')
            project.write_text(json.dumps(dict(board=dict(design_settings=dict(
                rule_severities=dict(courtyards_overlap='ignore'))))), encoding='utf-8')
            before = {source.name: source.read_bytes() for source in (path, project)}
            profile = with_common_checks(vendor_catalog.load_catalog()['profiles'][0])
            context = dict(board_type='rigid', copper_oz=1,
                           copper_basis='vendor_order_option', layers=2)
            with patch.object(tempfile, 'tempdir', str(temporary_root)):
                packet = dfm_checks.audit_snapshot(path, profile, context)
            overlaps = [finding for finding in packet['findings']
                        if finding.get('type') == 'courtyards_overlap']
            self.assertTrue(overlaps, 'Native DRC must retain the known courtyard overlap.')
            finding_ids = {item['uuid'] for finding in overlaps for item in finding.get('items', [])
                           if item.get('uuid')}
            self.assertTrue(identifiers <= finding_ids)
            result, = [row for row in packet['results']
                       if row['rule_id'] == 'engineering-component-clearance']
            self.assertEqual('FAIL', result['status'])
            self.assertTrue(identifiers <= set(result['object_ids']))
            override = packet['snapshot_overrides']['provider_severities']['courtyards_overlap']
            self.assertEqual(dict(original='ignore', applied='error'), override)
            self.assertEqual(before, {source.name: source.read_bytes() for source in (path, project)})
            self.assertFalse(path.with_suffix('.kicad_dru').exists())


@unittest.skipUnless(NATIVE, 'Requires an explicit native KiCad GUI test run.')
class NativeRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        import pcbnew
        from manufacturing_readiness_plugin import dfm_ui
        cls.wx, cls.pcbnew, cls.ui = wx, pcbnew, dfm_ui
        cls.app = wx.GetApp() or wx.App(False)
        cls.path = Path(__file__).resolve().parents[2] / 'quick_emerge_plugin/tests/fixtures/region_coupon.kicad_pcb'

    def setUp(self):
        temporary = patch.object(tempfile, 'tempdir', str(TEST_TEMP_ROOT))
        temporary.start(); self.addCleanup(temporary.stop)
        board = self.pcbnew.LoadBoard(str(self.path))
        self.frame = self.ui.DFMFrame(None, board, saved_board=True)
        self.frame.timer.Stop()

    def tearDown(self):
        if self.frame:
            self.frame.close(None)
        self.wx.YieldIfNeeded()

    def wait(self):
        deadline = time.monotonic() + 60
        while self.frame.busy and time.monotonic() < deadline:
            self.wx.YieldIfNeeded(); time.sleep(.02)
        self.assertFalse(self.frame.busy, self.frame.notice.GetLabel())

    def test_unsupported_layers_rejected_before_cli(self):
        self.frame.context_fields['layers'].ChangeValue('4')
        self.frame.confirm.SetValue(True)
        with patch.object(self.ui, 'audit_snapshot') as audit:
            self.frame.run(); audit.assert_not_called()
        self.assertIn('layer count', self.frame.notice.GetLabel())

    def test_worker_failure_clears_prior_result(self):
        self.frame.bundle = dict(old=True)
        self.frame.confirm.SetValue(True)
        with patch.object(self.ui, 'audit_snapshot', side_effect=OSError('CLI permission denied')):
            self.frame.run(); self.wait()
        self.assertIsNone(self.frame.bundle)
        self.assertIsNone(self.frame.document['run'])
        self.assertIn('permission denied', self.frame.notice.GetLabel())

    def test_completed_drc_survives_preview_failure(self):
        from manufacturing_readiness_plugin.dfm_checks import source_inputs
        profile = self.frame.document['profile']; context = self.frame.context()
        packet = dict(source_sha256=source_inputs(self.path, context)[1], findings=[],
                      results=[dict(rule_id=row['id'], status='UNKNOWN', message='Fixture') for row in profile['rules']],
                      notice='Completed native evidence')
        self.frame.confirm.SetValue(True)
        with patch.object(self.ui, 'audit_snapshot', return_value=packet), \
                patch('wayricad_runtime.saved_board.load_board', side_effect=ValueError('Preview unavailable')):
            self.frame.run(); self.wait()
        self.assertIsNotNone(self.frame.document['run'])
        self.assertIsNotNone(self.frame.bundle)
        self.assertIn('preview unavailable', self.frame.notice.GetLabel().lower())

    def test_actual_native_run_and_main_thread_preview(self):
        from wayricad_runtime.board_render import extract_board
        threads = []
        def extract(board):
            threads.append(threading.current_thread()); return extract_board(board)
        self.frame.confirm.SetValue(True)
        with patch('wayricad_runtime.board_render.extract_board', side_effect=extract):
            self.frame.run(); self.wait()
        self.assertIsNotNone(self.frame.bundle, self.frame.notice.GetLabel())
        self.assertGreater(len(self.frame.canvas.scene.get('primitives', [])), 0)
        self.assertEqual(threads, [threading.main_thread()])
        self.assertTrue(self.frame.bundle['native']['findings']['violations'])

    def test_process_choices_and_invalid_numbers(self):
        self.assertTrue(self.frame.context_fields['copper_oz'].GetItems())
        self.frame.context_fields['copper_oz'].ChangeValue('unknown')
        with self.assertRaisesRegex(ValueError, 'copper oz'): self.frame.context()

    def test_destroying_parent_cancels_child_without_explicit_child_close(self):
        self.frame.close(None); self.wx.YieldIfNeeded()
        parent = self.wx.Frame(None)
        try:
            board = self.pcbnew.LoadBoard(str(self.path))
            self.frame = self.ui.DFMFrame(parent, board, saved_board=True)
            process = Mock(); process.poll.return_value = None
            self.frame.process = process
            parent.Destroy(); self.wx.YieldIfNeeded()
            self.assertTrue(self.frame.closing)
            self.assertTrue(self.frame.cancel.is_set())
            process.terminate.assert_called_once()
            # A completion already queued by the worker must be harmless.
            self.frame.finished(None, None, None, None, None)
        finally:
            if parent:
                parent.Destroy()
            self.wx.YieldIfNeeded()


if __name__ == '__main__': unittest.main()
