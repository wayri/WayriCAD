"""Opt-in native wx smoke test: FUSION_NATIVE_GUI=1 with KiCad Python."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_fusion_instance_gui_test'

if os.environ.get('FUSION_NATIVE_GUI') == '1':
    import wx
    package = ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package
    gui = importlib.import_module(PACKAGE + '.gui')
    model = importlib.import_module(PACKAGE + '.model')


class FileDialogResult:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def GetPath(self):
        return str(self.path)


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_GUI') == '1', 'Opt-in native wx workflow')
class InstanceGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.variants = mock.patch.object(gui, 'detect_variants', return_value=[gui.DEFAULT])
        self.detect_variants = self.variants.start()
        self.dialog = gui.FusionDialog()

    def tearDown(self):
        self.dialog.Destroy()
        self.variants.stop()

    def test_hundred_automatic_aliases_for_numeric_long_filename(self):
        for _ in range(100):
            self.dialog.append_source('C:/Projects/12345678901234567890.kicad_pro')
        sources=self.dialog.options().sources
        model.validate_source_aliases(sources)
        self.assertEqual(len({s.alias.casefold() for s in sources}),100)
        self.assertTrue(all(len(s.alias)<=24 for s in sources))

    def test_hundred_mixed_instances_duplicate_move_remove_and_roundtrip(self):
        section_origin = {'project': 'C:/Projects/Example/source.kicad_pro',
                          'sheet_path': '/root/sheet', 'region_mm': [1, 2, 21, 22]}
        for index in range(98):
            extras = {'section_origin': section_origin} if index % 2 else {}
            self.dialog.append_source(f'C:/Projects/Example/source{index}.kicad_pro',
                                      alias=f'Design{index}', extras=extras)
        self.assertEqual(self.dialog.instance_count.GetLabel(), 'Instances: 98 / 100')
        self.assertEqual(self.dialog.grid.GetCellValue(1, 5), 'Section')
        self.assertTrue(self.dialog.grid.IsReadOnly(1, 5))

        self.dialog.grid.SelectRow(0)
        self.dialog.grid.SelectRow(1, addToSelected=True)
        scans_before = self.detect_variants.call_count
        with mock.patch.object(gui.wx, 'GetNumberFromUser', return_value=1):
            self.dialog.duplicate_selected(None)
        self.assertEqual(self.detect_variants.call_count, scans_before)
        specs = self.dialog.options().sources
        self.assertEqual(len(specs), 100)
        self.assertEqual([s.alias for s in specs[:4]], ['Design0', 'Design0_2', 'Design1', 'Design1_2'])
        self.assertEqual(specs[3].kind, 'section')
        self.assertEqual(specs[3].section_origin, section_origin)
        self.assertIsNone(specs[3].x_mm)
        self.assertEqual(self.dialog.instance_count.GetLabel(), 'Instances: 100 / 100')

        before = [s.alias for s in specs]
        self.dialog.grid.ClearSelection()
        self.dialog.grid.SelectRow(3)
        self.dialog.move(-1)
        self.assertEqual(self.dialog.options().sources[2].alias, before[3])
        self.assertEqual(self.dialog.grid.GetCellValue(2, 5), 'Section')
        self.dialog.grid.ClearSelection()
        self.dialog.grid.SelectRow(2)
        self.dialog.remove(None)
        self.assertEqual(self.dialog.instance_count.GetLabel(), 'Instances: 99 / 100')

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'setup.json'
            with mock.patch.object(gui.wx, 'FileDialog', return_value=FileDialogResult(path)):
                self.dialog.save_config(None)
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(len(saved['sources']), 99)
            self.assertEqual(saved['sources'][2]['section_origin'], section_origin)
            self.dialog.replace_sources([])
            with mock.patch.object(gui.wx, 'FileDialog', return_value=FileDialogResult(path)):
                self.dialog.load_config(None)
        self.assertEqual(self.dialog.instance_count.GetLabel(), 'Instances: 99 / 100')
        self.assertEqual(self.dialog.options().sources[2].kind, 'section')
        self.assertEqual(self.dialog.grid.GetCellValue(2, 5), 'Section')

    def test_capacity_rejection_keeps_existing_rows(self):
        for index in range(100):
            self.dialog.append_source(f'C:/Projects/Example/source{index}.kicad_pro', alias=f'D{index}')
        before = [s.alias for s in self.dialog.options().sources]
        with self.assertRaises(model.MergeError):
            self.dialog.append_source('C:/Projects/Example/extra.kicad_pro')
        self.assertEqual([s.alias for s in self.dialog.options().sources], before)
        self.dialog.grid.SelectRow(0)
        with mock.patch.object(gui.wx, 'MessageBox') as message:
            self.dialog.duplicate_selected(None)
        message.assert_called_once()
        self.assertEqual([s.alias for s in self.dialog.options().sources], before)

    def test_duplicate_keeps_each_rows_variant_choices(self):
        path = 'C:/Projects/Example/source.kicad_pro'
        self.dialog.append_source(path, alias='First')
        self.dialog.append_source(path, alias='Second')
        self.dialog.row_variants[0] = [gui.DEFAULT, 'A']
        self.dialog.row_variants[1] = [gui.DEFAULT, 'B']
        self.dialog.grid.SelectRow(0)
        self.dialog.grid.SelectRow(1, addToSelected=True)
        with mock.patch.object(gui.wx, 'GetNumberFromUser', return_value=1):
            self.dialog.duplicate_selected(None)
        self.assertEqual(self.dialog.row_variants,
                         [[gui.DEFAULT, 'A'], [gui.DEFAULT, 'A'],
                          [gui.DEFAULT, 'B'], [gui.DEFAULT, 'B']])

    def test_source_edit_clears_previous_analysis(self):
        self.dialog.append_source('C:/Projects/Example/source.kicad_pro', alias='Source')
        self.dialog.output_project = Path('C:/Projects/Example/merged.kicad_pro')
        self.dialog.open_button.Enable()
        self.dialog.preview.boxes = [('Source', 0, 0, 10, 10)]
        self.dialog.mapping.InsertItem(0, 'Source')
        event = mock.Mock()
        self.dialog.on_source_cell_changed(event)
        self.assertIsNone(self.dialog.output_project)
        self.assertFalse(self.dialog.open_button.IsEnabled())
        self.assertEqual(self.dialog.preview.boxes, [])
        self.assertEqual(self.dialog.mapping.GetItemCount(), 0)
        event.Skip.assert_called_once()

    def test_path_overrides_keep_section_origin_private(self):
        origin = {'project': 'C:/Projects/Example/source.kicad_pro',
                  'sheet_path': '/root/sheet', 'region_mm': [1, 2, 21, 22]}
        self.dialog.append_source('C:/Projects/Example/section.kicad_pro', alias='Section',
                                  extras={'section_origin': origin})
        original_dialog = wx.Dialog

        class AcceptPathDialog(original_dialog):
            def ShowModal(self):
                editor = next(child for child in self.GetChildren() if isinstance(child, wx.TextCtrl))
                self_outer.assertNotIn('section_origin', editor.GetValue())
                editor.SetValue(json.dumps({'path_variables': {'LIBRARY': 'D:/CAD/library'},
                                            'path_remaps': {}, 'extra_asset_paths': []}))
                return wx.ID_OK

        self_outer = self
        with mock.patch.object(gui.wx, 'Dialog', AcceptPathDialog):
            self.dialog.edit_source_paths(None)
        spec = self.dialog.options().sources[0]
        self.assertEqual(spec.section_origin, origin)
        self.assertEqual(spec.path_variables, {'LIBRARY': 'D:/CAD/library'})
        self.assertEqual(self.dialog.grid.GetCellValue(0, 5), 'Section')


if __name__ == '__main__':
    unittest.main()
