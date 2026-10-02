"""Opt-in native wx tests: FUSION_NATIVE_INSERTION_GUI=1 with KiCad Python."""
import importlib
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
PACKAGE = '_fusion_insertion_gui_test'

if os.environ.get('FUSION_NATIVE_INSERTION_GUI') == '1':
    import wx
    package = ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package
    ui = importlib.import_module(PACKAGE + '.insertion_gui')
    gui = importlib.import_module(PACKAGE + '.gui')
    model = importlib.import_module(PACKAGE + '.model')


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_INSERTION_GUI') == '1', 'Opt-in native wx workflow')
class InsertionGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.target = self.folder / 'target' / 'target.kicad_pro'
        self.incoming = self.folder / 'incoming' / 'incoming.kicad_pro'
        self.schematic = self.folder / 'sheet' / 'sheet.kicad_pro'
        for project in (self.target, self.incoming, self.schematic):
            project.parent.mkdir()
            project.write_text('{}', encoding='utf-8')
            project.with_suffix('.kicad_sch').write_text('(kicad_sch)', encoding='utf-8')
        for project in (self.target, self.incoming):
            project.with_suffix('.kicad_pcb').write_text('(kicad_pcb)', encoding='utf-8')
        section = model.SourceSpec(str(self.schematic), 'SHEET', variant='<Default>',
            section_origin={'project': str(self.incoming), 'sheet_path': '/root/child', 'region_mm': None})
        self.dialog = ui.InsertionDialog(target_path=str(self.target.with_suffix('.kicad_pcb')),
            sources=[model.SourceSpec(str(self.target), 'TARGET', variant='<Default>'),
                     model.SourceSpec(str(self.incoming), 'INCOMING', variant='<Default>'), section])

    def tearDown(self):
        self.dialog.Destroy()
        self.temp.cleanup()

    def pump_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            wx.YieldIfNeeded()
            time.sleep(0.01)
        self.assertTrue(predicate(), 'wx background callback did not finish')

    def test_target_exclusion_and_schematic_only_mode(self):
        self.assertEqual([source.alias for source in self.dialog.sources], ['INCOMING', 'SHEET'])
        with self.assertRaisesRegex(model.MergeError, 'no saved PCB'):
            self.dialog.selected_sources()
        self.dialog.include_layout.SetValue(False)
        self.assertEqual([source.alias for source in self.dialog.selected_sources()], ['INCOMING', 'SHEET'])
        self.dialog.source_list.Check(1, False)
        self.assertEqual([source.alias for source in self.dialog.selected_sources()], ['INCOMING'])

    def test_preview_stale_invalidation_and_explicit_apply(self):
        self.dialog.include_layout.SetValue(False)
        calls = []
        preview_gate = threading.Event()
        fake = ModuleType(PACKAGE + '.insertion')
        def preview(target, sources, include_layout, candidate, cli_path='', gap_mm=10.0):
            preview_gate.wait(5)
            Path(candidate).mkdir()
            calls.append(('preview', target, [source.alias for source in sources], include_layout, candidate))
            return {'target_project': str(self.target), 'candidate_directory': str(candidate),
                    'report': {'incoming_designs': len(sources)}}
        def apply(plan):
            calls.append(('apply', plan))
            return {'target_project': str(self.target), 'backup_directory': str(self.folder/'backup'),
                    'report': {'applied': True}}
        fake.preview_import = preview
        fake.apply_import = apply
        with mock.patch.dict(sys.modules, {PACKAGE + '.insertion': fake}):
            self.dialog.preview_import(None)
            self.assertFalse(self.dialog.target.IsEnabled())
            self.assertFalse(self.dialog.source_list.IsEnabled())
            self.assertFalse(self.dialog.include_layout.IsEnabled())
            self.assertFalse(self.dialog.candidate_name.IsEnabled())
            self.assertTrue(all(not button.IsEnabled() for button in self.dialog.source_buttons))
            preview_gate.set()
            self.pump_until(lambda: self.dialog.plan is not None)
            self.assertTrue(self.dialog.plan_file.is_file())
            self.assertEqual(calls[0][2], ['INCOMING', 'SHEET'])
            self.assertFalse(calls[0][3])
            self.assertFalse(self.dialog.apply_button.IsEnabled())
            saved_plan = self.dialog.plan_file
            self.dialog.source_list.Check(1, False)
            self.dialog.invalidate()
            self.assertIsNone(self.dialog.plan)
            self.assertFalse(self.dialog.open_button.IsEnabled())
            self.assertFalse(self.dialog.apply_button.IsEnabled())
            self.dialog.load_plan_path(saved_plan)
            self.assertEqual(self.dialog.plan['report']['incoming_designs'], 2)
            self.assertFalse(self.dialog.include_layout.GetValue())
            self.assertEqual(self.dialog.source_list.GetCount(), 0)
            self.dialog.invalidate()
            self.dialog.add_specs([model.SourceSpec(str(self.incoming), 'INCOMING', variant='<Default>')])
            self.dialog.preview_import(None)
            self.pump_until(lambda: self.dialog.plan is not None)
            self.assertEqual(calls[1][2], ['INCOMING'])
            self.dialog.closed.SetValue(True)
            self.dialog.on_acknowledge()
            self.assertTrue(self.dialog.apply_button.IsEnabled())
            with mock.patch.object(wx, 'MessageBox', side_effect=[wx.YES, wx.OK]):
                self.dialog.apply_import(None)
                self.pump_until(lambda: self.dialog.applied is not None)
            self.assertEqual(calls[2][0], 'apply')
            self.assertFalse(self.dialog.apply_button.IsEnabled())
            self.assertIn('backup', self.dialog.status.GetLabel())

    def test_main_dialog_uses_initial_board_as_target_not_incoming(self):
        with mock.patch.object(gui, 'detect_variants', return_value=[gui.DEFAULT]):
            main = gui.FusionDialog(initial=str(self.target.with_suffix('.kicad_pcb')))
            try:
                main.append_source(str(self.incoming), alias='INCOMING')
                main.grid.SelectRow(1)
                with mock.patch.object(ui, 'InsertionDialog') as insertion:
                    insertion.return_value.applied = None
                    main.open_insertion(None)
                args = insertion.call_args.kwargs
                self.assertEqual(ui.project_identity(args['target_path']), ui.project_identity(self.target))
                self.assertEqual([source.alias for source in args['sources']], ['INCOMING'])
                self.assertTrue(args['embedded'])
            finally:
                main.Destroy()

    def test_multi_subsheet_selection_preview_and_invalidation(self):
        fake = ModuleType(PACKAGE + '.sections')
        fake.list_sections = lambda source: [
            {'sheet_path': '/root/a', 'display_path': '/A', 'descendant_symbols': 2},
            {'sheet_path': '/root/b', 'display_path': '/B', 'descendant_symbols': 3}]
        fake.preview_schematic_sections = lambda source, paths, cli_path='': {
            'sheet_paths': paths, 'report': [{'sheet_path': path} for path in paths]}
        with mock.patch.dict(sys.modules, {PACKAGE + '.sections': fake}):
            section = ui.SectionBatchDialog(self.dialog,
                model.SourceSpec(str(self.incoming), 'INCOMING', variant='<Default>'))
            try:
                self.pump_until(lambda: len(section.instances) == 2)
                section.sheets.Check(0, True)
                section.sheets.Check(1, True)
                section.preview_selection(None)
                self.pump_until(lambda: section.plan is not None)
                self.assertEqual(section.plan['sheet_paths'], ['/root/a', '/root/b'])
                self.assertTrue(section.create_button.IsEnabled())
                section.max_sources = 1
                with self.assertRaisesRegex(model.MergeError, 'slots remain'):
                    section.selected_paths()
                section.sheets.Check(1, False)
                section.invalidate()
                self.assertIsNone(section.plan)
                self.assertFalse(section.create_button.IsEnabled())
            finally:
                section.Destroy()


if __name__ == '__main__':
    unittest.main()
