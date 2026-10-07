"""Opt-in native wx tests: FUSION_NATIVE_LINKED_GUI=1 with KiCad Python."""
import importlib
import copy
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import ModuleType
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_fusion_linked_gui_test'

if os.environ.get('FUSION_NATIVE_LINKED_GUI') == '1':
    import wx
    package = ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package
    ui = importlib.import_module(PACKAGE + '.linked_gui')
    gui = importlib.import_module(PACKAGE + '.gui')


def sample_scan():
    return {'links': [
        {'id': 'link-a', 'alias': 'AMP', 'status': 'changed', 'source_project': 'C:/Projects/Example/amp.kicad_pro',
         'selected_variant': '<Default>', 'wrapper_uuid': 'wrapper-a', 'sheet_count': 1, 'component_count': 2,
         'reference_map': {'U1': 'U4', 'R1': 'R5'},
         'major_changes': 1,
         'hierarchy': [{'sheet_path': '/root/a', 'display_path': '/Amplifier',
                        'symbols': [{'identity': '/root/a/u1', 'reference': 'U1', 'value': 'OpAmp'},
                                    {'identity': '/root/a/r1', 'reference': 'R1', 'value': '10k'}]},
                       {'sheet_path': '/root/a/b', 'display_path': '/Amplifier/Bias',
                        'symbols': [{'identity': '/root/a/b/r2', 'reference': 'R2', 'value': '4k7'}]}],
         'changes': [{'severity': 'major', 'category': 'pin_connection', 'identity': '/root/a/u1',
                      'reference': 'U1', 'pin': '3', 'before': 'NET_A', 'after': 'NET_B',
                      'before_display': 'R1.1', 'after_display': 'R2.3'}]},
        {'id': 'link-b', 'alias': 'FILTER', 'status': 'current', 'source_project': 'C:/Projects/Example/filter.kicad_pro',
         'selected_variant': '<Default>', 'wrapper_uuid': 'wrapper-b', 'sheet_count': 1, 'component_count': 1,
         'major_changes': 0, 'changes': []}],
        'legacy_candidates': [], 'report': {'scanned': 2}}


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_LINKED_GUI') == '1', 'Opt-in native wx workflow')
class LinkedGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.target = self.folder/'target'/'target.kicad_pro'
        self.target.parent.mkdir()
        self.target.write_text('{}', encoding='utf-8')
        self.dialog = ui.LinkedUpdatesDialog(target_path=str(self.target), embedded=True)
        self.dialog.candidate_parent.SetPath(str(self.folder))

    def tearDown(self):
        self.dialog.Destroy()
        self.temp.cleanup()

    def pump_until(self, predicate, timeout=5):
        end = time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:
            wx.YieldIfNeeded()
            time.sleep(0.01)
        self.assertTrue(predicate(), 'wx background callback did not finish')

    def test_overview_tree_diagram_and_change_review(self):
        self.dialog.show_scan(sample_scan())
        self.dialog.Show()
        self.dialog.Layout()
        self.dialog.diagram.Refresh()
        self.dialog.diagram.Update()
        wx.YieldIfNeeded()
        root = self.dialog.tree.GetRootItem()
        wrapper, cookie = self.dialog.tree.GetFirstChild(root)
        sheet, cookie = self.dialog.tree.GetFirstChild(wrapper)
        symbol, cookie = self.dialog.tree.GetFirstChild(sheet)
        self.assertIn('AMP', self.dialog.tree.GetItemText(wrapper))
        self.assertEqual(self.dialog.tree.GetItemText(sheet), 'AMP — 2 symbols')
        self.assertIn('U1', self.dialog.tree.GetItemText(symbol))
        self.assertIn('U1 → U4', self.dialog.tree.GetItemText(symbol))
        self.assertIn('major pin 3', self.dialog.tree.GetItemText(symbol))
        self.assertEqual(self.dialog.tree.GetChildrenCount(sheet, False), 3)
        self.assertEqual(len(self.dialog.diagram.nodes), 2)
        self.pump_until(lambda: len(self.dialog.diagram.hitboxes) == 6)
        self.dialog.select_link('link-a')
        self.assertEqual(self.dialog.selected_link_ids(), ['link-a'])
        self.assertEqual(self.dialog.changes.GetItemCount(), 1)
        self.assertEqual(self.dialog.changes.GetItemText(0), 'major')
        self.assertEqual(self.dialog.changes.GetItem(0, 3).GetText(), '3')
        self.assertEqual(self.dialog.changes.GetItem(0, 2).GetText(), 'U1 → U4')
        self.assertEqual(self.dialog.changes.GetItem(0, 4).GetText(), 'R1.1')
        self.assertTrue(self.dialog.major_ack.IsShown())
        self.assertIn('wrapper-a', self.dialog.target_summary.GetValue())

    def test_individual_ignore_defers_link_and_conflict_stays_blocked(self):
        data=sample_scan()
        data['links'][0]['changes'][0]['suggestion']='Review pin connection before update.'
        data['links'][0]['conflicts']=[{'category':'external_copper','message':'Shared copper',
                                      'suggestion':'Separate copper and rerun DRC.',
                                      'can_ignore':False}]
        self.dialog.show_scan(data)
        self.dialog.select_link('link-a')
        self.assertEqual(self.dialog.changes.GetItemCount(),2)
        self.dialog.changes.Select(0)
        self.dialog.on_change_selected(type('Selection',(),{'GetIndex':lambda unused:0})())
        self.assertIn('Review pin connection',self.dialog.change_advice.GetValue())
        self.dialog.toggle_deferred_change(None)
        self.assertIn('Deferred',self.dialog.changes.GetItemText(0,6))
        with mock.patch.object(wx,'MessageBox',return_value=wx.OK) as notice:
            self.dialog.preview_selected(None)
        self.assertIn('ignored for now',notice.call_args.args[0])
        self.dialog.changes.Select(1)
        self.dialog.on_change_selected(type('Selection',(),{'GetIndex':lambda unused:1})())
        self.assertIn('cannot be ignored',self.dialog.change_advice.GetValue())
        self.assertFalse(self.dialog.defer_change_button.IsEnabled())

    def test_scan_watch_and_major_preview_offline_plan(self):
        scan_gate = threading.Event()
        calls = []
        fake = ModuleType(PACKAGE+'.linked_updates')
        def scan(target, cli_path='', search_roots=None, source_overrides=None):
            scan_gate.wait(5)
            calls.append(('scan', search_roots, source_overrides))
            return sample_scan()
        def preview(target, ids, candidate, cli_path='', acknowledge_major=False,
                    source_overrides=None, identity_overrides=None,
                    retain_destination_layout=False):
            Path(candidate).mkdir()
            calls.append(('preview', ids, acknowledge_major, source_overrides,
                          identity_overrides, retain_destination_layout))
            return {'target_project': str(self.target), 'candidate_directory': str(candidate),
                    'candidate_hashes': {'target.kicad_pro': 'abc'}, 'target_hashes': {'target.kicad_pro': 'xyz'},
                    'source_hashes': [], 'report': {'linked_update': True, 'major_changes': 1,
                                                   'changes': sample_scan()['links'][0]['changes']}}
        fake.scan_links = scan
        fake.preview_update = preview
        with mock.patch.dict(sys.modules, {PACKAGE+'.linked_updates': fake}):
            self.dialog.scan_all()
            self.assertFalse(self.dialog.target.IsEnabled())
            self.assertFalse(self.dialog.scan_button.IsEnabled())
            scan_gate.set()
            self.pump_until(lambda: self.dialog.scan_data is not None)
            self.dialog.select_link('link-a')
            self.assertTrue(self.dialog.major_ack.IsEnabled())
            self.dialog.major_ack.SetValue(True)
            self.dialog.source_overrides['link-a'] = 'C:/Projects/Example/moved.kicad_pro'
            self.dialog.retain_layout.SetValue(True)
            self.dialog.preview_selected(None)
            self.pump_until(lambda: self.dialog.plan is not None)
            self.assertTrue(self.dialog.plan_file.is_file())
            self.assertEqual(calls[1], ('preview', ['link-a'], True,
                                       {'link-a': 'C:/Projects/Example/moved.kicad_pro'}, {}, True))
            self.assertFalse(self.dialog.apply_button.IsEnabled())
            saved = self.dialog.plan_file
            self.dialog.show_watch_scan(sample_scan())
            self.assertIsNotNone(self.dialog.plan)
            changed = sample_scan()
            changed['links'][0]['status'] = 'conflict'
            self.dialog.show_watch_scan(changed)
            self.assertIsNone(self.dialog.plan)
            standalone = ui.LinkedUpdatesDialog(target_path='', embedded=False)
            try:
                standalone.load_plan_path(saved)
                self.assertTrue(standalone.major_ack.IsShown())
                standalone.closed_ack.SetValue(True)
                standalone.on_acknowledge()
                self.assertFalse(standalone.apply_button.IsEnabled())
                standalone.major_ack.SetValue(True)
                standalone.on_acknowledge()
                self.assertTrue(standalone.apply_button.IsEnabled())
                applied = []
                insertion = ModuleType(PACKAGE+'.insertion')
                insertion.apply_import = lambda plan: (applied.append(plan),
                    {'backup_directory': str(self.folder/'backup'), 'target_project': str(self.target),
                     'report': {'linked_update': True}})[1]
                with mock.patch.dict(sys.modules, {PACKAGE+'.insertion': insertion}):
                    with mock.patch.object(wx, 'MessageBox', side_effect=[wx.YES, wx.OK]):
                        standalone.apply_updates(None)
                        self.pump_until(lambda: standalone.applied is not None)
                self.assertEqual(len(applied), 1)
                self.assertEqual(applied[0]['report']['linked_update'], True)
            finally:
                standalone.Destroy()

    def test_main_entry_prefills_current_project(self):
        with mock.patch.object(gui, 'detect_variants', return_value=[gui.DEFAULT]):
            main = gui.FusionDialog(initial=str(self.target.with_suffix('.kicad_pcb')))
            try:
                with mock.patch.object(ui, 'LinkedUpdatesDialog') as linked:
                    main.open_linked_updates(None)
                self.assertTrue(linked.call_args.kwargs['embedded'])
                self.assertEqual(Path(linked.call_args.kwargs['target_path']), self.target)
            finally:
                main.Destroy()

    def test_ambiguous_identity_requires_explicit_choice(self):
        data = sample_scan()
        data['links'][0]['auto_link_proposals'] = [
            {'before': '/root/a/u1', 'candidates': ['/root/new/u1', '/root/other/u1'],
             'method': 'Reference and symbol library', 'automatic': False}]
        self.dialog.show_scan(data)
        self.dialog.select_link('link-a')

        class Choice:
            def __enter__(self): return self
            def __exit__(self, *unused): pass
            def ShowModal(self): return wx.ID_OK
            def GetSelection(self): return 1

        with mock.patch.object(wx, 'SingleChoiceDialog', return_value=Choice()):
            self.dialog.auto_link(None)
        self.assertEqual(self.dialog.identity_overrides,
                         {'link-a': {'/root/a/u1': '/root/other/u1'}})
        self.assertIsNone(self.dialog.plan)
        calls = []
        fake = ModuleType(PACKAGE+'.linked_updates')
        def preview(target, ids, candidate, cli_path='', acknowledge_major=False,
                    source_overrides=None, identity_overrides=None,
                    retain_destination_layout=False):
            Path(candidate).mkdir()
            calls.append(identity_overrides)
            return {'target_project': str(self.target), 'candidate_directory': str(candidate),
                    'candidate_hashes': {}, 'target_hashes': {}, 'source_hashes': [],
                    'report': {'linked_update': True, 'major_changes': 1, 'changes': []}}
        fake.preview_update = preview
        self.dialog.major_ack.SetValue(True)
        with mock.patch.dict(sys.modules, {PACKAGE+'.linked_updates': fake}):
            self.dialog.preview_selected(None)
            self.pump_until(lambda: self.dialog.plan is not None)
        self.assertEqual(calls, [{'link-a': {'/root/a/u1': '/root/other/u1'}}])

    def test_legacy_adoption_requires_verified_provenance(self):
        data = sample_scan()
        data['legacy_candidates'] = [
            {'id': 'legacy:proven', 'alias': 'OLD', 'status': 'verified_legacy',
             'method': 'Archived source snapshot + exact schematic comparison'},
            {'id': 'legacy:guess', 'alias': 'GUESS', 'status': 'unverified_legacy',
             'method': 'Reference similarity'}]
        self.dialog.show_scan(data)

        class Choice:
            def __enter__(self): return self
            def __exit__(self, *unused): pass
            def ShowModal(self): return wx.ID_OK
            def GetSelections(self): return [0]

        calls = []
        fake = ModuleType(PACKAGE+'.linked_updates')
        def adopt(target, ids, candidate, cli_path=''):
            Path(candidate).mkdir()
            calls.append(ids)
            return {'target_project': str(self.target), 'candidate_directory': str(candidate),
                    'candidate_hashes': {}, 'target_hashes': {}, 'source_hashes': [],
                    'report': {'linked_update': True, 'major_changes': 0, 'changes': []}}
        fake.preview_adopt_links = adopt
        with mock.patch.object(wx, 'MultiChoiceDialog', return_value=Choice()):
            self.dialog.review_legacy_proposals(data['legacy_candidates'])
        self.assertEqual(self.dialog.pending_adoption_ids, ['legacy:proven'])
        with mock.patch.dict(sys.modules, {PACKAGE+'.linked_updates': fake}):
            self.dialog.preview_selected(None)
            self.pump_until(lambda: self.dialog.plan is not None)
        self.assertEqual(calls, [['legacy:proven']])

    def test_break_selected_and_all_links_preserve_missing_source(self):
        data = sample_scan()
        data['links'][0]['status'] = 'missing_source'
        data['links'][0]['error'] = 'The saved source was deleted.'
        self.dialog.show_scan(data)
        self.dialog.select_link('link-a')
        calls = []
        fake = ModuleType(PACKAGE+'.linked_updates')
        def preview(target, ids, candidate, cli_path=''):
            Path(candidate).mkdir()
            calls.append(ids)
            return {'target_project': str(self.target), 'candidate_directory': str(candidate),
                    'candidate_hashes': {}, 'target_hashes': {}, 'source_hashes': [],
                    'report': {'linked_break': True, 'broken_links': ids,
                               'local_design_preserved': True, 'sources_accessed': False}}
        fake.preview_break_links = preview
        with mock.patch.dict(sys.modules, {PACKAGE+'.linked_updates': fake}):
            self.dialog.preview_break_selected(None)
            self.pump_until(lambda: self.dialog.plan is not None)
            self.assertEqual(calls[-1], ['link-a'])
            self.assertIn('link break', self.dialog.apply_button.GetLabel())
            self.dialog.preview_break_all(None)
            self.pump_until(lambda: len(calls) == 2 and self.dialog.plan is not None)
        self.assertEqual(set(calls[-1]), {'link-a', 'link-b'})
        self.assertFalse(self.dialog.major_ack.IsShown())

    def test_undo_last_apply_requires_eligible_latest_backup(self):
        calls = []
        fake = ModuleType(PACKAGE+'.linked_updates')
        fake.list_transactions = lambda target: [
            {'backup_directory': str(self.folder/'newer-ineligible'), 'eligible': False,
             'operation': 'linked_undo', 'error': 'Receipt does not match current target.'},
            {'backup_directory': str(self.folder/'older-eligible'), 'eligible': True,
             'operation': 'linked_update', 'created_at': '2026-10-01T10:00:00Z'}]
        def undo(target, backup, candidate, cli_path=''):
            Path(candidate).mkdir()
            calls.append(backup)
            return {'target_project': str(self.target), 'candidate_directory': str(candidate),
                    'candidate_hashes': {}, 'target_hashes': {}, 'source_hashes': [],
                    'report': {'linked_undo': True, 'major_changes': 0}}
        fake.preview_undo = undo
        class Choice:
            def __enter__(self): return self
            def __exit__(self, *unused): pass
            def ShowModal(self): return wx.ID_OK
            def GetSelection(self): return 0
        with mock.patch.dict(sys.modules, {PACKAGE+'.linked_updates': fake}):
            with mock.patch.object(wx, 'SingleChoiceDialog', return_value=Choice()):
                self.dialog.preview_undo_last(None)
                self.pump_until(lambda: self.dialog.plan is not None)
        self.assertEqual(calls, [str(self.folder/'older-eligible')])
        self.assertIn('undo', self.dialog.apply_button.GetLabel())
        self.dialog.invalidate_plan()
        fake.list_transactions = lambda target: [
            {'backup_directory': str(self.folder/'last-backup'), 'eligible': False,
             'error': 'Saved target changed since Apply.'}]
        with mock.patch.dict(sys.modules, {PACKAGE+'.linked_updates': fake}):
            self.dialog.preview_undo_last(None)
            self.pump_until(lambda: not self.dialog.busy)
        self.assertIsNone(self.dialog.plan)
        self.assertIn('No eligible backup', self.dialog.status.GetLabel())
        self.assertIn('Saved target changed', self.dialog.validation.GetValue())

    def test_unsupported_incremental_update_shows_reason_and_keeps_break_available(self):
        data = sample_scan()
        data['links'][0]['update_unsupported_reason'] = 'Mixed stack layer mapping cannot be reconstructed safely.'
        self.dialog.show_scan(data)
        self.dialog.select_link('link-a')
        self.assertIn('full rebuild required', self.dialog.tree.GetItemText(self.dialog.link_tree_items['link-a']))
        self.assertIn('Mixed stack layer mapping', self.dialog.source_summary.GetValue())
        self.assertIn('Mixed stack layer mapping', self.dialog.validation.GetValue())
        self.assertFalse(self.dialog.update_button.IsEnabled())
        self.assertTrue(self.dialog.break_selected_button.IsEnabled())
        self.assertTrue(self.dialog.break_all_button.IsEnabled())
        self.assertTrue(self.dialog.undo_button.IsEnabled())
        with mock.patch.object(wx, 'MessageBox', return_value=wx.OK) as notice:
            self.dialog.preview_selected(None)
        self.assertIn('full combined rebuild', notice.call_args.args[0])
        self.dialog.select_link('link-b')
        self.assertTrue(self.dialog.update_button.IsEnabled())

    def test_local_pcb_layout_conflict_requires_explicit_retain_mode(self):
        data=sample_scan()
        data['links'][0]['conflicts']=[{'category':'destination_pcb_items',
                                      'message':'Placed layout changed in target'}]
        self.dialog.show_scan(data)
        self.dialog.select_link('link-a')
        self.dialog.major_ack.SetValue(True)
        with mock.patch.object(wx,'MessageBox',return_value=wx.OK) as notice:
            self.dialog.preview_selected(None)
        self.assertIn('Placed layout changed',notice.call_args.args[0])
        self.dialog.retain_layout.SetValue(True)
        calls=[]
        fake=ModuleType(PACKAGE+'.linked_updates')
        def preview(target,ids,candidate,**kwargs):
            Path(candidate).mkdir()
            calls.append(kwargs['retain_destination_layout'])
            return {'target_project':str(self.target),'candidate_directory':str(candidate),
                    'candidate_hashes':{},'target_hashes':{},'source_hashes':[],
                    'report':{'linked_update':True,'major_changes':0,'changes':[]}}
        fake.preview_update=preview
        with mock.patch.dict(sys.modules,{PACKAGE+'.linked_updates':fake}):
            self.dialog.preview_selected(None)
            self.pump_until(lambda:self.dialog.plan is not None)
        self.assertEqual(calls,[True])

    def test_hundred_links_remain_selectable_when_symbols_are_bounded(self):
        base = sample_scan()['links'][0]
        links = []
        for index in range(100):
            link = copy.deepcopy(base)
            link['id'] = f'link-{index}'
            link['alias'] = f'Module{index}'
            link['hierarchy'][0]['symbols'] = [
                {'identity': f'/root/a/r{number}', 'reference': f'R{number}', 'value': '10k'}
                for number in range(100)]
            links.append(link)
        self.dialog.show_scan({'links': links, 'legacy_candidates': [], 'report': {}})
        root = self.dialog.tree.GetRootItem()
        self.assertEqual(self.dialog.tree.GetChildrenCount(root, False), 100)
        self.assertEqual(len(self.dialog.diagram.nodes), 100)
        self.dialog.select_link('link-99')
        self.assertEqual(self.dialog.selected_link_ids(), ['link-99'])
        self.dialog.tree.SelectItem(self.dialog.link_tree_items['link-1'], True)
        self.assertEqual(set(self.dialog.selected_link_ids()), {'link-1', 'link-99'})


if __name__ == '__main__':
    unittest.main()
