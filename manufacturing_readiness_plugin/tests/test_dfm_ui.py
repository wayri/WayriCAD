"""Native hidden-window controller checks; these do not replace editor UI tests."""
from copy import deepcopy
from collections import Counter
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    import wx
    import pcbnew
    NATIVE = bool(os.environ.get('WAYRICAD_DFM_TEST_BOARD'))
except ImportError:
    NATIVE = False


@unittest.skipUnless(NATIVE, 'Requires cached KiCad Python and an explicit disposable test board.')
class NativeDFMControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from manufacturing_readiness_plugin import dfm_ui
        cls.module = dfm_ui
        cls.app = wx.GetApp() or wx.App(False)
        cls.board_path = Path(os.environ['WAYRICAD_DFM_TEST_BOARD']).resolve()
        cls.output = Path(os.environ['WAYRICAD_DFM_TEST_OUTPUT']).resolve()
        cls.output.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.sha = hashlib.sha256(self.board_path.read_bytes()).hexdigest()
        board = pcbnew.LoadBoard(str(self.board_path))
        self.frame = self.module.DFMFrame(None, board, saved_board=True)
        self.frame.timer.Stop()
        self.frame.Layout()

    def tearDown(self):
        self.frame.closing = True
        self.frame.cancel.set()
        self.frame.Destroy()
        wx.YieldIfNeeded()
        self.assertEqual(hashlib.sha256(self.board_path.read_bytes()).hexdigest(), self.sha)

    def profile(self):
        from manufacturing_readiness_plugin.checklists import PROFILE_SCHEMA
        return dict(schema=PROFILE_SCHEMA, id='native-ui-fixture', name='Synthetic native UI fixture',
                    vendor='Synthetic', service='Controller validation', revision='1',
                    process=dict(board_type='rigid', copper_oz=[1, 2], copper_basis='finished',
                                 inner_copper_oz=[.5, 1], layers=[2, 4],
                                 material='FR4', thickness_mm=[1.6], finish=['ENIG']),
                    sources=[dict(id='fixture', url='https://example.com/synthetic-test', title='Synthetic test only',
                                  retrieved='2026-11-04', verified='2026-11-04')],
                    rules=[dict(id='width', title='Fixture width rule', category='DRC', backend='native_drc',
                                constraint='track_width', unit='mm', minimum=.1, maximum=None, source_ids=['fixture'])])

    def select_fixture(self):
        self.frame.profiles.append(self.profile())
        self.frame.profile.Append('Synthetic native UI fixture')
        self.frame.profile.SetSelection(len(self.frame.profiles)-1)
        self.frame.choose_profile()

    def wait_finished(self):
        deadline = time.monotonic() + 35
        while self.frame.busy and time.monotonic() < deadline:
            wx.YieldIfNeeded(); time.sleep(.03)
        self.assertFalse(self.frame.busy, self.frame.notice.GetLabel())

    def file_dialog(self, path):
        class Dialog:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def ShowModal(self): return wx.ID_OK
            def GetPath(self): return str(path)
        return Dialog

    def test_constructor_and_catalogue_process_contexts(self):
        from manufacturing_readiness_plugin import checklists
        self.assertGreaterEqual(len(self.frame.profiles), 1)
        for index, profile in enumerate(self.frame.profiles):
            with self.subTest(profile=profile['id']):
                self.frame.profile.SetSelection(index); self.frame.choose_profile()
                for key, value in profile['process'].items():
                    if key not in self.frame.context_fields: continue
                    selected = value[0] if isinstance(value, list) else value
                    self.frame.context_fields[key].ChangeValue(str(selected))
                checklists.compile_native_rules(profile, self.frame.context())
        self.assertFalse(self.frame.confirm.GetValue())

    def test_saved_context_survives_pre_run_save_load(self):
        self.select_fixture()
        self.frame.context_fields['copper_oz'].ChangeValue('2')
        self.frame.context_fields['layers'].ChangeValue('4')
        self.frame.context_fields['inner_copper_oz'].ChangeValue('1')
        context = self.frame.context()
        with tempfile.TemporaryDirectory(dir=self.output) as directory:
            path = Path(directory) / 'selected-context.json'
            with patch.object(wx, 'FileDialog', self.file_dialog(path)):
                self.frame.save(None)
                self.assertTrue(path.is_file(), self.frame.notice.GetLabel())
                self.frame.context_fields['copper_oz'].ChangeValue('1')
                self.frame.context_fields['layers'].ChangeValue('2')
                self.frame.load(None)
            self.assertEqual(self.frame.context(), context)
            self.assertEqual(self.frame.document['selected_context'], context)
            self.assertFalse(self.frame.confirm.GetValue())

    def test_typed_copper_scope_and_human_labels(self):
        self.select_fixture()
        self.assertEqual(self.frame.context()['copper_basis'], 'finished')
        self.assertEqual(self.frame.context_fields['copper_basis'].GetValue(), self.module.BASIS_LABELS['finished'])
        for basis, inner in [('starting', '.5'), ('finished', '2'), ('finished', '')]:
            self.frame.context_fields['copper_basis'].ChangeValue(self.module.BASIS_LABELS[basis])
            self.frame.context_fields['inner_copper_oz'].ChangeValue(inner)
            self.frame.confirm.SetValue(True)
            with patch.object(self.module, 'audit_snapshot') as audit:
                self.frame.run(None)
                self.assertFalse(self.frame.busy)
                audit.assert_not_called()
        self.assertIsNone(self.frame.bundle)

    def test_portable_integer_context_loads_into_gui_without_false_staleness(self):
        from manufacturing_readiness_plugin import checklists
        from manufacturing_readiness_plugin.dfm_checks import source_inputs
        self.select_fixture()
        self.frame.context_fields['inner_copper_oz'].ChangeValue('1')
        gui_context = self.frame.context()
        portable_context = dict(gui_context, copper_oz=1, inner_copper_oz=1)
        source_sha = source_inputs(self.board_path, portable_context)[1]
        document = checklists.new_checklist(self.frame.document['profile'], selected_context=portable_context)
        document = checklists.add_manual_evidence(document, 'width', source_sha, 'Portable controller fixture note')
        document = checklists.record_run(document, source_sha, [dict(rule_id='width', status='UNKNOWN', message='Portable fixture run')])
        with tempfile.TemporaryDirectory(dir=self.output) as directory:
            path = Path(directory) / 'portable-integer-context.json'
            checklists.save_checklist(path, document)
            with patch.object(wx, 'FileDialog', self.file_dialog(path)):
                self.frame.load(None)
        self.assertIsInstance(self.frame.context()['copper_oz'], float)
        self.assertIsInstance(self.frame.context()['inner_copper_oz'], float)
        self.assertEqual(self.frame.current_sha(fresh=True), source_sha)
        state = checklists.checklist_state(self.frame.document, self.frame.current_sha())
        self.assertFalse(state['stale'])
        self.assertEqual(state['results'][0]['manual_evidence'][0]['detail'], 'Portable controller fixture note')

    def test_manual_vendor_runs_project_drc_without_vendor_pass(self):
        from manufacturing_readiness_plugin.dfm_checks import source_inputs
        index = next(index for index, value in enumerate(self.frame.profiles) if value['vendor'] == 'PCBWay')
        self.frame.profile.SetSelection(index); self.frame.choose_profile()
        self.assertIn('Run project DRC', self.frame.run_button.GetLabel())
        original = source_inputs(self.board_path)
        self.frame.confirm.SetValue(True)
        self.frame.run(None); self.wait_finished()
        self.assertIsNotNone(self.frame.bundle, self.frame.notice.GetLabel())
        self.assertEqual(self.frame.bundle['rule_mode'], 'project')
        self.assertIn('Project DRC only', self.frame.bundle['notice'])
        self.assertTrue(all(row['status'] == 'UNKNOWN' for row in self.frame.bundle['results']))
        self.assertEqual(source_inputs(self.board_path), original)

    def test_real_native_worker_records_completed_run(self):
        self.select_fixture(); self.frame.confirm.SetValue(True)
        self.frame.run(None); self.wait_finished()
        self.assertIsNotNone(self.frame.bundle, self.frame.notice.GetLabel())
        self.assertIsNotNone(self.frame.document['run'])
        self.assertEqual(self.frame.document['selected_context'], self.frame.context())
        self.assertEqual(self.frame.document['run']['source_sha256'], self.frame.current_sha(fresh=True))
        self.assertGreater(len(self.frame.canvas.scene.get('primitives', [])), 0)
        counts = Counter(row['severity'] for row in self.frame.bundle['findings'])
        self.assertEqual(counts, dict(error=2, warning=2))
        for status, count in [('WARN', 2), ('FAIL', 2)]:
            self.frame.severity_choice.SetStringSelection(status)
            self.frame.refresh_rows()
            self.assertEqual(len(self.frame.rows), count)
            self.assertEqual([self.frame.table.GetItemText(index) for index in range(count)], [status] * count)
        self.frame.severity_choice.SetSelection(0)
        self.frame.family_choice.SetStringSelection('Silkscreen')
        self.frame.refresh_rows()
        self.assertEqual(len(self.frame.rows), 2)
        self.assertTrue(all(self.module.family(row) == 'Silkscreen' for row in self.frame.rows))
        self.frame.family_choice.SetSelection(0)
        self.frame.refresh_rows()
        linked = next((row for row in self.frame.rows if row.get('object_ids')), None)
        self.assertIsNotNone(linked, 'Synthetic fixture should retain its intentional native object findings.')
        identifier = linked['object_ids'][0]
        self.frame.pick_object(identifier)
        wx.YieldIfNeeded()
        self.assertGreaterEqual(self.frame.table.GetFirstSelected(), 0)
        selected = self.frame.rows[self.frame.table.GetFirstSelected()]
        self.assertIn(identifier, selected['object_ids'])
        self.frame.canvas.ids = selected['object_ids']
        with patch('wayricad_runtime.analysis_selection.select_origin') as select:
            self.frame.cross_probe(None)
            select.assert_called_once_with(self.board_path, self.frame.canvas.ids,
                                           expected_sha256=self.sha, focus=True)
        from wayricad_runtime.board_render import draw_wx
        self.frame.canvas.SetSize((640, 400))
        bitmap = wx.Bitmap(640, 400)
        dc = wx.MemoryDC(bitmap); dc.SetBackground(wx.Brush('#f7fafb')); dc.Clear()
        scale, project, _inverse = self.frame.canvas.transform()
        graphics = wx.GraphicsContext.Create(dc)
        draw_wx(graphics, self.frame.canvas.scene, project, highlight_ids=self.frame.canvas.ids, scale=scale, alpha=.8)
        del graphics
        dc.SelectObject(wx.NullBitmap)
        self.assertTrue(bitmap.SaveFile(str(self.output / 'hidden-controller-canvas.png'), wx.BITMAP_TYPE_PNG))
        with patch.object(self.frame, 'current_sha', return_value='b' * 64), \
                patch('wayricad_runtime.analysis_selection.select_origin') as select:
            self.frame.cross_probe(None)
            select.assert_not_called()
            self.assertFalse(self.frame.canvas.scene)

    def test_cancellation_finishes_without_retaining_result(self):
        self.select_fixture(); self.frame.confirm.SetValue(True)
        self.frame.run(None); self.frame.cancel.set(); self.wait_finished()
        self.assertIsNone(self.frame.bundle)
        self.assertIsNone(self.frame.document['run'])
        self.assertIn('cancel', self.frame.notice.GetLabel().lower())

    def test_inflight_native_cancellation_finishes_cleanly(self):
        self.select_fixture(); self.frame.confirm.SetValue(True)
        self.frame.run(None)
        deadline = time.monotonic() + 8
        while self.frame.process is None and self.frame.busy and time.monotonic() < deadline:
            wx.YieldIfNeeded(); time.sleep(.02)
        process = self.frame.process
        self.assertIsNotNone(process, self.frame.notice.GetLabel())
        ready = time.monotonic() + .25
        while time.monotonic() < ready and process.poll() is None:
            wx.YieldIfNeeded(); time.sleep(.02)
        if process.poll() is not None:
            self.wait_finished()
            self.skipTest('Native CLI completed before the in-flight cancellation window.')
        self.frame.cancel.set(); self.wait_finished()
        self.assertIsNone(self.frame.bundle)
        self.assertIsNone(self.frame.document['run'])
        self.assertIn('cancel', self.frame.notice.GetLabel().lower())
        self.assertIsNotNone(process.poll())

    def test_stale_finished_result_is_discarded(self):
        self.select_fixture()
        context = self.frame.context()
        self.frame.busy = True
        with patch.object(self.frame, 'current_sha', return_value='b' * 64):
            self.frame.finished(dict(source_sha256='a' * 64), {}, None,
                                self.module.checklists.profile_digest(self.frame.document['profile']), context)
        self.assertIsNone(self.frame.bundle)
        self.assertIsNone(self.frame.document['run'])
        self.assertTrue(self.frame.pending_change)

    def test_invalidation_clears_visual_preview(self):
        self.select_fixture()
        self.frame.canvas.scene = dict(bounds=[0, 0, 1, 1], primitives=[])
        self.frame.canvas.ids = ['old-item']
        self.frame.detail.SetValue('Old finding')
        self.frame.invalidate()
        self.assertFalse(self.frame.canvas.scene)
        self.assertEqual(self.frame.canvas.ids, [])
        self.assertNotIn('Old finding', self.frame.detail.GetValue())

    def test_layer_filter_hides_other_copper_and_dimensions(self):
        from manufacturing_readiness_plugin.dfm_dimensions import track_width_dimensions
        from wayricad_runtime.board_render import extract_board
        board = pcbnew.BOARD()
        tracks = []
        for layer, y in [(pcbnew.F_Cu, 0), (pcbnew.B_Cu, 10)]:
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(0), pcbnew.FromMM(y)))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(10), pcbnew.FromMM(y)))
            track.SetWidth(pcbnew.FromMM(1)); track.SetLayer(layer); board.Add(track); tracks.append(track)
        identifiers = [str(track.m_Uuid.AsString()) for track in tracks]
        dimensions = track_width_dimensions(tracks, identifiers, pcbnew.ToMM)
        scene = extract_board(board)
        context = self.frame.context()
        packet = dict(source_sha256=self.frame.current_sha(fresh=True), board_sha256=self.sha,
                      results=[], findings=[], dimensions=dimensions, notice='Native in-memory geometry controller check.')
        self.frame.finished(packet, scene, None, self.module.checklists.profile_digest(self.frame.document['profile']), context)
        self.assertEqual(self.frame.canvas.dimensions, dimensions['items'])
        self.frame.canvas.ids = identifiers
        self.frame.canvas.SetSize((640, 400))

        def render():
            bitmap = wx.Bitmap(640, 400)
            dc = wx.MemoryDC(bitmap)
            with patch.object(wx, 'AutoBufferedPaintDC', return_value=dc):
                self.frame.canvas.paint(None)
            dc.SelectObject(wx.NullBitmap)
            return bitmap.ConvertToImage()

        def pixel(image, point):
            _scale, project, _inverse = self.frame.canvas.transform()
            x, y = (int(round(value)) for value in project(point))
            return image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y)

        all_layers = render()
        self.assertNotEqual(pixel(all_layers, (5, 0)), (247, 250, 251))
        self.assertNotEqual(pixel(all_layers, (5, 10)), (247, 250, 251))
        self.frame.layer_choice.SetSelection(self.frame.layer_ids.index(pcbnew.F_Cu))
        self.frame.layer_changed(None)
        front = render()
        self.assertEqual(self.frame.canvas.visible_layers, [pcbnew.F_Cu])
        self.assertNotEqual(pixel(front, (5, 0)), (247, 250, 251))
        self.assertEqual(pixel(front, (5, 10)), (247, 250, 251))
        self.frame.layer_choice.SetSelection(self.frame.layer_ids.index(pcbnew.B_Cu))
        self.frame.layer_changed(None)
        back = render()
        self.assertEqual(pixel(back, (5, 0)), (247, 250, 251))
        self.assertNotEqual(pixel(back, (5, 10)), (247, 250, 251))
        self.frame.layer_choice.SetSelection(0); self.frame.layer_changed(None)
        self.assertIsNone(self.frame.canvas.visible_layers)

    def test_empty_board_bounds_and_entrypoint_contract(self):
        self.frame.canvas.scene = dict(bounds=None, primitives=[], layers={})
        self.frame.canvas.SetSize((640, 400))
        self.assertTrue(math.isfinite(self.frame.canvas.transform()[0]))
        bitmap = wx.Bitmap(640, 400); dc = wx.MemoryDC(bitmap)
        with patch.object(wx, 'AutoBufferedPaintDC', return_value=dc):
            self.frame.canvas.paint(None)
        dc.SelectObject(wx.NullBitmap)
        module = importlib.import_module('manufacturing_readiness_plugin.dfm_entrypoint')
        self.assertTrue(callable(module.main))
        root = Path(self.module.__file__).parent
        manifest = json.loads((root / 'plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['actions']), 2)
        primary, dfm = manifest['actions']
        self.assertEqual((primary['identifier'], primary['entrypoint']), ('open', 'ipc_entrypoint.py'))
        self.assertEqual((dfm['identifier'], dfm['entrypoint']), ('dfm-studio', 'dfm_entrypoint.py'))
        config = json.loads((root / 'wayricad-tool.json').read_text(encoding='utf-8'))
        self.assertEqual((config['module'], config['class']), ('manufacturing_readiness_plugin', 'ManufacturingReadinessPlugin'))


if __name__ == '__main__':
    unittest.main()
