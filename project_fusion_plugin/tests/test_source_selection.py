"""Selection request and hierarchy-depth tests independent of wx and KiCad GUI."""
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_sections import PACKAGE, SectionTests, model, s, sch, sx

selection = importlib.import_module(PACKAGE + '.source_selection')


class SourceSelectionTests(unittest.TestCase):
    def test_whole_project_returns_original_spec_without_extraction(self):
        spec = model.SourceSpec('source.kicad_pro', 'A')
        request = {'whole_project': True, 'sheet_paths': [], 'max_depth': None,
                   'include_layout': True, 'region_mm': None}
        self.assertEqual(selection.materialize_selection(spec, request, 'unused'), [spec])

    def test_whole_schematic_only_extracts_root_without_board(self):
        spec = model.SourceSpec('source.kicad_pro', 'A')
        request = {'whole_project': True, 'sheet_paths': [], 'max_depth': None,
                   'include_layout': False, 'region_mm': None}
        source = mock.Mock(sheets=[mock.Mock(old_path='/root')])
        with mock.patch.object(selection, 'discover', return_value=source), \
             mock.patch.object(selection, 'preview_schematic_sections', return_value={'reviewed': True}) as preview, \
             mock.patch.object(selection, 'apply_schematic_sections', return_value=[spec]) as apply:
            self.assertEqual(selection.materialize_selection(spec, request, 'destination', 'cli'), [spec])
        preview.assert_called_once_with(spec, ['/root'], 'cli', allow_root=True)
        apply.assert_called_once_with({'reviewed': True}, Path('destination'))

    def test_selected_pages_pass_depth_to_review_and_apply(self):
        spec = model.SourceSpec('source.kicad_pro', 'A')
        request = {'whole_project': False, 'sheet_paths': ['/root/a'], 'max_depth': 0,
                   'include_layout': False, 'region_mm': None}
        with mock.patch.object(selection, 'preview_schematic_sections', return_value={'reviewed': True}) as preview, \
             mock.patch.object(selection, 'apply_schematic_sections', return_value=[spec]) as apply:
            self.assertEqual(selection.materialize_selection(spec, request, 'destination', 'cli'), [spec])
        preview.assert_called_once_with(spec, ['/root/a'], 'cli', max_depth=0)
        apply.assert_called_once_with({'reviewed': True}, Path('destination'))

    def test_layout_requires_one_subtree_and_passes_depth(self):
        spec = model.SourceSpec('source.kicad_pro', 'A')
        request = {'whole_project': False, 'sheet_paths': ['/root/a'], 'max_depth': 0,
                   'include_layout': True, 'region_mm': [0, 0, 10, 10]}
        with mock.patch.object(selection, 'preview_section', return_value={'reviewed': True}) as preview, \
             mock.patch.object(selection, 'apply_section', return_value=spec) as apply:
            self.assertEqual(selection.materialize_selection(spec, request, 'destination', 'cli'), [spec])
        preview.assert_called_once_with(spec, '/root/a', [0, 0, 10, 10], 'cli', max_depth=0)
        apply.assert_called_once_with({'reviewed': True}, Path('destination'))
        request['sheet_paths'].append('/root/b')
        with self.assertRaisesRegex(model.MergeError, 'exactly one'):
            selection.materialize_selection(spec, request, 'destination')

    def test_depth_zero_removes_child_sheet_node_from_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            spec, path = SectionTests().fixture(base)
            child = sx.load(base/'child.kicad_sch')
            grand_id = '66666666-6666-4666-8666-666666666666'
            child.append(sx.loads(f'''(sheet (uuid "{grand_id}")
                (property "Sheetname" "Nested") (property "Sheetfile" "grand.kicad_sch"))'''))
            sx.save(base/'child.kicad_sch', child)
            (base/'grand.kicad_sch').write_text('''(kicad_sch (version 20260306)
                (uuid "77777777-7777-4777-8777-777777777777") (lib_symbols))''')
            source = sch.discover(spec, sch.new_uuid())
            selected = next(item for item in source.sheets if item.old_path == path)
            limited = base/'limited'; limited.mkdir()
            paths = s._write_hierarchy(source, selected, limited, 'board', max_depth=0)
            self.assertEqual(set(paths), {path})
            self.assertEqual(sx.children(sx.load(limited/'board.kicad_sch'), 'sheet'), [])
            unlimited = base/'unlimited'; unlimited.mkdir()
            paths = s._write_hierarchy(source, selected, unlimited, 'board', max_depth=None)
            self.assertEqual(len(paths), 2)
            self.assertEqual(len(sx.children(sx.load(unlimited/'board.kicad_sch'), 'sheet')), 1)


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_GUI') == '1', 'native wx opt-in')
class SourceSelectionWxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx = wx
        cls.app = wx.GetApp() or wx.App(False)

    def test_narrow_tree_and_depth_request(self):
        wx = self.wx
        frame = wx.Frame(None, size=(380, 520))
        panel = selection.SourceSelectionPanel(frame, lambda: None)
        spec = model.SourceSpec('C:/Projects/Example/board.kicad_pro', 'Example')
        root = '/11111111-1111-4111-8111-111111111111'
        child = root + '/22222222-2222-4222-8222-222222222222'
        grand = child + '/33333333-3333-4333-8333-333333333333'
        instances = [
            {'sheet_path': child, 'display_path': '/Example/Power/', 'file': 'power.kicad_sch', 'descendant_symbols': 2},
            {'sheet_path': grand, 'display_path': '/Example/Power/Filter/', 'file': 'filter.kicad_sch', 'descendant_symbols': 1},
        ]
        try:
            frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
            frame.GetSizer().Add(panel, 1, wx.EXPAND)
            frame.Show()
            with mock.patch.object(selection, 'list_sections', return_value=instances):
                panel.load_spec(spec)
            panel.selected.SetValue(True)
            panel.whole.SetValue(False)
            panel.pages.SelectItem(panel.pages.GetFirstChild(panel.pages.GetRootItem())[0])
            panel.depth_check.SetValue(True)
            panel.depth.SetValue(0)
            panel.set_include_layout(True)
            frame.Layout(); wx.Yield()
            request = panel.selected_request()
            self.assertEqual(request['sheet_paths'], [child])
            self.assertEqual(request['max_depth'], 0)
            self.assertTrue(request['include_layout'])
            self.assertLessEqual(panel.GetBestSize().width, 380)
        finally:
            frame.Destroy(); wx.Yield()
